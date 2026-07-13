import os
import re
import json
import uuid
import asyncio
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any, cast

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.db.models import Func, IntegerField, QuerySet, Subquery
from django.db.models.fields.json import KeyTransform
from django.http import StreamingHttpResponse

import structlog
from asgiref.sync import async_to_sync
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field
from rest_framework import exceptions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer
from rest_framework.viewsets import GenericViewSet

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.streaming import sse_streaming_response
from posthog.clickhouse.query_tagging import Product, tag_queries
from posthog.cloud_utils import is_cloud
from posthog.event_usage import EventSource, get_event_source
from posthog.helpers.impersonation import is_impersonated
from posthog.models import OrganizationMembership, Team, User
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.utils import UUID
from posthog.rate_limit import ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle
from posthog.renderers import ServerSentEventRenderer
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.temporal.session_replay.session_summary.workflow import execute_summarize_session
from posthog.temporal.session_replay.session_summary_group.types import FailedSessionInfo, SessionSummaryStreamUpdate
from posthog.temporal.session_replay.session_summary_group.workflow import execute_summarize_session_group
from posthog.utils import relative_date_parse

from products.replay.backend.models.session_summaries import SessionGroupSummary, SingleSessionSummary
from products.replay.backend.models.team_session_summaries_config import (
    CUSTOM_TAG_DESCRIPTION_MAX_LENGTH,
    CUSTOM_TAG_NAME_MAX_LENGTH,
    CUSTOM_TAGS_MAX_COUNT,
    PRODUCT_CONTEXT_MAX_LENGTH,
    TeamSessionSummariesConfig,
)

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
from ee.hogai.utils.aio import async_to_sync as async_generator_to_sync

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
_CUSTOM_TAG_NAME_RE = re.compile(rf"^[a-z0-9_]{{1,{CUSTOM_TAG_NAME_MAX_LENGTH}}}$")
_WHITESPACE_RUN_RE = re.compile(r"\s+")
# Relative-date shorthand accepted by `relative_date_parse` (e.g. `-7d`, `-1dStart`). Its own regex is
# loose enough that free text like `yesterday` matches on a stray `y` and silently parses to a wrong
# instant, so the list endpoint validates against this stricter anchored form before parsing.
_RELATIVE_DATE_RE = re.compile(r"^-?\d+[hdwmqsy](?:Start|End)?$", re.IGNORECASE)


def _validate_date_param(field: str, value: str) -> None:
    """Reject values `relative_date_parse` can't meaningfully parse, so a bad query param is a 400
    rather than a silently-wrong (or empty) page. Accepts strict relative shorthand or an ISO date."""
    if _RELATIVE_DATE_RE.match(value):
        return
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return
    except ValueError:
        pass
    try:
        datetime.strptime(value, "%Y-%m-%d")  # unpadded ISO, e.g. 2021-1-1
        return
    except ValueError:
        pass
    raise exceptions.ValidationError(
        {field: f"Invalid date value '{value}'. Use an ISO date (YYYY-MM-DD) or relative shorthand like `-7d`."}
    )


def _sanitize_custom_tag_description(value: str) -> str:
    collapsed = _WHITESPACE_RUN_RE.sub(" ", value or "").strip()
    return collapsed.replace("<", "").replace(">", "")


# Substring used by ``execute_summarize_session`` (via the Temporal workflow) when the workflow
# finished successfully but produced no summary row — typically because ``fetch_session_data_activity``
# returned False (no events / recording too short). Kept here as a module-level constant so the coupling
# between the workflow's exception text and the API-layer classification is explicit and grep-able.
_NO_READY_SUMMARY_ERROR_SUBSTRING = "No ready summary found in DB"

