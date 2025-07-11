import os
from typing import cast

import posthoganalytics
import structlog
from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework import exceptions, serializers, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from ee.session_recordings.session_summary.summarize_session import ExtraSummaryContext
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.query_tagging import tag_queries, Product
from posthog.cloud_utils import is_cloud
from posthog.models import User
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.temporal.ai.session_summary.summarize_session_group import execute_summarize_session_group

logger = structlog.get_logger(__name__)


class SessionSummariesSerializer(serializers.Serializer):
    session_ids = serializers.ListField(
        child=serializers.CharField(),
        min_length=1,
        max_length=50,
        help_text="List of session IDs to summarize (max 50)",
    )
    focus_area = serializers.CharField(
        required=False, allow_blank=True, max_length=500, help_text="Optional focus area for the summary"
    )


class SessionSummariesViewSet(TeamAndOrgViewSetMixin, GenericViewSet):
    scope_object = "session_recording"
    permission_classes = [IsAuthenticated]
    serializer_class = SessionSummariesSerializer

    @extend_schema(
        operation_id="create_session_summaries",
        description="Generate AI summaries for a group of session recordings",
        request=SessionSummariesSerializer,
    )
    @action(methods=["POST"], detail=False)
    def create_summaries(self, request: Request, **kwargs) -> Response:
        if not request.user.is_authenticated:
            raise exceptions.NotAuthenticated()

        tag_queries(product=Product.REPLAY)

        user = cast(User, request.user)

        # Validate environment requirements (same as single session summarize)
        environment_is_allowed = settings.DEBUG or is_cloud()
        has_openai_api_key = bool(os.environ.get("OPENAI_API_KEY"))
        if not environment_is_allowed or not has_openai_api_key:
            raise exceptions.ValidationError("session summary is only supported in PostHog Cloud")

        if not posthoganalytics.feature_enabled("ai-session-summary", str(user.distinct_id)):
            raise exceptions.ValidationError("session summary is not enabled for this user")

        # Validate input
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        session_ids = serializer.validated_data["session_ids"]
        focus_area = serializer.validated_data.get("focus_area")

        # Validate that all session IDs belong to the team and exist
        self._validate_sessions_exist(session_ids)

        # Prepare extra context
        extra_summary_context = None
        if focus_area:
            extra_summary_context = ExtraSummaryContext(focus_area=focus_area)

        try:
            # Execute the session group summary
            result = execute_summarize_session_group(
                session_ids=session_ids,
                user_id=user.pk,
                team=self.team,
                extra_summary_context=extra_summary_context,
                local_reads_prod=False,
            )

            # Return the enriched patterns list
            return Response(result.model_dump(exclude_none=True), status=status.HTTP_200_OK)

        except Exception as e:
            logger.exception(
                "Failed to generate session group summary",
                session_ids=session_ids,
                team_id=self.team.pk,
                user_id=user.pk,
                error=str(e),
            )
            raise exceptions.APIException("Failed to generate session summaries. Please try again later.")

    def _validate_sessions_exist(self, session_ids: list[str]) -> None:
        """Validate that all session IDs exist and belong to the team"""
        for session_id in session_ids:
            if not SessionReplayEvents().exists(session_id=session_id, team=self.team):
                raise exceptions.ValidationError(f"Session {session_id} not found or does not belong to this team")
