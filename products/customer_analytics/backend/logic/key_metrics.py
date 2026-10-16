from datetime import date, timedelta
from typing import Any, cast

from django.utils import timezone

from pydantic import BaseModel

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.property import property_to_expr
from posthog.hogql.visitor import clone_expr

from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Team, User

from products.actions.backend.facade.api import action_filter_conditions
from products.customer_analytics.backend.facade.contracts import KeyMetric

KEY_METRICS = {
    "signup_event": "Sign-ups",
    "payment_event": "Payments",
    "subscription_event": "Subscriptions",
    "activity_event": "Active users",
}
PEOPLE_METRIC = "activity_event"
DAYS = 35
EXECUTION_MODE = ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE
DAILY = (
    "SELECT toDate(timestamp) AS day FROM events"
    " WHERE timestamp >= toStartOfDay({today}) - INTERVAL {days} DAY AND timestamp < toStartOfDay({today})"
    " AND {match} AND {test_accounts}"
    " GROUP BY day ORDER BY day"
)
WEEKLY_PEOPLE = (
    "SELECT uniqIf(person_id, timestamp >= toStartOfDay({today}) - INTERVAL 7 DAY),"
    " uniqIf(person_id, timestamp < toStartOfDay({today}) - INTERVAL 7 DAY) FROM events"
    " WHERE timestamp >= toStartOfDay({today}) - INTERVAL 14 DAY AND timestamp < toStartOfDay({today})"
    " AND {match} AND {test_accounts}"
)


def _configured_nodes(team: Team) -> dict[str, dict[str, Any]]:
    config = team.customer_analytics_config
    return {
        key: node
        for key in KEY_METRICS
        if isinstance(node := getattr(config, key), dict) and node.get("kind") in ("EventsNode", "ActionsNode")
    }


def _action_ids(nodes: dict[str, dict[str, Any]]) -> list[int]:
    return [int(node["id"]) for node in nodes.values() if node["kind"] == "ActionsNode"]


def _condition(node: dict[str, Any], team: Team, actions: dict[int, ast.Expr]) -> ast.Expr:
    if node["kind"] == "ActionsNode":
        match = clone_expr(actions[int(node["id"])])
    elif node.get("event"):
        match = parse_expr("event = {event}", placeholders={"event": ast.Constant(value=node["event"])})
    else:
        match = ast.Constant(value=True)
    if node.get("properties"):
        return ast.And(exprs=[match, property_to_expr(node["properties"], team)])
    return match


def _select(query: str, **placeholders: ast.Expr) -> ast.SelectQuery:
    return cast(ast.SelectQuery, parse_select(query, placeholders=placeholders))


def _run(query: ast.SelectQuery, team: Team, user: User) -> list[Any] | None:
    from posthog.api.services.query import process_query_dict  # noqa: PLC0415 — the query service imports this facade

    response = process_query_dict(
        team,
        {"kind": "HogQLQuery", "query": to_printed_hogql(query, team), "modifiers": {"convertToProjectTimezone": True}},
        execution_mode=EXECUTION_MODE,
        user=user,
    )
    results = (response.model_dump() if isinstance(response, BaseModel) else response).get("results")
    return None if results is None else list(results)


def _day(value: date | str) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value[:10])


def key_metrics(team: Team, user: User) -> list[KeyMetric] | None:
    nodes = _configured_nodes(team)
    actions = action_filter_conditions(team=team, action_ids=_action_ids(nodes))
    conditions = {
        key: _condition(node, team, actions)
        for key, node in nodes.items()
        if node["kind"] == "EventsNode" or int(node["id"]) in actions
    }
    if not conditions:
        return []
    test_accounts = property_to_expr(team.test_account_filters or [], team)
    today = timezone.now().astimezone(team.timezone_info).date()

    daily = _select(
        DAILY,
        today=ast.Constant(value=today),
        days=ast.Constant(value=DAYS),
        match=ast.Or(exprs=[clone_expr(c) for c in conditions.values()]),
        test_accounts=clone_expr(test_accounts),
    )
    daily.select.extend(
        ast.Alias(
            alias=key,
            expr=parse_expr(
                "uniqIf(person_id, {match})" if key == PEOPLE_METRIC else "countIf({match})",
                placeholders={"match": clone_expr(condition)},
            ),
        )
        for key, condition in conditions.items()
    )
    rows = _run(daily, team, user)
    if rows is None:
        return None
    by_day = {_day(row[0]): row[1:] for row in rows}

    days = [today - timedelta(days=offset) for offset in range(DAYS, 0, -1)]
    metrics = []
    for index, (key, condition) in enumerate(conditions.items()):
        points = [(day, float(by_day[day][index]) if day in by_day else 0.0) for day in days]
        if key == PEOPLE_METRIC:
            weekly_query = _select(
                WEEKLY_PEOPLE, today=ast.Constant(value=today), match=condition, test_accounts=clone_expr(test_accounts)
            )
            weekly = _run(weekly_query, team, user)
            if weekly is None:
                return None
            this_week, last_week = (float(value) for value in weekly[0])
        else:
            this_week, last_week = sum(v for _, v in points[-7:]), sum(v for _, v in points[-14:-7])
        metrics.append(
            KeyMetric(
                key=key,
                name=nodes[key].get("custom_name") or KEY_METRICS[key],
                people=key == PEOPLE_METRIC,
                daily=points,
                this_week=this_week,
                last_week=last_week,
            )
        )
    return metrics
