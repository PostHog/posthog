from django.utils.timezone import datetime

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql_queries.web_analytics.web_analytics_query_runner import WebAnalyticsQueryRunner
from posthog.models.filters.mixins.utils import cached_property
from posthog.schema import WebOverviewStatsQueryResponse, WebOverviewStatsQuery


class WebOverviewStatsQueryRunner(WebAnalyticsQueryRunner):
    query: WebOverviewStatsQuery
    query_type = WebOverviewStatsQuery

    def to_query(self) -> ast.SelectQuery | ast.SelectUnionQuery:
        with self.timings.measure("date_expr"):
            start = self.query_date_range.previous_period_date_from_as_hogql()
            mid = self.query_date_range.date_from_as_hogql()
            end = self.query_date_range.date_to_as_hogql()
        with self.timings.measure("overview_stats_query"):
            overview_stats_query = parse_select(
                """
SELECT
    uniq(if(timestamp >= {mid} AND timestamp < {end}, events.person_id, NULL)) AS unique_users,
    uniq(if(timestamp >= {start} AND timestamp < {mid}, events.person_id, NULL)) AS previous_unique_users,

    uniq(if(timestamp >= {mid} AND timestamp < {end}, events.properties.$session_id, NULL)) AS unique_sessions,
    uniq(if(timestamp >= {start} AND timestamp < {mid}, events.properties.$session_id, NULL)) AS previous_unique_sessions,

    countIf(timestamp >= {mid} AND timestamp < {end}) AS current_pageviews,
    countIf(timestamp >= {start} AND timestamp < {mid}) AS previous_pageviews
FROM
    events
WHERE
    event = '$pageview' AND
    timestamp >= {start} AND
    timestamp < {end} AND
    {event_properties}
                """,
                timings=self.timings,
                placeholders={"start": start, "mid": mid, "end": end, "event_properties": self.event_properties()},
                backend="cpp",
            )
        return overview_stats_query

    def calculate(self):
        response = execute_hogql_query(
            query_type="overview_stats_query",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
        )

        return WebOverviewStatsQueryResponse(
            columns=response.columns, results=response.results, timings=response.timings, types=response.types
        )

    @cached_property
    def query_date_range(self):
        return QueryDateRange(date_range=self.query.dateRange, team=self.team, interval=None, now=datetime.now())

    def event_properties(self) -> ast.Expr:
        return property_to_expr(self.query.properties, team=self.team)
