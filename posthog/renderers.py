from typing import Any

import orjson
from rest_framework.renderers import BaseRenderer, JSONRenderer
from rest_framework.utils.encoders import JSONEncoder

CleaningMarker = bool | dict[int, "CleaningMarker"]

_drf_default = JSONEncoder().default


def orjson_default(obj: Any) -> Any:
    """Fallback serializer for ``orjson.dumps`` that tolerates non-UTF-8 bytes.

    orjson calls this for any value it can't natively encode, including ``bytes``.
    DRF's encoder decodes bytes as strict UTF-8, which raises on binary / non-UTF-8
    content (common in data-warehouse text columns). orjson turns a raising
    ``default`` into a generic ``TypeError: Type is not JSON serializable: bytes``,
    voiding the whole payload over a single bad cell. Decode leniently instead so
    one cell can't fail an entire query result or API response.
    """
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    return _drf_default(obj)


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
