import math

import orjson
from rest_framework.renderers import BaseRenderer, JSONRenderer
from rest_framework.utils.encoders import JSONEncoder

from posthog.exceptions_capture import capture_exception

CleaningMarker = bool | dict[int, "CleaningMarker"]


def _null_non_finite(value):
    # Matches orjson, which writes NaN and infinity as null; the stdlib encoder would emit invalid JSON.
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _null_non_finite(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_null_non_finite(item) for item in value]
    return value


class SafeJSONRenderer(JSONRenderer):
    def render(self, data, accepted_media_type=None, renderer_context=None) -> bytes:
        if data is None:
            return b""

        option = orjson.OPT_UTC_Z

        if renderer_context and renderer_context.get("indent"):
            option |= orjson.OPT_INDENT_2

        try:
            return orjson.dumps(data, default=JSONEncoder().default, option=option)
        except orjson.JSONEncodeError as e:
            # orjson caps nesting at 255 levels, while stdlib json is bounded only by the
            # interpreter's recursion limit, so a deep but finite payload can still be served.
            if str(e) != "Recursion limit reached":
                raise
            capture_exception(e)
            return super().render(_null_non_finite(data), accepted_media_type, renderer_context)


class ServerSentEventRenderer(BaseRenderer):
    media_type = "text/event-stream"
    format = "txt"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data
