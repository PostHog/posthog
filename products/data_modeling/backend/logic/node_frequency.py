"""ORM-facing glue between the `Node` graph and the pure freshness logic.

`freshness.py` stays pure (primitives only); this module reads the declared target
off `Node.properties`, extracts the `(nodes, edges, targets)` graph for a DAG, and
resolves per-source freshness. Storing the target in `properties` is a deliberate
stopgap: it lets us validate the model with no migration before promoting it to a
typed column.
"""

import uuid
import dataclasses
from collections.abc import Collection, Iterable, Mapping
from datetime import timedelta
from typing import Any

from django.db.models import Q, QuerySet

from posthog.dataclasses import frozen

from products.data_modeling.backend.facade.contracts import SavedQueryNodeState, SuspensionMarker
from products.data_modeling.backend.logic.cohort_scheduling import MINUTES_PER_WEEK
from products.data_modeling.backend.logic.freshness import (
    STREAMING,
    ClampedCadence,
    ClampReason,
    InvalidTarget,
    TargetBounds,
    TargetOption,
    all_source_floor_bounds,
    all_source_floors,
    ancestors_of,
    clamp_to_source_floor,
    compute_effective_cadences,
    compute_target_bounds,
    descendants_broken_by_pin,
    descendants_of,
    find_invalid_targets,
    intersect_target_bounds,
    max_data_age,
    nodes_below_source_floor,
    normalize_seed_target,
)
from products.data_modeling.backend.logic.node_suspension import merged_suspension_state
from products.data_modeling.backend.logic.refresh_floor import read_plan_refresh_floor
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.edge import Edge
from products.data_modeling.backend.models.node import SAVED_QUERY_NODE_TYPES, Node, NodeType
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSchema

# Declared target lives here, mirroring properties["system"]["suspended"] (circuit breaker).
_SYSTEM_KEY = "system"
_FREQUENCY_KEY = "frequency"
_TARGET_SECONDS_KEY = "target_seconds"
_ANCHOR_MINUTES_KEY = "anchor_minutes"
_PINNED_KEY = "pinned"

# `resolve_dependency_to_node` stamps this on source (TABLE) nodes at creation.
_ORIGIN_KEY = "origin"
_WAREHOUSE_TABLE_ID_KEY = "warehouse_table_id"
_ORIGIN_POSTHOG = "posthog"
_ORIGIN_WAREHOUSE = "warehouse"


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class NodeIdentity:
    """What a node is in access-control terms, so a caller can decide whether to name it.

    All three empty means the node predates the origin stamp, and a caller that redacts should
    treat it as withheld rather than guess.
    """

    saved_query_id: str | None  # views, materialized views and endpoints, under `warehouse_view`
    warehouse_table_id: str | None  # imported source tables, under `warehouse_table`
    is_posthog_table: bool  # `events`, `persons` and friends, readable by anyone on the project


def node_identity(node: Node) -> NodeIdentity:
    """Resolve one node to the resource its name belongs to."""
    if node.saved_query_id is not None:
        return NodeIdentity(saved_query_id=str(node.saved_query_id), warehouse_table_id=None, is_posthog_table=False)
    properties = node.properties or {}
    table_id = properties.get(_WAREHOUSE_TABLE_ID_KEY)
    return NodeIdentity(
        saved_query_id=None,
        warehouse_table_id=str(table_id) if table_id else None,
        is_posthog_table=properties.get(_ORIGIN_KEY) == _ORIGIN_POSTHOG,
    )


def get_declared_target(node: Node) -> timedelta | None:
    """Return the node's declared freshness target, or None if it has none."""
    seconds = (node.properties or {}).get(_SYSTEM_KEY, {}).get(_FREQUENCY_KEY, {}).get(_TARGET_SECONDS_KEY)
    return timedelta(seconds=seconds) if seconds is not None else None


def is_declared_pin(properties: Mapping[str, Any] | None) -> bool:
    """Return whether node properties say it holds its declared target instead of following its consumers."""
    return bool((properties or {}).get(_SYSTEM_KEY, {}).get(_FREQUENCY_KEY, {}).get(_PINNED_KEY, False))


