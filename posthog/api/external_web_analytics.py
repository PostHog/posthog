from rest_framework import viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.hogql_queries.web_analytics.external.summary_query_runner import WebAnalyticsExternalSummaryQueryRunner
from posthog.schema import (
    WebAnalyticsExternalSummaryQuery,
    DateRange,
)


class ExternalWebAnalyticsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "query"
    scope_object_read_actions = ["summary"]
    scope_object_write_actions: list[str] = []

    @action(methods=["POST"], detail=False)
    def summary(self, request: Request, **kwargs) -> Response:
        date_from = request.data.get("date_from")
        date_to = request.data.get("date_to")
        explicit_date = request.data.get("explicit_date", False)

        if not date_from or not date_to:
            raise ValidationError({"date_range": ["date_from and date_to are required"]}, code="required")

        query = WebAnalyticsExternalSummaryQuery(
            kind="WebAnalyticsExternalSummaryQuery",
            dateRange=DateRange(date_from=date_from, date_to=date_to, explicitDate=explicit_date),
            properties=[],
        )

        query_runner = WebAnalyticsExternalSummaryQueryRunner(
            query=query,
            team=self.team,
        )

        result = query_runner.calculate()
        return Response(result.model_dump())
