import json
import hashlib
from datetime import timedelta
from typing import Any, cast

from django.utils import timezone

from posthog.schema import HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.visitor import clone_expr

from posthog.models import Team, User

from products.actions.backend.facade.api import action_filter_conditions, action_revisions
from products.customer_analytics.backend.facade.contracts import KeyMetric

KEY_METRICS = {
    "signup_event": "Sign-ups",
    "payment_event": "Payments",
    "subscription_event": "Subscriptions",
    "activity_event": "Active users",
}
PEOPLE_METRIC = "activity_event"
DAYS = 35
QUERY_TIMEOUT_SECONDS = 10
DAILY = (
    "SELECT toDate(timestamp) AS day FROM events"
    " WHERE timestamp >= toStartOfDay(now()) - INTERVAL {days} DAY AND timestamp < toStartOfDay(now())"
    " AND {match} AND {test_accounts}"
    " GROUP BY day ORDER BY day"
)
WEEKLY_PEOPLE = (
    "SELECT uniqIf(person_id, timestamp >= toStartOfDay(now()) - INTERVAL 7 DAY),"
    " uniqIf(person_id, timestamp < toStartOfDay(now()) - INTERVAL 7 DAY) FROM events"
    " WHERE timestamp >= toStartOfDay(now()) - INTERVAL 14 DAY AND timestamp < toStartOfDay(now())"
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


def _run(query: ast.SelectQuery, team: Team, user: User, query_type: str) -> list[Any]:
    return execute_hogql_query(
        query,
        team,
        query_type=query_type,
        user=user,
        modifiers=HogQLQueryModifiers(convertToProjectTimezone=True),
        settings=HogQLGlobalSettings(max_execution_time=QUERY_TIMEOUT_SECONDS, timeout_overflow_mode="throw"),
    ).results


def key_metrics_fingerprint(team: Team) -> str:
    nodes = _configured_nodes(team)
    payload = [nodes, action_revisions(team=team, action_ids=_action_ids(nodes)), team.test_account_filters]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]


def key_metrics(team: Team, user: User) -> list[KeyMetric]:
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

    daily = _select(
        DAILY,
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
    by_day = {row[0]: row[1:] for row in _run(daily, team, user, "customer_analytics_key_metrics_daily")}

    today = timezone.now().astimezone(team.timezone_info).date()
    days = [today - timedelta(days=offset) for offset in range(DAYS, 0, -1)]
    metrics = []
    for index, (key, condition) in enumerate(conditions.items()):
        points = [(day, float(by_day[day][index]) if day in by_day else 0.0) for day in days]
        if key == PEOPLE_METRIC:
            weekly_query = _select(WEEKLY_PEOPLE, match=condition, test_accounts=clone_expr(test_accounts))
            weekly = _run(weekly_query, team, user, "customer_analytics_key_metrics_weekly")
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