def get_declared_pin(node: Node) -> bool:
    """Return whether the node holds its declared target instead of following its consumers."""
    return is_declared_pin(node.properties)


def declared_targets_by_saved_query(team_id: int, saved_query_ids: Iterable[str | uuid.UUID]) -> dict[str, timedelta]:
    """Declared freshness target per saved query id, for those whose node carries one.

    Batched for callers that render many saved queries at once.
    """
    ids = [str(saved_query_id) for saved_query_id in saved_query_ids]
    if not ids:
        return {}

    return declared_targets_from_nodes(
        Node.objects.filter(team_id=team_id, saved_query_id__in=ids).only("saved_query_id", "properties")
    )


def declared_targets_from_nodes(nodes: Iterable[Node]) -> dict[str, timedelta]:
    """Declared freshness target per saved query id, from nodes the caller already loaded.

    A saved query can hold nodes in several DAGs, but `apply_saved_query_frequency_target` writes
    the same target to all of them, so the first one found wins.
    """
    targets: dict[str, timedelta] = {}
    for node in nodes:
        target = get_declared_target(node)
        if target is not None:
            targets.setdefault(str(node.saved_query_id), target)
    return targets


def node_states_by_saved_query(
    team_id: int, saved_query_ids: Iterable[str | uuid.UUID]
) -> dict[str, SavedQueryNodeState]:
    """Declared target and suspension per saved query id, from one read of their nodes.

    Batched for callers that render many saved queries at once.
    """
    ids = [str(saved_query_id) for saved_query_id in saved_query_ids]
    if not ids:
        return {}

    nodes_by_query: dict[str, list[Node]] = {}
    for node in Node.objects.filter(team_id=team_id, saved_query_id__in=ids).only("saved_query_id", "properties"):
        nodes_by_query.setdefault(str(node.saved_query_id), []).append(node)
    targets = declared_targets_from_nodes(node for nodes in nodes_by_query.values() for node in nodes)
    return {
        query_id: SavedQueryNodeState(
            declared_target=targets.get(query_id),
            suspended={
                engine: SuspensionMarker(at=marker["at"], reason=marker["reason"], job_id=marker["job_id"])
                for engine, marker in merged_suspension_state(nodes).items()
            },
        )
        for query_id, nodes in nodes_by_query.items()
    }


def set_declared_target(node: Node, target: timedelta | None) -> None:
    """Set (or clear, with None) the node's declared target without touching sibling system state.

    Clearing the target also clears the pin, because a pin holds the target and has nothing to hold without one.
    """
    stage_declared_target(node, target)
    node.save(update_fields=["properties"])


def stage_declared_target(node: Node, target: timedelta | None) -> None:
    """`set_declared_target` without the save, for callers that write many nodes in one update."""
    properties = node.properties or {}
    frequency = properties.setdefault(_SYSTEM_KEY, {}).setdefault(_FREQUENCY_KEY, {})
    if target is None:
        frequency.pop(_TARGET_SECONDS_KEY, None)
        frequency.pop(_PINNED_KEY, None)
    else:
        frequency[_TARGET_SECONDS_KEY] = int(target.total_seconds())
    node.properties = properties


def set_declared_pin(node: Node, pinned: bool) -> None:
    """Pin (or unpin) the node's declared target without touching sibling system state."""
    if pinned and get_declared_target(node) is None:
        raise ValueError("a node needs a declared target before it can be pinned")
    properties = node.properties or {}
    frequency = properties.setdefault(_SYSTEM_KEY, {}).setdefault(_FREQUENCY_KEY, {})
    if pinned:
        frequency[_PINNED_KEY] = True
    else:
        frequency.pop(_PINNED_KEY, None)
    node.properties = properties
    node.save(update_fields=["properties"])


def get_declared_anchor(node: Node) -> int | None:
    """Return the node's declared schedule anchor (minutes past Monday 00:00 UTC), or None."""
    return (node.properties or {}).get(_SYSTEM_KEY, {}).get(_FREQUENCY_KEY, {}).get(_ANCHOR_MINUTES_KEY)


