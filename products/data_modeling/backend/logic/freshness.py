"""Per-node freshness-target propagation for the v2 data-modeling DAG.

Pure graph functions over primitives — no Django, no Temporal. A separate layer
extracts the graph (node ids, edges, declared targets, source intervals) from the
`Node`/`Edge` models and feeds it here. Keeping this pure keeps it the cheapest
rung to test and lets the whole model be validated before any scheduling changes.

Vocabulary, one term per concept:
- declared target: what a user set on a node ("data no older than X"); optional.
- effective cadence: what propagation computes for a node:
  min(own declared target, finest effective cadence among its consumers).
  None means unscheduled (no declared target, no consumer demanding freshness).
- source interval: how often a source (TABLE) node actually receives new data;
  STREAMING (timedelta zero) when continuous.
- tier: the group of nodes sharing one effective cadence; each tier gets one
  Temporal schedule (see cohort_scheduling).
- bounds: a declarable target must sit in [source floor .. consumer ceiling].
  source_floor = the slowest ancestor source interval (you cannot promise fresher
  data than your slowest source delivers); consumer_ceiling = the finest declared
  target among descendants (you cannot be staler than a consumer requires).
  In interval-space a smaller timedelta means fresher/more frequent, so as plain
  timedeltas: source_floor <= target <= consumer_ceiling.

Worked example, a chain src -> view -> endpoint:
  src is an imported table syncing every 1hour (its source interval), endpoint
  declares a 6hour target, view declares nothing. Effective cadences: endpoint
  6hour (its own declared target), view 6hour (inherited from its finest consumer).
  One 6hour tier containing both nodes. If view later declares its own target it is
  bounded to [1hour .. 6hour]: a 30min target is rejected (finer than src delivers),
  a 12hour target is rejected (staler than endpoint requires).

Edges are (upstream_id, downstream_id): data flows upstream -> downstream, so a node's
"children"/descendants are reached by following edges forward.
"""

import dataclasses
from collections import defaultdict, deque
from datetime import timedelta

from products.data_modeling.backend.logic.graph_traversal import reachable

# A streamed source (e.g. the events table) is continuously fresh, so it imposes no
# floor: a descendant may be as tight as the buckets allow. Imported sources instead
# carry their real sync interval.
#
# Loud invariant: STREAMING overloads timedelta(0). A timedelta in this module means
# one of three things depending on where it flows: a real interval, timedelta(0) for
# "streaming, no floor" (sorts below every real interval so min/max propagation just
# works), and None elsewhere for "unscheduled". Do not compare against timedelta(0)
# directly; compare against STREAMING so the intent stays searchable.
STREAMING = timedelta(0)

# Intervals build_schedule_spec can realize exactly (minute buckets must divide 60, hour
# buckets 24, then weekly/monthly); anything else silently degrades or crashes there.
# Spelled out literally so this module stays Django-free; a test pins each value to the
# canonical sync-frequency buckets in warehouse_sources.
SCHEDULABLE_BUCKETS: frozenset[timedelta] = frozenset(
    {
        timedelta(minutes=1),
        timedelta(minutes=5),
        timedelta(minutes=15),
        timedelta(minutes=30),
        timedelta(hours=1),
        timedelta(hours=6),
        timedelta(hours=12),
        timedelta(hours=24),
        timedelta(days=7),
        timedelta(days=30),
    }
)


class UnsatisfiableFrequencyError(ValueError):
    """A declared target falls outside the node's legal [source_floor, consumer_ceiling] range."""


class UnsupportedFrequencyTargetError(ValueError):
    """A declared target is not one of the schedulable cadence buckets (SCHEDULABLE_BUCKETS)."""


def is_finer_than(cadence: timedelta, other: timedelta) -> bool:
    """Whether `cadence` refreshes more often than `other` (smaller timedelta = fresher)."""
    return cadence < other


def is_coarser_than(cadence: timedelta, other: timedelta) -> bool:
    """Whether `cadence` refreshes less often than `other` (bigger timedelta = staler)."""
    return cadence > other


def format_cadence(interval: timedelta) -> str:
    """Human label for a cadence, matching the sync-frequency bucket names ("15min", "6hour", "7day")."""
    seconds = int(interval.total_seconds())
    if seconds >= 86400 and seconds % 86400 == 0:
        return f"{seconds // 86400}day"
    if seconds >= 3600 and seconds % 3600 == 0:
        return f"{seconds // 3600}hour"
    if seconds >= 60 and seconds % 60 == 0:
        return f"{seconds // 60}min"
    return str(interval)


