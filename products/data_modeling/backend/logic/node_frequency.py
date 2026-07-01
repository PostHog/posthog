"""ORM-facing glue between the `Node` graph and the pure freshness logic.

`freshness.py` stays pure (primitives only); this module reads the declared target
off `Node.properties`, extracts the `(nodes, edges, targets)` graph for a DAG, and
resolves per-source freshness. Storing the target in `properties` is a deliberate
stopgap (see products/data_modeling/dev/freshness-targets-and-consistency.md) — it
lets us validate the model with no migration before promoting it to a typed column.
"""

import dataclasses
from datetime import timedelta

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


def _resolve_warehouse_source_interval(node: Node) -> timedelta | None:
    """Sync interval for an imported (origin=warehouse) source, or None if it has no schedule.

    None covers manual/`never` schemas, paused schemas, and tables we can't resolve to a schema
    — all "best-effort, no floor" from a freshness standpoint.
    """
    table_id = (node.properties or {}).get(_WAREHOUSE_TABLE_ID_KEY)
    table = None
    if table_id:
        table = DataWarehouseTable.objects.filter(team_id=node.team_id, id=table_id).exclude(deleted=True).first()
    if table is None:
        table = DataWarehouseTable.objects.filter(team_id=node.team_id, name=node.name).exclude(deleted=True).first()
    if table is None:
        return None

    schema = ExternalDataSchema.objects.filter(table_id=table.id).exclude(deleted=True).first()
    if schema is None or not schema.should_sync:
        return None
    return schema.sync_frequency_interval


def resolve_source_intervals(source_nodes: list[Node]) -> tuple[dict[str, timedelta], set[str]]:
    """Classify each source (TABLE) node into a freshness floor.

    Returns (source_intervals, best_effort_source_ids). A best-effort source is treated as
    STREAMING (no floor) but flagged so the wiring layer can warn that its downstream freshness
    is not actually guaranteed: streamed PostHog builtins are genuinely continuous, but a
    manual/paused/unresolvable import only *looks* fresh.
    """
    source_intervals: dict[str, timedelta] = {}
    best_effort: set[str] = set()
    for node in source_nodes:
        node_id = str(node.id)
        origin = (node.properties or {}).get(_ORIGIN_KEY)
        if origin == _ORIGIN_WAREHOUSE:
            interval = _resolve_warehouse_source_interval(node)
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


def persist_seed_targets(dag: DAG, default: timedelta | None = None) -> int:
    """Persist a seed target on every schedulable node lacking one; never overwrites.

    `default` covers nodes with no seedable cadence anywhere (no saved-query interval, no
    DAG interval) — the operator escape hatch for DAGs that are scheduled but carry no
    interval metadata. Returns how many targets were written.
    """
    seeds = seed_targets(dag)
    written = 0
    for node in Node.objects.filter(dag=dag).exclude(type=NodeType.TABLE):
        if get_frequency_target(node) is not None:
            continue
        target = seeds.get(str(node.id), default)
        if target is None:
            continue
        set_frequency_target(node, target)
        written += 1
    return written


def seed_targets(dag: DAG) -> dict[str, timedelta]:
    """Derive a starting target per schedulable node from what the DAG already carries.

    A node inherits its saved query's `sync_frequency_interval` if set, else the DAG's
    `sync_frequency_interval`; nodes with neither are omitted. This deliberately preserves the
    distinct per-query frequencies of teams still on v1 (whose DAG runs several schedules at
    different cadences) rather than flattening everything to a single DAG cadence. Read-only; PR B
    reuses it as the actual backfill, and the preview overlays it in memory.
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
