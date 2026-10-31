import re
from datetime import date, datetime, time, timedelta
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
from posthog.utils import relative_date_parse

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
DATE_OPERATORS = {"is_date_exact", "is_date_before", "is_date_after"}
RELATIVE_DATE = re.compile(r"^-?[0-9]+[hdwmqysHDWMQY]")
DAILY = (
    "SELECT toDate(timestamp) AS day FROM events"
    " WHERE timestamp >= {start} AND timestamp < {end}"
    " AND {match} AND {test_accounts}"
    " GROUP BY day ORDER BY day"
)
WEEKLY_PEOPLE = (
    "SELECT uniqIf(person_id, timestamp >= {week}), uniqIf(person_id, timestamp < {week}) FROM events"
    " WHERE timestamp >= {start} AND timestamp < {end}"
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


def _anchored(filters: Any, team: Team, anchor: datetime) -> Any:
    if isinstance(filters, list):
        return [_anchored(item, team, anchor) for item in filters]
    if not isinstance(filters, dict):
        return filters
    anchored = {key: _anchored(value, team, anchor) if key == "values" else value for key, value in filters.items()}
    value = anchored.get("value")
    if anchored.get("operator") in DATE_OPERATORS and isinstance(value, str) and RELATIVE_DATE.match(value):
        resolved = relative_date_parse(value, team.timezone_info, now=anchor)
        anchored["value"] = resolved.strftime("%Y-%m-%d %H:%M:%S")
    return anchored


def _anchored_node(node: dict[str, Any], team: Team, anchor: datetime) -> dict[str, Any]:
    if not node.get("properties"):
        return node
    return {**node, "properties": _anchored(node["properties"], team, anchor)}


def _condition(node: dict[str, Any], team: Team, anchor: datetime) -> ast.Expr:
    if node["kind"] == "ActionsNode":
        match = parse_expr("matchesAction({id})", placeholders={"id": ast.Constant(value=int(node["id"]))})
    elif node.get("event"):
        match = parse_expr("event = {event}", placeholders={"event": ast.Constant(value=node["event"])})
    else:
        match = ast.Constant(value=True)
    if node.get("properties"):
        return ast.And(exprs=[match, property_to_expr(_anchored(node["properties"], team, anchor), team)])
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


def _midnight(team: Team, day: date) -> ast.Constant:
    return ast.Constant(value=datetime.combine(day, time.min, tzinfo=team.timezone_info))


def _day(value: date | str) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value[:10])


def key_metrics(team: Team, user: User) -> list[KeyMetric] | None:
    nodes = _configured_nodes(team)
    live_actions = action_filter_conditions(team=team, action_ids=_action_ids(nodes))
    today = timezone.now().astimezone(team.timezone_info).date()
    anchor = datetime.combine(today, time.min, tzinfo=team.timezone_info)
    conditions = {
        key: _condition(node, team, anchor)
        for key, node in nodes.items()
        if node["kind"] == "EventsNode" or int(node["id"]) in live_actions
    }
    if not conditions:
        return []
    test_accounts = property_to_expr(_anchored(team.test_account_filters or [], team, anchor), team)

    daily = _select(
        DAILY,
        start=_midnight(team, today - timedelta(days=DAYS)),
        end=_midnight(team, today),
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
    weekly = (
        _run(
            _select(
                WEEKLY_PEOPLE,
                start=_midnight(team, today - timedelta(days=14)),
                week=_midnight(team, today - timedelta(days=7)),
                end=_midnight(team, today),
                match=conditions[PEOPLE_METRIC],
                test_accounts=clone_expr(test_accounts),
            ),
            team,
            user,
        )
        if PEOPLE_METRIC in conditions
        else []
    )
    if rows is None or weekly is None:
        return None
    by_day = {_day(row[0]): row[1:] for row in rows}

    days = [today - timedelta(days=offset) for offset in range(DAYS, 0, -1)]
    metrics = []
    for index, key in enumerate(conditions):
        points = [(day, float(by_day[day][index]) if day in by_day else 0.0) for day in days]
        if key == PEOPLE_METRIC:
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
                node=_anchored_node(nodes[key], team, anchor),
            )
        )
    return metrics