# Cap on concurrent in-flight per-session summary tasks within a single streaming request.
# Each task triggers a Temporal workflow that issues ClickHouse + LLM provider calls, so an
# unbounded fan-out (e.g. 300 sessions in one batch) can spike both. 10 keeps backpressure
# reasonable while still amortizing latency for typical batch sizes.
_STREAM_BATCH_CONCURRENCY = 10


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
    custom_tags = serializers.DictField(
        child=serializers.CharField(),
        required=False,
        help_text=(
            f"Team-defined tags layered on top of the fixed taxonomy, as a {{name: description}} map. "
            f"Names must be lowercase snake_case (max {CUSTOM_TAG_NAME_MAX_LENGTH} chars), descriptions "
            f"max {CUSTOM_TAG_DESCRIPTION_MAX_LENGTH} chars, max {CUSTOM_TAGS_MAX_COUNT} entries."
        ),
    )

    class Meta:
        model = TeamSessionSummariesConfig
        fields = ["product_context", "custom_tags"]

    def validate_product_context(self, value: str) -> str:
        # Prevent prompt injection via the <product_context> wrapper in the summary prompt.
        return _PRODUCT_CONTEXT_WRAPPER_TAG_RE.sub("", value).strip()

    def validate_custom_tags(self, value: dict[str, str]) -> dict[str, str]:
        if len(value) > CUSTOM_TAGS_MAX_COUNT:
            raise exceptions.ValidationError(f"At most {CUSTOM_TAGS_MAX_COUNT} custom tags are allowed.")
        cleaned: dict[str, str] = {}
        for name, description in value.items():
            if not _CUSTOM_TAG_NAME_RE.match(name):
                raise exceptions.ValidationError(
                    f"Invalid tag name '{name}': must be lowercase snake_case, "
                    f"1-{CUSTOM_TAG_NAME_MAX_LENGTH} chars, [a-z0-9_]."
                )
            description = _sanitize_custom_tag_description(description or "")
            if not description:
                raise exceptions.ValidationError(f"Description for tag '{name}' is required.")
            if len(description) > CUSTOM_TAG_DESCRIPTION_MAX_LENGTH:
                raise exceptions.ValidationError(
                    f"Description for tag '{name}' exceeds {CUSTOM_TAG_DESCRIPTION_MAX_LENGTH} characters."
                )
            cleaned[name] = description
        return cleaned


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
    ) -> tuple[EnrichedSessionGroupSummaryPatternsList, list[FailedSessionInfo]]:
        """Consume the workflow stream and return (patterns, failed_sessions) for the response."""
        results: list[
            tuple[
                SessionSummaryStreamUpdate,
                tuple[EnrichedSessionGroupSummaryPatternsList, str, list[FailedSessionInfo]] | str,
            ]
        ] = []
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
        if not isinstance(summary_iteration, tuple) or len(summary_iteration) != 3:
            error_message = f"Unexpected result type ({type(summary_iteration)}) when generating summaries (session ids: {logging_session_ids(session_ids)}): {results}"
            logger.exception(error_message)
            raise exceptions.APIException(error_message)
        summary, _, failed_sessions = summary_iteration
        if not summary or not isinstance(summary, EnrichedSessionGroupSummaryPatternsList):
            error_message = f"Unexpected result type ({type(summary)}) when generating summaries (session ids: {logging_session_ids(session_ids)}): {results}"
            logger.exception(error_message)
            raise exceptions.APIException(error_message)
        return summary, failed_sessions

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
            summary, failed_sessions = async_to_sync(self._get_summary_from_progress_stream)(
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
                failed_session_count=len(failed_sessions),
            )
            # Sibling field rather than a wrapper, to keep existing `patterns` consumers untouched.
            response_body = summary.model_dump(exclude_none=True, mode="json")
            response_body["failed_sessions"] = [
                {"session_id": fs.session_id, "category": fs.category, "reason": fs.reason} for fs in failed_sessions
            ]
            return Response(response_body, status=status.HTTP_200_OK)
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

    @extend_schema(exclude=True)
    @action(
        methods=["POST"],
        detail=False,
        url_path="stream_batch",
        required_scopes=["session_recording:read"],
        renderer_classes=[ServerSentEventRenderer],
    )
    def stream_batch_session_summaries(self, request: Request, **kwargs) -> StreamingHttpResponse:
        user = self._validate_user(request)
        # Use _parse_input (not _validate_input) — the individual flow must surface bad
        # session IDs as per-session error events, not fail the whole batch up front.
        session_ids, extra_summary_context = self._parse_input(request)
        tracking_id = generate_tracking_id()
        team = self.team

        capture_session_summary_started(
            user=user,
            team=team,
            tracking_id=tracking_id,
            summary_source="api",
            summary_type="single",
            session_ids=session_ids,
        )

        async def async_stream() -> AsyncGenerator[bytes]:
            SSE_KEEPALIVE_COMMENT = b": keepalive\n\n"
            SSE_KEEPALIVE_INTERVAL = 15  # seconds — well under typical LB idle timeouts (60s)

            sem = asyncio.Semaphore(_STREAM_BATCH_CONCURRENCY)
            pending: set[asyncio.Task[tuple[str, SessionSummarySerializer | Exception]]] = set()
            for session_id in session_ids:

                async def _run(sid: str = session_id) -> tuple[str, SessionSummarySerializer | Exception]:
                    async with sem:
                        result = await self._summarize_session(
                            session_id=sid,
                            user=user,
                            team=team,
                            extra_summary_context=extra_summary_context,
                        )
                    return sid, result

                pending.add(asyncio.create_task(_run()))

            completed_ids: list[str] = []
            failed_ids: list[str] = []

            try:
                while pending:
                    done, pending = await asyncio.wait(
                        pending, timeout=SSE_KEEPALIVE_INTERVAL, return_when=asyncio.FIRST_COMPLETED
                    )
                    if not done:
                        yield SSE_KEEPALIVE_COMMENT
                        continue

                    for task in done:
                        sid, result = task.result()
                        if isinstance(result, Exception):
                            error_type, error_message = self._classify_summary_error(result)
                            # _summarize_session returns exceptions as values, so we're not in an except
                            # block here — sys.exc_info() is empty. Pass exc_info=result explicitly so
                            # the traceback isn't dropped.
                            logger.error(
                                f"Failed to generate streaming session summary for session {sid} from team {team.pk} by user {user.id}: {result}",
                                team_id=team.pk,
                                user_id=user.id,
                                error_type=error_type,
                                exc_info=result,
                            )
                            failed_ids.append(sid)
                            event_data = json.dumps(
                                {
                                    "session_id": sid,
                                    "error": error_type,
                                    "error_message": error_message,
                                }
                            )
                            yield f"event: error\ndata: {event_data}\n\n".encode()
                        else:
                            completed_ids.append(sid)
                            event_data = json.dumps({"session_id": sid, "summary": result.data})
                            yield f"event: summary\ndata: {event_data}\n\n".encode()
            finally:
                # Cancel still-running tasks on client disconnect or any other early exit
                # to avoid wasting Temporal workflow + LLM calls.
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)

            capture_session_summary_generated(
                user=user,
                team=team,
                tracking_id=tracking_id,
                summary_source="api",
                summary_type="single",
                session_ids=session_ids,
                success=len(failed_ids) == 0,
            )

            done_data = json.dumps({"completed": completed_ids, "failed": failed_ids})
            yield f"event: done\ndata: {done_data}\n\n".encode()

        return sse_streaming_response(
            async_stream() if settings.SERVER_GATEWAY_INTERFACE == "ASGI" else async_generator_to_sync(async_stream),
            endpoint="session_summaries",
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
            was_impersonated=is_impersonated(self.request),
        )
        super().perform_destroy(instance)


