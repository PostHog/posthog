import orjson
from rest_framework.renderers import BaseRenderer, JSONRenderer

from posthog.json_encoders import orjson_default

CleaningMarker = bool | dict[int, "CleaningMarker"]


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
