import os
import asyncio
from datetime import datetime
from typing import Any, cast

from django.conf import settings

import structlog
import posthoganalytics
from asgiref.sync import async_to_sync
from drf_spectacular.utils import extend_schema
from rest_framework import exceptions, serializers, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.query_tagging import Product, tag_queries
from posthog.cloud_utils import is_cloud
from posthog.models import Team, User
from posthog.rate_limit import ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle
from posthog.temporal.ai.session_summary.summarize_session import execute_summarize_session
from posthog.temporal.ai.session_summary.summarize_session_group import execute_summarize_session_group
from posthog.temporal.ai.session_summary.types.group import SessionSummaryStep, SessionSummaryStreamUpdate

from ee.hogai.session_summaries.session.output_data import SessionSummarySerializer
from ee.hogai.session_summaries.session.summarize_session import ExtraSummaryContext
from ee.hogai.session_summaries.session_group.patterns import EnrichedSessionGroupSummaryPatternsList
from ee.hogai.session_summaries.session_group.summarize_session_group import find_sessions_timestamps
from ee.hogai.session_summaries.session_group.summary_notebooks import (
    create_notebook_from_summary_content,
    generate_notebook_content_from_summary,
)
from ee.hogai.session_summaries.utils import logging_session_ids

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


class SessionSummariesViewSet(TeamAndOrgViewSetMixin, GenericViewSet):
    scope_object = "session_recording"  # Keeping recording, as Replay is the main source of info for summary, for now
    permission_classes = [IsAuthenticated]
    throttle_classes = [ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle]
    serializer_class = SessionSummariesSerializer

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
        if not posthoganalytics.feature_enabled("ai-session-summary", str(user.distinct_id)):
            raise exceptions.ValidationError("Session summaries are not enabled for this user")
        return user

    def _validate_input(self, request: Request) -> tuple[list[str], datetime, datetime, ExtraSummaryContext | None]:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session_ids = serializer.validated_data["session_ids"]
        focus_area = serializer.validated_data.get("focus_area")
        # Check that sessions exist and get min/max timestamps for follow-up queries
        min_timestamp, max_timestamp = find_sessions_timestamps(session_ids=session_ids, team=self.team)
        # Prepare extra context, if provided
        extra_summary_context = None
        if focus_area:
            extra_summary_context = ExtraSummaryContext(focus_area=focus_area)
        return session_ids, min_timestamp, max_timestamp, extra_summary_context

    @staticmethod
    async def _get_summary_from_progress_stream(
        session_ids: list[str],
        user_id: int,
        team: Team,
        min_timestamp: datetime,
        max_timestamp: datetime,
        extra_summary_context: ExtraSummaryContext | None = None,
    ) -> EnrichedSessionGroupSummaryPatternsList:
        """Helper function to consume the async generator and return a summary"""
        results: list[
            tuple[SessionSummaryStreamUpdate, SessionSummaryStep, EnrichedSessionGroupSummaryPatternsList | str | dict]
        ] = []
        async for update in execute_summarize_session_group(
            session_ids=session_ids,
            user_id=user_id,
            team=team,
            min_timestamp=min_timestamp,
            max_timestamp=max_timestamp,
            extra_summary_context=extra_summary_context,
        ):
            results.append(update)
        if not results:
            error_message = f"No summaries were generated for the provided sessions (session ids: {logging_session_ids(session_ids)})"
            logger.exception(error_message)
            raise exceptions.APIException(error_message)
        # The last item in the result should be the summary, if not - raise an exception
        last_result = results[-1]
        summary = last_result[-1]
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
    @action(methods=["POST"], detail=False)
    def create_session_summaries(self, request: Request, **kwargs) -> Response:
        user = self._validate_user(request)
        session_ids, min_timestamp, max_timestamp, extra_summary_context = self._validate_input(request)
        # Summarize provided sessions
        try:
            summary = async_to_sync(self._get_summary_from_progress_stream)(
                session_ids=session_ids,
                user_id=user.id,
                team=self.team,
                min_timestamp=min_timestamp,
                max_timestamp=max_timestamp,
                extra_summary_context=extra_summary_context,
            )
            summary_title = "API generated"
            summary_content = generate_notebook_content_from_summary(
                summary=summary,
                session_ids=session_ids,
                project_name=self.team.name,
                team_id=self.team.id,
                summary_title=summary_title,
            )
            async_to_sync(create_notebook_from_summary_content)(
                user=user, team=self.team, summary_content=summary_content, summary_title=summary_title
            )
            return Response(summary.model_dump(exclude_none=True, mode="json"), status=status.HTTP_200_OK)
        except Exception as err:
            logger.exception(
                f"Failed to generate session group summary for sessions {logging_session_ids(session_ids)} from team {self.team.id} by user {user.id}: {err}",
                team_id=self.team.id,
                user_id=user.id,
                error=str(err),
            )
            raise exceptions.APIException(
                f"Failed to generate session summaries for sessions {logging_session_ids(session_ids)}. Please try again later."
            )

    @staticmethod
    async def _summarize_session(
        session_id: str,
        user_id: int,
        team: Team,
        extra_summary_context: ExtraSummaryContext | None = None,
    ) -> SessionSummarySerializer | Exception:
        try:
            summary_raw = await execute_summarize_session(
                session_id=session_id, user_id=user_id, team=team, extra_summary_context=extra_summary_context
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
        user_id: int,
        team: Team,
        extra_summary_context: ExtraSummaryContext | None = None,
    ) -> dict[str, dict[str, Any]]:
        tasks = {}
        async with asyncio.TaskGroup() as tg:
            for session_id in session_ids:
                tasks[session_id] = tg.create_task(
                    self._summarize_session(
                        session_id=session_id, user_id=user_id, team=team, extra_summary_context=extra_summary_context
                    )
                )
        summaries: dict[str, dict[str, Any]] = {}
        for session_id, task in tasks.items():
            res: SessionSummarySerializer | Exception = task.result()
            if isinstance(res, Exception):
                logger.exception(
                    f"Failed to generate individual session summary for session {session_id} from team {team.pk} by user {user_id}: {res}",
                    team_id=team.pk,
                    user_id=user_id,
                )
            else:
                # Return only successful summaries
                summaries[session_id] = res.data
        return summaries

    @extend_schema(
        operation_id="create_session_summaries_individually",
        description="Generate AI individual summary for each session, without grouping.",
        request=SessionSummariesSerializer,
    )
    @action(methods=["POST"], detail=False)
    def create_session_summaries_individually(self, request: Request, **kwargs) -> Response:
        user = self._validate_user(request)
        session_ids, _, _, extra_summary_context = self._validate_input(request)
        # Summarize provided sessions individually
        try:
            summaries = async_to_sync(self._get_individual_summaries)(
                session_ids=session_ids,
                user_id=user.id,
                team=self.team,
                extra_summary_context=extra_summary_context,
            )
            return Response(summaries, status=status.HTTP_200_OK)
        except Exception as err:
            logger.exception(
                f"Failed to generate individual session summaries for sessions {logging_session_ids(session_ids)} from team {self.team.id} by user {user.id}: {err}",
                team_id=self.team.id,
                user_id=user.id,
                error=str(err),
            )
            raise exceptions.APIException(
                f"Failed to generate individual session summaries for sessions {logging_session_ids(session_ids)}. Please try again later."
            )
