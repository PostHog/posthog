from django.utils.timezone import datetime

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql_queries.web_analytics.ctes import SESSION_CTE
from posthog.hogql_queries.web_analytics.web_analytics_query_runner import WebAnalyticsQueryRunner
from posthog.models.filters.mixins.utils import cached_property
from posthog.schema import WebTopSourcesQuery, WebTopSourcesQueryResponse


class WebTopSourcesQueryRunner(WebAnalyticsQueryRunner):
    query: WebTopSourcesQuery
    query_type = WebTopSourcesQuery

    def to_query(self) -> ast.SelectQuery | ast.SelectUnionQuery:
        with self.timings.measure("session_query"):
            session_query = parse_select(SESSION_CTE, timings=self.timings)
        with self.timings.measure("top_sources_query"):
            top_sources_query = parse_select(
                """
SELECT
    blended_source,
    count(num_pageviews) as total_pageviews,
    count(DISTINCT person_id) as unique_visitors,
    avg(is_bounce) AS bounce_rate
FROM
    {session_query}
WHERE
    blended_source IS NOT NULL
GROUP BY blended_source

ORDER BY total_pageviews DESC
LIMIT 100
                """,
                timings=self.timings,
                placeholders={"session_query": session_query},
            )
        return top_sources_query

    def calculate(self):
        response = execute_hogql_query(
            query_type="top_sources_query",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
        )

        return WebTopSourcesQueryResponse(
            columns=response.columns, result=response.results, timings=response.timings, types=response.types
        )

    @cached_property
    def query_date_range(self):
        return QueryDateRange(date_range=self.query.dateRange, team=self.team, interval=None, now=datetime.now())
