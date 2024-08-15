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
from posthog.schema import WebGoalsQueryResponse, WebGoalsQuery, CachedWebGoalsQueryResponse


class WebGoalsQueryRunner(WebAnalyticsQueryRunner):
    query: WebGoalsQuery
    response: WebGoalsQueryResponse
    cached_response: CachedWebGoalsQueryResponse

    def to_query(self) -> ast.SelectQuery | ast.SelectUnionQuery:
        with self.timings.measure("date_expr"):
            start = self.query_date_range.date_from_as_hogql()
            end = self.query_date_range.date_to_as_hogql()

        actions = Action.objects.filter(team=self.team).order_by("pinned_at", "-last_calculated_at")[:5]
        action = actions[0]

        return parse_select(
            """
SELECT
    sum(action_count) as count,
    uniq(person_id) as total_people,
    uniq(action_person_id) as uniques,
    uniques/total_people as rate
FROM (
    SELECT
        any(events.person_id) as person_id,
        session.session_id as session_id,
        countIf({action_where}) as action_count,
        if (action_count > 0, person_id, NULL) as action_person_id,
    FROM events
    WHERE and(
        events.`$session_id` IS NOT NULL,
        event = '$pageview' OR {action_where},
        timestamp >= {start},
        timestamp < {end},
        {event_properties},
        {session_properties}
    )
    GROUP BY session_id
)
    """,
            placeholders={
                "start": start,
                "end": end,
                "event_properties": self.event_properties(),
                "session_properties": self.session_properties(),
                "action_where": action_to_expr(action),
            },
        )

    def calculate(self):
        response = execute_hogql_query(
            query_type="web_goals_query",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )
        assert response.results

        row = response.results[0]

        return WebGoalsQueryResponse(
            results=[
                [row[0], row[1], row[2], row[3]],
            ],
            samplingRate=self._sample_rate,
            modifiers=self.modifiers,
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
