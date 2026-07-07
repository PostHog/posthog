"""ORM-facing glue between the `Node` graph and the pure freshness logic.

`freshness.py` stays pure (primitives only); this module reads the declared target
off `Node.properties`, extracts the `(nodes, edges, targets)` graph for a DAG, and
resolves per-source freshness. Storing the target in `properties` is a deliberate
stopgap: it lets us validate the model with no migration before promoting it to a
typed column.
"""

import uuid
import dataclasses
from datetime import timedelta

from django.db.models import Q

from products.data_modeling.backend.logic.freshness import STREAMING
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.edge import Edge
from products.data_modeling.backend.models.node import Node, NodeType
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSchema

# Declared target lives here, mirroring properties["system"]["suspended"] (circuit breaker).
_SYSTEM_KEY = "system"
_FREQUENCY_KEY = "frequency"
_TARGET_SECONDS_KEY = "target_seconds"

# `resolve_dependency_to_node` stamps this on source (TABLE) nodes at creation.
_ORIGIN_KEY = "origin"
_WAREHOUSE_TABLE_ID_KEY = "warehouse_table_id"
_ORIGIN_POSTHOG = "posthog"
_ORIGIN_WAREHOUSE = "warehouse"


def get_frequency_target(node: Node) -> timedelta | None:
    """Return the node's declared freshness target, or None if it has none."""
    seconds = (node.properties or {}).get(_SYSTEM_KEY, {}).get(_FREQUENCY_KEY, {}).get(_TARGET_SECONDS_KEY)
    return timedelta(seconds=seconds) if seconds is not None else None


def set_frequency_target(node: Node, target: timedelta | None) -> None:
    """Set (or clear, with None) the node's declared target without touching sibling system state."""
    properties = node.properties or {}
    frequency = properties.setdefault(_SYSTEM_KEY, {}).setdefault(_FREQUENCY_KEY, {})
    if target is None:
        frequency.pop(_TARGET_SECONDS_KEY, None)
    else:
        frequency[_TARGET_SECONDS_KEY] = int(target.total_seconds())
    node.properties = properties
    node.save(update_fields=["properties"])


def _resolve_warehouse_source_intervals(nodes: list[Node]) -> dict[str, timedelta | None]:
    """Sync interval per imported (origin=warehouse) source node id, batched.

    A node maps to None when it has no schedule: manual/`never` schemas, paused schemas, and
    tables we can't resolve to a schema are all "best-effort, no floor" from a freshness
    standpoint. Tables resolve by the stamped table id first, falling back to the node name.
    """
    if not nodes:
        return {}
    team_ids = {node.team_id for node in nodes}
    table_ids = {table_id for node in nodes if (table_id := (node.properties or {}).get(_WAREHOUSE_TABLE_ID_KEY))}
    names = {node.name for node in nodes}
    tables = (
        DataWarehouseTable.objects.filter(team_id__in=team_ids)
        .filter(Q(id__in=table_ids) | Q(name__in=names))
        .exclude(deleted=True)
    )
    tables_by_id: dict[tuple[int, str], DataWarehouseTable] = {}
    tables_by_name: dict[tuple[int, str], DataWarehouseTable] = {}
    for table in tables:
        tables_by_id.setdefault((table.team_id, str(table.id)), table)
        tables_by_name.setdefault((table.team_id, table.name), table)

    schemas_by_table_id: dict[uuid.UUID, ExternalDataSchema] = {}
    for schema in ExternalDataSchema.objects.filter(table_id__in=[table.id for table in tables]).exclude(deleted=True):
        if schema.table_id is not None:
            schemas_by_table_id.setdefault(schema.table_id, schema)

    intervals: dict[str, timedelta | None] = {}
    for node in nodes:
        table_id = (node.properties or {}).get(_WAREHOUSE_TABLE_ID_KEY)
        node_table = tables_by_id.get((node.team_id, str(table_id))) if table_id else None
        if node_table is None:
            node_table = tables_by_name.get((node.team_id, node.name))
        node_schema = schemas_by_table_id.get(node_table.id) if node_table is not None else None
        if node_schema is None or not node_schema.should_sync:
            intervals[str(node.id)] = None
        else:
            intervals[str(node.id)] = node_schema.sync_frequency_interval
    return intervals


