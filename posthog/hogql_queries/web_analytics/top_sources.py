from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.web_analytics.ctes import SESSION_CTE, SOURCE_CTE
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
        with self.timings.measure("sources_query"):
            source_query = parse_select(
                SOURCE_CTE,
                timings=self.timings,
                placeholders={"source_where": self.events_where()},
            )
        with self.timings.measure("top_sources_query"):
            top_sources_query = parse_select(
                """
SELECT
    source_query.$initial_utm_source as "Initial UTM Source",
    source_query.total_pageviews as "context.columns.views",
    source_query.unique_visitors as "context.columns.visitors",
    bounce_rate.bounce_rate AS "context.columns.bounce_rate"
FROM
    {source_query} AS source_query
LEFT JOIN  (
        SELECT
            session.$initial_utm_source,
            avg(session.is_bounce) as bounce_rate
        FROM
            {session_query} AS session
        GROUP BY
            session.$initial_utm_source
    ) AS bounce_rate
ON source_query.$initial_utm_source = bounce_rate.$initial_utm_source
WHERE
    "Initial UTM Source" IS NOT NULL
ORDER BY "context.columns.views" DESC
LIMIT 10
                """,
                timings=self.timings,
                placeholders={"session_query": session_query, "source_query": source_query},
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
