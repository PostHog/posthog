from django.utils.timezone import datetime

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.web_analytics.ctes import SESSION_CTE, PATHNAME_CTE
from posthog.hogql_queries.web_analytics.web_analytics_query_runner import WebAnalyticsQueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.filters.mixins.utils import cached_property
from posthog.schema import WebTopPagesQuery, WebTopPagesQueryResponse


class WebTopPagesQueryRunner(WebAnalyticsQueryRunner):
    query: WebTopPagesQuery
    query_type = WebTopPagesQuery

    def to_query(self) -> ast.SelectQuery | ast.SelectUnionQuery:
        with self.timings.measure("top_pages_query"):
            top_sources_query = parse_select(
                f"""
WITH

pathname_cte AS (
{PATHNAME_CTE}
),
session_cte AS (
{SESSION_CTE}
),

bounce_rate_cte AS (
SELECT session_cte.earliest_pathname,
       avg(session_cte.is_bounce) as bounce_rate
FROM session_cte
GROUP BY earliest_pathname
)

SELECT pathname_cte.pathname as pathname,
pathname_cte.total_pageviews as total_pageviews,
pathname_cte.unique_visitors as unique_visitors,
pathname_cte.scroll_gt80_percentage as scroll_gt80_percentage,
pathname_cte.average_scroll_percentage as average_scroll_percentage,
bounce_rate_cte.bounce_rate as bounce_rate
FROM
    pathname_cte LEFT OUTER JOIN bounce_rate_cte
ON pathname_cte.pathname = bounce_rate_cte.earliest_pathname
ORDER BY total_pageviews DESC
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

        return WebTopPagesQueryResponse(
            columns=response.columns, result=response.results, timings=response.timings, types=response.types
        )

    @cached_property
    def query_date_range(self):
        return QueryDateRange(date_range=self.query.dateRange, team=self.team, interval=None, now=datetime.now())
