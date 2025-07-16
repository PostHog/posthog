from django.conf import settings
from rest_framework import viewsets
from rest_framework.request import Request
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import PermissionDenied

from posthog.api.mixins import PydanticModelMixin
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action

from posthog.auth import SessionAuthentication, PersonalAPIKeyAuthentication

from .serializers import (
    WebAnalyticsOverviewRequestSerializer,
    WebAnalyticsTrendRequestSerializer,
    WebAnalyticsBreakdownRequestSerializer,
    WebAnalyticsOverviewResponseSerializer,
    WebAnalyticsTrendResponseSerializer,
    WebAnalyticsBreakdownResponseSerializer,
)

from posthog.hogql_queries.web_analytics.external.summary_query_runner import WebAnalyticsExternalSummaryQueryRunner
from posthog.schema import (
    WebAnalyticsExternalSummaryQuery,
    WebAnalyticsExternalSummaryRequest,
    WebAnalyticsExternalSummaryQueryResponse,
    DateRange,
)
from .data import WebAnalyticsDataFactory
from .query_adapter import ExternalWebAnalyticsQueryAdapter

TEAM_IDS_WITH_EXTERNAL_WEB_ANALYTICS = [2]


class ExternalWebAnalyticsViewSet(TeamAndOrgViewSetMixin, PydanticModelMixin, viewsets.ViewSet):
    scope_object = "query"
    scope_object_read_actions = ["summary", "overview", "trend", "breakdown"]
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication]
    scope_object_write_actions: list[str] = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.factory = WebAnalyticsDataFactory()

    def _can_use_external_web_analytics(self) -> None:
        available = True if settings.DEBUG else self.team_id in TEAM_IDS_WITH_EXTERNAL_WEB_ANALYTICS

        if not available:
            raise PermissionDenied("External web analytics is not enabled for this team.")

    @extend_schema(
        request=WebAnalyticsExternalSummaryRequest,
        responses={200: WebAnalyticsExternalSummaryQueryResponse},
        description="Get an overview of web analytics data.",
    )
    @action(methods=["POST"], detail=False)
    def summary(self, request: Request, **kwargs) -> Response:
        data = self.get_model(request.data, WebAnalyticsExternalSummaryRequest)

        query = WebAnalyticsExternalSummaryQuery(
            kind="WebAnalyticsExternalSummaryQuery",
            dateRange=DateRange(date_from=data.date_from, date_to=data.date_to, explicitDate=data.explicit_date),
            properties=[],
        )

        query_runner = WebAnalyticsExternalSummaryQueryRunner(
            query=query,
            team=self.team,
        )

        result = query_runner.calculate()
        return Response(result.model_dump())

    @extend_schema(
        parameters=[WebAnalyticsOverviewRequestSerializer],
        responses={200: WebAnalyticsOverviewResponseSerializer},
        description="Get simple overview metrics: visitors, views, sessions, bounce rate, session duration",
    )
    @action(methods=["GET"], detail=False)
    def overview(self, request: Request, **kwargs) -> Response:
        self._can_use_external_web_analytics()

        serializer = WebAnalyticsOverviewRequestSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        adapter = ExternalWebAnalyticsQueryAdapter(team=self.team)
        data = adapter.get_overview_data(serializer)
        return Response(data)

    @extend_schema(
        parameters=[WebAnalyticsTrendRequestSerializer],
        responses={200: WebAnalyticsTrendResponseSerializer},
        description="Get trends for visitors, views, or sessions.",
    )
    @action(methods=["GET"], detail=False)
    def trend(self, request: Request, **kwargs) -> Response:
        self._can_use_external_web_analytics()

        serializer = WebAnalyticsTrendRequestSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        mock_data = self.factory.generate_trends_data(serializer.validated_data, request=request, team_id=self.team_id)
        return Response(mock_data)

    @extend_schema(
        parameters=[WebAnalyticsBreakdownRequestSerializer],
        responses={200: WebAnalyticsBreakdownResponseSerializer},
        description="Get a breakdown of web analytics data by supported properties.",
    )
    @action(methods=["GET"], detail=False)
    def breakdown(self, request: Request, **kwargs) -> Response:
        self._can_use_external_web_analytics()

        serializer = WebAnalyticsBreakdownRequestSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        mock_data = self.factory.generate_breakdown_data(
            serializer.validated_data, request=request, team_id=self.team_id
        )
        return Response(mock_data)