def set_declared_anchor(node: Node, anchor_minutes: int | None) -> None:
    """Set (or clear, with None) the node's schedule anchor without touching sibling system state."""
    if anchor_minutes is not None and not 0 <= anchor_minutes < MINUTES_PER_WEEK:
        raise ValueError(f"anchor_minutes must be in [0, {MINUTES_PER_WEEK}), got {anchor_minutes}")
    properties = node.properties or {}
    frequency = properties.setdefault(_SYSTEM_KEY, {}).setdefault(_FREQUENCY_KEY, {})
    if anchor_minutes is None:
        frequency.pop(_ANCHOR_MINUTES_KEY, None)
    else:
        frequency[_ANCHOR_MINUTES_KEY] = anchor_minutes
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
            # Best-effort fallback: name is not unique per team, and on a collision the
            # index above kept an arbitrary row, so this may resolve to the wrong table.
            # Acceptable because an unresolvable/wrong match only widens the best-effort
            # set; never treat this path as authoritative.
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


@frozen
class FrequencyGraph:
    """The primitives `freshness.py` operates on, extracted from one DAG's Node/Edge rows."""

    nodes: set[str]  # schedulable (non-TABLE) node ids
    edges: list[tuple[str, str]]  # (upstream_id, downstream_id), includes source tables
    declared_targets: dict[str, timedelta]  # declared per-node targets
    declared_anchors: dict[str, int]  # declared per-node schedule anchors (minutes past Monday 00:00 UTC)
    pinned: set[str]  # nodes that hold their declared target instead of following their consumers
    source_intervals: dict[str, timedelta]  # per source (TABLE) node
    best_effort_source_ids: set[str]  # sources treated as STREAMING but not guaranteed
    names: dict[str, str]  # node id -> display name, so a bound can name what set it
    identities: dict[str, NodeIdentity]  # node id -> the resource its name belongs to
    plan_floor: timedelta | None  # finest cadence the team's plan lets a view be set to
    schedule_plan_floor: timedelta | None  # finest cadence the scheduler runs a view at on the team's plan
    plan_floor_evaluated: bool
    managed_node_ids: set[str]  # nodes whose target the managed viewset provider declares
    stand_ins: dict[str, str]  # stand-in source id -> the node that sets its interval

    def target_bounds(self, node_id: str) -> TargetBounds:
        """Every cadence `node_id` may be set to, with each blocker given as a real node id."""
        bounds = compute_target_bounds(
            node_id=node_id,
            edges=self.edges,
            declared_targets=self.declared_targets,
            source_intervals=self.source_intervals,
            pinned=self.pinned,
            plan_floor=self.plan_floor,
            schedule_plan_floor=self.schedule_plan_floor,
        )

        def real(blocker: str | None) -> str | None:
            return self.stand_ins.get(blocker, blocker) if blocker is not None else None

        # A stand-in is a source with no parents, so only the floor side of the bounds can name one.
        return dataclasses.replace(
            bounds,
            options=tuple(dataclasses.replace(option, blocker=real(option.blocker)) for option in bounds.options),
            floor=bounds.floor and dataclasses.replace(bounds.floor, blocker=real(bounds.floor.blocker)),
        )

    def invalid_targets(self, declared_targets: dict[str, timedelta] | None = None) -> list[InvalidTarget]:
        """Declared targets outside their bounds. A provider's cadence may sit below its source floor."""
        return find_invalid_targets(
            edges=self.edges,
            declared_targets=self.declared_targets if declared_targets is None else declared_targets,
            source_intervals=self.source_intervals,
            floor_exempt=self.managed_node_ids,
            pinned=self.pinned,
        )


def _managed_view_source_id(managed_node_id: str) -> str:
    """The stand-in source a managed view's readers see in its place."""
    return f"{managed_node_id}:managed-view"


