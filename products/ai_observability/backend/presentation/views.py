from collections.abc import Callable
from datetime import datetime
from functools import partial
from typing import Any

from django.db import transaction
from django.http import HttpResponseBase

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle

from posthog.api.documentation import _FallbackSerializer
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.event_usage import report_user_action
from posthog.helpers.impersonation import is_impersonated
from posthog.models.user import User
from posthog.permissions import PostHogFeatureFlagPermission, get_authenticator_scopes
from posthog.rate_limit import (
    AIObservabilitySummarizationBurstThrottle,
    AIObservabilitySummarizationDailyThrottle,
    AIObservabilitySummarizationSustainedThrottle,
)
from posthog.scopes import scopes_not_covered

from products.engineering_analytics.backend.facade.contracts import ENGINEERING_ANALYTICS_FEATURE_FLAG
from products.exports.backend.facade.api import get_export_asset, get_export_asset_content_response

from ..facade import api, contracts
from .query_concurrency import query_concurrency_slots
from .trace_exports import TraceExportRateThrottle
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


class TraceClustersQuerySerializer(serializers.Serializer):
    created_at = serializers.DateTimeField(
        help_text="When the trace started, as the trace resource's createdAt. Bounds which clustering runs are read."
    )

    def validate_created_at(self, value: datetime) -> datetime:
        if not api.is_usable_trace_start(value):
            raise serializers.ValidationError("Trace start is out of range.")
        return value


class TraceSearchQuerySerializer(TraceQuerySerializer):
    q = serializers.CharField(max_length=200, help_text="The text to find in the trace's steps, ignoring case.")


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


EXPORT_ID_PARAMETER = OpenApiParameter(
    "export_id", OpenApiTypes.INT, OpenApiParameter.PATH, description="The export id the create call returned."
)
EXPORT_NOT_FOUND_RESPONSE = OpenApiResponse(description="You have no export with this id for this trace.")


# Gives the export request body its own schema, apart from the trace read's query parameters.
class TraceExportCreateSerializer(TraceQuerySerializer):
    pass


class TraceExportErrorSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Why the file cannot be downloaded yet.")


class TraceViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "llm_analytics"
    scope_object_read_actions = [
        "retrieve",
        "node",
        "evaluations",
        "clusters",
        "feedback",
        "search",
        "summary",
        "exports",
        "export_status",
        "export_content",
    ]
    scope_object_write_actions = ["request_summary"]
    # Traces are project-wide data, so a grant on a single llm_analytics object must not open them.
    requires_resource_level_access = True
    serializer_class = _FallbackSerializer
    permission_classes = [PostHogFeatureFlagPermission]
    # Other actions are absent from the map, so the permission lets them through.
    posthog_feature_flag = {ENGINEERING_ANALYTICS_FEATURE_FLAG: ["pull_request"]}

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
        query_serializer=TraceClustersQuerySerializer,
        parameters=[TRACE_ID_PARAMETER],
        responses={
            200: OpenApiResponse(response=contracts.TraceClusters),
            400: OpenApiResponse(description="The created_at parameter or the encoded trace id is malformed."),
            429: THROTTLED_RESPONSE,
        },
        operation_id="ai_observability_traces_clusters_retrieve",
    )
    @action(
        detail=True,
        methods=["GET"],
        url_path="clusters",
        required_scopes=["llm_analytics:read", "ai_observability_clusters:read"],
    )
    def clusters(self, request: ValidatedRequest, pk: str, **kwargs: Any) -> Response:
        """The clusters that list this trace, from the newest scheduled run of each clustering job that lists it."""
        try:
            trace_id = decode_trace_id_segment(pk)
        except MalformedTraceIdSegmentError:
            return Response({"detail": "Malformed encoded trace id."}, status=status.HTTP_400_BAD_REQUEST)
        created_at = request.validated_query_data["created_at"]
        clusters = self._read(
            request, lambda user, _hint: api.get_trace_clusters(self.team, user, trace_id, created_at)
        )
        return Response(clusters.model_dump(mode="json", by_alias=True))

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
    @action(detail=True, methods=["GET"], url_path="search")
    def search(self, request: ValidatedRequest, pk: str, **kwargs: Any) -> Response:
        """Find text in a trace's steps: each matching step in tree order with its number of occurrences."""
        try:
            trace_id = decode_trace_id_segment(pk)
        except MalformedTraceIdSegmentError:
            return Response({"detail": "Malformed encoded trace id."}, status=status.HTTP_400_BAD_REQUEST)
        query = request.validated_query_data["q"]
        try:
            results = self._read(request, lambda user, hint: api.search_trace(self.team, user, trace_id, query, hint))
        except api.TraceNotFoundError:
            return Response({"detail": "Trace not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(results.model_dump(mode="json", by_alias=True))

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

    @validated_request(
        query_serializer=TraceQuerySerializer,
        parameters=[TRACE_ID_PARAMETER],
        responses={
            200: OpenApiResponse(response=contracts.TracePullRequestLookup),
            400: OpenApiResponse(description="The timestamp hint or the encoded trace id is malformed."),
            403: OpenApiResponse(
                description="The engineering-analytics feature flag is off for the project, or the API key lacks a scope."
            ),
            429: THROTTLED_RESPONSE,
        },
        operation_id="ai_observability_traces_pull_request_retrieve",
    )
    @action(
        detail=True,
        methods=["GET"],
        # The read opens engineering analytics data, so a key needs that product's scope as well.
        required_scopes=["llm_analytics:read", "engineering_analytics:read"],
    )
    def pull_request(self, request: ValidatedRequest, pk: str, **kwargs: Any) -> Response:
        """The pull request the trace's git branch belongs to, from engineering analytics."""
        try:
            trace_id = decode_trace_id_segment(pk)
        except MalformedTraceIdSegmentError:
            return Response({"detail": "Malformed encoded trace id."}, status=status.HTTP_400_BAD_REQUEST)
        lookup = self._read(
            request,
            lambda user, hint: api.get_trace_pull_request(self.team, user, self.user_access_control, trace_id, hint),
        )
        return Response(lookup.model_dump(mode="json", by_alias=True))

    @validated_request(
        request_serializer=TraceExportCreateSerializer,
        parameters=[TRACE_ID_PARAMETER],
        responses={
            201: OpenApiResponse(response=contracts.TraceExport),
            400: OpenApiResponse(description="The timestamp hint or the encoded trace id is malformed."),
            429: OpenApiResponse(description="Too many exports were requested."),
        },
        operation_id="ai_observability_traces_exports_create",
    )
    @action(detail=True, methods=["POST"], url_path="exports", throttle_classes=[TraceExportRateThrottle])
    def exports(self, request: ValidatedRequest, pk: str, **kwargs: Any) -> Response:
        """Starts writing the trace and every node, inputs and outputs included, to a JSON file. Poll the export until it completes, then download it."""
        try:
            trace_id = decode_trace_id_segment(pk)
        except MalformedTraceIdSegmentError:
            return Response({"detail": "Malformed encoded trace id."}, status=status.HTTP_400_BAD_REQUEST)
        export = api.create_trace_export(
            self.team,
            _user(request),
            trace_id,
            request.validated_data.get("timestamp_hint"),
            was_impersonated=is_impersonated(request),
        )
        return Response(export.model_dump(mode="json", by_alias=True), status=status.HTTP_201_CREATED)

    @validated_request(
        parameters=[TRACE_ID_PARAMETER, EXPORT_ID_PARAMETER],
        responses={
            200: OpenApiResponse(response=contracts.TraceExport),
            400: OpenApiResponse(description="The encoded trace id is malformed."),
            404: EXPORT_NOT_FOUND_RESPONSE,
        },
        operation_id="ai_observability_traces_exports_retrieve",
    )
    @action(detail=True, methods=["GET"], url_path=r"exports/(?P<export_id>\d+)")
    def export_status(self, request: ValidatedRequest, pk: str, export_id: str, **kwargs: Any) -> Response:
        """The state of one of your exports of this trace."""
        try:
            export = self._trace_export(request, pk, export_id)
        except MalformedTraceIdSegmentError:
            return Response({"detail": "Malformed encoded trace id."}, status=status.HTTP_400_BAD_REQUEST)
        except api.TraceExportNotFoundError:
            return Response({"detail": "Export not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(export.model_dump(mode="json", by_alias=True))

    @extend_schema(
        parameters=[TRACE_ID_PARAMETER, EXPORT_ID_PARAMETER],
        responses={
            (200, "application/json"): OpenApiResponse(response=contracts.TraceExportFile),
            400: OpenApiResponse(description="The encoded trace id is malformed."),
            404: EXPORT_NOT_FOUND_RESPONSE,
            409: OpenApiResponse(
                response=TraceExportErrorSerializer, description="The export is still being written, or failed."
            ),
        },
        operation_id="ai_observability_traces_exports_content_retrieve",
    )
    @action(detail=True, methods=["GET"], url_path=r"exports/(?P<export_id>\d+)/content")
    def export_content(self, request: Request, pk: str, export_id: str, **kwargs: Any) -> HttpResponseBase:
        """Downloads a completed export as a JSON file."""
        try:
            export = self._trace_export(request, pk, export_id)
        except MalformedTraceIdSegmentError:
            return Response({"detail": "Malformed encoded trace id."}, status=status.HTTP_400_BAD_REQUEST)
        except api.TraceExportNotFoundError:
            return Response({"detail": "Export not found."}, status=status.HTTP_404_NOT_FOUND)
        asset = get_export_asset(team_id=self.team.pk, asset_id=export.id)
        if export.status != "complete" or asset is None:
            detail = export.exception or "The export is still being prepared."
            return Response({"detail": detail}, status=status.HTTP_409_CONFLICT)
        response = get_export_asset_content_response(asset=asset, download=True)
        transaction.on_commit(
            partial(
                report_user_action,
                request.user,
                "llma trace export downloaded",
                {"export_id": export.id},
                team=self.team,
                request=request,
            ),
            robust=True,
        )
        return response

    def _trace_export(self, request: Request, pk: str, export_id: str) -> contracts.TraceExport:
        return api.get_trace_export(self.team, _user(request), decode_trace_id_segment(pk), int(export_id))


def _user(request: Request) -> User:
    # An export runs later as the user who asked for it, so unlike a trace read it cannot go without one.
    if not isinstance(request.user, User):
        raise NotAuthenticated()
    return request.user
