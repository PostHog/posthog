"""Contract-shaped reads of saved queries for consumers outside this product."""

from collections.abc import Collection, Iterable
from typing import TYPE_CHECKING
from uuid import UUID

from django.conf import settings
from django.db.models import Q

from ..facade.contracts import SavedQueryDefinition, SavedQuerySummary, UpstreamTableRef
from ..models.datawarehouse_saved_query import DataWarehouseSavedQuery
from ..models.edge import Edge
from ..models.node import Node, NodeType
from .node_frequency import declared_targets_by_saved_query
from .saved_query_freshness import saved_query_materialized_at

POSTHOG_TABLE_ORIGIN = "posthog"
PROXY_SAVED_QUERY_ID_PROPERTY = "saved_query_id"
WAREHOUSE_TABLE_ID_PROPERTY = "warehouse_table_id"

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import AccessControlLevel, UserAccessControl


def _clickhouse_type(entry: object) -> str | None:
    """The stored ClickHouse type, reading a current dict entry keyed ``clickhouse`` or a legacy
    bare type string. None for anything else, so a column with no readable type is dropped."""
    if isinstance(entry, dict):
        entry = entry.get("clickhouse")
    return entry if isinstance(entry, str) else None


def get_saved_query_columns(team_id: int, saved_query_id: UUID | str) -> dict[str, str]:
    """Each column's ClickHouse type, including any ``Nullable()`` wrapper.

    Empty for a view that has not run yet, since the columns are only recorded once a run has
    established them. A caller must treat that as unknown rather than as having no columns.

    The ``columns`` map stores each value as a bare type string (legacy rows) or a dict keyed
    ``clickhouse`` (current rows); both are unwrapped here so a consumer reads a plain type string.
    """
    stored = (
        DataWarehouseSavedQuery.objects.filter(team_id=team_id, id=saved_query_id)
        .exclude(deleted=True)
        .values_list("columns", flat=True)
        .first()
    )
    return {name: type_ for name, entry in (stored or {}).items() if (type_ := _clickhouse_type(entry)) is not None}


def get_saved_query_summary(team_id: int, saved_query_id: UUID | str) -> SavedQuerySummary | None:
    """The saved query only if it still resolves, else None.

    Soft-deleted rows are excluded because ``soft_delete`` rewrites ``name`` to a tombstone -- a
    caller holding a stored reference must not query that name.
    """
    saved_query = (
        DataWarehouseSavedQuery.objects.filter(team_id=team_id, id=saved_query_id).exclude(deleted=True).first()
    )
    if saved_query is None:
        return None
    return SavedQuerySummary(
        id=str(saved_query.id),
        team_id=saved_query.team_id,
        name=saved_query.name,
        last_run_at=saved_query_materialized_at(saved_query),
    )


def all_saved_query_columns(team_id: int) -> dict[str, dict[str, str]]:
    """Each still-resolving saved query's columns, by id, unwrapped the way ``get_saved_query_columns`` does."""
    rows = DataWarehouseSavedQuery.objects.filter(team_id=team_id).exclude(deleted=True).values_list("id", "columns")
    return {
        str(saved_query_id): {
            name: type_ for name, entry in (stored or {}).items() if (type_ := _clickhouse_type(entry)) is not None
        }
        for saved_query_id, stored in rows
    }


def get_saved_query_sql(team_id: int, saved_query_id: UUID | str) -> str | None:
    """The HogQL text of the saved query exactly as stored, or None when it no longer resolves or
    stores no text. Soft-deleted rows are excluded for the reason ``get_saved_query_summary`` gives."""
    stored = (
        DataWarehouseSavedQuery.objects.filter(team_id=team_id, id=saved_query_id)
        .exclude(deleted=True)
        .values_list("query", flat=True)
        .first()
    )
    sql = stored.get("query") if isinstance(stored, dict) else None
    return sql if isinstance(sql, str) else None


def all_saved_query_names(team_id: int) -> dict[str, str]:
    """The current name of every saved query in this team that still resolves. One query."""
    rows = DataWarehouseSavedQuery.objects.filter(team_id=team_id).exclude(deleted=True).values_list("id", "name")
    return {str(saved_query_id): name for saved_query_id, name in rows}


def saved_query_definitions(team_id: int) -> list[SavedQueryDefinition]:
    """Every saved query in this team that still resolves, with its HogQL, materialization and DAG node interval."""
    saved_queries = list(
        DataWarehouseSavedQuery.objects.filter(team_id=team_id)
        .exclude(deleted=True)
        .only("id", "name", "query", "is_materialized", "is_test", "managed_viewset_id", "created_at")
        .order_by("created_at", "id")
    )
    intervals = declared_targets_by_saved_query(team_id, [saved_query.id for saved_query in saved_queries])
    return [
        SavedQueryDefinition(
            id=saved_query.id,
            name=saved_query.name,
            hogql=(saved_query.query or {}).get("query") or "",
            is_materialized=bool(saved_query.is_materialized),
            sync_frequency_interval=intervals.get(str(saved_query.id)),
            is_test=saved_query.is_test,
            is_managed=saved_query.managed_viewset_id is not None,
            created_at=saved_query.created_at,
        )
        for saved_query in saved_queries
    ]


