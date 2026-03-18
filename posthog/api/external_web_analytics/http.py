from django.conf import settings

import posthoganalytics
from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema
from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import PydanticModelMixin
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.clickhouse.client.limit import get_web_analytics_api_rate_limiter
from posthog.models.user import User
from posthog.rate_limit import WebAnalyticsAPIBurstThrottle, WebAnalyticsAPISustainedThrottle

from .data import WebAnalyticsDataFactory
from .query_adapter import ExternalWebAnalyticsQueryAdapter
from .serializers import (
    WebAnalyticsBreakdownRequestSerializer,
    WebAnalyticsBreakdownResponseSerializer,
    WebAnalyticsOverviewRequestSerializer,
    WebAnalyticsOverviewResponseSerializer,
    WebAnalyticsTrendRequestSerializer,
    WebAnalyticsTrendResponseSerializer,
)

TEAM_IDS_WITH_EXTERNAL_WEB_ANALYTICS = [1, 2]


class ExternalWebAnalyticsViewSet(TeamAndOrgViewSetMixin, PydanticModelMixin, viewsets.ViewSet):
    """
    Provides access to web analytics data for a project. This is currently in Concept state, please join the feature preview to try it out when it's ready.
    """

    scope_object = "query"
    scope_object_read_actions = ["summary", "overview", "trend", "breakdown"]
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    scope_object_write_actions: list[str] = []
    throttle_classes = [WebAnalyticsAPIBurstThrottle, WebAnalyticsAPISustainedThrottle]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.factory = WebAnalyticsDataFactory()

    def _can_use_external_web_analytics(self) -> None:
        if settings.DEBUG:
            return

        available = False

        if self.team_id in TEAM_IDS_WITH_EXTERNAL_WEB_ANALYTICS and isinstance(self.request.user, User):
            user = self.request.user

            web_analytics_api_enabled = posthoganalytics.feature_enabled("web-analytics-api", str(user.distinct_id))

            available = web_analytics_api_enabled

        if not available:
            raise PermissionDenied("External web analytics is not available for this user - please contact support.")

    @extend_schema(
        parameters=[WebAnalyticsOverviewRequestSerializer],
        responses=OpenApiResponse(
            response=WebAnalyticsOverviewResponseSerializer,
            description="Get simple overview metrics: visitors, views, sessions, bounce rate, session duration",
        ),
        examples=[
            OpenApiExample(
                "Overview Response",
                description="Example response with key metrics",
                response_only=True,
                value={
                    "visitors": 12500,
                    "views": 45000,
                    "sessions": 18200,
                    "bounce_rate": 0.32,
                    "session_duration": 185.5,
                },
            )
        ],
    )
    @action(methods=["GET"], detail=False)
    def overview(self, request: Request, **kwargs) -> Response:
        """
        This endpoint is in Concept state, please join the feature preview to try it out when it's ready. Get an overview of web analytics data including visitors, views, sessions, bounce rate, and session duration.
        """
        self._can_use_external_web_analytics()

        serializer = WebAnalyticsOverviewRequestSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        with get_web_analytics_api_rate_limiter().run(
            team_id=self.team.pk,
            task_id=f"web_analytics_overview_{self.team.pk}",
        ):
            adapter = ExternalWebAnalyticsQueryAdapter(team=self.team)
            data = adapter.get_overview_data(serializer)
            return Response(data)

    @extend_schema(
        parameters=[WebAnalyticsTrendRequestSerializer],
        responses=OpenApiResponse(
            response=WebAnalyticsTrendResponseSerializer,
            description="Get trends for visitors, views, or sessions.",
        ),
        exclude=True,  # TODO: remove this once we support trend queries
        examples=[
            OpenApiExample(
                "Trend Response",
                description="Example paginated response with trend data",
                response_only=True,
                value={
                    "next": None,
                    "results": [
                        {"time": "2024-01-01T00:00:00Z", "value": 420},
                        {"time": "2024-01-02T00:00:00Z", "value": 380},
                        {"time": "2024-01-03T00:00:00Z", "value": 465},
                    ],
                },
            )
        ],
    )
    @action(methods=["GET"], detail=False)
    def trend(self, request: Request, **kwargs) -> Response:
        """
        This endpoint is in Concept state, please join the feature preview to try it out when it's ready. Get trends for visitors, views, or sessions over time.
        """
        self._can_use_external_web_analytics()

        serializer = WebAnalyticsTrendRequestSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        with get_web_analytics_api_rate_limiter().run(
            team_id=self.team.pk,
            task_id=f"web_analytics_trend_{self.team.pk}",
        ):
            mock_data = self.factory.generate_trends_data(
                serializer.validated_data, request=request, team_id=self.team_id
            )
            return Response(mock_data)

    @extend_schema(
        parameters=[WebAnalyticsBreakdownRequestSerializer],
        responses=OpenApiResponse(
            response=WebAnalyticsBreakdownResponseSerializer,
            description="Get a breakdown of web analytics data by supported properties.",
        ),
        examples=[
            OpenApiExample(
                "Breakdown Response",
                description="Example paginated response with breakdown data",
                response_only=True,
                value={
                    "next": f"{settings.SITE_URL}/api/web_analytics/breakdown?offset=2&limit=2",
                    "results": [
                        {"breakdown_value": "/home", "visitors": 8500, "views": 12000, "sessions": 9200},
                        {"breakdown_value": "/about", "visitors": 2100, "views": 2800, "sessions": 2300},
                    ],
                },
            )
        ],
    )
    @action(methods=["GET"], detail=False)
    def breakdown(self, request: Request, **kwargs) -> Response:
        """
        This endpoint is in Concept state, please join the feature preview to try it out when it's ready. Get a breakdown by a property (e.g. browser, device type, country, etc.).
        """
        self._can_use_external_web_analytics()

        serializer = WebAnalyticsBreakdownRequestSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        with get_web_analytics_api_rate_limiter().run(
            team_id=self.team.pk,
            task_id=f"web_analytics_breakdown_{self.team.pk}",
        ):
            adapter = ExternalWebAnalyticsQueryAdapter(team=self.team, request=request)
            data = adapter.get_breakdown_data(serializer)
            return Response(data)
