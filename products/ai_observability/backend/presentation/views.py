from collections.abc import Callable
from datetime import datetime
from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle

from posthog.api.documentation import _FallbackSerializer
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.models.user import User
from posthog.permissions import get_authenticator_scopes
from posthog.rate_limit import (
    AIObservabilitySummarizationBurstThrottle,
    AIObservabilitySummarizationDailyThrottle,
    AIObservabilitySummarizationSustainedThrottle,
)
from posthog.scopes import scopes_not_covered

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


TRACE_ID_PARAMETER = OpenApiParameter(
    "id",
    OpenApiTypes.STR,
    OpenApiParameter.PATH,
    description="The trace id, sent as the unpadded base64url encoding of its UTF-8 bytes.",
)
NODE_ID_PARAMETER = OpenApiParameter(
    "node_id",
    OpenApiTypes.STR,
    OpenApiParameter.PATH,
    description="The node id, sent as the unpadded base64url encoding of its UTF-8 bytes. The root node's id is the trace id.",
)
SURVEY_RESPONSE_SCOPES = ["survey:read", "query:read"]


def _token_allows(request: ValidatedRequest, required_scopes: list[str]) -> bool:
    """True for session auth, which carries no scopes."""
    scopes = get_authenticator_scopes(getattr(request, "successful_authenticator", None))
    return scopes is None or "*" in scopes or not scopes_not_covered(scopes, required_scopes)


THROTTLED_RESPONSE = OpenApiResponse(description="Too many queries are running for the project or organization.")
NOT_APPROVED_DETAIL = "AI data processing must be approved by your organization before using summaries."
NOT_A_USER_DETAIL = "Summaries are only available to signed-in users and their personal API keys."


class TraceSummaryRequestSerializer(serializers.Serializer):
    regenerate = serializers.BooleanField(
        default=False, help_text="Replace a ready summary with a new one. A pending summary is never replaced."
    )


class TraceViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "llm_analytics"
    scope_object_read_actions = ["retrieve", "node", "evaluations", "feedback", "summary"]
    scope_object_write_actions = ["request_summary"]
    # Traces are project-wide data, so a grant on a single llm_analytics object must not open them.
    requires_resource_level_access = True
    serializer_class = _FallbackSerializer

    def _read[T](self, request: ValidatedRequest, read: Callable[[User | None, datetime | None], T]) -> T:
        tag_queries(feature=Feature.QUERY)
        user = request.user if isinstance(request.user, User) else None
        with query_concurrency_slots(self.team):
            return read(user, request.validated_query_data.get("timestamp_hint"))

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

    @validated_request(
        query_serializer=TraceQuerySerializer,
        parameters=[TRACE_ID_PARAMETER, NODE_ID_PARAMETER],
        responses={
            200: OpenApiResponse(response=contracts.TraceNodeDetail),
            400: OpenApiResponse(description="The timestamp hint or an encoded id is malformed."),
            404: OpenApiResponse(description="No node with this id in the trace."),
            429: THROTTLED_RESPONSE,
        },
        operation_id="ai_observability_traces_nodes_retrieve",
    )
    @action(detail=True, methods=["GET"], url_path=r"nodes/(?P<node_id>[A-Za-z0-9_-]+)")
    def node(self, request: ValidatedRequest, pk: str, node_id: str, **kwargs: Any) -> Response:
        """One node of a trace: its event properties as ingested, the keys that hold its input, output and tools, its error and its metadata."""
        try:
            trace_id = decode_trace_id_segment(pk)
            decoded_node_id = decode_trace_id_segment(node_id)
        except MalformedTraceIdSegmentError:
            return Response({"detail": "Malformed encoded id."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            node = self._read(
                request, lambda user, hint: api.get_trace_node(self.team, user, trace_id, decoded_node_id, hint)
            )
        except api.TraceNodeNotFoundError:
            return Response({"detail": "Node not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(node.model_dump(mode="json", by_alias=True))

    @validated_request(
        parameters=[TRACE_ID_PARAMETER],
        responses={
            200: OpenApiResponse(response=contracts.TraceEvaluationResults),
            400: OpenApiResponse(description="The encoded trace id is malformed."),
            429: THROTTLED_RESPONSE,
        },
        operation_id="ai_observability_traces_evaluations_retrieve",
    )
    @action(detail=True, methods=["GET"], url_path="evaluations")
    def evaluations(self, request: ValidatedRequest, pk: str, **kwargs: Any) -> Response:
        """A trace's evaluation results, newest first and at most 250, each with its outcome and label ready to render,
        plus a roll-up of the latest run of each evaluation on each node."""
        try:
            trace_id = decode_trace_id_segment(pk)
        except MalformedTraceIdSegmentError:
            return Response({"detail": "Malformed encoded trace id."}, status=status.HTTP_400_BAD_REQUEST)
        results = self._read(request, lambda user, _hint: api.get_trace_evaluation_results(self.team, user, trace_id))
        return Response(results.model_dump(mode="json", by_alias=True))

    @validated_request(
        query_serializer=TraceQuerySerializer,
        parameters=[TRACE_ID_PARAMETER],
        responses={
            200: OpenApiResponse(response=contracts.TraceFeedback),
            400: OpenApiResponse(description="The timestamp hint or the encoded trace id is malformed."),
            429: THROTTLED_RESPONSE,
        },
        operation_id="ai_observability_traces_feedback_retrieve",
    )
    @action(detail=True, methods=["GET"], url_path="feedback")
    def feedback(self, request: ValidatedRequest, pk: str, **kwargs: Any) -> Response:
        """End-user feedback on a trace: scores and comments from its feedback events, survey responses linked to it, and surveys shown but not answered."""
        try:
            trace_id = decode_trace_id_segment(pk)
        except MalformedTraceIdSegmentError:
            return Response({"detail": "Malformed encoded trace id."}, status=status.HTTP_400_BAD_REQUEST)
        # Survey responses are survey data, so a token also needs the scopes the survey responses endpoint requires.
        include_surveys = _token_allows(request, SURVEY_RESPONSE_SCOPES)
        feedback = self._read(
            request,
            lambda user, hint: api.get_trace_feedback(self.team, user, trace_id, hint, include_surveys=include_surveys),
        )
        return Response(feedback.model_dump(mode="json", by_alias=True))

    def get_throttles(self) -> list[BaseThrottle]:
        # Shares the legacy summary endpoint's scopes, so a user has one summarization budget. Reads poll, so only
        # requests spend it.
        if self.action == "request_summary":
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
    @action(detail=True, methods=["GET"], url_path="summary")
    def summary(self, request: ValidatedRequest, pk: str, **kwargs: Any) -> Response:
        """The trace's AI summary: pending while it is written, then ready with links to its steps, or failed with the reason. A summary is kept for an hour and shown only to users whose property access matches the requester's."""
        return self._summary_response(
            request, pk, lambda user, trace_id: api.get_trace_summary(self.team, user, trace_id)
        )

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
    @summary.mapping.post
    def request_summary(self, request: ValidatedRequest, pk: str, **kwargs: Any) -> Response:
        """Request an AI summary of the trace. A ready summary is returned as is unless `regenerate` is set; otherwise a job starts writing one, or the request joins the job already writing it."""
        return self._summary_response(
            request,
            pk,
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
        pk: str,
        call: Callable[[User, str], contracts.TraceSummary],
        *,
        pending_status: int = status.HTTP_200_OK,
    ) -> Response:
        try:
            trace_id = decode_trace_id_segment(pk)
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
