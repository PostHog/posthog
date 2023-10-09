from django.utils.timezone import datetime

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.web_analytics.web_analytics_query_runner import WebAnalyticsQueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.filters.mixins.utils import cached_property
from posthog.schema import WebTopClicksQuery, WebTopClicksQueryResponse


class WebTopClicksQueryRunner(WebAnalyticsQueryRunner):
    query: WebTopClicksQuery
    query_type = WebTopClicksQuery

    def to_query(self) -> ast.SelectQuery | ast.SelectUnionQuery:
        with self.timings.measure("top_clicks_query"):
            top_sources_query = parse_select(
                """
SELECT
    properties.$el_text as el_text,
    count() as total_clicks,
    COUNT(DISTINCT events.person_id) as unique_visitors
FROM
    events
WHERE
    event == '$autocapture'
AND events.timestamp >= now() - INTERVAL 7 DAY
AND events.properties.$event_type = 'click'
AND el_text IS NOT NULL
GROUP BY
    el_text
ORDER BY total_clicks DESC
                """,
                timings=self.timings,
            )
        return top_sources_query

    def calculate(self):
        response = execute_hogql_query(
            query_type="top_sources_query",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
        )

        return WebTopClicksQueryResponse(
            columns=response.columns, results=response.results, timings=response.timings, types=response.types
        )

    @cached_property
    def query_date_range(self):
        return QueryDateRange(date_range=self.query.dateRange, team=self.team, interval=None, now=datetime.now())