def build_frequency_graph(dag: DAG) -> FrequencyGraph:
    """Extract the freshness graph for a DAG: schedulable nodes, edges, targets, source floors."""
    nodes = list(Node.objects.filter(dag=dag).exclude(saved_query__deleted=True))
    managed_node_ids = {
        str(node_id)
        for node_id in Node.objects.filter(dag=dag, saved_query__managed_viewset__isnull=False).values_list(
            "id", flat=True
        )
    }
    edges: list[tuple[str, str]] = []
    managed_reader_edges: list[tuple[str, str]] = []
    for source_id, target_id in Edge.objects.filter(dag=dag).values_list("source_id", "target_id"):
        edge = (str(source_id), str(target_id))
        # The same split as NON_SCHEDULING_EDGES, from ids already loaded instead of a second join.
        is_managed_reader = edge[0] in managed_node_ids and edge[1] not in managed_node_ids
        (managed_reader_edges if is_managed_reader else edges).append(edge)

    schedulable = {str(node.id) for node in nodes if node.type in SAVED_QUERY_NODE_TYPES}
    declared_targets: dict[str, timedelta] = {}
    declared_anchors: dict[str, int] = {}
    pinned: set[str] = set()
    for node in nodes:
        target = get_declared_target(node)
        if target is not None:
            declared_targets[str(node.id)] = target
            if get_declared_pin(node):
                pinned.add(str(node.id))
        anchor = get_declared_anchor(node)
        if anchor is not None:
            declared_anchors[str(node.id)] = anchor

    source_nodes = [node for node in nodes if node.type == NodeType.TABLE]
    source_intervals, best_effort = resolve_source_intervals(source_nodes)
    plan_floor_reading = read_plan_refresh_floor(dag.team_id)
    plan_floor = plan_floor_reading.floor
    schedule_plan_floor = plan_floor.schedule_floor if plan_floor is not None else None
    names = {str(node.id): node.name for node in nodes}
    identities = {str(node.id): node_identity(node) for node in nodes}

    # A reader never sets a managed view's cadence, and it cannot be fresher than that view's data.
    # The view's readers see a stand-in source that changes as often as that data does.
    stand_ins: dict[str, str] = {}
    if managed_reader_edges:
        runs_every, _clamped = clamp_to_source_floor(
            compute_effective_cadences(
                nodes=schedulable, edges=edges, declared_targets=declared_targets, pinned=pinned
            ),
            edges=edges,
            source_intervals=source_intervals,
            pinned=pinned,
        )
        # A materialized view's data changes once per run, whatever its inputs do, so it counts as a
        # source at its run cadence. A query-time view passes its inputs' changes straight through.
        materialized = {str(node.id) for node in nodes if node.type == NodeType.MAT_VIEW}
        run_intervals = {
            node_id: interval
            for node_id, interval in runs_every.items()
            if node_id in materialized and interval is not None
        }
        refreshes = all_source_floor_bounds(edges, {**source_intervals, **run_intervals})
        for managed_id, reader_id in managed_reader_edges:
            if managed_id not in names:
                continue
            stand_in = _managed_view_source_id(managed_id)
            if stand_in not in stand_ins:
                refresh = refreshes.get(managed_id)
                blamed = refresh.blocker if refresh is not None and refresh.blocker in names else managed_id
                stand_ins[stand_in] = blamed
                source_intervals[stand_in] = refresh.value if refresh is not None else STREAMING
                names[stand_in] = names[blamed]
                identities[stand_in] = identities[blamed]
            edges.append((stand_in, reader_id))

    return FrequencyGraph(
        nodes=schedulable,
        edges=edges,
        declared_targets=declared_targets,
        declared_anchors=declared_anchors,
        pinned=pinned,
        source_intervals=source_intervals,
        best_effort_source_ids=best_effort,
        names=names,
        identities=identities,
        plan_floor=plan_floor.min_interval if plan_floor is not None else None,
        schedule_plan_floor=schedule_plan_floor,
        plan_floor_evaluated=plan_floor_reading.evaluated,
        managed_node_ids=managed_node_ids,
        stand_ins=stand_ins,
    )


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class EffectiveCadence:
    """How often the scheduler runs a view, and what holds it back when something does."""

    cadence: timedelta
    reason: ClampReason | None  # None when nothing coarsened the cadence the view would otherwise run at


