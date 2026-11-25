from functools import cached_property

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter
from rest_framework import serializers
from rest_framework.exceptions import ParseError

from posthog.api.routing import PARENT_LOOKUP_KWARG_PREFIX

from ...facade import api
from .trace_ids import UnreadableSessionIdError, decode_session_id_segment
from .trace_resource import TraceQuerySerializer, TraceResourceViewSet

# Named `id` so that every sub-resource path reads `sessions/{id}/...`, the same parameter as the session's own route.
SESSION_LOOKUP = "id"

SESSION_ID_PARAMETER = OpenApiParameter(
    "id",
    OpenApiTypes.STR,
    OpenApiParameter.PATH,
    description="The session id, sent as the unpadded base64url encoding of its UTF-8 bytes. A session id is at most "
    f"{api.SESSION_ID_MAX_LENGTH} characters, the longest the sessions list hands out.",
)
UNREADABLE_SESSION_ID = f"Malformed encoded session id, or a session id over {api.SESSION_ID_MAX_LENGTH} characters."


class SessionQuerySerializer(TraceQuerySerializer):
    timestamp_hint = serializers.DateTimeField(
        required=False,
        help_text="When the session's first turn happened, as carried by links into it. Lets a session older than "
        "the AI events retention load from the shared events table.",
    )


class SessionResourceViewSet(TraceResourceViewSet):
    """A session, or a sub-resource of one, that every endpoint names by the session id in its path."""

    @cached_property
    def session_id(self) -> str:
        segment = self.kwargs.get("pk") or self.kwargs[f"{PARENT_LOOKUP_KWARG_PREFIX}{SESSION_LOOKUP}"]
        try:
            return decode_session_id_segment(segment)
        except UnreadableSessionIdError as error:
            raise ParseError(UNREADABLE_SESSION_ID) from error
