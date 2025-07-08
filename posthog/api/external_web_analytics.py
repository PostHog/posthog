from rest_framework import viewsets
from rest_framework.request import Request
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema

from posthog.api.mixins import PydanticModelMixin
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.hogql_queries.web_analytics.external.summary_query_runner import WebAnalyticsExternalSummaryQueryRunner
from posthog.hogql_queries.web_analytics.external.web_overview_query_runner import (
    WebAnalyticsExternalWebOverviewQueryRunner,
)
from posthog.hogql_queries.web_analytics.external.web_stats_table_query_runner import (
    WebAnalyticsExternalWebStatsTableQueryRunner,
)
from posthog.schema import (
    WebAnalyticsExternalSummaryQuery,
    WebAnalyticsExternalSummaryRequest,
    WebAnalyticsExternalSummaryQueryResponse,
    WebAnalyticsExternalWebOverviewQuery,
    WebAnalyticsExternalWebOverviewRequest,
    WebAnalyticsExternalWebOverviewQueryResponse,
    WebAnalyticsExternalWebStatsTableQuery,
    WebAnalyticsExternalWebStatsTableRequest,
    WebAnalyticsExternalWebStatsTableQueryResponse,
    DateRange,
)


class ExternalWebAnalyticsViewSet(TeamAndOrgViewSetMixin, PydanticModelMixin, viewsets.ViewSet):
    """
    This viewset is used to get an overview of web analytics data for a project.

    It is for external purposes only, and *NOT* used by the internal web analytics product.
    """

    scope_object = "query"
    scope_object_read_actions = ["summary", "web_overview", "web_stats_table"]
    scope_object_write_actions: list[str] = []

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
        request=WebAnalyticsExternalWebOverviewRequest,
        responses={200: WebAnalyticsExternalWebOverviewQueryResponse},
        description="Get web analytics overview data with metrics like visitors, sessions, pageviews, bounce rate, and session duration.",
    )
    @action(methods=["POST"], detail=False)
    def web_overview(self, request: Request, **kwargs) -> Response:
        data = self.get_model(request.data, WebAnalyticsExternalWebOverviewRequest)

        query = WebAnalyticsExternalWebOverviewQuery(
            kind="WebAnalyticsExternalWebOverviewQuery",
            dateRange=DateRange(date_from=data.date_from, date_to=data.date_to, explicitDate=data.explicit_date),
            properties=[],
        )

        query_runner = WebAnalyticsExternalWebOverviewQueryRunner(
            query=query,
            team=self.team,
        )

        result = query_runner.calculate()
        return Response(result.model_dump())

    @extend_schema(
        request=WebAnalyticsExternalWebStatsTableRequest,
        responses={200: WebAnalyticsExternalWebStatsTableQueryResponse},
        description="Get web analytics stats table data broken down by various dimensions like page, UTM parameters, geography, etc.",
    )
    @action(methods=["POST"], detail=False)
    def web_stats_table(self, request: Request, **kwargs) -> Response:
        data = self.get_model(request.data, WebAnalyticsExternalWebStatsTableRequest)

        query = WebAnalyticsExternalWebStatsTableQuery(
            kind="WebAnalyticsExternalWebStatsTableQuery",
            dateRange=DateRange(date_from=data.date_from, date_to=data.date_to, explicitDate=data.explicit_date),
            breakdownBy=data.breakdown_by,
            includeBounceRate=data.include_bounce_rate,
            includeScrollDepth=data.include_scroll_depth,
            limit=data.limit,
            orderBy=data.order_by,
            properties=[],
        )

        query_runner = WebAnalyticsExternalWebStatsTableQueryRunner(
            query=query,
            team=self.team,
        )

        result = query_runner.calculate()
        return Response(result.model_dump())
