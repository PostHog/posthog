from typing import Optional

from django.utils.timezone import datetime

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr, get_property_type
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql_queries.web_analytics.web_analytics_query_runner import (
    WebAnalyticsQueryRunner,
)
from posthog.models.filters.mixins.utils import cached_property
from posthog.schema import CachedWebOverviewQueryResponse, WebOverviewQueryResponse, WebOverviewQuery


class WebOverviewQueryRunner(WebAnalyticsQueryRunner):
    query: WebOverviewQuery
    response: WebOverviewQueryResponse
    cached_response: CachedWebOverviewQueryResponse

    def to_query(self) -> ast.SelectQuery | ast.SelectUnionQuery:
        with self.timings.measure("date_expr"):
            start = self.query_date_range.previous_period_date_from_as_hogql()
            mid = self.query_date_range.date_from_as_hogql()
            end = self.query_date_range.date_to_as_hogql()

        if self.query.compare:
            return parse_select(
                """
SELECT
    uniq(if(start_timestamp >= {mid} AND start_timestamp < {end}, person_id, NULL)) AS unique_users,
    uniq(if(start_timestamp >= {start} AND start_timestamp < {mid}, person_id, NULL)) AS previous_unique_users,
    sumIf(filtered_pageview_count, start_timestamp >= {mid} AND start_timestamp < {end}) AS current_pageviews,
    sumIf(filtered_pageview_count, start_timestamp >= {start} AND start_timestamp < {mid}) AS previous_pageviews,
    uniq(if(start_timestamp >= {mid} AND start_timestamp < {end}, session_id, NULL)) AS unique_sessions,
    uniq(if(start_timestamp >= {start} AND start_timestamp < {mid}, session_id, NULL)) AS previous_unique_sessions,
    avg(if(start_timestamp >= {mid}, session_duration, NULL)) AS avg_duration_s,
    avg(if(start_timestamp < {mid}, session_duration, NULL)) AS prev_avg_duration_s,
    avg(if(start_timestamp >= {mid}, is_bounce, NULL)) AS bounce_rate,
    avg(if(start_timestamp < {mid}, is_bounce, NULL)) AS prev_bounce_rate
FROM (
    SELECT
        any(events.person_id) as person_id,
        session.session_id as session_id,
        min(session.$start_timestamp) as start_timestamp,
        any(session.$session_duration) as session_duration,
        count() as filtered_pageview_count,
        any(session.$is_bounce) as is_bounce
    FROM events
    WHERE and(
        events.`$session_id` IS NOT NULL,
        event = '$pageview',
        timestamp >= {start},
        timestamp < {end},
        {event_properties},
        {session_properties}
    )
    GROUP BY session_id
    HAVING and(
        start_timestamp >= {start},
        start_timestamp < {end}
    )
)

    """,
                placeholders={
                    "start": start,
                    "mid": mid,
                    "end": end,
                    "event_properties": self.event_properties(),
                    "session_properties": self.session_properties(),
                },
            )
        else:
            return parse_select(
                """
                SELECT
    uniq(person_id) AS unique_users,
    NULL as previous_unique_users,
    sum(filtered_pageview_count) AS current_pageviews,
    NULL as previous_pageviews,
    uniq(session_id) AS unique_sessions,
    NULL as previous_unique_sessions,
    avg(session_duration) AS avg_duration_s,
    NULL as prev_avg_duration_s,
    avg(is_bounce) AS bounce_rate,
    NULL as prev_bounce_rate
FROM (
    SELECT
        any(events.person_id) as person_id,
        session.session_id as session_id,
        min(session.$start_timestamp) as start_timestamp,
        any(session.$session_duration) as session_duration,
        count() as filtered_pageview_count,
        any(session.$is_bounce) as is_bounce
    FROM events
    WHERE and(
        events.`$session_id` IS NOT NULL,
        event = '$pageview',
        timestamp >= {mid},
        timestamp < {end},
        {event_properties},
        {session_properties}
    )
    GROUP BY session_id
    HAVING and(
        start_timestamp >= {mid},
        start_timestamp < {end}
    )
)
                """,
                placeholders={
                    "mid": mid,
                    "end": end,
                    "event_properties": self.event_properties(),
                    "session_properties": self.session_properties(),
                },
            )

    def calculate(self):
        response = execute_hogql_query(
            query_type="overview_stats_pages_query",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
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
            modifiers=self.modifiers,
            dateFrom=self.query_date_range.date_from_str,
            dateTo=self.query_date_range.date_to_str,
        )

    @cached_property
    def query_date_range(self):
        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=None,
            now=datetime.now(),
        )

    def all_properties(self) -> ast.Expr:
        properties = self.query.properties + self._test_account_filters
        return property_to_expr(properties, team=self.team)

    def event_properties(self) -> ast.Expr:
        properties = [
            p for p in self.query.properties + self._test_account_filters if get_property_type(p) in ["event", "person"]
        ]
        return property_to_expr(properties, team=self.team, scope="event")

    def session_properties(self) -> ast.Expr:
        properties = [
            p for p in self.query.properties + self._test_account_filters if get_property_type(p) == "session"
        ]
        return property_to_expr(properties, team=self.team, scope="event")


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
