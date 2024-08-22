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


class NoActionsError(Exception):
    pass


class WebGoalsQueryRunner(WebAnalyticsQueryRunner):
    query: WebGoalsQuery
    response: WebGoalsQueryResponse
    cached_response: CachedWebGoalsQueryResponse

    def to_query(self) -> ast.SelectQuery | ast.SelectUnionQuery:
        with self.timings.measure("date_expr"):
            start = self.query_date_range.date_from_as_hogql()
            end = self.query_date_range.date_to_as_hogql()

        actions = Action.objects.filter(team=self.team).order_by("pinned_at", "-last_calculated_at")[:5]
        if not actions:
            raise NoActionsError("No actions found")

        inner_aliases: list[ast.Expr] = []
        outer_aliases: list[ast.Expr] = []
        action_exprs: list[ast.Expr] = []
        for n, action in enumerate(actions):
            expr = action_to_expr(action)
            action_exprs.append(expr)
            inner_aliases.append(ast.Alias(alias=f"action_count_{n}", expr=ast.Call(name="countIf", args=[expr])))
            inner_aliases.append(
                ast.Alias(
                    alias=f"action_person_id_{n}",
                    expr=ast.Call(
                        name="if",
                        args=[
                            ast.CompareOperation(
                                op=ast.CompareOperationOp.Gt,
                                left=ast.Field(chain=[f"action_count_{n}"]),
                                right=ast.Constant(value=0),
                            ),
                            ast.Field(chain=["person_id"]),
                            ast.Constant(value=None),
                        ],
                    ),
                )
            )
            outer_aliases.append(ast.Alias(alias=f"action_name_{n}", expr=ast.Constant(value=action.name)))
            outer_aliases.append(
                ast.Alias(
                    alias=f"action_total_{n}", expr=ast.Call(name="sum", args=[ast.Field(chain=[f"action_count_{n}"])])
                ),
            )
            outer_aliases.append(
                ast.Alias(
                    alias=f"action_uniques_{n}",
                    expr=ast.Call(name="uniq", args=[ast.Field(chain=[f"action_person_id_{n}"])]),
                ),
            )

        inner_select = parse_select(
            """
SELECT
    any(events.person_id) as person_id
FROM events
WHERE and(
    events.`$session_id` IS NOT NULL,
    event = '$pageview' OR {action_where},
    timestamp >= {start},
    timestamp < {end},
    {event_properties},
    {session_properties}
)
GROUP BY events.`$session_id`
        """,
            placeholders={
                "start": start,
                "end": end,
                "event_properties": self.event_properties(),
                "session_properties": self.session_properties(),
                "action_where": ast.Or(exprs=action_exprs),
            },
        )
        assert isinstance(inner_select, ast.SelectQuery)
        for alias in inner_aliases:
            inner_select.select.append(alias)

        outer_select = parse_select(
            """
SELECT
    uniq(person_id) as total_people
FROM {inner_select}
    """,
            placeholders={
                "inner_select": inner_select,
            },
        )
        assert isinstance(outer_select, ast.SelectQuery)
        for alias in outer_aliases:
            outer_select.select.append(alias)

        return outer_select

    def calculate(self):
        try:
            query = self.to_query()
        except NoActionsError:
            return WebGoalsQueryResponse(results=[], samplingRate=self._sample_rate, modifiers=self.modifiers)

        response = execute_hogql_query(
            query_type="web_goals_query",
            query=query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )
        assert response.results

        row = response.results[0]
        num_visitors = row[0]
        num_actions = (len(row) - 1) // 3

        results = []
        for i in range(num_actions):
            action_name = row[(i * 3) + 1]
            action_total = row[(i * 3) + 2]
            action_unique = row[(i * 3) + 3]
            action_rate = action_unique / num_visitors if num_visitors else None
            results.append([action_name, action_total, action_unique, action_rate])

        return WebGoalsQueryResponse(
            results=results,
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
