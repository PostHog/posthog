from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.property import property_to_expr
from posthog.hogql_queries.web_analytics.web_analytics_query_runner import (
    WebAnalyticsQueryRunner,
)
from posthog.schema import (
    CachedWebActiveHoursHeatMapQueryResponse,
    WebActiveHoursHeatMapQuery,
    WebActiveHoursHeatMapQueryResponse,
    WebActiveHoursHeatMapResult,
)


class WebActiveHoursHeatMapQueryRunner(WebAnalyticsQueryRunner):
    query: WebActiveHoursHeatMapQuery
    response: WebActiveHoursHeatMapQueryResponse
    cached_response: CachedWebActiveHoursHeatMapQueryResponse

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def to_query(self) -> ast.SelectQuery:
        query = parse_select(
            """
            SELECT
                toDayOfWeek(timestamp) as day,
                toHour(timestamp) as hour,
                uniq(events.person_id) as total
            FROM events
            WHERE and(
                event = '$pageview',
                {all_properties},
                {current_period},
            )
            GROUP BY day, hour
            ORDER BY day, hour
            LIMIT 168 -- 24 hours * 7 days
            """,
            placeholders={
                "all_properties": self._all_properties(),
                "current_period": self._current_period_expression(field="timestamp"),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query

    def calculate(self):
        query = self.to_query()
        response = execute_hogql_query(
            query_type="date_and_time_heatmap_query",
            query=query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
        )
        results = [
            WebActiveHoursHeatMapResult(day=int(row[0]), hour=int(row[1]), total=int(row[2]))
            for row in response.results
        ]

        assert results is not None

        return WebActiveHoursHeatMapQueryResponse(
            results=results,
            timings=response.timings,
            hogql=response.hogql,
            modifiers=self.modifiers,
        )

    def _all_properties(self) -> ast.Expr:
        properties = self.query.properties + self._test_account_filters
        return property_to_expr(properties, team=self.team)