def effective_cadence(node_id: str, graph: FrequencyGraph) -> EffectiveCadence | None:
    """The cadence the scheduler runs `node_id` at, or None when nothing schedules it."""
    scheduled, clamped = scheduled_cadences(graph)
    cadence = scheduled.get(node_id)
    if cadence is None:
        return None
    clamp = next((change for change in clamped if change.node_id == node_id), None)
    return EffectiveCadence(cadence=cadence, reason=clamp.reason if clamp is not None else None)


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class SavedQueryFrequencyBounds:
    """A saved query's selectable cadences, plus what a caller needs to name the blockers."""

    bounds: TargetBounds
    names: dict[str, str]  # node id -> display name, covering every blocker the bounds reference
    identities: dict[str, NodeIdentity]  # node id -> the resource its name belongs to
    best_effort_source_ids: set[str]  # upstream sources with no schedule, so the floor is a guess
    max_data_age: timedelta
    speeds_up: dict[timedelta, set[str]]  # cadence -> upstream nodes that would run more often if this were set to it
    pinned: bool
    effective: EffectiveCadence | None  # None when nothing schedules the view


def saved_query_target_bounds(team_id: int, saved_query_id: str | uuid.UUID) -> SavedQueryFrequencyBounds | None:
    """Every cadence this saved query may be set to, folded across each DAG holding a node for it.

    The read-side twin of `apply_saved_query_frequency_target`: same nodes, same per-DAG graphs,
    same validator input, so a cadence offered here cannot be refused by the write that follows.

    None means no DAG node carries this saved query, which is not "anything goes" — it is a target
    with nowhere to be stored, and the caller owes the reader a different answer than a picker.
    """
    nodes = list(Node.objects.filter(team_id=team_id, saved_query_id=saved_query_id).select_related("dag"))
    if not nodes:
        return None

    per_dag: list[TargetBounds] = []
    names: dict[str, str] = {}
    identities: dict[str, NodeIdentity] = {}
    best_effort: set[str] = set()
    speeds_up: dict[timedelta, set[str]] = {}
    data_ages: list[timedelta] = []
    effective: list[EffectiveCadence] = []
    graphs: dict[str, FrequencyGraph] = {}
    for node in nodes:
        # a saved query can hold two nodes in one DAG, and that DAG's graph is the same for both
        dag_key = str(node.dag_id)
        if dag_key not in graphs:
            graphs[dag_key] = build_frequency_graph(node.dag)
        graph = graphs[dag_key]
        per_dag.append(graph.target_bounds(str(node.id)))
        names.update(graph.names)
        identities.update(graph.identities)
        # a best-effort source elsewhere in the DAG says nothing about this node's freshness
        ancestors = ancestors_of(str(node.id), graph.edges)
        best_effort |= graph.best_effort_source_ids & ancestors
        candidates = [option.value for option in per_dag[-1].options if option.allowed]
        for cadence, sped_up in _speeds_up_by_cadence(team_id, str(node.id), graph, ancestors, candidates).items():
            speeds_up.setdefault(cadence, set()).update(sped_up)
        data_ages.append(max_data_age(str(node.id), graph.edges, graph.source_intervals, graph.declared_targets))
        if (runs_at := effective_cadence(str(node.id), graph)) is not None:
            effective.append(runs_at)

    return SavedQueryFrequencyBounds(
        bounds=intersect_target_bounds(per_dag),
        names=names,
        identities=identities,
        best_effort_source_ids=best_effort,
        max_data_age=max(data_ages),
        speeds_up=speeds_up,
        pinned=any(get_declared_pin(node) for node in nodes),
        # A saved query with nodes in several DAGs runs at the finest cadence any of them asks for
        effective=min(effective, key=lambda runs_at: runs_at.cadence, default=None),
    )


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class SavedQueryPinPreview:
    """What pinning a saved query to each cadence would do, for the one endpoint that shows it."""

    # cadence -> downstream nodes that would read data older than their own cadence if this were pinned to it
    delays_if_pinned: dict[timedelta, set[str]]
    # cadence -> downstream nodes whose own target a pin at that cadence would put out of reach
    pin_blocked_by: dict[timedelta, set[str]]
    # cadence -> the cadence this view would run at if it held that target without a pin
    unpinned_cadence: dict[timedelta, timedelta]


