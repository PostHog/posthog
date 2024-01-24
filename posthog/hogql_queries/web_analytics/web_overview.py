from typing import Optional

from django.utils.timezone import datetime

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql_queries.web_analytics.web_analytics_query_runner import (
    WebAnalyticsQueryRunner,
)
from posthog.models.filters.mixins.utils import cached_property
from posthog.schema import WebOverviewQueryResponse, WebOverviewQuery


class WebOverviewQueryRunner(WebAnalyticsQueryRunner):
    query: WebOverviewQuery
    query_type = WebOverviewQuery

    def to_query(self) -> ast.SelectQuery | ast.SelectUnionQuery:
        with self.timings.measure("date_expr"):
            start = self.query_date_range.previous_period_date_from_as_hogql()
            mid = self.query_date_range.date_from_as_hogql()
            end = self.query_date_range.date_to_as_hogql()
        with self.timings.measure("overview_stats_query"):
            query = parse_select(
                """
WITH pages_query AS (
        SELECT
        uniq(if(timestamp >= {mid} AND timestamp < {end}, events.person_id, NULL)) AS unique_users,
        uniq(if(timestamp >= {start} AND timestamp < {mid}, events.person_id, NULL)) AS previous_unique_users,
        countIf(timestamp >= {mid} AND timestamp < {end}) AS current_pageviews,
        countIf(timestamp >= {start} AND timestamp < {mid}) AS previous_pageviews,
        uniq(if(timestamp >= {mid} AND timestamp < {end}, events.properties.$session_id, NULL)) AS unique_sessions,
        uniq(if(timestamp >= {start} AND timestamp < {mid}, events.properties.$session_id, NULL)) AS previous_unique_sessions
    FROM
        events
    SAMPLE {sample_rate}
    WHERE
        event = '$pageview' AND
        timestamp >= {start} AND
        timestamp < {end} AND
        {event_properties}
    ),
sessions_query AS (
    SELECT
        avg(if(min_timestamp >= {mid}, duration_s, NULL)) AS avg_duration_s,
        avg(if(min_timestamp < {mid}, duration_s, NULL)) AS prev_avg_duration_s,
        avg(if(min_timestamp >= {mid}, is_bounce, NULL)) AS bounce_rate,
        avg(if(min_timestamp < {mid}, is_bounce, NULL)) AS prev_bounce_rate
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
        SAMPLE {sample_rate}
        WHERE
            session_id IS NOT NULL
            AND (events.event == '$pageview' OR events.event == '$autocapture' OR events.event == '$pageleave')
            AND ({session_where})
        GROUP BY
            events.properties.`$session_id`
        HAVING
            ({session_having})
        )
    )
SELECT
    unique_users,
    previous_unique_users,
    current_pageviews,
    previous_pageviews,
    unique_sessions,
    previous_unique_sessions,
    avg_duration_s,
    prev_avg_duration_s,
    bounce_rate,
    prev_bounce_rate
FROM pages_query
CROSS JOIN sessions_query
                """,
                timings=self.timings,
                placeholders={
                    "start": start,
                    "mid": mid,
                    "end": end,
                    "event_properties": self.event_properties(),
                    "session_where": self.session_where(include_previous_period=True),
                    "session_having": self.session_having(include_previous_period=True),
                    "sample_rate": self._sample_ratio,
                    "sample_expr": ast.SampleExpr(sample_value=self._sample_ratio),
                },
                backend="cpp",
            )

        return query

    def calculate(self):
        response = execute_hogql_query(
            query_type="overview_stats_pages_query",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
        )
        assert response.results

        row = response.results[0]

        return WebOverviewQueryResponse(
            results=[
                to_data("visitors", "unit", self._unsample(row[0]), self._unsample(row[1])),
                to_data("views", "unit", self._unsample(row[2]), self._unsample(row[3])),
                to_data("sessions", "unit", self._unsample(row[4]), self._unsample(row[5])),
                to_data("session duration", "duration_s", row[6], row[7]),
                to_data("bounce rate", "percentage", row[8], row[9], is_increase_bad=True),
            ],
            samplingRate=self._sample_rate,
        )

    @cached_property
    def query_date_range(self):
        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=None,
            now=datetime.now(),
        )

    def event_properties(self) -> ast.Expr:
        return property_to_expr(self.query.properties + self._test_account_filters, team=self.team)


def to_data(
    key: str,
    kind: str,
    value: Optional[float],
    previous: Optional[float],
    is_increase_bad: Optional[bool] = None,
) -> dict:
    if kind == "percentage":
        if value is not None:
            value = value * 100
        if previous is not None:
            previous = previous * 100

    return {
        "key": key,
        "kind": kind,
        "isIncreaseBad": is_increase_bad,
        "value": value,
        "previous": previous,
        "changeFromPreviousPct": round(100 * (value - previous) / previous)
        if value is not None and previous is not None and previous != 0
        else None,
    }
