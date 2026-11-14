from typing import Any

from drf_spectacular.utils import OpenApiResponse
from rest_framework import status
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request

from ...facade import api, contracts
from .trace_ids import MalformedTraceIdSegmentError, decode_trace_id_segment
from .trace_resource import TRACE_ID_PARAMETER, TraceResourceViewSet, request_user


class TraceReviewStatusViewSet(TraceResourceViewSet):
    @validated_request(
        parameters=[TRACE_ID_PARAMETER],
        responses={
            200: OpenApiResponse(response=contracts.TraceReviewStatus),
            400: OpenApiResponse(description="The encoded trace id is malformed."),
        },
        operation_id="ai_observability_traces_review_retrieve",
    )
    def list(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """The trace's human review with its scores ready to render, and the review queue the trace waits in."""
        try:
            trace_id = decode_trace_id_segment(self.trace_segment)
        except MalformedTraceIdSegmentError:
            return Response({"detail": "Malformed encoded trace id."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            api.get_trace_review_status(self.team, request_user(request), trace_id).model_dump(
                mode="json", by_alias=True
            )
        )
