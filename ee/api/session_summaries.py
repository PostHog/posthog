import os
import re
import asyncio
from datetime import datetime
from typing import Any, cast

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.db.models import Func, IntegerField, QuerySet

import structlog
from asgiref.sync import async_to_sync
from drf_spectacular.utils import extend_schema
from loginas.utils import is_impersonated_session
from rest_framework import exceptions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer
from rest_framework.viewsets import GenericViewSet

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.clickhouse.query_tagging import Product, tag_queries
from posthog.cloud_utils import is_cloud
from posthog.event_usage import EventSource, get_event_source
from posthog.models import OrganizationMembership, Team, User
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.utils import UUID
from posthog.rate_limit import ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle
from posthog.temporal.session_replay.session_summary.workflow import execute_summarize_session
from posthog.temporal.session_replay.session_summary_group.types import SessionSummaryStreamUpdate
from posthog.temporal.session_replay.session_summary_group.workflow import execute_summarize_session_group
from posthog.utils import relative_date_parse

from ee.hogai.session_summaries.session.output_data import SessionSummarySerializer
from ee.hogai.session_summaries.session.summarize_session import ExtraSummaryContext
from ee.hogai.session_summaries.session_group.patterns import EnrichedSessionGroupSummaryPatternsList
from ee.hogai.session_summaries.session_group.summarize_session_group import (
    find_sessions_timestamps,
    partition_sessions_by_recording_existence,
)
from ee.hogai.session_summaries.tracking import (
    SummarySource,
    capture_session_summary_generated,
    capture_session_summary_started,
    generate_tracking_id,
)
from ee.hogai.session_summaries.utils import logging_session_ids
from ee.models.session_summaries import SessionGroupSummary
from ee.models.team_session_summaries_config import PRODUCT_CONTEXT_MAX_LENGTH, TeamSessionSummariesConfig

logger = structlog.get_logger(__name__)


class SessionSummariesSerializer(serializers.Serializer):
    session_ids = serializers.ListField(
        child=serializers.CharField(),
        min_length=1,
        max_length=300,
        help_text="List of session IDs to summarize (max 300)",
    )
    focus_area = serializers.CharField(
        required=False, allow_blank=True, max_length=500, help_text="Optional focus area for the summarization"
    )


_PRODUCT_CONTEXT_WRAPPER_TAG_RE = re.compile(r"</?\s*product_context\b[^>]*>", re.IGNORECASE)

# Substring used by ``execute_summarize_session`` (via the Temporal workflow) when the workflow
# finished successfully but produced no summary row — typically because ``fetch_session_data_activity``
# returned False (no events / recording too short). Kept here as a module-level constant so the coupling
# between the workflow's exception text and the API-layer classification is explicit and grep-able.
_NO_READY_SUMMARY_ERROR_SUBSTRING = "No ready summary found in DB"


class SessionSummariesConfigSerializer(serializers.ModelSerializer):
    product_context = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=PRODUCT_CONTEXT_MAX_LENGTH,
        help_text=(
            "Free-form description of the team's product, used to tailor AI-generated single-session replay "
            "summaries. Injected into the system prompt of every summary generated for this team via the "
            "replay page."
        ),
    )

    class Meta:
        model = TeamSessionSummariesConfig
        fields = ["product_context"]

    def validate_product_context(self, value: str) -> str:
        # Prevent prompt injection via the <product_context> wrapper in the summary prompt.
        return _PRODUCT_CONTEXT_WRAPPER_TAG_RE.sub("", value).strip()