def _adjacency(edges: list[tuple[str, str]]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Return (children, parents) maps. Edges are (upstream, downstream)."""
    children: dict[str, list[str]] = defaultdict(list)
    parents: dict[str, list[str]] = defaultdict(list)
    for upstream, downstream in edges:
        children[upstream].append(downstream)
        parents[downstream].append(upstream)
    return children, parents


def compute_effective_cadences(
    *,
    nodes: set[str],
    edges: list[tuple[str, str]],
    declared_targets: dict[str, timedelta],
) -> dict[str, timedelta | None]:
    """Resolve each node's effective cadence.

    Returns a value for every id in `nodes`. `None` means "unscheduled" — a node with
    no declared target and no scheduled descendant demanding freshness (the
    ride-downstream opt-out). Source nodes are not expected in `nodes`.
    """
    children, parents = _adjacency(edges)
    # reverse-topological pass, iterative because recursion overflows on deep chains
    out_degree = {node: sum(1 for child in children.get(node, []) if child in nodes) for node in nodes}
    queue = deque(node for node in nodes if out_degree[node] == 0)
    resolved: dict[str, timedelta | None] = {}
    while queue:
        node = queue.popleft()
        candidates: list[timedelta] = []
        if node in declared_targets:
            candidates.append(declared_targets[node])
        for child in children.get(node, []):
            if child in nodes and (child_effective := resolved[child]) is not None:
                candidates.append(child_effective)
        # min = the finest demand wins (smaller timedelta = fresher)
        resolved[node] = min(candidates) if candidates else None
        for parent in parents.get(node, []):
            if parent in nodes:
                out_degree[parent] -= 1
                if out_degree[parent] == 0:
                    queue.append(parent)

    if len(resolved) != len(nodes):
        raise ValueError(f"cycle detected in DAG; unresolved nodes: {sorted(nodes - resolved.keys())}")
    return resolved


def declared_target_bounds(
    *,
    node_id: str,
    edges: list[tuple[str, str]],
    declared_targets: dict[str, timedelta],
    source_intervals: dict[str, timedelta],
) -> tuple[timedelta, timedelta | None]:
    """Return (source_floor, consumer_ceiling) for a node's declarable target.

    source_floor = the slowest interval among ancestor source nodes (STREAMING sources
    add no floor). consumer_ceiling = the finest declared target among descendants, or
    None if no descendant declares one. A floor coarser than the ceiling means the node
    is unsatisfiable.
    """
    children, parents = _adjacency(edges)

    ancestor_source_intervals = [
        source_intervals[ancestor] for ancestor in reachable(node_id, parents) if ancestor in source_intervals
    ]
    source_floor = max(ancestor_source_intervals) if ancestor_source_intervals else STREAMING

    descendant_targets = [
        declared_targets[descendant] for descendant in reachable(node_id, children) if descendant in declared_targets
    ]
    consumer_ceiling = min(descendant_targets) if descendant_targets else None

    return source_floor, consumer_ceiling


def validate_declared_target(
    *,
    node_id: str,
    target: timedelta,
    edges: list[tuple[str, str]],
    declared_targets: dict[str, timedelta],
    source_intervals: dict[str, timedelta],
) -> None:
    """Raise if `target` is not a schedulable bucket or falls outside the node's bounds."""
    if target not in SCHEDULABLE_BUCKETS:
        supported = ", ".join(format_cadence(interval) for interval in sorted(SCHEDULABLE_BUCKETS))
        raise UnsupportedFrequencyTargetError(
            f"Requested freshness ({format_cadence(target)}) is not a schedulable cadence; pick one of: {supported}"
        )
    source_floor, consumer_ceiling = declared_target_bounds(
        node_id=node_id, edges=edges, declared_targets=declared_targets, source_intervals=source_intervals
    )
    if is_finer_than(target, source_floor):
        raise UnsatisfiableFrequencyError(
            f"Requested freshness ({format_cadence(target)}) is more frequent than this node's sources can deliver;"
            f" the slowest upstream source syncs every {format_cadence(source_floor)}"
        )
    if consumer_ceiling is not None and is_coarser_than(target, consumer_ceiling):
        raise UnsatisfiableFrequencyError(
            f"Requested freshness ({format_cadence(target)}) is less frequent than a downstream consumer requires"
            f" (tightest downstream target: {format_cadence(consumer_ceiling)})"
        )


@dataclasses.dataclass
class InvalidTarget:
    """A declared target that currently sits outside its node's legal bounds."""

    node_id: str
    declared: timedelta
    source_floor: timedelta
    consumer_ceiling: timedelta | None


def find_invalid_targets(
    *,
    edges: list[tuple[str, str]],
    declared_targets: dict[str, timedelta],
    source_intervals: dict[str, timedelta],
) -> list[InvalidTarget]:
    """Re-validate every declared target against its current bounds.

    Targets drift: a descendant declaring a finer target lowers ancestors' ceilings, and
    graph edits move floors. Runtime freshness stays correct (finest demand wins) — what
    breaks is declared == effective, so run this on any graph mutation and surface the result.
    """
    invalid: list[InvalidTarget] = []
    for node_id, declared in declared_targets.items():
        source_floor, consumer_ceiling = declared_target_bounds(
            node_id=node_id, edges=edges, declared_targets=declared_targets, source_intervals=source_intervals
        )
        if is_finer_than(declared, source_floor) or (
            consumer_ceiling is not None and is_coarser_than(declared, consumer_ceiling)
        ):
            invalid.append(
                InvalidTarget(
                    node_id=node_id, declared=declared, source_floor=source_floor, consumer_ceiling=consumer_ceiling
                )
            )
    return invalid
