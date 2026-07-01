"""Per-node freshness-target propagation for the v2 data-modeling DAG.

Pure graph functions over primitives — no Django, no Temporal. A separate layer
extracts the graph (node ids, edges, declared targets, source intervals) from the
`Node`/`Edge` models and feeds it here. Keeping this pure keeps it the cheapest
rung to test and lets the whole model be validated before any scheduling changes.

Model (see products/data_modeling/dev/freshness-targets-and-consistency.md):
- A node's declared *target* is optional ("data no older than X").
- A node's *effective* cadence = min(own target, tightest of everything downstream).
- A legal target sits in [max(ancestor source intervals) … min(descendant targets)]:
  it can't be fresher than its sources deliver, nor staler than a consumer needs.

Edges are (upstream_id, downstream_id): data flows upstream -> downstream, so a node's
"children"/descendants are reached by following edges forward.
"""

from collections import defaultdict
from datetime import timedelta

# A streamed source (e.g. the events table) is continuously fresh, so it imposes no
# floor: a descendant may be as tight as the buckets allow. Imported sources instead
# carry their real sync interval.
STREAMING = timedelta(0)


class UnsatisfiableFrequencyError(ValueError):
    """A target falls outside the node's legal [floor, ceiling] range."""


def _adjacency(edges: list[tuple[str, str]]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Return (children, parents) maps. Edges are (upstream, downstream)."""
    children: dict[str, list[str]] = defaultdict(list)
    parents: dict[str, list[str]] = defaultdict(list)
    for upstream, downstream in edges:
        children[upstream].append(downstream)
        parents[downstream].append(upstream)
    return children, parents


def _reachable(start: str, adjacency: dict[str, list[str]]) -> set[str]:
    """All nodes reachable from `start` (exclusive) by following `adjacency`."""
    seen: set[str] = set()
    stack = list(adjacency.get(start, []))
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        stack.extend(adjacency.get(node, []))
    return seen


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
    children, _ = _adjacency(edges)
    memo: dict[str, timedelta | None] = {}

    def effective(node: str) -> timedelta | None:
        if node in memo:
            return memo[node]
        candidates: list[timedelta] = []
        if node in targets:
            candidates.append(targets[node])
        for child in children.get(node, []):
            if child not in nodes:
                continue
            child_effective = effective(child)
            if child_effective is not None:
                candidates.append(child_effective)
        result = min(candidates) if candidates else None
        memo[node] = result
        return result

    return {node: effective(node) for node in nodes}


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
        source_intervals[ancestor] for ancestor in _reachable(node_id, parents) if ancestor in source_intervals
    ]
    floor = max(ancestor_source_intervals) if ancestor_source_intervals else STREAMING

    descendant_targets = [targets[descendant] for descendant in _reachable(node_id, children) if descendant in targets]
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
    """Raise UnsatisfiableFrequencyError if `target` is outside the node's [floor, ceiling]."""
    floor, ceiling = frequency_target_bounds(
        node_id=node_id, edges=edges, targets=targets, source_intervals=source_intervals
    )
    if target < floor:
        raise UnsatisfiableFrequencyError(
            f"target {target} is fresher than the tightest ancestor source can deliver ({floor})"
        )
    if ceiling is not None and target > ceiling:
        raise UnsatisfiableFrequencyError(f"target {target} is staler than a downstream consumer requires ({ceiling})")
