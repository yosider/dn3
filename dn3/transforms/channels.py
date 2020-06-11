import torch
import numpy as np

# Not crazy about this approach..
from mne.utils._bunch import NamedInt
from mne.io.constants import FIFF
# Careful this doesn't overlap with future additions to MNE, might have to coordinate
DEEP_1010_SCALE_CH = NamedInt('DN3_DEEP1010_SCALE_CH', 3000)
DEEP_1010_EXTRA_CH = NamedInt('DN3_DEEP1010_EXTRA_CH', 3001)

_LEFT_NUMBERS = list(reversed(range(1, 9, 2)))
_RIGHT_NUMBERS = list(range(2, 10, 2))

_EXTRA_CHANNELS = 5

DEEP_1010_CHS_LISTING = [
    # EEG
    "NZ",
    "FP1", "FPZ", "FP2",
    "AF7", "AF3", "AFZ", "AF4", "AF8",
    "F9", *["F{}".format(n) for n in _LEFT_NUMBERS], "FZ", *["F{}".format(n) for n in _RIGHT_NUMBERS], "F10",

    "FT9", "FT7", *["FC{}".format(n) for n in _LEFT_NUMBERS[1:]], "FCZ",
    *["FC{}".format(n) for n in _RIGHT_NUMBERS[:-1]], "FT8", "FT10",
                                                                                                                                  
    "T9", "T7", "T3",  *["C{}".format(n) for n in _LEFT_NUMBERS[1:]], "CZ",
    *["C{}".format(n) for n in _RIGHT_NUMBERS[:-1]], "T4", "T8", "T10",

    "TP9", "TP7", *["CP{}".format(n) for n in _LEFT_NUMBERS[1:]], "CPZ",
    *["CP{}".format(n) for n in _RIGHT_NUMBERS[:-1]], "TP8", "TP10",

    "P9", "P7", "T5",  *["P{}".format(n) for n in _LEFT_NUMBERS[1:]], "PZ",
    *["P{}".format(n) for n in _RIGHT_NUMBERS[:-1]],  "T6", "P8", "P10",

    "PO7", "PO3", "POZ", "PO4", "PO8",
    "O1",  "OZ", "O2",
    "IZ",
    # EOG
    "VEOGL", "VEOGR", "HEOGL", "HEOGR",

    # Ear clip references
    "A1", "A2", "REF",
    # SCALING
    "SCALE",
    # Extra
    *["EX{}".format(n) for n in range(1, _EXTRA_CHANNELS+1)]
]
EOG_INDS = [DEEP_1010_CHS_LISTING.index(ch) for ch in ["VEOGL", "VEOGR", "HEOGL", "HEOGR"]]
REF_INDS = [DEEP_1010_CHS_LISTING.index(ch) for ch in ["A1", "A2", "REF"]]
EXTRA_INDS = list(range(len(DEEP_1010_CHS_LISTING) - _EXTRA_CHANNELS, len(DEEP_1010_CHS_LISTING)))
SCALE_IND = -len(EXTRA_INDS) + len(DEEP_1010_CHS_LISTING)
_NUM_EEG_CHS = len(DEEP_1010_CHS_LISTING) - len(EOG_INDS) - len(REF_INDS) - len(EXTRA_INDS) - 1

DEEP_1010_CH_TYPES = ([FIFF.FIFFV_EEG_CH] * _NUM_EEG_CHS) + ([FIFF.FIFFV_EOG_CH] * len(EOG_INDS)) + \
                     ([FIFF.FIFFV_EEG_CH] * len(REF_INDS)) + [DEEP_1010_SCALE_CH] + \
                     ([DEEP_1010_EXTRA_CH] * _EXTRA_CHANNELS)


def _deep_1010(map, names, eog, ear_ref, extra):

    for i, ch in enumerate(names):
        if ch not in eog and ch not in ear_ref and ch not in extra:
            try:
                map[i, DEEP_1010_CHS_LISTING.index(str(ch).upper())] = 1.0
            except ValueError:
                print("Warning: channel {} not found in standard layout. Skipping...".format(ch))
                continue

    # Normalize for when multiple values are mapped to single location
    summed = map.sum(axis=0)[np.newaxis, :]
    mapping = torch.from_numpy(np.divide(map, summed, out=np.zeros_like(map), where=summed != 0)).float()
    mapping.requires_grad_(False)
    return mapping


def _valid_character_heuristics(names, informative_characters):
    new_names = list()
    for name in names:
        possible = ''.join(c for c in name.upper() if c in informative_characters).replace(' ', '')
        if possible == "":
            print("Could not use channel {}. Could not resolve its true label, rename first.".format(name))
        else:
            new_names.append(possible)
    return new_names


def _heuristic_eog_resolution(eog_ch_names: list):
    return _valid_character_heuristics(eog_ch_names, "VHEOGLR")[:len(EOG_INDS)]


def _heuristic_ref_resolution(ear_ref_names: list):
    return _valid_character_heuristics(ear_ref_names, 'A12REF')[:len(REF_INDS)]


def _heuristic_eeg_resolution(eeg_ch_names: list):
    informative_characters = set([c for name in DEEP_1010_CHS_LISTING[:_NUM_EEG_CHS] for c in name])
    return _valid_character_heuristics(eeg_ch_names, informative_characters)[:_NUM_EEG_CHS]


