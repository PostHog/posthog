from typing import Any

from drf_spectacular.utils import OpenApiResponse
from rest_framework import status
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request

from ...facade import api, contracts
from .trace_ids import MalformedTraceIdSegmentError, decode_trace_id_segment
from .trace_resource import THROTTLED_RESPONSE, TRACE_ID_PARAMETER, TraceResourceViewSet


class TraceEvaluationsViewSet(TraceResourceViewSet):
    @validated_request(
        parameters=[TRACE_ID_PARAMETER],
        responses={
            200: OpenApiResponse(response=contracts.TraceEvaluationResults),
            400: OpenApiResponse(description="The encoded trace id is malformed."),
            429: THROTTLED_RESPONSE,
        },
        operation_id="ai_observability_traces_evaluations_retrieve",
    )
    def list(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """A trace's evaluation results, newest first and at most 250, each with its outcome and label ready to render,
        plus a roll-up of the latest run of each evaluation on each node."""
        try:
            trace_id = decode_trace_id_segment(self.trace_segment)
        except MalformedTraceIdSegmentError:
            return Response({"detail": "Malformed encoded trace id."}, status=status.HTTP_400_BAD_REQUEST)
        results = self._read(request, lambda user, _hint: api.get_trace_evaluation_results(self.team, user, trace_id))
        return Response(results.model_dump(mode="json", by_alias=True))