@extend_schema_field(OpenApiTypes.OBJECT)
class SessionSummaryContentField(serializers.JSONField):
    """Full LLM-generated summary JSON (`SessionSummarySerializer` schema): segments,
    key_actions, segment_outcomes, session_outcome, optional sentiment."""


@extend_schema_field(
    {
        "type": "object",
        "nullable": True,
        "properties": {
            "focus_area": {"type": "string"},
        },
    }
)
class ExtraSummaryContextField(serializers.JSONField):
    """Optional `ExtraSummaryContext` dict — `focus_area` keyword used when generating the summary."""


@extend_schema_field({"type": "object", "nullable": True})
class RunMetadataField(serializers.JSONField):
    """`SessionSummaryRunMeta` dict — `model_used`, `visual_confirmation`, and (for video runs)
    `visual_confirmation_results` plus any `failed_sessions` entries. Null on legacy rows that
    predate run metadata."""


_SESSION_OUTCOME_SCHEMA = {
    "type": "object",
    "nullable": True,
    "properties": {
        "success": {"type": "boolean"},
        "description": {"type": "string"},
    },
}

_OUTCOME_CHOICES = (
    ("success", "Session outcome marked successful by the summary"),
    ("failure", "Session outcome marked unsuccessful by the summary"),
    ("unknown", "Summary did not record an outcome"),
)


