from typing import Any

import orjson
from rest_framework.renderers import BaseRenderer, JSONRenderer
from rest_framework.utils.encoders import JSONEncoder

CleaningMarker = bool | dict[int, "CleaningMarker"]

_DRF_ENCODER = JSONEncoder()


def orjson_default(obj: Any) -> Any:
    # ClickHouse can return non-UTF-8 binary (FixedString, aggregate states); DRF's
    # encoder does a bare .decode() that blows up on those — fall back to hex.
    if isinstance(obj, bytes):
        try:
            return obj.decode()
        except UnicodeDecodeError:
            return obj.hex()
    return _DRF_ENCODER.default(obj)


class SafeJSONRenderer(JSONRenderer):
    def render(self, data, accepted_media_type=None, renderer_context=None) -> bytes:
        if data is None:
            return b""

        option = orjson.OPT_UTC_Z

        if renderer_context and renderer_context.get("indent"):
            option |= orjson.OPT_INDENT_2

        return orjson.dumps(data, default=orjson_default, option=option)


class ServerSentEventRenderer(BaseRenderer):
    media_type = "text/event-stream"
    format = "txt"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data
