from datetime import datetime
from typing import Any

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, status
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request

from ...facade import api, contracts
from .trace_ids import MalformedTraceIdSegmentError, decode_trace_id_segment
from .trace_resource import THROTTLED_RESPONSE, TRACE_ID_PARAMETER, TraceResourceViewSet


class TraceClustersQuerySerializer(serializers.Serializer):
    created_at = serializers.DateTimeField(
        help_text="When the trace started, as the trace resource's createdAt. Bounds which clustering runs are read."
    )

    def validate_created_at(self, value: datetime) -> datetime:
        if not api.is_usable_trace_start(value):
            raise serializers.ValidationError("Trace start is out of range.")
        return value


class TraceClustersViewSet(TraceResourceViewSet):
    required_scopes = ["llm_analytics:read", "ai_observability_clusters:read"]

    @validated_request(
        query_serializer=TraceClustersQuerySerializer,
        parameters=[TRACE_ID_PARAMETER],
        responses={
            200: OpenApiResponse(response=contracts.TraceClusters),
            400: OpenApiResponse(description="The created_at parameter or the encoded trace id is malformed."),
            429: THROTTLED_RESPONSE,
        },
        operation_id="ai_observability_traces_clusters_retrieve",
    )
    def list(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """The clusters that list this trace, from the newest scheduled run of each clustering job that lists it."""
        try:
            trace_id = decode_trace_id_segment(self.trace_segment)
        except MalformedTraceIdSegmentError:
            return Response({"detail": "Malformed encoded trace id."}, status=status.HTTP_400_BAD_REQUEST)
        created_at = request.validated_query_data["created_at"]
        clusters = self._read(
            request, lambda user, _hint: api.get_trace_clusters(self.team, user, trace_id, created_at)
        )
        return Response(clusters.model_dump(mode="json", by_alias=True))