class SingleSessionSummaryMinimalSerializer(serializers.ModelSerializer):
    """Lightweight projection for list endpoints — omits the full `summary` JSON (~50 KB per row)."""

    created_by = UserBasicSerializer(read_only=True, allow_null=True)
    session_outcome = serializers.SerializerMethodField(
        help_text=(
            "Headline outcome from the summary: `{success: bool, description: string}` or null if the "
            "summary did not record one. Useful for quickly classifying a session as success/failure."
        ),
    )
    exception_count = serializers.SerializerMethodField(
        help_text="Number of exception event IDs surfaced by this summary (capped at 100).",
    )
    has_exceptions = serializers.SerializerMethodField(
        help_text="True if the summary surfaced any exception events.",
    )
    model_used = serializers.SerializerMethodField(
        help_text="LLM model identifier that generated this summary, if recorded in run metadata.",
    )
    visual_confirmation = serializers.SerializerMethodField(
        help_text="True if the summary was produced with video-based visual confirmation (the rasterized-recording path).",
    )
    extra_summary_context = ExtraSummaryContextField(
        read_only=True,
        help_text="Optional context passed to the summary at generation time (e.g. `focus_area`).",
    )

    class Meta:
        model = SingleSessionSummary
        fields = [
            "id",
            "session_id",
            "distinct_id",
            "session_start_time",
            "session_duration",
            "session_outcome",
            "exception_count",
            "has_exceptions",
            "model_used",
            "visual_confirmation",
            "extra_summary_context",
            "created_at",
            "created_by",
        ]
        read_only_fields = fields

    @extend_schema_field(_SESSION_OUTCOME_SCHEMA)
    def get_session_outcome(self, obj: SingleSessionSummary) -> dict | None:
        # The list queryset annotates `session_outcome_json` and defers the heavy `summary`
        # column, so a page of rows never hydrates the full ~50 KB summary JSON just to read
        # the outcome. Fall back to the in-memory column for any non-list/deferred-free path.
        outcome = getattr(obj, "session_outcome_json", None)
        if outcome is None and "summary" not in obj.get_deferred_fields() and isinstance(obj.summary, dict):
            outcome = obj.summary.get("session_outcome")
        return outcome if isinstance(outcome, dict) else None

    @extend_schema_field(OpenApiTypes.INT)
    def get_exception_count(self, obj: SingleSessionSummary) -> int:
        return len(obj.exception_event_ids or [])

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_has_exceptions(self, obj: SingleSessionSummary) -> bool:
        return bool(obj.exception_event_ids)

    @extend_schema_field({"type": "string", "nullable": True})
    def get_model_used(self, obj: SingleSessionSummary) -> str | None:
        meta = obj.run_metadata or {}
        return meta.get("model_used") if isinstance(meta, dict) else None

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_visual_confirmation(self, obj: SingleSessionSummary) -> bool:
        meta = obj.run_metadata or {}
        return bool(meta.get("visual_confirmation")) if isinstance(meta, dict) else False