class SessionSummariesViewSet(TeamAndOrgViewSetMixin, GenericViewSet):
    scope_object = "session_recording"  # Keeping recording, as Replay is the main source of info for summary, for now
    permission_classes = [IsAuthenticated]
    throttle_classes = [ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle]
    serializer_class = SessionSummariesSerializer

    @staticmethod
    def _resolve_summary_source(request: Request) -> SummarySource:
        return "mcp" if get_event_source(request) == EventSource.MCP else "api"

    def _validate_user(self, request: Request) -> User:
        if not request.user.is_authenticated:
            raise exceptions.NotAuthenticated()
        tag_queries(product=Product.SESSION_SUMMARY)
        user = cast(User, request.user)
        # Validate environment requirements
        environment_is_allowed = settings.DEBUG or is_cloud()
        has_openai_api_key = bool(os.environ.get("OPENAI_API_KEY"))
        if not environment_is_allowed or not has_openai_api_key:
            raise exceptions.ValidationError("Session summaries are only supported in PostHog Cloud")
        return user

    def _validate_input(self, request: Request) -> tuple[list[str], datetime, datetime, ExtraSummaryContext | None]:
        """Strict input validation for the group flow — needs all sessions to exist to compute timestamps."""
        session_ids, extra_summary_context = self._parse_input(request)
        min_timestamp, max_timestamp = find_sessions_timestamps(session_ids=session_ids, team=self.team)
        return session_ids, min_timestamp, max_timestamp, extra_summary_context

    def _parse_input(self, request: Request) -> tuple[list[str], ExtraSummaryContext | None]:
        """Parse and validate request body without checking session existence.

        Used by the individual flow, which surfaces "no recording" as a per-session error rather
        than failing the whole batch when one ID is bad.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session_ids = serializer.validated_data["session_ids"]
        focus_area = serializer.validated_data.get("focus_area")
        extra_summary_context = ExtraSummaryContext(focus_area=focus_area) if focus_area else None
        return session_ids, extra_summary_context

    @staticmethod
    async def _get_summary_from_progress_stream(
        session_ids: list[str],
        user: User,
        team: Team,
        min_timestamp: datetime,
        max_timestamp: datetime,
        extra_summary_context: ExtraSummaryContext | None = None,
    ) -> EnrichedSessionGroupSummaryPatternsList:
        """Helper function to consume the async generator and return a summary"""
        results: list[tuple[SessionSummaryStreamUpdate, tuple[EnrichedSessionGroupSummaryPatternsList, str] | str]] = []
        async for update_type, data in execute_summarize_session_group(
            session_ids=session_ids,
            user=user,
            team=team,
            min_timestamp=min_timestamp,
            max_timestamp=max_timestamp,
            summary_title="Group summary",  # Generic name, as no user input is provided (vs the chat)
            extra_summary_context=extra_summary_context,
        ):
            if update_type == SessionSummaryStreamUpdate.SESSION_PROGRESS:
                continue  # The old consumers of this API don't expect this update type, as it's a PostHog AI chat feature
            assert not isinstance(data, dict)
            results.append((update_type, data))
        if not results:
            error_message = f"No summaries were generated for the provided sessions (session ids: {logging_session_ids(session_ids)})"
            logger.exception(error_message)
            raise exceptions.APIException(error_message)
        # The last item in the result should be the summary, if not - raise an exception
        last_result = results[-1]
        summary_iteration = last_result[-1]
        if not isinstance(summary_iteration, tuple) or len(summary_iteration) != 2:
            error_message = f"Unexpected result type ({type(summary_iteration)}) when generating summaries (session ids: {logging_session_ids(session_ids)}): {results}"
            logger.exception(error_message)
            raise exceptions.APIException(error_message)
        summary, _ = summary_iteration
        if not summary or not isinstance(summary, EnrichedSessionGroupSummaryPatternsList):
            error_message = f"Unexpected result type ({type(summary)}) when generating summaries (session ids: {logging_session_ids(session_ids)}): {results}"
            logger.exception(error_message)
            raise exceptions.APIException(error_message)
        return summary

    @extend_schema(
        operation_id="create_session_summaries",
        description="Generate AI summary for a group of session recordings to find patterns and generate a notebook.",
        request=SessionSummariesSerializer,
    )
    @action(methods=["POST"], detail=False, required_scopes=["session_recording:read"])
    def create_session_summaries(self, request: Request, **kwargs) -> Response:
        user = self._validate_user(request)
        session_ids, min_timestamp, max_timestamp, extra_summary_context = self._validate_input(request)
        summary_source = self._resolve_summary_source(request)
        tracking_id = (
            generate_tracking_id()
        )  # Unified id to combine start/end, calculate duration, check success rate and so
        capture_session_summary_started(
            user=user,
            team=self.team,
            tracking_id=tracking_id,
            summary_source=summary_source,
            summary_type="group",
            session_ids=session_ids,
        )
        # Summarize provided sessions
        try:
            summary = async_to_sync(self._get_summary_from_progress_stream)(
                session_ids=session_ids,
                user=user,
                team=self.team,
                min_timestamp=min_timestamp,
                max_timestamp=max_timestamp,
                extra_summary_context=extra_summary_context,
            )
            capture_session_summary_generated(
                user=user,
                team=self.team,
                tracking_id=tracking_id,
                summary_source=summary_source,
                summary_type="group",
                session_ids=session_ids,
                success=True,
            )
            return Response(summary.model_dump(exclude_none=True, mode="json"), status=status.HTTP_200_OK)
        except Exception as err:
            logger.exception(
                f"Failed to generate session group summary for sessions {logging_session_ids(session_ids)} from team {self.team.id} by user {user.id}: {err}",
                team_id=self.team.id,
                user_id=user.id,
                error=str(err),
            )
            capture_session_summary_generated(
                user=user,
                team=self.team,
                tracking_id=tracking_id,
                summary_source=summary_source,
                summary_type="group",
                session_ids=session_ids,
                success=False,
                error_type=type(err).__name__,
                error_message=str(err),
            )
            raise exceptions.APIException(
                f"Failed to generate session summaries for sessions {logging_session_ids(session_ids)}. Please try again later."
            )

    @staticmethod
    def _classify_summary_error(err: BaseException) -> tuple[str, str]:
        """Map an internal exception to a (error_type, error_message) pair returned to the caller.

        We don't surface raw exception strings — they leak internals and aren't actionable. The handful of
        types below cover the failure modes the API layer can observe today; everything else falls through to
        a generic ``summary_failed``.
        """
        message = str(err)
        # Raised by execute_summarize_session when the workflow finished but no summary row was written —
        # in practice that means fetch_session_data_activity returned False (no events / too short).
        if isinstance(err, ValueError) and _NO_READY_SUMMARY_ERROR_SUBSTRING in message:
            return (
                "no_events_or_too_short",
                "Recording has no usable events to summarize (typically because it is too short).",
            )
        return ("summary_failed", "Failed to generate a summary for this session. Please try again later.")

    @staticmethod
    async def _summarize_session(
        session_id: str,
        user: User,
        team: Team,
        extra_summary_context: ExtraSummaryContext | None = None,
    ) -> SessionSummarySerializer | Exception:
        try:
            summary_raw = await execute_summarize_session(
                session_id=session_id,
                user=user,
                team=team,
                extra_summary_context=extra_summary_context,
            )
            summary = SessionSummarySerializer(data=summary_raw)
            summary.is_valid(raise_exception=True)
            return summary
        except Exception as err:
            # Let caller handle the error
            return err

    async def _get_individual_summaries(
        self,
        session_ids: list[str],
        user: User,
        team: Team,
        extra_summary_context: ExtraSummaryContext | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Run per-session summaries concurrently. Returns one entry per requested session.

        Successful entries match the existing summary shape (``segments``, ``key_actions``, etc.). Failed
        entries return ``{"error": <type>, "error_message": <human-readable>}`` so callers can tell
        "skipped on purpose" from "tool broke" without re-invoking with singletons.
        """
        tasks = {}
        async with asyncio.TaskGroup() as tg:
            for session_id in session_ids:
                tasks[session_id] = tg.create_task(
                    self._summarize_session(
                        session_id=session_id,
                        user=user,
                        team=team,
                        extra_summary_context=extra_summary_context,
                    )
                )
        results: dict[str, dict[str, Any]] = {}
        for session_id, task in tasks.items():
            res: SessionSummarySerializer | Exception = task.result()
            if isinstance(res, Exception):
                error_type, error_message = self._classify_summary_error(res)
                logger.exception(
                    f"Failed to generate individual session summary for session {session_id} from team {team.pk} by user {user.id}: {res}",
                    team_id=team.pk,
                    user_id=user.id,
                    error_type=error_type,
                )
                results[session_id] = {"error": error_type, "error_message": error_message}
            else:
                results[session_id] = res.data
        return results

    @extend_schema(
        operation_id="create_session_summaries_individually",
        description="Generate AI individual summary for each session, without grouping.",
        request=SessionSummariesSerializer,
        tags=["replay"],
    )
    @action(methods=["POST"], detail=False, required_scopes=["session_recording:read"])
    def create_session_summaries_individually(self, request: Request, **kwargs) -> Response:
        user = self._validate_user(request)
        session_ids, extra_summary_context = self._parse_input(request)
        summary_source = self._resolve_summary_source(request)
        # Don't fail the whole batch if some sessions have no recording — partition them out and surface
        # each missing session as a per-session error in the response (matches the partial-success contract
        # this endpoint already had for downstream summary failures).
        found_session_ids, missing_session_ids = partition_sessions_by_recording_existence(
            session_ids=session_ids, team=self.team
        )
        tracking_id = generate_tracking_id()
        capture_session_summary_started(
            user=user,
            team=self.team,
            tracking_id=tracking_id,
            summary_source=summary_source,
            summary_type="single",
            session_ids=session_ids,
        )
        # Summarize provided sessions individually
        try:
            summaries: dict[str, dict[str, Any]] = {}
            if found_session_ids:
                summaries.update(
                    async_to_sync(self._get_individual_summaries)(
                        session_ids=found_session_ids,
                        user=user,
                        team=self.team,
                        extra_summary_context=extra_summary_context,
                    )
                )
            for missing_id in missing_session_ids:
                summaries[missing_id] = {
                    "error": "recording_not_found",
                    "error_message": (
                        "No recording found for this session ID. The recording may not have been captured, "
                        "may have expired, or may belong to a different team."
                    ),
                }
            capture_session_summary_generated(
                user=user,
                team=self.team,
                tracking_id=tracking_id,
                summary_source=summary_source,
                summary_type="single",
                session_ids=session_ids,
                success=True,
            )
            return Response(summaries, status=status.HTTP_200_OK)
        except Exception as err:
            logger.exception(
                f"Failed to generate individual session summaries for sessions {logging_session_ids(session_ids)} from team {self.team.id} by user {user.id}: {err}",
                team_id=self.team.id,
                user_id=user.id,
                error=str(err),
            )
            capture_session_summary_generated(
                user=user,
                team=self.team,
                tracking_id=tracking_id,
                summary_source=summary_source,
                summary_type="single",
                session_ids=session_ids,
                success=False,
                error_type=type(err).__name__,
                error_message=str(err),
            )
            raise exceptions.APIException(
                f"Failed to generate individual session summaries for sessions {logging_session_ids(session_ids)}. Please try again later."
            )

    @extend_schema(
        methods=["GET"],
        operation_id="retrieve_session_summaries_config",
        description=(
            "Retrieve the team's session summaries configuration "
            "(product context used to tailor single-session replay summaries)."
        ),
        responses=SessionSummariesConfigSerializer,
    )
    @extend_schema(
        operation_id="update_session_summaries_config",
        description=(
            "Update the team's session summaries configuration "
            "(product context used to tailor single-session replay summaries)."
        ),
        request=SessionSummariesConfigSerializer,
        responses=SessionSummariesConfigSerializer,
        methods=["PATCH"],
    )
    @action(methods=["GET", "PATCH"], detail=False, serializer_class=SessionSummariesConfigSerializer)
    def config(self, request: Request, **kwargs) -> Response:
        team_config = get_or_create_team_extension(self.team, TeamSessionSummariesConfig)
        if request.method == "PATCH":
            effective_level = self.user_permissions.team(self.team).effective_membership_level
            if effective_level is None or effective_level < OrganizationMembership.Level.ADMIN:
                raise exceptions.PermissionDenied("Only project admins can modify the session summaries configuration.")
            serializer = SessionSummariesConfigSerializer(team_config, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
        else:
            serializer = SessionSummariesConfigSerializer(team_config)
        return Response(serializer.data, status=status.HTTP_200_OK)


class SessionGroupSummaryMinimalSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    session_count = serializers.SerializerMethodField()

    class Meta:
        model = SessionGroupSummary
        fields = [
            "id",
            "title",
            "session_count",
            "created_at",
            "created_by",
        ]
        read_only_fields = fields

    def get_session_count(self, obj: SessionGroupSummary) -> int:
        # Use annotated value if available (from list action), otherwise calculate
        if hasattr(obj, "session_count"):
            return int(obj.session_count or 0)
        return len(obj.session_ids) if obj.session_ids else 0


class SessionGroupSummarySerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = SessionGroupSummary
        fields = [
            "id",
            "title",
            "session_ids",
            "summary",
            "extra_summary_context",
            "run_metadata",
            "created_at",
            "created_by",
            "team",
        ]
        read_only_fields = fields


def log_session_summary_group_activity(
    activity: str,
    summary: SessionGroupSummary,
    organization_id: UUID | None,
    team_id: int,
    user: User,
    was_impersonated: bool,
    changes: list[Change] | None = None,
) -> None:
    log_activity(
        organization_id=organization_id,
        team_id=team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=summary.id,
        scope="SessionGroupSummary",
        activity=activity,
        detail=Detail(changes=changes, name=summary.title),
    )


@extend_schema(
    description="API for retrieving and managing stored group session summaries.",
)
class SessionGroupSummaryViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "session_recording"
    queryset = SessionGroupSummary.objects.all()
    lookup_field = "id"

    def get_serializer_class(self) -> type[BaseSerializer]:
        return SessionGroupSummaryMinimalSerializer if self.action == "list" else SessionGroupSummarySerializer

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        queryset = queryset.filter(team=self.team)
        queryset = queryset.select_related("created_by", "team")
        if self.action == "list":
            # Only load fields needed for list view
            queryset = queryset.only("id", "title", "session_ids", "created_at", "created_by", "team")
            # Annotate with session_count for sorting
            queryset = queryset.annotate(
                session_count=Func("session_ids", function="CARDINALITY", output_field=IntegerField())
            )
            queryset = self._filter_list_request(self.request, queryset)
        order = self.request.GET.get("order", None)
        if order:
            queryset = queryset.order_by(order)
        else:
            queryset = queryset.order_by("-created_at")

        return queryset

    def _filter_list_request(self, request: Request, queryset: QuerySet) -> QuerySet:
        filters = request.GET.dict()
        for key in filters:
            value = filters.get(key, None)
            if key == "created_by":
                queryset = queryset.filter(created_by__uuid=value)
            elif key == "date_from" and isinstance(value, str):
                queryset = queryset.filter(created_at__gt=relative_date_parse(value, self.team.timezone_info))
            elif key == "date_to" and isinstance(value, str):
                queryset = queryset.filter(created_at__lt=relative_date_parse(value, self.team.timezone_info))
            elif key == "search":
                queryset = queryset.filter(title__icontains=value)
        return queryset

    def perform_destroy(self, instance: SessionGroupSummary) -> None:
        if isinstance(self.request.user, AnonymousUser):
            # Don't log activity for anonymous users
            raise exceptions.PermissionDenied("User is not allowed to delete session summaries")
        log_session_summary_group_activity(
            activity="deleted",
            summary=instance,
            organization_id=self.request.user.current_organization_id,
            team_id=self.team_id,
            user=self.request.user,
            was_impersonated=is_impersonated_session(self.request),
        )
        super().perform_destroy(instance)
