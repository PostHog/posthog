from typing import Optional, List

from django.utils.timezone import datetime

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql_queries.web_analytics.web_analytics_query_runner import WebAnalyticsQueryRunner
from posthog.models.filters.mixins.utils import cached_property
from posthog.schema import WebOverviewQueryResponse, WebOverviewQuery


class WebOverviewQueryRunner(WebAnalyticsQueryRunner):
    query: WebOverviewQuery
    query_type = WebOverviewQuery

    def to_queries(self) -> List[ast.SelectQuery | ast.SelectUnionQuery]:
        with self.timings.measure("date_expr"):
            start = self.query_date_range.previous_period_date_from_as_hogql()
            mid = self.query_date_range.date_from_as_hogql()
            end = self.query_date_range.date_to_as_hogql()
        with self.timings.measure("overview_stats_query"):
            pages_query = parse_select(
                """
SELECT
    uniq(if(timestamp >= {mid} AND timestamp < {end}, events.person_id, NULL)) AS unique_users,
    uniq(if(timestamp >= {start} AND timestamp < {mid}, events.person_id, NULL)) AS previous_unique_users,

    countIf(timestamp >= {mid} AND timestamp < {end}) AS current_pageviews,
    countIf(timestamp >= {start} AND timestamp < {mid}) AS previous_pageviews,

    uniq(if(timestamp >= {mid} AND timestamp < {end}, events.properties.$session_id, NULL)) AS unique_sessions,
    uniq(if(timestamp >= {start} AND timestamp < {mid}, events.properties.$session_id, NULL)) AS previous_unique_sessions
FROM
    events
WHERE
    event = '$pageview' AND
    timestamp >= {start} AND
    timestamp < {end} AND
    {event_properties}
                """,
                timings=self.timings,
                placeholders={
                    "start": start,
                    "mid": mid,
                    "end": end,
                    "event_properties": self.event_properties(),
                },
                backend="cpp",
            )

        sessions_query = parse_select(
            """
SELECT
    avg(if(min_timestamp > {mid}, duration_s, NULL)) AS avg_duration_s,
    avg(if(min_timestamp <= {mid}, duration_s, NULL)) AS prev_avg_duration_s,

    avg(if(min_timestamp > {mid}, is_bounce, NULL)) AS bounce_rate,
    avg(if(min_timestamp <= {mid}, is_bounce, NULL)) AS prev_bounce_rate

FROM (SELECT
        events.properties.`$session_id` AS session_id,
        min(events.timestamp) AS min_timestamp,
        max(events.timestamp) AS max_timestamp,
        dateDiff('second', min_timestamp, max_timestamp) AS duration_s,
        countIf(events.event == '$pageview') AS num_pageviews,
        countIf(events.event == '$autocapture') AS num_autocaptures,

        -- definition of a GA4 bounce from here https://support.google.com/analytics/answer/12195621?hl=en
        (num_autocaptures == 0 AND num_pageviews <= 1 AND duration_s < 10) AS is_bounce
    FROM
        events
    WHERE
        session_id IS NOT NULL
        AND (events.event == '$pageview' OR events.event == '$autocapture' OR events.event == '$pageleave')
        AND ({session_where})
    GROUP BY
        events.properties.`$session_id`
    HAVING
        ({session_having})
    )
            """,
            timings=self.timings,
            placeholders={
                "start": start,
                "mid": mid,
                "end": end,
                "session_where": self.session_where(include_previous_period=True),
                "session_having": self.session_having(include_previous_period=True),
            },
            backend="cpp",
        )

        return [pages_query, sessions_query]

    def to_query(self) -> ast.SelectQuery:
        return self.to_queries()[0]

    def calculate(self):
        [pages_query, sessions_query] = self.to_queries()
        pages_response = execute_hogql_query(
            query_type="overview_stats_pages_query",
            query=pages_query,
            team=self.team,
            timings=self.timings,
        )
        sessions_response = execute_hogql_query(
            query_type="overview_stats_pages_query",
            query=sessions_query,
            team=self.team,
            timings=self.timings,
        )

        pages_row = pages_response.results[0]
        sessions_row = sessions_response.results[0]

        return WebOverviewQueryResponse(
            results=[
                to_data("visitors", "count", pages_row[0], pages_row[1]),
                to_data("views", "count", pages_row[2], pages_row[3]),
                to_data("sessions", "count", pages_row[4], pages_row[5]),
                to_data("session duration", "duration_s", sessions_row[0], sessions_row[1]),
                to_data("bounce rate", "percentage", sessions_row[2], sessions_row[3], is_increase_bad=True),
            ],
        )

    @cached_property
    def query_date_range(self):
        return QueryDateRange(date_range=self.query.dateRange, team=self.team, interval=None, now=datetime.now())

    def event_properties(self) -> ast.Expr:
        return property_to_expr(self.query.properties, team=self.team)


def to_data(
    key: str, kind: str, value: Optional[float], previous: Optional[float], is_increase_bad: Optional[bool] = None
) -> dict:
    if kind == "percentage":
        value = value * 100 if not None else None
        previous = previous * 100 if not None else None

    return {
        "key": key,
        "kind": kind,
        "isIncreaseBad": is_increase_bad,
        "value": value,
        "changeFromPreviousPct": round(100 * (value - previous) / previous)
        if value is not None and previous is not None
        else None,
    }