def _likely_eeg_channel(name):
    for ch in DEEP_1010_CHS_LISTING[:_NUM_EEG_CHS]:
        if ch in name.upper():
            return True
    return False


def map_named_channels_deep_1010(channel_names: list, EOG=None, ear_ref=None, extra_channels=None):
    """
    Maps channel names to the Deep1010 format, will automatically map EOG and extra channels if they have been
    named according to standard convention. Otherwise provide as keyword arguments.

    Parameters
    ----------
    channel_names : list
                   List of channel names from dataset
    EOG : list, str
         Must be a single channel name, or left and right EOG channels, optionally vertical L/R then horizontal
         L/R for four channels.
    ear_ref : Optional, str, list
               One or two channels to be used as references. If two, should be left and right in that order.
    extra_channels : list, None
                     Up to 6 extra channels to include. Currently not standardized, but could include ECG, respiration,
                     EMG, etc.

    Returns
    -------
    mapping : torch.Tensor
              Mapping matrix from previous channel sequence to Deep1010.
    """
    map = np.zeros((len(channel_names), len(DEEP_1010_CHS_LISTING)))

    if isinstance(EOG, str):
        EOG = [EOG] * 4
    elif EOG is None:
        EOG = []
    elif len(EOG) == 2:
        EOG = EOG * 2
    else:
        assert len(EOG) == 4
    for eog_map, eog_std in zip(EOG, EOG_INDS):
        try:
            map[channel_names.index(eog_map), eog_std] = 1.0
        except ValueError:
            raise ValueError("EOG channel {} not found in provided channels.".format(eog_map))

    if isinstance(ear_ref, str):
        ear_ref = [ear_ref] * 2
    elif ear_ref is None:
        ear_ref = []
    else:
        assert len(ear_ref) <= len(REF_INDS)
    for ref_map, ref_std in zip(ear_ref, REF_INDS):
        try:
            map[channel_names.index(ref_map), ref_std] = 1.0
        except ValueError:
            raise ValueError("Reference channel {} not found in provided channels.".format(ref_map))

    if isinstance(extra_channels, str):
        extra_channels = [extra_channels]
    elif extra_channels is None:
        extra_channels = []
    assert len(extra_channels) <= _EXTRA_CHANNELS
    for ch, place in zip(extra_channels, EXTRA_INDS):
        if ch is not None:
            map[channel_names.index(ch), place] = 1.0

    return _deep_1010(map, channel_names, EOG, ear_ref, extra_channels)


def map_dataset_channels_deep_1010(channels: np.ndarray, exclude_stim=True):
    """
    Maps channels as stored by a :any:`DN3ataset` to the Deep1010 format, will automatically map EOG and extra channels
    by type.

    Parameters
    ----------
    channels : np.ndarray
               Channels that remain a 1D sequence (they should not have been projected into 2 or 3D grids) of name and
               type. This means the array has 2 dimensions:
               ..math:: N_{channels} \by 2
               With the latter dimension containing name and type respectively, as is constructed by default in most
               cases.
    exclude_stim : bool
                   This option allows the stim channel to be added as an *extra* channel. The default (True) will not do
                   this, and it is very rare if ever where this would be needed.

    Returns
    -------
    mapping : torch.Tensor
              Mapping matrix from previous channel sequence to Deep1010.
    """
    if len(channels.shape) != 2 or channels.shape[1] != 2:
        raise ValueError("Deep1010 Mapping: channels must be a 2 dimensional array with dim0 = num_channels, dim1 = 2."
                         " Got {}".format(channels.shape))
    eeg = list()
    eog = list()
    reference = list()

    # Use this for some semblance of order in the "extras"
    extra = [None for _ in range(_EXTRA_CHANNELS)]
    extra_idx = 0

    for name, ch_type in channels:
        # Annoyingly numpy converts them to strings...
        ch_type = int(ch_type)
        if ch_type == FIFF.FIFFV_EEG_CH and _likely_eeg_channel(name):
            eeg.append(name)
        elif ch_type == FIFF.FIFFV_EOG_CH:
            eog.append(name)
        elif ch_type == FIFF.FIFFV_STIM_CH:
            if exclude_stim:
                continue
            # if stim, always set as last extra
            extra[-1] = name
        elif 'REF' in name.upper() or 'A1' in name.upper() or 'A2' in name.upper():
            reference.append(name)
        else:
            if extra_idx == _EXTRA_CHANNELS - 1 and not exclude_stim:
                print("Stim channel overwritten by {} in Deep1010 mapping.".format(name))
            elif extra_idx == _EXTRA_CHANNELS:
                print("No more room in extra channels for {}".format(name))
                continue
            extra[extra_idx] = name
            extra_idx += 1

    # FIXME -  This probably belongs in the heuristics
    for ch_type, chs, num in zip(['reference', 'EOG', 'EEG'], [reference, eog, eeg],
                                 [len(REF_INDS), len(EOG_INDS), _NUM_EEG_CHS]):
        if len(chs) > num:
            for name in chs[num:]:
                print("Losing assumed {} channel {} because there are too many.".format(ch_type, name))

    reference = _heuristic_ref_resolution(reference)
    eog = _heuristic_eog_resolution(eog)
    eeg = _heuristic_eeg_resolution(eeg)

    return map_named_channels_deep_1010(eeg + eog + reference + extra, eog, reference, extra)


def print_channel_mapping(original_names, mapping):
    pass

