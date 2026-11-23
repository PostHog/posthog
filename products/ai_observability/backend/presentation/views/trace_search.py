from typing import Any

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, status
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request

from ...facade import api, contracts
from .trace_ids import MalformedTraceIdSegmentError, decode_trace_id_segment
from .trace_resource import THROTTLED_RESPONSE, TRACE_ID_PARAMETER, TraceQuerySerializer, TraceResourceViewSet


class TraceSearchQuerySerializer(TraceQuerySerializer):
    q = serializers.CharField(max_length=200, help_text="The text to find in the trace's steps, ignoring case.")


class TraceSearchViewSet(TraceResourceViewSet):
    @validated_request(
        query_serializer=TraceSearchQuerySerializer,
        parameters=[TRACE_ID_PARAMETER],
        responses={
            200: OpenApiResponse(response=contracts.TraceSearchResults),
            400: OpenApiResponse(
                description="The query is missing or too long, or the timestamp hint or the encoded trace id is malformed."
            ),
            404: OpenApiResponse(description="No trace with this id in the project."),
            429: THROTTLED_RESPONSE,
            504: OpenApiResponse(description="The search took too long on this trace."),
        },
        operation_id="ai_observability_traces_search_retrieve",
    )
    def list(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """Find text in a trace's steps: each matching step in tree order with its number of occurrences."""
        try:
            trace_id = decode_trace_id_segment(self.trace_segment)
        except MalformedTraceIdSegmentError:
            return Response({"detail": "Malformed encoded trace id."}, status=status.HTTP_400_BAD_REQUEST)
        query = request.validated_query_data["q"]
        try:
            results = self._read(request, lambda user, hint: api.search_trace(self.team, user, trace_id, query, hint))
        except api.TraceNotFoundError:
            return Response({"detail": "Trace not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(results.model_dump(mode="json", by_alias=True))
