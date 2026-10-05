"""Which lineage nodes a caller may see, by node type and by the object behind each node."""

from collections import defaultdict
from typing import TYPE_CHECKING
from uuid import UUID

from django.db.models import Q, QuerySet

from posthog.dataclasses import frozen
from posthog.scopes import APIScopeObject

from products.warehouse_sources.backend.facade.api import all_queryable_table_keys, allowed_table_ids

from ..models.edge import Edge
from ..models.node import Node, NodeType
from .saved_query_reads import allowed_saved_query_ids

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import UserAccessControl

WAREHOUSE_OBJECT_SCOPES: tuple[APIScopeObject, ...] = ("warehouse_view", "warehouse_table", "external_data_source")

_ORIGIN_KEY = "origin"
_ORIGIN_POSTHOG = "posthog"
_WAREHOUSE_TABLE_ID_KEY = "warehouse_table_id"
_SAVED_QUERY_ID_KEY = "saved_query_id"


@frozen
class NodeVisibility:
    """The nodes one caller may not see: whole types, plus individual nodes."""

    hidden_types: frozenset[str]
    hidden_ids: frozenset[str]

    @classmethod
    def none(cls) -> "NodeVisibility":
        return cls(hidden_types=frozenset(), hidden_ids=frozenset())

    def exclude_nodes(self, queryset: QuerySet) -> QuerySet:
        if self.hidden_types:
            queryset = queryset.exclude(type__in=self.hidden_types)
        if self.hidden_ids:
            queryset = queryset.exclude(id__in=self.hidden_ids)
        return queryset

    def exclude_edges(self, queryset: QuerySet) -> QuerySet:
        if self.hidden_types:
            queryset = queryset.exclude(Q(source__type__in=self.hidden_types) | Q(target__type__in=self.hidden_types))
        if self.hidden_ids:
            queryset = queryset.exclude(Q(source_id__in=self.hidden_ids) | Q(target_id__in=self.hidden_ids))
        return queryset

    def hides(self, node_type: str, node_id: str | UUID) -> bool:
        return node_type in self.hidden_types or str(node_id) in self.hidden_ids

    def types_only(self) -> "NodeVisibility":
        """The type dimension alone, for a caller that has to know which denied nodes it reaches."""
        return NodeVisibility(hidden_types=self.hidden_types, hidden_ids=frozenset())


def node_visibility_for(team_id: int, user_access_control: "UserAccessControl") -> NodeVisibility:
    """Resolve both dimensions for one caller, once per request."""
    return NodeVisibility(
        hidden_types=_hidden_node_types(user_access_control),
        hidden_ids=_hidden_node_ids(team_id, user_access_control),
    )


def _hidden_node_types(user_access_control: "UserAccessControl") -> frozenset[str]:
    if user_access_control.check_access_level_for_resource("data_catalog", required_level="viewer"):
        return frozenset()
    return frozenset({NodeType.METRIC})