def allowed_saved_query_ids(
    team_id: int,
    user_access_control: "UserAccessControl",
    *,
    required_level: "AccessControlLevel" = "viewer",
    ids: Collection[UUID] | None = None,
) -> frozenset[UUID]:
    """The saved queries this caller may reach at ``required_level``.

    ``ids`` narrows the objects loaded before their access controls are read, so a caller asking
    about one view does not pay for the whole project. ``None`` asks about every view; an empty
    collection asks about none.
    """
    if ids is not None and not ids:
        return frozenset()
    if ids is None:
        return user_access_control.allowed_object_ids(
            "warehouse_view",
            team_id,
            required_level,
            lambda: _resolve_allowed_saved_query_ids(team_id, user_access_control, required_level, None),
        )
    return _resolve_allowed_saved_query_ids(team_id, user_access_control, required_level, ids)


def _resolve_allowed_saved_query_ids(
    team_id: int,
    user_access_control: "UserAccessControl",
    required_level: "AccessControlLevel",
    ids: Collection[UUID] | None,
) -> frozenset[UUID]:
    candidates = DataWarehouseSavedQuery.objects.filter(team_id=team_id).exclude(deleted=True)
    if ids is not None:
        candidates = candidates.filter(id__in=ids)
    saved_queries = list(candidates.only("id", "created_by_id"))
    user_access_control.preload_object_access_controls(list(saved_queries))
    return frozenset(
        saved_query.id
        for saved_query in saved_queries
        if user_access_control.check_access_level_for_object(saved_query, required_level)
    )


def backing_table_ids_by_saved_query(team_id: int, *, table_ids: Collection[UUID] | None = None) -> dict[UUID, UUID]:
    """Private backing table ids mapped to their saved query ids. One query.

    Includes soft-deleted saved queries because deleting a view leaves its backing table behind.
    The URL predicate deliberately matches the HogQL catalog's private-backing-table exclusion.

    ``table_ids`` narrows the lookup to the tables a caller asked about, so a caller holding a
    handful of tables does not load the team's whole view list. ``None`` asks about every table; an
    empty collection asks about none.
    """
    if table_ids is not None and not table_ids:
        return {}
    saved_queries = (
        DataWarehouseSavedQuery.objects.filter(team_id=team_id, table__isnull=False)
        .select_related("table")
        .only("id", "team_id", "table_id", "table__url_pattern")
    )
    if table_ids is not None:
        saved_queries = saved_queries.filter(table_id__in=table_ids)
    return {
        saved_query.table_id: saved_query.id
        for saved_query in saved_queries
        if saved_query.table_id is not None
        and saved_query.table is not None
        and saved_query.folder_path in saved_query.table.url_pattern
    }


def get_materialized_table_uri(team_id: int, saved_query_id: UUID | str) -> str | None:
    """The S3 Delta table a materialized view's rows live in, for a consumer that reads them directly.

    None when the view no longer resolves or was never materialized — either way there is no Delta
    table to read. The path is built from the same two model properties the materialization activity
    writes to (``_build_model_table_uri``), so a reader lands on the table that run produced.
    """
    saved_query = (
        DataWarehouseSavedQuery.objects.filter(team_id=team_id, id=saved_query_id).exclude(deleted=True).first()
    )
    if saved_query is None or not saved_query.is_materialized:
        return None
    return f"{settings.BUCKET_URL}/{saved_query.folder_path}/{saved_query.normalized_name}"


def get_node_ids_for_saved_queries(team_id: int, saved_query_ids: Iterable[UUID | str]) -> dict[str, str]:
    """The DAG node each of these saved queries sits on, as one query.

    A saved query can appear in several DAGs; the lowest node id wins so a link built from this
    stays put across refreshes instead of following whichever row the database returned first.
    """
    ids = list(saved_query_ids)
    if not ids:
        return {}
    rows = (
        Node.objects.filter(team_id=team_id, saved_query_id__in=ids).order_by("id").values_list("saved_query_id", "id")
    )
    nodes: dict[str, str] = {}
    for saved_query_id, node_id in rows:
        nodes.setdefault(str(saved_query_id), str(node_id))
    return nodes


def get_node_ids_for_posthog_tables(team_id: int, table_names: Iterable[str]) -> dict[str, str]:
    """The DAG node each of these PostHog tables sits on, as one query. A table no view reads has none."""
    names = list(table_names)
    if not names:
        return {}
    rows = (
        Node.objects.filter(
            team_id=team_id,
            type=NodeType.TABLE,
            name__in=names,
            saved_query__isnull=True,
            properties__origin=POSTHOG_TABLE_ORIGIN,
        )
        .order_by("id")
        .values_list("name", "id")
    )
    nodes: dict[str, str] = {}
    for name, node_id in rows:
        nodes.setdefault(name, str(node_id))
    return nodes


