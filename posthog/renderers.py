from typing import Dict

import orjson
from rest_framework.renderers import JSONRenderer
from rest_framework.utils.encoders import JSONEncoder

CleaningMarker = bool | Dict[int, "CleaningMarker"]


class SafeJSONRenderer(JSONRenderer):
    def render(self, data, accepted_media_type=None, renderer_context=None) -> bytes:
        if data is None:
            return b""

        option = orjson.OPT_UTC_Z

        if renderer_context and renderer_context.get("indent"):
            option |= orjson.OPT_INDENT_2

        return orjson.dumps(data, default=JSONEncoder().default, option=option)
