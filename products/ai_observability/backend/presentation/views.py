from datetime import datetime
from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse
from rest_framework import serializers, status, viewsets
from rest_framework.response import Response

from posthog.api.documentation import _FallbackSerializer
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.models.user import User

from ..facade import api, contracts
from .query_concurrency import query_concurrency_slots
from .trace_ids import MalformedTraceIdSegmentError, decode_trace_id_segment


class TraceQuerySerializer(serializers.Serializer):
    timestamp_hint = serializers.DateTimeField(
        required=False,
        help_text="When the trace happened, as carried by links into it. Lets a trace older than the AI events retention load from the shared events table.",
    )

    def validate_timestamp_hint(self, value: datetime) -> datetime:
        if not api.is_usable_timestamp_hint(value):
            raise serializers.ValidationError("Timestamp hint is out of range.")
        return value


class TraceViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "llm_analytics"
    # Traces are project-wide data, so a grant on a single llm_analytics object must not open them.
    requires_resource_level_access = True
    serializer_class = _FallbackSerializer

    @validated_request(
        query_serializer=TraceQuerySerializer,
        parameters=[
            OpenApiParameter(
                "id",
                OpenApiTypes.STR,
                OpenApiParameter.PATH,
                description="The trace id, sent as the unpadded base64url encoding of its UTF-8 bytes.",
            )
        ],
        responses={
            200: OpenApiResponse(response=contracts.Trace),
            400: OpenApiResponse(description="The timestamp hint or the encoded trace id is malformed."),
            404: OpenApiResponse(description="No trace with this id in the project."),
            429: OpenApiResponse(description="Too many queries are running for the project or organization."),
        },
        operation_id="ai_observability_traces_retrieve",
    )
    def retrieve(self, request: ValidatedRequest, pk: str, **kwargs: Any) -> Response:
        """A trace ready to render: its tree with roll-ups, timeline, totals and person, without inputs or outputs."""
        try:
            trace_id = decode_trace_id_segment(pk)
        except MalformedTraceIdSegmentError:
            return Response({"detail": "Malformed encoded trace id."}, status=status.HTTP_400_BAD_REQUEST)
        tag_queries(feature=Feature.QUERY)
        user = request.user if isinstance(request.user, User) else None
        try:
            with query_concurrency_slots(self.team):
                trace = api.get_trace(self.team, user, trace_id, request.validated_query_data.get("timestamp_hint"))
        except api.TraceNotFoundError:
            return Response({"detail": "Trace not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(trace.model_dump(mode="json", by_alias=True))
