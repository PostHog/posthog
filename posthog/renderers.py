from typing import Dict

import orjson
from rest_framework.renderers import JSONRenderer
from rest_framework.utils.encoders import JSONEncoder

CleaningMarker = bool | Dict[int, "CleaningMarker"]


class SafeJSONRenderer(JSONRenderer):
    def render(self, data, accepted_media_type=None, renderer_context=None) -> bytes:
        if data is None:
            return b""

        return orjson.dumps(data, default=JSONEncoder().default, option=orjson.OPT_UTC_Z)