def get_saved_query_ids_for_nodes(team_id: int, node_ids: Iterable[UUID | str]) -> list[str]:
    """The saved queries behind these DAG nodes. Source-table nodes have none and are dropped."""
    rows = Node.objects.filter(team_id=team_id, id__in=list(node_ids), saved_query__isnull=False).values_list(
        "saved_query_id", flat=True
    )
    return [str(saved_query_id) for saved_query_id in rows]


def dependent_saved_query_ids(team_id: int, saved_query_ids: Collection[UUID]) -> dict[UUID, frozenset[UUID]]:
    """The live saved queries that read directly from each given one, keyed by the given id.

    Follows the edges of every node a saved query has, so a dependent in another DAG counts too.
    """
    dependents: dict[UUID, set[UUID]] = {saved_query_id: set() for saved_query_id in saved_query_ids}
    edges = (
        Edge.objects.filter(
            team_id=team_id,
            source__saved_query_id__in=saved_query_ids,
            target__saved_query__isnull=False,
        )
        .exclude(target__saved_query__deleted=True)
        .values_list("source__saved_query_id", "target__saved_query_id")
    )
    for source_id, target_id in edges:
        dependents[source_id].add(target_id)
    return {saved_query_id: frozenset(ids) for saved_query_id, ids in dependents.items()}


def saved_query_node_ids(team_id: int, saved_query_id: UUID | str) -> set[str]:
    """The DAG nodes that stand for this saved query, cross-DAG proxy table nodes included."""
    return _node_ids_standing_for(team_id, {str(saved_query_id)})


def _node_ids_standing_for(team_id: int, saved_query_ids: set[str]) -> set[str]:
    return {
        str(node_id)
        for node_id in Node.objects.filter(team_id=team_id)
        .filter(Q(saved_query_id__in=saved_query_ids) | Q(properties__saved_query_id__in=saved_query_ids))
        .values_list("id", flat=True)
    }


def reachable_node_ids(team_id: int, start_node_ids: set[str], *, upstream: bool, max_depth: int | None) -> set[str]:
    """Node ids reachable from `start_node_ids` within `max_depth` hops, the start nodes excluded.

    One query per hop, each reading the frontier's edges off the `Edge` foreign-key indexes, so
    the work is bounded by the cone that is reached rather than by every edge the team owns.
    Upstream follows edges into the frontier back to their sources; downstream follows edges
    out of it to their targets.
    """
    edges = Edge.objects.filter(team_id=team_id)

    reached: set[str] = set()
    frontier = set(start_node_ids)
    depth = 0
    while frontier and (max_depth is None or depth < max_depth):
        if upstream:
            neighbor_ids = edges.filter(target_id__in=frontier).values_list("source_id", flat=True)
        else:
            neighbor_ids = edges.filter(source_id__in=frontier).values_list("target_id", flat=True)
        frontier = {str(neighbor_id) for neighbor_id in neighbor_ids} - reached - start_node_ids
        reached |= frontier
        depth += 1
    return reached


def upstream_table_refs(team_id: int, saved_query_id: UUID | str) -> frozenset[UpstreamTableRef]:
    """The tables this saved query reads from, directly or through other views in any DAG."""
    return frozenset(
        UpstreamTableRef(name=name, warehouse_table_id=_warehouse_table_id(properties))
        for name, properties in _upstream_table_nodes(team_id, str(saved_query_id))
        if _proxied_saved_query_id(properties) is None
    )


def _upstream_table_nodes(team_id: int, saved_query_id: str) -> list[tuple[str, dict[str, object]]]:
    tables_by_node_id: dict[str, tuple[str, dict[str, object]]] = {}
    walked_saved_query_ids: set[str] = set()
    pending_saved_query_ids = {saved_query_id}
    while pending_saved_query_ids:
        walked_saved_query_ids |= pending_saved_query_ids
        start_node_ids = _node_ids_standing_for(team_id, pending_saved_query_ids)
        reached = reachable_node_ids(team_id, start_node_ids, upstream=True, max_depth=None)
        for node_id, name, properties in Node.objects.filter(
            team_id=team_id, id__in=reached, type=NodeType.TABLE
        ).values_list("id", "name", "properties"):
            tables_by_node_id[str(node_id)] = (name, properties or {})
        pending_saved_query_ids = _proxied_saved_query_ids(tables_by_node_id.values()) - walked_saved_query_ids
    return list(tables_by_node_id.values())


def _proxied_saved_query_ids(table_nodes: Iterable[tuple[str, dict[str, object]]]) -> set[str]:
    return {
        proxied_id for _, properties in table_nodes if (proxied_id := _proxied_saved_query_id(properties)) is not None
    }


def _proxied_saved_query_id(properties: dict[str, object]) -> str | None:
    proxied_id = properties.get(PROXY_SAVED_QUERY_ID_PROPERTY)
    return str(proxied_id) if proxied_id else None


def _warehouse_table_id(properties: dict[str, object]) -> str | None:
    warehouse_table_id = properties.get(WAREHOUSE_TABLE_ID_PROPERTY)
    return str(warehouse_table_id) if warehouse_table_id else None
