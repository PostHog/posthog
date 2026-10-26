"""Which lineage nodes a caller may not see because they are denied the object behind the node."""

from collections import defaultdict
from typing import TYPE_CHECKING
from uuid import UUID

from products.warehouse_sources.backend.facade.api import all_queryable_table_keys, denied_table_ids

from ..models.edge import Edge
from ..models.node import Node, NodeType
from .saved_query_reads import allowed_saved_query_ids

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import UserAccessControl

_ORIGIN_POSTHOG = "posthog"


def hidden_node_ids(team_id: int, user_access_control: "UserAccessControl") -> frozenset[str]:
    """Nodes whose backing view or table this caller may not read, and the metrics those nodes feed.

    A view node follows its saved query, and a cross-DAG placeholder follows the view it stands for.
    A table node follows its warehouse table, so a rule on the table's source also hides it. A table
    node that carries no table id is matched by name. A name that matches no warehouse table belongs
    to a PostHog table, which every project member reads.
    """
    if user_access_control.is_organization_admin:
        return frozenset()

    denied_tables = denied_table_ids(team_id, user_access_control)
    views_may_be_denied = not user_access_control.has_resource_access("warehouse_view") or bool(
        user_access_control.blocked_resource_ids_by_scope.get("warehouse_view")
    )
    if not denied_tables and not views_may_be_denied:
        return frozenset()

    rows = Node.objects.filter(team_id=team_id).values_list(
        "id",
        "type",
        "name",
        "saved_query_id",
        "properties__origin",
        "properties__warehouse_table_id",
        "properties__saved_query_id",
    )

    hidden: set[str] = set()
    saved_query_by_node: dict[str, UUID] = {}
    unresolved_table_names: dict[str, str] = {}
    has_metric_nodes = False

    for node_id, node_type, name, saved_query_id, origin, table_id, referenced_saved_query_id in rows:
        key = str(node_id)
        if node_type == NodeType.METRIC:
            has_metric_nodes = True
            continue
        backing_saved_query = saved_query_id if saved_query_id is not None else referenced_saved_query_id
        if backing_saved_query is not None:
            if views_may_be_denied:
                _record_or_hide(backing_saved_query, key, saved_query_by_node, hidden)
            continue
        if table_id is not None:
            table_uuid = _as_uuid(table_id)
            if table_uuid is None or table_uuid in denied_tables:
                hidden.add(key)
            continue
        if node_type == NodeType.TABLE and origin != _ORIGIN_POSTHOG:
            unresolved_table_names[key] = name

    if saved_query_by_node:
        allowed = allowed_saved_query_ids(team_id, user_access_control, ids=set(saved_query_by_node.values()))
        hidden |= {node_id for node_id, saved_query_id in saved_query_by_node.items() if saved_query_id not in allowed}
    if denied_tables and unresolved_table_names:
        for node_id, matched in _tables_matching_names(team_id, unresolved_table_names).items():
            if matched & denied_tables:
                hidden.add(node_id)

    if hidden and has_metric_nodes:
        hidden |= _metrics_fed_by(team_id, hidden)
    return frozenset(hidden)


def _as_uuid(value: object) -> UUID | None:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _record_or_hide(value: object, node_id: str, by_node: dict[str, UUID], hidden: set[str]) -> None:
    # A reference that does not parse names no object anyone can be granted, so it fails closed.
    resolved = _as_uuid(value)
    if resolved is None:
        hidden.add(node_id)
        return
    by_node[node_id] = resolved


def _tables_matching_names(team_id: int, unresolved_table_names: dict[str, str]) -> dict[str, set[UUID]]:
    """Table ids each unmarked table node could name, under either spelling of the table name."""
    tables_by_name: dict[str, set[UUID]] = defaultdict(set)
    for table_id, names in all_queryable_table_keys(team_id).items():
        tables_by_name[names.row_name.lower()].add(table_id)
        tables_by_name[names.queryable_key.lower()].add(table_id)
    return {node_id: tables_by_name.get(name.lower(), set()) for node_id, name in unresolved_table_names.items()}


def _metrics_fed_by(team_id: int, hidden: set[str]) -> set[str]:
    """Metric nodes with a hidden direct source. A metric whose edges never synced shows no sources,
    so this cannot reach it."""
    targets = Edge.objects.filter(team_id=team_id, target__type=NodeType.METRIC, source_id__in=hidden).values_list(
        "target_id", flat=True
    )
    return {str(target_id) for target_id in targets}
