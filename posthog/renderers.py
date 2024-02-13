import math
from typing import Dict, Tuple

import orjson
from rest_framework.renderers import JSONRenderer
from rest_framework.utils.encoders import JSONEncoder

CleaningMarker = bool | Dict[int, "CleaningMarker"]


def clean_data_for_json(data) -> Tuple[CleaningMarker, CleaningMarker]:
    """Replace NaNs and Infinities with None, in-place, marking which fields had to be scrubbed.
    Return markers that should be set at the parent level, which is used for setting the markers recursively."""
    if isinstance(data, float):
        return (math.isnan(data), math.isinf(data))
    if isinstance(data, list):
        nan_map: Dict[int, CleaningMarker] = {}
        inf_map: Dict[int, CleaningMarker] = {}
        for index, item in enumerate(data):
            nan, inf = clean_data_for_json(item)
            if nan:
                nan_map[index] = nan
                if nan is True:
                    data[index] = None
            if inf:
                inf_map[index] = inf
                if inf is True:
                    data[index] = None
        return (nan_map, inf_map)
    if isinstance(data, dict):
        marker_payload: Dict[str, CleaningMarker] = {}
        for key, value in data.items():
            nan, inf = clean_data_for_json(value)
            if nan:
                marker_payload[f"{key}::nan"] = nan
                if nan is True:
                    data[key] = None
            if inf:
                marker_payload[f"{key}::inf"] = inf
                if inf is True:
                    data[key] = None
        data.update(marker_payload)
    return (False, False)


class SafeJSONRenderer(JSONRenderer):
    def render(self, data, accepted_media_type=None, renderer_context=None):
        if data is None:
            return b""

        return orjson.dumps(data, default=JSONEncoder().default)
