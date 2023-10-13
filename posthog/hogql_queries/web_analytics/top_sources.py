from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.web_analytics.ctes import SESSION_CTE
from posthog.hogql_queries.web_analytics.web_analytics_query_runner import WebAnalyticsQueryRunner
from posthog.schema import WebTopSourcesQuery, WebTopSourcesQueryResponse


class WebTopSourcesQueryRunner(WebAnalyticsQueryRunner):
    query: WebTopSourcesQuery
    query_type = WebTopSourcesQuery

    def to_query(self) -> ast.SelectQuery | ast.SelectUnionQuery:
        with self.timings.measure("session_query"):
            session_query = parse_select(
                SESSION_CTE,
                timings=self.timings,
                placeholders={"session_where": self.session_where(), "session_having": self.session_having()},
            )
        with self.timings.measure("top_sources_query"):
            top_sources_query = parse_select(
                """
SELECT
    blended_source as "Source",
    count(num_pageviews) as "context.columns.views",
    count(DISTINCT person_id) as "context.columns.visitors",
    avg(is_bounce) AS "context.columns.bounce_rate"
FROM
    {session_query}
WHERE
    "Source" IS NOT NULL
GROUP BY "Source"

ORDER BY "context.columns.views" DESC
LIMIT 10
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
            columns=response.columns, results=response.results, timings=response.timings, types=response.types
        )
