from typing import Optional

from django.utils.timezone import datetime

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr, get_property_type, action_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql_queries.web_analytics.web_analytics_query_runner import (
    WebAnalyticsQueryRunner,
)
from posthog.models import Action
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
    avg(if(start_timestamp < {mid}, is_bounce, NULL)) AS prev_bounce_rate,
    uniq(if(start_timestamp >= {mid} AND start_timestamp < {end}, conversion_person_id, NULL)) / unique_users AS unique_converting_people,
    uniq(if(start_timestamp >= {start} AND start_timestamp < {mid}, conversion_person_id, NULL)) / previous_unique_users AS previous_unique_converting_people
FROM (
    SELECT
        any(events.person_id) as person_id,
        session.session_id as session_id,
        min(session.$start_timestamp) as start_timestamp,
        any(session.$session_duration) as session_duration,
        {pageview_count_expression} as filtered_pageview_count,
        {conversion_person_id_expr} as conversion_person_id,
        any(session.$is_bounce) as is_bounce
    FROM events
    WHERE and(
        events.`$session_id` IS NOT NULL,
        {event_type_expr},
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
                    "pageview_count_expression": self.pageview_count_expression,
                    "conversion_person_id_expr": self.conversion_person_id_expr,
                    "event_type_expr": self.event_type_expr,
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
    NULL as prev_bounce_rate,
    uniq(conversion_person_id) / unique_users AS unique_converting_users,
    NULL AS previous_unique_converting_users
FROM (
    SELECT
        any(events.person_id) as person_id,
        session.session_id as session_id,
        min(session.$start_timestamp) as start_timestamp,
        any(session.$session_duration) as session_duration,
        {pageview_count_expression} as filtered_pageview_count,
        {conversion_person_id_expr} as conversion_person_id,
        any(session.$is_bounce) as is_bounce
    FROM events
    WHERE and(
        events.`$session_id` IS NOT NULL,
        {event_type_expr},
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
                    "pageview_count_expression": self.pageview_count_expression,
                    "conversion_person_id_expr": self.conversion_person_id_expr,
                    "event_type_expr": self.event_type_expr,
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

        results = [
                to_data("visitors", "unit", self._unsample(row[0]), self._unsample(row[1])),
                to_data("views", "unit", self._unsample(row[2]), self._unsample(row[3])),
                to_data("sessions", "unit", self._unsample(row[4]), self._unsample(row[5])),
                to_data("session duration", "duration_s", row[6], row[7]),
                to_data("bounce rate", "percentage", row[8], row[9], is_increase_bad=True),
            ]
        if self.query.conversionGoal:
            results.append(to_data("conversion rate", "percentage", row[10], row[11]))

        return WebOverviewQueryResponse(
            results=results,
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

    @cached_property
    def conversion_goal_action (self)-> Optional[Action]:
        if self.query.conversionGoal:
            return Action.objects.get(pk=self.query.conversionGoal.actionId)
        else:
            return None

    @cached_property
    def conversion_person_id_expr(self) -> ast.Expr:
        if self.conversion_goal_action:
            action_expr = action_to_expr(self.conversion_goal_action)
            return ast.Call(name='any', args=[ast.Call(name="if", args=[action_expr, ast.Field(chain=['events', 'person_id']), ast.Constant(value=None)])])
        else:
            return ast.Constant(value=None)

    @cached_property
    def pageview_count_expression(self) -> ast.Expr:
        if self.conversion_goal_action:
            return ast.Call(name='countIf', args=[ast.CompareOperation(left=ast.Field(chain=['event']), op=ast.CompareOperationOp.Eq, right=ast.Constant(value='$pageview'))])
        else:
            return ast.Call(name='count', args=[])

    @cached_property
    def event_type_expr(self) -> ast.Expr:
        pageview_expr = ast.CompareOperation(op=ast.CompareOperationOp.Eq, left=ast.Field(chain=['event']), right=ast.Constant(value='$pageview'))

        if self.conversion_goal_action:
            return ast.Call(name='or', args=[
                pageview_expr,
                action_to_expr(self.conversion_goal_action)
            ])
        else:
            return pageview_expr

import math
def to_data(
    key: str,
    kind: str,
    value: Optional[float],
    previous: Optional[float],
    is_increase_bad: Optional[bool] = None,
) -> dict:
    if value is not None and math.isnan(value):
        value = None
    if previous is not None and math.isnan(previous):
        previous = None
    if kind == "percentage":
        if value is not None:
            value = value * 100
        if previous is not None:
            previous = previous * 100

    try:
        if value is not None and previous:
            change_from_previous_pct = round(100 * (value - previous) / previous)
        else:
            change_from_previous_pct = None
    except ValueError:
        change_from_previous_pct = None

    return {
        "key": key,
        "kind": kind,
        "isIncreaseBad": is_increase_bad,
        "value": value,
        "previous": previous,
        "changeFromPreviousPct": change_from_previous_pct,
    }
