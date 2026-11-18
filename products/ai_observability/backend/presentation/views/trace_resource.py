from collections.abc import Callable
from datetime import datetime

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse
from rest_framework import serializers, viewsets
from rest_framework.exceptions import NotAuthenticated
from rest_framework.request import Request

from posthog.api.documentation import PostHogAutoSchema, _FallbackSerializer
from posthog.api.mixins import ValidatedRequest
from posthog.api.routing import PARENT_LOOKUP_KWARG_PREFIX, TeamAndOrgViewSetMixin
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.models.user import User

from ...facade import api
from ..query_concurrency import query_concurrency_slots

# Named `id` so that every sub-resource path reads `traces/{id}/...`, the same parameter as the trace's own route.
TRACE_LOOKUP = "id"

TRACE_ID_PARAMETER = OpenApiParameter(
    "id",
    OpenApiTypes.STR,
    OpenApiParameter.PATH,
    description="The trace id, sent as the unpadded base64url encoding of its UTF-8 bytes.",
)
THROTTLED_RESPONSE = OpenApiResponse(description="Too many queries are running for the project or organization.")


class TraceQuerySerializer(serializers.Serializer):
    timestamp_hint = serializers.DateTimeField(
        required=False,
        help_text="When the trace happened, as carried by links into it. Lets a trace older than the AI events retention load from the shared events table.",
    )

    def validate_timestamp_hint(self, value: datetime) -> datetime:
        if not api.is_usable_timestamp_hint(value):
            raise serializers.ValidationError("Timestamp hint is out of range.")
        return value


class TraceResourceSchema(PostHogAutoSchema):
    """Keeps drf-spectacular from wrapping a single-object sub-resource's `list` response in an array."""

    def _is_list_view(self, serializer: object = None) -> bool:
        return False


class TraceResourceViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "llm_analytics"
    scope_object_read_actions = ["list", "retrieve"]
    scope_object_write_actions: list[str] = []
    # Traces are project-wide data, so a grant on a single llm_analytics object must not open them.
    requires_resource_level_access = True
    serializer_class = _FallbackSerializer
    schema = TraceResourceSchema()

    @property
    def trace_segment(self) -> str:
        return self.kwargs[f"{PARENT_LOOKUP_KWARG_PREFIX}{TRACE_LOOKUP}"]

    def _read[T](self, request: ValidatedRequest, read: Callable[[User | None, datetime | None], T]) -> T:
        tag_queries(feature=Feature.QUERY)
        user = request.user if isinstance(request.user, User) else None
        with query_concurrency_slots(self.team):
            return read(user, request.validated_query_data.get("timestamp_hint"))


def request_user(request: Request) -> User:
    # An export runs later as the user who asked for it, so unlike a trace read it cannot go without one.
    if not isinstance(request.user, User):
        raise NotAuthenticated()
    return request.user
