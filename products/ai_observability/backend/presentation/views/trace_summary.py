from collections.abc import Callable
from typing import Any

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.models.user import User
from posthog.rate_limit import (
    AIObservabilitySummarizationBurstThrottle,
    AIObservabilitySummarizationDailyThrottle,
    AIObservabilitySummarizationSustainedThrottle,
)

from ...facade import api, contracts
from .trace_ids import MalformedTraceIdSegmentError, decode_trace_id_segment
from .trace_resource import TRACE_ID_PARAMETER, TraceQuerySerializer, TraceResourceViewSet

NOT_APPROVED_DETAIL = "AI data processing must be approved by your organization before using summaries."
NOT_A_USER_DETAIL = "Summaries are only available to signed-in users and their personal API keys."


class TraceSummaryRequestSerializer(serializers.Serializer):
    regenerate = serializers.BooleanField(
        default=False, help_text="Replace a ready summary with a new one. A pending summary is never replaced."
    )


class TraceSummaryViewSet(TraceResourceViewSet):
    scope_object_read_actions = ["list"]
    scope_object_write_actions = ["create"]

    def get_throttles(self) -> list[BaseThrottle]:
        # Shares the legacy summary endpoint's scopes, so a user has one summarization budget. Reads poll, so only
        # requests spend it.
        if self.action == "create":
            return [
                *super().get_throttles(),
                AIObservabilitySummarizationBurstThrottle(),
                AIObservabilitySummarizationSustainedThrottle(),
                AIObservabilitySummarizationDailyThrottle(),
            ]
        return super().get_throttles()

    @validated_request(
        parameters=[TRACE_ID_PARAMETER],
        responses={
            200: OpenApiResponse(response=contracts.TraceSummary),
            400: OpenApiResponse(description="The encoded trace id is malformed."),
            403: OpenApiResponse(description="The organization has not approved AI data processing."),
            404: OpenApiResponse(description="No summary of this trace that this user may see."),
        },
        operation_id="ai_observability_traces_summary_retrieve",
    )
    def list(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """The trace's AI summary: pending while it is written, then ready with links to its steps, or failed with the reason. A summary is kept for an hour and shown only to users whose property access matches the requester's."""
        return self._summary_response(request, lambda user, trace_id: api.get_trace_summary(self.team, user, trace_id))

    @validated_request(
        request_serializer=TraceSummaryRequestSerializer,
        query_serializer=TraceQuerySerializer,
        parameters=[TRACE_ID_PARAMETER],
        responses={
            200: OpenApiResponse(response=contracts.TraceSummary, description="A ready or failed summary."),
            202: OpenApiResponse(response=contracts.TraceSummary, description="The summary is being written."),
            400: OpenApiResponse(description="The timestamp hint or the encoded trace id is malformed."),
            403: OpenApiResponse(description="The organization has not approved AI data processing."),
            429: OpenApiResponse(description="Too many summaries requested."),
        },
        operation_id="ai_observability_traces_summary_create",
    )
    def create(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """Request an AI summary of the trace. A ready summary is returned as is unless `regenerate` is set; otherwise a job starts writing one, or the request joins the job already writing it."""
        return self._summary_response(
            request,
            lambda user, trace_id: api.request_trace_summary(
                self.team,
                user,
                trace_id,
                request.validated_query_data.get("timestamp_hint"),
                regenerate=request.validated_data["regenerate"],
            ),
            pending_status=status.HTTP_202_ACCEPTED,
        )

    def _summary_response(
        self,
        request: ValidatedRequest,
        call: Callable[[User, str], contracts.TraceSummary],
        *,
        pending_status: int = status.HTTP_200_OK,
    ) -> Response:
        try:
            trace_id = decode_trace_id_segment(self.trace_segment)
        except MalformedTraceIdSegmentError:
            return Response({"detail": "Malformed encoded trace id."}, status=status.HTTP_400_BAD_REQUEST)
        if not isinstance(request.user, User):
            return Response({"detail": NOT_A_USER_DETAIL}, status=status.HTTP_403_FORBIDDEN)
        try:
            summary = call(request.user, trace_id)
        except api.AIDataProcessingNotApprovedError:
            return Response({"detail": NOT_APPROVED_DETAIL}, status=status.HTTP_403_FORBIDDEN)
        except api.TraceSummaryNotFoundError:
            return Response({"detail": "No summary yet."}, status=status.HTTP_404_NOT_FOUND)
        response_status = pending_status if summary.status == "pending" else status.HTTP_200_OK
        return Response(summary.model_dump(mode="json", by_alias=True), status=response_status)
