"""Resolve a trends, stickiness or lifecycle result row to the query series it reports.

These mirror `getResultSeries` and `getResultSeriesIndex` in `frontend/src/scenes/insights/utils/resultSeries.ts`, so
backend readers identify series by the rules the frontend uses, without the legacy `action` field on result rows.
Queries, rows and series nodes are JSON-shaped, as stored on an insight or dumped from a schema model.
"""

from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING, Any

from products.actions.backend.models.action import Action

if TYPE_CHECKING:
    from posthog.models import Team

WAREHOUSE_NODE_KINDS = frozenset({"DataWarehouseNode", "LifecycleDataWarehouseNode"})


def get_result_order(result: Mapping[str, Any]) -> int:
    """The row's series index, or its formula index on a formula row."""
    order = result.get("order")
    return order if isinstance(order, int) else 0


def has_formula_results(query: Mapping[str, Any]) -> bool:
    """Whether the query returns formula rows in place of series rows.

    This mirrors the trends runner, which reads `formulaNodes`, then `formulas`, then `formula`, and ignores an empty
    list or string. The calendar heatmap runner ignores formulas and reports series 0, so its query keeps its formulas
    without returning formula rows.
    """
    if query.get("kind") != "TrendsQuery":
        return False
    trends_filter = query.get("trendsFilter") or {}
    if trends_filter.get("display") == "CalendarHeatmap":
        return False
    return bool(trends_filter.get("formulaNodes") or trends_filter.get("formulas") or trends_filter.get("formula"))


def get_result_series_index(query: Mapping[str, Any], result: Mapping[str, Any]) -> int | None:
    """The query series index of a series row. None on a formula row, because its `order` indexes the formulas."""
    return None if has_formula_results(query) else get_result_order(result)


def get_result_series(query: Mapping[str, Any], result: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """The query series node the row reports. None on a formula row, and on a row whose series the query does not hold."""
    index = get_result_series_index(query, result)
    series = query.get("series")
    if index is None or not isinstance(series, list) or not 0 <= index < len(series):
        return None
    node = series[index]
    return node if isinstance(node, Mapping) else None


def get_action_names(team: "Team", query: Mapping[str, Any]) -> dict[int, str | None]:
    """The current names of the actions the query's series reference, which the runners label action series with."""
    action_ids = {action_id for node in _series_nodes(query) if (action_id := _action_id(node)) is not None}
    if not action_ids:
        return {}
    return dict(Action.objects.filter(pk__in=action_ids, team__project_id=team.project_id).values_list("pk", "name"))


def get_series_key(node: Mapping[str, Any], action_names: Mapping[int, str | None] | None = None) -> str | None:
    """The key the runners label a series with: its event, its table, its action's name, or a group's member keys.

    None for an all-events series. The query does not hold an action's name, so without `action_names` an action has
    no key, as on the frontend, and a group takes the names its member actions were saved with.
    """
    kind = node.get("kind")
    if kind == "EventsNode":
        return node.get("event")
    if kind in WAREHOUSE_NODE_KINDS:
        return node.get("table_name")
    if kind == "ActionsNode":
        action_id = _action_id(node)
        return action_names.get(action_id) if action_names is not None and action_id is not None else None
    if kind != "GroupNode":
        return None
    member_keys: list[str] = []
    for member in node.get("nodes") or []:
        member_key = _group_member_key(member, action_names)
        if member_key is None:
            return None
        member_keys.append(member_key)
    return ", ".join(member_keys)


def get_series_custom_name(node: Mapping[str, Any], action_names: Mapping[int, str | None] | None = None) -> str | None:
    """The series' rename, by the rule the trends runner applies to `custom_name`.

    That is the custom name, or a `name` other than the key the series queries. Without `action_names` an action has
    no key, so only its custom name counts.
    """
    custom_name = node.get("custom_name")
    if isinstance(custom_name, str) and custom_name:
        return custom_name
    name = node.get("name")
    if not isinstance(name, str) or not name:
        return None
    if node.get("kind") == "ActionsNode" and action_names is None:
        return None
    return name if name != get_series_key(node, action_names) else None


def _series_nodes(query: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    # Actors queries hold the index of one series in `series`, not a list of nodes.
    series = query.get("series")
    if not isinstance(series, list):
        return
    for node in series:
        if isinstance(node, Mapping):
            yield node
            yield from (member for member in node.get("nodes") or [] if isinstance(member, Mapping))


def _action_id(node: Mapping[str, Any]) -> int | None:
    if node.get("kind") != "ActionsNode":
        return None
    try:
        return int(node["id"])
    except (KeyError, TypeError, ValueError):
        return None


def _group_member_key(member: Mapping[str, Any], action_names: Mapping[int, str | None] | None) -> str | None:
    kind = member.get("kind")
    if kind == "EventsNode":
        event = member.get("event")
        return "All events" if event is None else event
    if kind == "ActionsNode":
        if action_names is None:
            return member.get("name") or None
        action_id = _action_id(member)
        return (action_names.get(action_id) if action_id is not None else None) or "Unnamed action"
    return get_series_key(member, action_names)
