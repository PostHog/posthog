from collections import defaultdict

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.property import (
    property_to_expr,
)
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.web_analytics.web_analytics_query_runner import (
    WebAnalyticsQueryRunner,
    map_columns,
)
from posthog.schema import (
    WebTimeOfActivityQuery,
    CachedWebTimeOfActivityQueryResponse,
    WebTimeOfActivityQueryResponse,
)


class WebTimeOfActivityQueryRunner(WebAnalyticsQueryRunner):
    query: WebTimeOfActivityQuery
    response: WebTimeOfActivityQueryResponse
    cached_response: CachedWebTimeOfActivityQueryResponse

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def to_query(self) -> ast.SelectQuery:
        with self.timings.measure("time_of_activity_query"):
            query = parse_select(
                """

    SELECT
        uniq(events.$session_id) AS num_sessions,
        toDayOfWeek(timestamp, 0) AS day_of_week,
        toHour(timestamp) AS hour
    FROM events
    WHERE and(
        timestamp >= {date_from},
        timestamp < {date_to},
        or (
            events.event == '$pageview',
            events.event == 'autocapture'
        ),
        {all_properties}
    )
    GROUP BY day_of_week, hour
    ORDER BY day_of_week ASC, hour ASC
""",
                timings=self.timings,
                placeholders={
                    "all_properties": self._all_properties(),
                    "date_from": self._date_from(),
                    "date_to": self._date_to(),
                },
            )
        assert isinstance(query, ast.SelectQuery)
        return query

    def _all_properties(self) -> ast.Expr:
        properties = self.query.properties  # + self._test_account_filters
        return property_to_expr(properties, team=self.team)

    def _date_to(self) -> ast.Expr:
        return self.query_date_range.date_to_as_hogql()

    def _date_from(self) -> ast.Expr:
        return self.query_date_range.date_from_as_hogql()

    def calculate(self):
        response = execute_hogql_query(
            query_type="stats_table_query",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
        )
        results = response.results

        assert results is not None

        # we used clickhouse's toDayOfWeek function with mode=0
        # convert this to a string, so that it's easier to read the response body
        num_to_day = {
            1: "monday",
            2: "tuesday",
            3: "wednesday",
            4: "thursday",
            5: "friday",
            6: "saturday",
            7: "sunday",
        }

        results_mapped = map_columns(
            results,
            {
                1: num_to_day.get,
            },
        )

        results_dict: dict[str, dict[int, int]] = defaultdict(lambda: {})
        for result in results_mapped:
            results_dict[result[1]][result[2]] = result[0]

        return WebTimeOfActivityQueryResponse(
            columns=response.columns,
            results=results_dict,
            timings=response.timings,
            types=response.types,
            hogql=response.hogql,
            modifiers=self.modifiers,
        )