def resolve_source_intervals(source_nodes: list[Node]) -> tuple[dict[str, timedelta], set[str]]:
    """Classify each source (TABLE) node into a freshness floor.

    Returns (source_intervals, best_effort_source_ids). A best-effort source is treated as
    STREAMING (no floor) but flagged so the wiring layer can warn that its downstream freshness
    is not actually guaranteed: streamed PostHog builtins are genuinely continuous, but a
    manual/paused/unresolvable import only *looks* fresh.
    """
    warehouse_intervals = _resolve_warehouse_source_intervals(
        [node for node in source_nodes if (node.properties or {}).get(_ORIGIN_KEY) == _ORIGIN_WAREHOUSE]
    )
    source_intervals: dict[str, timedelta] = {}
    best_effort: set[str] = set()
    for node in source_nodes:
        node_id = str(node.id)
        origin = (node.properties or {}).get(_ORIGIN_KEY)
        if origin == _ORIGIN_WAREHOUSE:
            interval = warehouse_intervals[node_id]
            if interval is None:
                source_intervals[node_id] = STREAMING
                best_effort.add(node_id)
            else:
                source_intervals[node_id] = interval
        elif origin == _ORIGIN_POSTHOG:
            source_intervals[node_id] = STREAMING
        else:
            # Unknown/unstamped origin: assume continuous but flag it — we can't prove a floor.
            source_intervals[node_id] = STREAMING
            best_effort.add(node_id)
    return source_intervals, best_effort


@dataclasses.dataclass
class FrequencyGraph:
    """The primitives `freshness.py` operates on, extracted from one DAG's Node/Edge rows."""

    nodes: set[str]  # schedulable (non-TABLE) node ids
    edges: list[tuple[str, str]]  # (upstream_id, downstream_id), includes source tables
    targets: dict[str, timedelta]  # declared per-node targets
    source_intervals: dict[str, timedelta]  # per source (TABLE) node
    best_effort_source_ids: set[str]  # sources treated as STREAMING but not guaranteed


def build_frequency_graph(dag: DAG) -> FrequencyGraph:
    """Extract the freshness graph for a DAG: schedulable nodes, edges, targets, source floors."""
    nodes = list(Node.objects.filter(dag=dag))
    edges = [
        (str(source_id), str(target_id))
        for source_id, target_id in Edge.objects.filter(dag=dag).values_list("source_id", "target_id")
    ]

    schedulable = {str(node.id) for node in nodes if node.type != NodeType.TABLE}
    targets: dict[str, timedelta] = {}
    for node in nodes:
        target = get_frequency_target(node)
        if target is not None:
            targets[str(node.id)] = target

    source_nodes = [node for node in nodes if node.type == NodeType.TABLE]
    source_intervals, best_effort = resolve_source_intervals(source_nodes)

    return FrequencyGraph(
        nodes=schedulable,
        edges=edges,
        targets=targets,
        source_intervals=source_intervals,
        best_effort_source_ids=best_effort,
    )


def seed_targets(dag: DAG) -> dict[str, timedelta]:
    """Derive a starting target per schedulable node from what the DAG already carries.

    A node inherits its saved query's `sync_frequency_interval` if set, else the DAG's
    `sync_frequency_interval`; nodes with neither are omitted. This deliberately preserves the
    distinct per-query frequencies of teams still on v1 (whose DAG runs several schedules at
    different cadences) rather than flattening everything to a single DAG cadence. Read-only;
    the preview overlays these in memory, and a backfill can persist them.
    """
    seeds: dict[str, timedelta] = {}
    for node in Node.objects.filter(dag=dag).exclude(type=NodeType.TABLE).select_related("saved_query"):
        interval = None
        if node.saved_query is not None and node.saved_query.sync_frequency_interval is not None:
            interval = node.saved_query.sync_frequency_interval
        elif dag.sync_frequency_interval is not None:
            interval = dag.sync_frequency_interval
        if interval is not None:
            seeds[str(node.id)] = interval
    return seeds
