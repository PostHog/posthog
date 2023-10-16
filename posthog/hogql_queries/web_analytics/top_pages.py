from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.web_analytics.ctes import SESSION_CTE, PATHNAME_CTE, PATHNAME_SCROLL_CTE
from posthog.hogql_queries.web_analytics.web_analytics_query_runner import WebAnalyticsQueryRunner
from posthog.schema import WebTopPagesQuery, WebTopPagesQueryResponse


class WebTopPagesQueryRunner(WebAnalyticsQueryRunner):
    query: WebTopPagesQuery
    query_type = WebTopPagesQuery

    def to_query(self) -> ast.SelectQuery | ast.SelectUnionQuery:
        with self.timings.measure("session_query"):
            session_query = parse_select(
                SESSION_CTE,
                timings=self.timings,
                placeholders={"session_where": self.session_where(), "session_having": self.session_having()},
            )
        with self.timings.measure("pathname_query"):
            pathname_query = parse_select(
                PATHNAME_CTE, timings=self.timings, placeholders={"pathname_where": self.events_where()}
            )
        with self.timings.measure("pathname_scroll_query"):
            pathname_scroll_query = parse_select(
                PATHNAME_SCROLL_CTE,
                timings=self.timings,
                placeholders={"pathname_scroll_where": self.events_where()},
            )
        with self.timings.measure("top_pages_query"):
            top_sources_query = parse_select(
                """
SELECT
    pathname.$pathname as "context.columns.pathname",
    pathname.total_pageviews as "context.columns.views",
    pathname.unique_visitors as "context.columns.visitors",
    bounce_rate.bounce_rate as "context.columns.bounce_rate",
    scroll_data.scroll_gt80_percentage as scroll_gt80_percentage,
    scroll_data.average_scroll_percentage as average_scroll_percentage
FROM
    {pathname_query} AS pathname
LEFT OUTER JOIN
    (
        SELECT
            session.$initial_pathname,
            avg(session.is_bounce) as bounce_rate
        FROM
            {session_query} AS session
        GROUP BY
            session.$initial_pathname
    ) AS bounce_rate
ON
    pathname.$pathname = bounce_rate.$initial_pathname
LEFT OUTER JOIN
    {pathname_scroll_query} AS scroll_data
ON
    pathname.$pathname = scroll_data.$pathname
ORDER BY
    "context.columns.views" DESC
LIMIT 10
                """,
                timings=self.timings,
                placeholders={
                    "pathname_query": pathname_query,
                    "session_query": session_query,
                    "pathname_scroll_query": pathname_scroll_query,
                },
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
            columns=response.columns, results=response.results, timings=response.timings, types=response.types
        )