class SingleSessionSummarySerializer(serializers.ModelSerializer):
    """Full session summary, including the generated `summary` JSON content."""

    created_by = UserBasicSerializer(read_only=True, allow_null=True)
    summary = SessionSummaryContentField(
        read_only=True,
        help_text=(
            "Full LLM-generated summary JSON. Contains `segments` (chronological journey segments), "
            "`key_actions` (per-segment events with `abandonment` / `confusion` / `exception` flags — "
            "the structured source of session-level problems), `segment_outcomes`, and `session_outcome`. "
            "Video-based runs additionally include a `sentiment` block."
        ),
    )
    exception_event_ids = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
        help_text="Event IDs (capped at 100) where exceptions occurred during the session — extracted from the summary for searchability.",
    )
    extra_summary_context = ExtraSummaryContextField(
        read_only=True,
        help_text="Optional context passed to the summary at generation time (e.g. `focus_area`).",
    )
    run_metadata = RunMetadataField(
        read_only=True,
        help_text="`SessionSummaryRunMeta` — model used, whether video-based visual confirmation was applied, and visual-confirmation event-to-asset mappings.",
    )

    class Meta:
        model = SingleSessionSummary
        fields = [
            "id",
            "session_id",
            "distinct_id",
            "session_start_time",
            "session_duration",
            "summary",
            "exception_event_ids",
            "extra_summary_context",
            "run_metadata",
            "created_at",
            "created_by",
        ]
        read_only_fields = fields