def saved_query_pin_preview(team_id: int, saved_query_id: str | uuid.UUID) -> SavedQueryPinPreview:
    """The pin preview for every cadence the saved query's nodes offer, folded across their DAGs.

    Kept apart from `saved_query_target_bounds` because it costs a full-graph pass per cadence and
    only the node frequency endpoint reads it.
    """
    delays_if_pinned: dict[timedelta, set[str]] = {}
    pin_blocked_by: dict[timedelta, set[str]] = {}
    unpinned_cadence: dict[timedelta, timedelta] = {}
    graphs: dict[str, FrequencyGraph] = {}
    for node in Node.objects.filter(team_id=team_id, saved_query_id=saved_query_id).select_related("dag"):
        dag_key = str(node.dag_id)
        if dag_key not in graphs:
            graphs[dag_key] = build_frequency_graph(node.dag)
        graph = graphs[dag_key]
        node_id = str(node.id)
        options = graph.target_bounds(node_id).options
        for cadence, delayed in _delays_if_pinned_by_cadence(node_id, graph, options).items():
            delays_if_pinned.setdefault(cadence, set()).update(delayed)
        below_floor = nodes_below_source_floor(
            edges=graph.edges,
            declared_targets=graph.declared_targets,
            source_intervals=graph.source_intervals,
            pinned=graph.pinned - {node_id},
        )
        for option in options:
            stranded = descendants_broken_by_pin(
                node_id=node_id,
                target=option.value,
                edges=graph.edges,
                declared_targets=graph.declared_targets,
                source_intervals=graph.source_intervals,
                pinned=graph.pinned,
                already_below_floor=below_floor,
            )
            pin_blocked_by.setdefault(option.value, set()).update(invalid.node_id for invalid in stranded)
        for cadence, runs_at in _unpinned_cadence_by_cadence(node_id, graph, options).items():
            # A saved query with nodes in several DAGs runs at the finest cadence any of them asks for
            unpinned_cadence[cadence] = min(runs_at, unpinned_cadence.get(cadence, runs_at))
    return SavedQueryPinPreview(
        delays_if_pinned=delays_if_pinned, pin_blocked_by=pin_blocked_by, unpinned_cadence=unpinned_cadence
    )


def _speeds_up_by_cadence(
    team_id: int, node_id: str, graph: FrequencyGraph, ancestors: set[str], candidates: list[timedelta]
) -> dict[timedelta, set[str]]:
    """The materializing ancestors that would run more often if `node_id` were set to each candidate.

    Runs the scheduler's own propagation and source-floor clamp, so an ancestor its sources hold
    back, or one another consumer already drives faster, is not listed. Ephemeral views never run,
    so they are left out.
    """

    def run(declared_targets: dict[str, timedelta]) -> dict[str, timedelta | None]:
        return scheduled_cadences(graph, declared_targets=declared_targets)[0]

    upstream = ancestors & graph.nodes
    ephemeral = {
        str(view_id)
        for view_id in Node.objects.filter(team_id=team_id, id__in=upstream, type=NodeType.VIEW).values_list(
            "id", flat=True
        )
    }
    materializing = upstream - ephemeral
    if not materializing:
        return {}

    current = run(graph.declared_targets)
    result: dict[timedelta, set[str]] = {}
    for cadence in candidates:
        proposed = run({**graph.declared_targets, node_id: cadence})
        result[cadence] = {
            ancestor
            for ancestor in materializing
            if (after := proposed.get(ancestor)) is not None
            and ((before := current.get(ancestor)) is None or after < before)
        }
    return result


def _delays_if_pinned_by_cadence(
    node_id: str, graph: FrequencyGraph, options: Iterable[TargetOption]
) -> dict[timedelta, set[str]]:
    """The downstream views that would read data older than their own cadence if `node_id` were pinned to each option.

    A descendant's effective cadence comes from its own target and its own consumers, never from
    `node_id`, so one pass over the current graph answers every option.
    """
    effective = compute_effective_cadences(
        nodes=graph.nodes, edges=graph.edges, declared_targets=graph.declared_targets, pinned=graph.pinned
    )
    descendants = descendants_of(node_id, graph.edges) & graph.nodes
    return {
        option.value: {
            descendant
            for descendant in descendants
            if (cadence := effective.get(descendant)) is not None and cadence < option.value
        }
        for option in options
    }