def _as_uuid(value: object) -> UUID | None:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _hidden_node_ids(team_id: int, user_access_control: "UserAccessControl") -> frozenset[str]:
    """Nodes whose backing view or table this caller may not read, plus the metrics they feed.

    Empty without a single object-level rule, which is the common case and the one the Models
    scene pays for on every page of nodes and edges. An allowlisted scope counts as a rule: a
    caller with no resource-level access reaches only the objects they hold a grant on, and the
    edge list applies no resource-level check of its own.
    """
    blocked = user_access_control.blocked_resource_ids_by_scope
    allowlisted = user_access_control.allowlisted_resource_ids_by_scope
    if not any(blocked.get(scope) or allowlisted.get(scope) for scope in WAREHOUSE_OBJECT_SCOPES):
        return frozenset()

    rows = Node.objects.filter(team_id=team_id).values_list(
        "id",
        "type",
        "name",
        "saved_query_id",
        f"properties__{_ORIGIN_KEY}",
        f"properties__{_WAREHOUSE_TABLE_ID_KEY}",
        f"properties__{_SAVED_QUERY_ID_KEY}",
    )

    hidden: set[str] = set()
    saved_query_by_node: dict[str, UUID] = {}
    table_by_node: dict[str, UUID] = {}
    unresolved_table_names: dict[str, str] = {}
    has_metric_nodes = False

    for node_id, node_type, name, saved_query_id, origin, table_id, referenced_saved_query_id in rows:
        key = str(node_id)
        if node_type == NodeType.METRIC:
            has_metric_nodes = True
            continue
        backing_saved_query = saved_query_id if saved_query_id is not None else referenced_saved_query_id
        if backing_saved_query is not None:
            _record_or_hide(_as_uuid(backing_saved_query), key, saved_query_by_node, hidden)
            continue
        if table_id is not None:
            _record_or_hide(_as_uuid(table_id), key, table_by_node, hidden)
            continue
        if node_type == NodeType.TABLE and origin != _ORIGIN_POSTHOG:
            unresolved_table_names[key] = name

    hidden |= _hidden_by_saved_query(team_id, user_access_control, saved_query_by_node)
    hidden |= _hidden_by_table(team_id, user_access_control, table_by_node, unresolved_table_names)

    if hidden and has_metric_nodes:
        hidden |= _metrics_fed_by(team_id, hidden)
    return frozenset(hidden)


def _record_or_hide(resolved: UUID | None, node_id: str, by_node: dict[str, UUID], hidden: set[str]) -> None:
    if resolved is None:
        hidden.add(node_id)
        return
    by_node[node_id] = resolved


def _hidden_by_saved_query(
    team_id: int, user_access_control: "UserAccessControl", saved_query_by_node: dict[str, UUID]
) -> set[str]:
    if not saved_query_by_node:
        return set()
    allowed = allowed_saved_query_ids(team_id, user_access_control, ids=set(saved_query_by_node.values()))
    return {node_id for node_id, saved_query_id in saved_query_by_node.items() if saved_query_id not in allowed}


def _hidden_by_table(
    team_id: int,
    user_access_control: "UserAccessControl",
    table_by_node: dict[str, UUID],
    unresolved_table_names: dict[str, str],
) -> set[str]:
    tables_by_node_name = _tables_matching_names(team_id, unresolved_table_names)
    candidates = set(table_by_node.values())
    for matched in tables_by_node_name.values():
        candidates |= matched
    if not candidates:
        return set()
    allowed = allowed_table_ids(team_id, user_access_control, ids=candidates)
    hidden = {node_id for node_id, table_id in table_by_node.items() if table_id not in allowed}
    hidden |= {node_id for node_id, matched in tables_by_node_name.items() if not matched <= allowed}
    return hidden


def _tables_matching_names(team_id: int, unresolved_table_names: dict[str, str]) -> dict[str, set[UUID]]:
    """Table ids each unmarked table node could name, under either spelling. Nodes matching no
    table are left out: their name belongs to a PostHog table, which anyone on the project reads."""
    if not unresolved_table_names:
        return {}
    tables_by_name: dict[str, set[UUID]] = defaultdict(set)
    for table_id, names in all_queryable_table_keys(team_id).items():
        tables_by_name[names.row_name.lower()].add(table_id)
        tables_by_name[names.queryable_key.lower()].add(table_id)
    matches = {node_id: tables_by_name.get(name.lower(), set()) for node_id, name in unresolved_table_names.items()}
    return {node_id: matched for node_id, matched in matches.items() if matched}


def _metrics_fed_by(team_id: int, hidden: set[str]) -> set[str]:
    """Metric nodes with a hidden direct source. A metric whose edges never synced keeps its name
    and shows no sources, so this cannot reach it."""
    targets = Edge.objects.filter(team_id=team_id, target__type=NodeType.METRIC, source_id__in=hidden).values_list(
        "target_id", flat=True
    )
    return {str(target_id) for target_id in targets}
