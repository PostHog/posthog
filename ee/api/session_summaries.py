from datetime import datetime
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
from posthog.rate_limit import ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.temporal.ai.session_summary.summarize_session_group import execute_summarize_session_group

logger = structlog.get_logger(__name__)


class SessionsSummariesSerializer(serializers.Serializer):
    session_ids = serializers.ListField(
        child=serializers.CharField(),
        min_length=1,
        max_length=50,
        help_text="List of session IDs to summarize (max 50)",
    )
    focus_area = serializers.CharField(
        required=False, allow_blank=True, max_length=500, help_text="Optional focus area for the summarization"
    )


class SessionsSummariesViewSet(TeamAndOrgViewSetMixin, GenericViewSet):
    scope_object = "session_recording"  # Keeping recording, as Replay is the main source of info for summary, for now
    permission_classes = [IsAuthenticated]
    throttle_classes = [ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle]
    serializer_class = SessionsSummariesSerializer

    @extend_schema(
        operation_id="create_sessions_summaries",
        description="Generate AI summaries per-session and a general summary for a group of session recordings",
        request=SessionsSummariesSerializer,
    )
    @action(methods=["POST"], detail=False)
    def create_sessions_summaries(self, request: Request, **kwargs) -> Response:
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
        sessions_found, min_timestamp, max_timestamp = self._get_sessions_metadata(session_ids)
        # Prepare extra context, if provided
        extra_summary_context = None
        if focus_area:
            extra_summary_context = ExtraSummaryContext(focus_area=focus_area)
        try:
            # Execute the session group summary
            result = execute_summarize_session_group(
                session_ids=session_ids,
                user_id=user.pk,
                team=self.team,
                min_timestamp=min_timestamp,
                max_timestamp=max_timestamp,
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

    def _get_sessions_metadata(self, session_ids: list[str]) -> tuple[set[str], datetime, datetime]:
        """Validate that all session IDs exist and belong to the team and return min/max timestamps for the entire list of sessions"""
        replay_events = SessionReplayEvents()
        sessions_found, min_timestamp, max_timestamp = replay_events.sessions_found_with_timestamps(
            session_ids, self.team
        )
        # Check for missing sessions
        if len(sessions_found) != len(session_ids):
            missing_sessions = set(session_ids) - sessions_found
            raise exceptions.ValidationError(
                f"Sessions not found or do not belong to this team: {', '.join(missing_sessions)}"
            )
        # Check for missing timestamps
        if min_timestamp is None or max_timestamp is None:
            raise exceptions.ValidationError(
                f"Failed to get min ({min_timestamp}) or max ({max_timestamp}) timestamps for sessions: {', '.join(session_ids)}"
            )
        return sessions_found, min_timestamp, max_timestamp


#   from posthog.models.notebook.notebook import Notebook
#   from posthog.models.team import Team
#   from posthog.models.user import User

#   # Create notebook content
#   notebook_content = {
#       "type": "doc",
#       "content": [
#           {
#               "type": "heading",
#               "attrs": {"level": 1},
#               "content": [{"type": "text", "text": "My Notebook Title"}]
#           },
#           {
#               "type": "ph-image",
#               "attrs": {
#                   "height": 300,
#                   "title": "Example Image",
#                   "nodeId": "unique-image-id",
#                   "src": "https://example.com/image.jpg",
#                   "file": None
#               }
#           },
#           {
#               "type": "paragraph",
#               "content": [
#                   {"type": "text", "text": "Check out "},
#                   {
#                       "type": "text",
#                       "marks": [{"type": "link", "attrs": {"href": "https://posthog.com", "target": "_blank"}}],
#                       "text": "PostHog"
#                   },
#                   {"type": "text", "text": " for more information!"}
#               ]
#           }
#       ]
#   }
