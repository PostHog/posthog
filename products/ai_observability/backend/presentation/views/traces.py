from typing import Any

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request

from ...facade import api, contracts
from .trace_ids import MalformedTraceIdSegmentError, decode_trace_id_segment
from .trace_resource import THROTTLED_RESPONSE, TRACE_ID_PARAMETER, TraceQuerySerializer, TraceResourceViewSet


class TraceAvailabilityRequestSerializer(serializers.Serializer):
    trace_ids = serializers.ListField(
        child=serializers.CharField(max_length=255, trim_whitespace=False),
        min_length=1,
        max_length=2,
        help_text="Application and evaluator trace IDs to check without loading trace contents.",
    )


class TraceAvailabilitySerializer(serializers.Serializer):
    available_trace_ids = serializers.ListField(
        child=serializers.CharField(),
        help_text="Requested trace IDs readable from AI events or the shared events table.",
    )


class TraceViewSet(TraceResourceViewSet):
    scope_object_read_actions = ["retrieve", "availability"]

    @validated_request(
        request_serializer=TraceAvailabilityRequestSerializer,
        responses={200: TraceAvailabilitySerializer, 429: THROTTLED_RESPONSE},
        operation_id="ai_observability_traces_availability_create",
    )
    @action(detail=False, methods=["POST"])
    def availability(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        trace_ids = self._read(
            request,
            lambda user, _hint: api.get_available_trace_ids(self.team, user, request.validated_data["trace_ids"]),
        )
        return Response(TraceAvailabilitySerializer(instance={"available_trace_ids": trace_ids}).data)

    @validated_request(
        query_serializer=TraceQuerySerializer,
        parameters=[TRACE_ID_PARAMETER],
        responses={
            200: OpenApiResponse(response=contracts.Trace),
            400: OpenApiResponse(description="The timestamp hint or the encoded trace id is malformed."),
            404: OpenApiResponse(description="No trace with this id in the project."),
            429: THROTTLED_RESPONSE,
        },
        operation_id="ai_observability_traces_retrieve",
    )
    def retrieve(self, request: ValidatedRequest, pk: str, **kwargs: Any) -> Response:
        """A trace ready to render: its tree with roll-ups, timeline, totals and person, without inputs or outputs."""
        try:
            trace_id = decode_trace_id_segment(pk)
        except MalformedTraceIdSegmentError:
            return Response({"detail": "Malformed encoded trace id."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            trace = self._read(request, lambda user, hint: api.get_trace(self.team, user, trace_id, hint))
        except api.TraceNotFoundError:
            return Response({"detail": "Trace not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(trace.model_dump(mode="json", by_alias=True))
