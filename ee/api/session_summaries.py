import os
from datetime import datetime
from typing import cast

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
from posthog.temporal.ai.session_summary.summarize_session_group import execute_summarize_session_group
from posthog.temporal.ai.session_summary.types.group import SessionSummaryStep, SessionSummaryStreamUpdate

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
        description="Generate AI summaries per-session and a general summary for a group of session recordings",
        request=SessionSummariesSerializer,
    )
    @action(methods=["POST"], detail=False)
    def create_session_summaries(self, request: Request, **kwargs) -> Response:
        # Validate the user/team
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
        # Validate input
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
        # Summarize provided sessions
        try:
            summary = async_to_sync(self._get_summary_from_progress_stream)(
                session_ids=session_ids,
                user_id=user.pk,
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
                f"Failed to generate session group summary for sessions {logging_session_ids(session_ids)} from team {self.team.pk} by user {user.pk}: {err}",
                team_id=self.team.pk,
                user_id=user.pk,
                error=str(err),
            )
            raise exceptions.APIException(
                f"Failed to generate session summaries for sessions {logging_session_ids(session_ids)}. Please try again later."
            )