def _unpinned_cadence_by_cadence(
    node_id: str, graph: FrequencyGraph, options: Iterable[TargetOption]
) -> dict[timedelta, timedelta]:
    """The cadence `node_id` would run at for each option if it held that target without a pin.

    Computed with only this node's pin removed, so a pin further downstream still stops the demand
    of the views below it, and then clamped to the source floor like the scheduler does.
    """
    others = graph.pinned - {node_id}
    result: dict[timedelta, timedelta] = {}
    for option in options:
        runs_at = scheduled_cadences(
            graph, declared_targets={**graph.declared_targets, node_id: option.value}, pinned=others
        )[0].get(node_id)
        result[option.value] = runs_at or option.value
    return result


def scheduled_cadences_by_node(team_id: int, dag_ids: Iterable[uuid.UUID | str]) -> dict[str, timedelta | None]:
    """The cadence the scheduler runs each node of these DAGs at, keyed by node id."""
    result: dict[str, timedelta | None] = {}
    for dag in DAG.objects.filter(team_id=team_id, id__in=set(dag_ids)):
        result.update(scheduled_cadences(build_frequency_graph(dag))[0])
    return result


def scheduled_cadences(
    graph: FrequencyGraph,
    *,
    declared_targets: Mapping[str, timedelta] | None = None,
    pinned: Collection[str] | None = None,
) -> tuple[dict[str, timedelta | None], list[ClampedCadence]]:
    """The cadence the scheduler runs each node at: effective cadences, then the source and plan floor clamp.

    The one place this pair is spelled out, so the scheduler, the tier reports and the pickers can't
    disagree about pins. `declared_targets` and `pinned` override the graph's own for what-if reads.
    """
    declared = dict(graph.declared_targets if declared_targets is None else declared_targets)
    pins = graph.pinned if pinned is None else pinned
    effective = compute_effective_cadences(nodes=graph.nodes, edges=graph.edges, declared_targets=declared, pinned=pins)
    return clamp_to_source_floor(
        effective,
        edges=graph.edges,
        source_intervals=graph.source_intervals,
        pinned=pins,
        plan_floor=graph.schedule_plan_floor,
    )


def schedulable_nodes(dag: DAG) -> QuerySet[Node]:
    """The DAG's schedulable nodes: everything that carries a live saved query (not a source
    table, not a soft-deleted query). The one definition of "what gets a freshness target"."""
    return Node.objects.filter(dag=dag, type__in=SAVED_QUERY_NODE_TYPES).exclude(saved_query__deleted=True)


def persist_seed_targets(dag: DAG, default: timedelta | None = None) -> int:
    """Persist a seed target on every schedulable node lacking one; never overwrites. Each seed is
    normalized (see `normalize_seed_target`) so the persisted target equals what the scheduler will
    run. `default` is the operator escape hatch for scheduled DAGs with no interval metadata
    anywhere. Returns how many targets were written.
    """
    graph = build_frequency_graph(dag)
    floors = all_source_floors(graph.edges, graph.source_intervals)
    seeds = seed_targets(dag)
    written = 0
    for node in schedulable_nodes(dag):
        node_id = str(node.id)
        if get_declared_target(node) is not None:
            continue
        raw = seeds.get(node_id, default)
        if raw is None:
            continue
        set_declared_target(node, normalize_seed_target(raw, floors.get(node_id, STREAMING)))
        written += 1
    return written


def seed_targets(dag: DAG) -> dict[str, timedelta]:
    """Derive a starting target per schedulable node from what the DAG already carries.

    A node inherits its saved query's `sync_frequency_interval` if set, else the DAG's
    `sync_frequency_interval`; nodes with neither are omitted. This deliberately preserves the
    distinct per-query frequencies of teams still on v1 (whose DAG runs several schedules at
    different cadences) rather than flattening everything to a single DAG cadence. Read-only;
    the preview overlays these in memory, and a backfill can persist them.
    """
    seeds: dict[str, timedelta] = {}
    for node in schedulable_nodes(dag).select_related("saved_query"):
        interval = None
        if node.saved_query is not None and node.saved_query.sync_frequency_interval is not None:
            interval = node.saved_query.sync_frequency_interval
        elif dag.sync_frequency_interval is not None:
            interval = dag.sync_frequency_interval
        if interval is not None:
            seeds[str(node.id)] = interval
    return seeds
