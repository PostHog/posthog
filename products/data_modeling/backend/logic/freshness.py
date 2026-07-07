"""Per-node freshness-target propagation for the v2 data-modeling DAG.

Pure graph functions over primitives — no Django, no Temporal. A separate layer
extracts the graph (node ids, edges, declared targets, source intervals) from the
`Node`/`Edge` models and feeds it here. Keeping this pure keeps it the cheapest
rung to test and lets the whole model be validated before any scheduling changes.

Model:
- A node's declared *target* is optional ("data no older than X").
- A node's *effective* cadence = min(own target, tightest of everything downstream).
- A legal target sits in [max(ancestor source intervals) … min(descendant targets)]:
  it can't be fresher than its sources deliver, nor staler than a consumer needs.

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
STREAMING = timedelta(0)

# Intervals build_schedule_spec can realize exactly (minute buckets must divide 60, hour
# buckets 24, then weekly/monthly); anything else silently degrades or crashes there.
# Spelled out literally so this module stays Django-free; a test pins each value to the
# canonical sync-frequency buckets in warehouse_sources.
SUPPORTED_TARGETS: frozenset[timedelta] = frozenset(
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
    """A target falls outside the node's legal [floor, ceiling] range."""


class UnsupportedFrequencyTargetError(ValueError):
    """A target is not one of the schedulable cadence buckets (SUPPORTED_TARGETS)."""


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
    targets: dict[str, timedelta],
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
        if node in targets:
            candidates.append(targets[node])
        for child in children.get(node, []):
            if child in nodes and (child_effective := resolved[child]) is not None:
                candidates.append(child_effective)
        resolved[node] = min(candidates) if candidates else None
        for parent in parents.get(node, []):
            if parent in nodes:
                out_degree[parent] -= 1
                if out_degree[parent] == 0:
                    queue.append(parent)

    if len(resolved) != len(nodes):
        raise ValueError(f"cycle detected in DAG; unresolved nodes: {sorted(nodes - resolved.keys())}")
    return resolved


def frequency_target_bounds(
    *,
    node_id: str,
    edges: list[tuple[str, str]],
    targets: dict[str, timedelta],
    source_intervals: dict[str, timedelta],
) -> tuple[timedelta, timedelta | None]:
    """Return (floor, ceiling) for a node's declarable target.

    floor = max delivered interval among ancestor source nodes (STREAMING sources add
    no floor). ceiling = tightest declared target among descendants, or None if no
    descendant declares one. floor > ceiling means the node is unsatisfiable.
    """
    children, parents = _adjacency(edges)

    ancestor_source_intervals = [
        source_intervals[ancestor] for ancestor in reachable(node_id, parents) if ancestor in source_intervals
    ]
    floor = max(ancestor_source_intervals) if ancestor_source_intervals else STREAMING

    descendant_targets = [targets[descendant] for descendant in reachable(node_id, children) if descendant in targets]
    ceiling = min(descendant_targets) if descendant_targets else None

    return floor, ceiling


def validate_frequency_target(
    *,
    node_id: str,
    target: timedelta,
    edges: list[tuple[str, str]],
    targets: dict[str, timedelta],
    source_intervals: dict[str, timedelta],
) -> None:
    """Raise if `target` is not a supported bucket or falls outside the node's [floor, ceiling]."""
    if target not in SUPPORTED_TARGETS:
        supported = ", ".join(format_cadence(interval) for interval in sorted(SUPPORTED_TARGETS))
        raise UnsupportedFrequencyTargetError(
            f"Requested freshness ({format_cadence(target)}) is not a schedulable cadence; pick one of: {supported}"
        )
    floor, ceiling = frequency_target_bounds(
        node_id=node_id, edges=edges, targets=targets, source_intervals=source_intervals
    )
    if target < floor:
        raise UnsatisfiableFrequencyError(
            f"Requested freshness ({format_cadence(target)}) is more frequent than this node's sources can deliver;"
            f" the slowest upstream source syncs every {format_cadence(floor)}"
        )
    if ceiling is not None and target > ceiling:
        raise UnsatisfiableFrequencyError(
            f"Requested freshness ({format_cadence(target)}) is less frequent than a downstream consumer requires"
            f" (tightest downstream target: {format_cadence(ceiling)})"
        )


@dataclasses.dataclass
class InvalidTarget:
    """A declared target that currently sits outside its node's legal [floor, ceiling] range."""

    node_id: str
    target: timedelta
    floor: timedelta
    ceiling: timedelta | None


def find_invalid_targets(
    *,
    edges: list[tuple[str, str]],
    targets: dict[str, timedelta],
    source_intervals: dict[str, timedelta],
) -> list[InvalidTarget]:
    """Re-validate every declared target against its current bounds.

    Targets drift: a descendant declaring a tighter target lowers ancestors' ceilings, and
    graph edits move floors. Runtime freshness stays correct (tightest demand wins) — what
    breaks is declared == effective, so run this on any graph mutation and surface the result.
    """
    invalid: list[InvalidTarget] = []
    for node_id, target in targets.items():
        floor, ceiling = frequency_target_bounds(
            node_id=node_id, edges=edges, targets=targets, source_intervals=source_intervals
        )
        if target < floor or (ceiling is not None and target > ceiling):
            invalid.append(InvalidTarget(node_id=node_id, target=target, floor=floor, ceiling=ceiling))
    return invalid