@extend_schema(
    description=(
        "Read stored AI-generated session summaries (the `ee_single_session_summary` table). "
        "Returns whatever was persisted by the summarization workflow — does NOT trigger generation. "
        "For generating new summaries, see the `/session_summaries/stream_batch/` action."
    ),
)
class SingleSessionSummaryViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    scope_object = "session_recording"
    queryset = SingleSessionSummary.objects.all()
    lookup_field = "session_id"
    lookup_value_regex = r"[^/]+"  # session IDs are typically UUIDs but allow any non-slash identifier

    def get_serializer_class(self) -> type[BaseSerializer]:
        return SingleSessionSummaryMinimalSerializer if self.action == "list" else SingleSessionSummarySerializer

    def safely_get_object(self, queryset: QuerySet) -> SingleSessionSummary:
        """Return the latest stored *default-context* summary for a `session_id`, matching
        `SingleSessionSummaryManager.get_summary(..., extra_summary_context=None)` — a focused
        (`focus_area`) summary must not shadow the default one."""
        obj = (
            queryset.filter(session_id=self.kwargs[self.lookup_field], extra_summary_context__isnull=True)
            .order_by("-created_at")
            .first()
        )
        if obj is None:
            raise exceptions.NotFound("No stored summary found for this session.")
        # `SingleSessionSummary` is not a mapped access-control resource, so the resource-level
        # `scope_object` check admits users who only hold object-level grants to *some* recording.
        # Gate on the underlying recording so summary access mirrors `SessionRecordingViewSet`.
        recording = SessionRecording.get_or_build(session_id=obj.session_id, team=self.team)
        if recording.deleted:
            raise exceptions.NotFound("The recording for this summary has been deleted.")
        if not self.user_access_control.check_access_level_for_object(recording, required_level="viewer"):
            raise exceptions.PermissionDenied("You do not have access to this recording.")
        return obj

    # Ordering is forwarded straight to `.order_by()`, so it must be allowlisted: an arbitrary value
    # would raise an unhandled `FieldError` (500), and a related-field path would add a silent JOIN.
    ALLOWED_ORDER_FIELDS = frozenset(
        f"{prefix}{field}" for field in ("created_at", "session_start_time", "session_duration") for prefix in ("", "-")
    )

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        queryset = queryset.filter(team=self.team).select_related("created_by", "team")
        if self.action != "list":
            return queryset

        # Scope filters (which sessions) run *before* the latest-per-session dedupe; state filters
        # (the latest summary's outcome / exception / visual flags) run *after*, so the list never
        # surfaces a session whose latest summary no longer matches — keeping list and retrieve in sync.
        queryset = self._filter_list_request(self.request, queryset)
        # The latest-per-session subquery has to use `ORDER BY session_id, -created_at` to be valid
        # with `DISTINCT ON (session_id)`.
        latest_ids = queryset.order_by("session_id", "-created_at").distinct("session_id").values("id")
        # Defer the heavy `summary` column and project just `session_outcome` so a page of rows doesn't
        # pull the full ~50 KB summary JSON per row (see `SingleSessionSummaryMinimalSerializer`).
        deduped = (
            SingleSessionSummary.objects.filter(team=self.team, id__in=Subquery(latest_ids))
            .select_related("created_by", "team")
            .defer("summary")
            .annotate(session_outcome_json=KeyTransform("session_outcome", "summary"))
        )
        deduped = self._apply_state_filters(self.request, deduped)
        deduped = self._restrict_to_accessible_recordings(deduped)
        deduped = self._exclude_deleted_recordings(deduped)

        order = self.request.GET.get("order") or "-created_at"
        if order not in self.ALLOWED_ORDER_FIELDS:
            raise exceptions.ValidationError(
                {"order": f"Invalid order field. Allowed values: {', '.join(sorted(self.ALLOWED_ORDER_FIELDS))}."}
            )
        return deduped.order_by(order)

    def _restrict_to_accessible_recordings(self, queryset: QuerySet) -> QuerySet:
        """Mirror `SessionRecordingViewSet` object-level access for the list path, entirely in SQL.

        Most recordings live only in ClickHouse and have no Postgres `SessionRecording` row, so we must
        never blanket-restrict to recordings that exist here. Two modes:
        - no team-wide recording access (admitted via object grants only) → restrict to granted sessions;
        - team-wide access → keep everything (incl. ClickHouse-only sessions) but drop explicit denies.
        Filtering uses subqueries so the database applies the predicate before pagination.
        """
        uac = self.user_access_control
        team_recordings = SessionRecording.objects.filter(team=self.team)
        accessible = uac.filter_queryset_by_access_level(team_recordings)
        if not uac.check_access_level_for_resource("session_recording", required_level="viewer"):
            return queryset.filter(session_id__in=Subquery(accessible.values("session_id")))
        blocked = team_recordings.exclude(id__in=accessible.values("id")).values("session_id")
        return queryset.exclude(session_id__in=Subquery(blocked))

    def _exclude_deleted_recordings(self, queryset: QuerySet) -> QuerySet:
        """Don't surface summaries whose recording was soft-deleted in Postgres (e.g. crypto-shredded).
        ClickHouse-side retention/TTL expiry is not enforced here — that needs the recordings query and
        is tracked as a follow-up."""
        deleted = SessionRecording.objects.filter(team=self.team, deleted=True).values("session_id")
        return queryset.exclude(session_id__in=Subquery(deleted))

    def _filter_list_request(self, request: Request, queryset: QuerySet) -> QuerySet:
        """Scope filters — narrow *which sessions* are considered, before the latest-per-session dedupe."""
        params = request.GET
        # Only the default (null-context) summaries, matching the retrieve path's `get_summary` semantics —
        # otherwise the list could surface a focused (`focus_area`) row that retrieve doesn't return.
        queryset = queryset.filter(extra_summary_context__isnull=True)
        if date_from := params.get("date_from"):
            _validate_date_param("date_from", date_from)
            queryset = queryset.filter(created_at__gte=relative_date_parse(date_from, self.team.timezone_info))
        if date_to := params.get("date_to"):
            _validate_date_param("date_to", date_to)
            queryset = queryset.filter(created_at__lte=relative_date_parse(date_to, self.team.timezone_info))
        if distinct_id := params.get("distinct_id"):
            queryset = queryset.filter(distinct_id=distinct_id)
        if created_by := params.get("created_by"):
            try:
                uuid.UUID(created_by)
            except (ValueError, TypeError):
                raise exceptions.ValidationError({"created_by": "Must be a valid UUID."})
            queryset = queryset.filter(created_by__uuid=created_by)
        # Multi-value filter: agents typically arrive with a list of session IDs from `query-session-recordings-list`
        # and want the persisted summaries for that exact set.
        session_ids_raw = params.get("session_ids")
        if session_ids_raw:
            session_ids = [sid.strip() for sid in session_ids_raw.split(",") if sid.strip()]
            if session_ids:
                queryset = queryset.filter(session_id__in=session_ids)
        return queryset

    def _apply_state_filters(self, request: Request, queryset: QuerySet) -> QuerySet:
        """State filters — applied to the deduped latest-per-session rows, so a match reflects each
        session's *latest* summary (consistent with what the retrieve endpoint returns)."""
        params = request.GET
        outcome = params.get("outcome")
        if outcome == "success":
            queryset = queryset.filter(summary__session_outcome__success=True)
        elif outcome == "failure":
            queryset = queryset.filter(summary__session_outcome__success=False)
        elif outcome == "unknown":
            queryset = queryset.filter(summary__session_outcome__isnull=True)
        if (has_exceptions := params.get("has_exceptions")) is not None:
            if has_exceptions.lower() == "true":
                queryset = queryset.filter(exception_event_ids__len__gt=0)
            elif has_exceptions.lower() == "false":
                queryset = queryset.filter(exception_event_ids__len=0)
        if (has_visual := params.get("has_visual_confirmation")) is not None:
            if has_visual.lower() == "true":
                queryset = queryset.filter(run_metadata__visual_confirmation=True)
            elif has_visual.lower() == "false":
                queryset = queryset.exclude(run_metadata__visual_confirmation=True)
        return queryset

    @extend_schema(
        operation_id="single_session_summaries_list",
        extensions={"x-product": "replay"},
        description=(
            "List stored AI-generated session summaries for the team, one row per session (latest summary "
            "kept). Use to discover which sessions have been summarized and to filter for sessions with "
            "specific problems — `has_exceptions=true`, `outcome=failure`, or a custom `session_ids` "
            "narrowing. Returns lightweight rows without the full summary JSON; use the retrieve endpoint "
            "for the per-segment / per-action detail."
        ),
        parameters=[
            OpenApiParameter(
                name="session_ids",
                type=str,
                required=False,
                description="Comma-separated list of session IDs to restrict the result to (uses the `(team, session_id)` index).",
            ),
            OpenApiParameter(
                name="distinct_id",
                type=str,
                required=False,
                description="Filter to summaries for a single user (the session's `distinct_id`).",
            ),
            OpenApiParameter(
                name="outcome",
                type=str,
                required=False,
                enum=[c[0] for c in _OUTCOME_CHOICES],
                description=(
                    "Filter by the summary's recorded `session_outcome.success` field. `success` for true, "
                    "`failure` for false, `unknown` for summaries without an outcome."
                ),
            ),
            OpenApiParameter(
                name="has_exceptions",
                type=bool,
                required=False,
                description="When true, only summaries that surfaced one or more exception events; when false, only summaries without exceptions.",
            ),
            OpenApiParameter(
                name="has_visual_confirmation",
                type=bool,
                required=False,
                description="When true, only summaries produced via the video-based visual-confirmation workflow.",
            ),
            OpenApiParameter(
                name="created_by",
                type=str,
                required=False,
                description="Filter to summaries triggered by a specific user, identified by `User.uuid`.",
            ),
            OpenApiParameter(
                name="date_from",
                type=str,
                required=False,
                description="Inclusive lower bound on `created_at`, accepts relative shorthand like `-7d`.",
            ),
            OpenApiParameter(
                name="date_to",
                type=str,
                required=False,
                description="Inclusive upper bound on `created_at`, accepts relative shorthand like `-1d`.",
            ),
            OpenApiParameter(
                name="order",
                type=str,
                required=False,
                enum=sorted(ALLOWED_ORDER_FIELDS),
                description=(
                    "Ordering field, defaults to `-created_at` (most recent first). Allowed: "
                    "`created_at`, `session_start_time`, `session_duration` (prefix with `-` for descending)."
                ),
            ),
        ],
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        return super().list(request, *args, **kwargs)

    @extend_schema(
        operation_id="single_session_summaries_retrieve",
        extensions={"x-product": "replay"},
        description=(
            "Get the latest stored AI summary for a single session by `session_id`. Returns the full "
            "`summary` JSON (segments with named timeline, per-action `abandonment` / `confusion` / "
            "`exception` flags, segment outcomes, headline `session_outcome`, optional `sentiment`), the "
            "`exception_event_ids` array, the `extra_summary_context` (e.g. `focus_area`) used at "
            "generation time, and the `run_metadata` (LLM model used, whether visual confirmation was "
            "applied). 404 if no summary has been generated for this session yet — to trigger generation, "
            "use the existing `session-recording-summarize` flow rather than this endpoint."
        ),
    )
    def retrieve(self, request: Request, *args, **kwargs) -> Response:
        return super().retrieve(request, *args, **kwargs)
