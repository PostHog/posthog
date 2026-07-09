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

# A streamed source (e.g. the events table) is continuously fresh, so it imposes no
# floor: a descendant may be as tight as the buckets allow. Imported sources instead
# carry their real sync interval.
#
# STREAMING overloads timedelta(0): it sorts below every real interval, so min/max
# propagation needs no special case. Compare against STREAMING rather than a bare
# timedelta(0) so the intent stays searchable; None (elsewhere) means "unscheduled".
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


def all_source_floors(edges: list[tuple[str, str]], source_intervals: dict[str, timedelta]) -> dict[str, timedelta]:
    """Every node's source floor (slowest ancestor source interval) in one forward pass.

    One forward pass instead of a per-node ancestor walk, so a whole-graph check is O(N+E) rather
    than O(N^2). STREAMING for a node with no ancestor source. Nodes in a cycle are omitted
    (callers default them to STREAMING; the scheduling path rejects cycles upstream).
    """
    children, parents = _adjacency(edges)
    all_ids = set(source_intervals) | {node for edge in edges for node in edge}
    in_degree = {node: len(parents.get(node, [])) for node in all_ids}
    queue = deque(node for node in all_ids if in_degree[node] == 0)
    floor: dict[str, timedelta] = {}
    while queue:
        node = queue.popleft()
        floor[node] = max([source_intervals.get(node, STREAMING), *(floor[parent] for parent in parents.get(node, []))])
        for child in children.get(node, []):
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)
    return floor


def all_consumer_ceilings(
    edges: list[tuple[str, str]], declared_targets: dict[str, timedelta]
) -> dict[str, timedelta | None]:
    """Every node's consumer ceiling (finest declared target among strict descendants) in one
    reverse pass. None when no descendant declares a target. Cyclic nodes are omitted."""
    children, parents = _adjacency(edges)
    all_ids = set(declared_targets) | {node for edge in edges for node in edge}
    out_degree = {node: len(children.get(node, [])) for node in all_ids}
    queue = deque(node for node in all_ids if out_degree[node] == 0)
    ceiling: dict[str, timedelta | None] = {}
    while queue:
        node = queue.popleft()
        candidates = [declared_targets[child] for child in children.get(node, []) if child in declared_targets]
        candidates += [ceiling[child] for child in children.get(node, []) if ceiling.get(child) is not None]
        ceiling[node] = min(candidates) if candidates else None
        for parent in parents.get(node, []):
            out_degree[parent] -= 1
            if out_degree[parent] == 0:
                queue.append(parent)
    return ceiling


def nearest_schedulable_bucket_at_least(floor: timedelta) -> timedelta:
    """The finest schedulable bucket no finer than `floor` — coarsen up to a runnable cadence.

    A source delivering every 45min means running finer than 1hour recomputes identical data, so
    the meaningful cadence is the smallest bucket >= the floor. Source intervals are themselves
    schedulable buckets, so a real floor is always <= the coarsest bucket; assert that rather than
    fall back to a bucket finer than the floor (which would silently defeat the clamp).
    """
    coarser_or_equal = [bucket for bucket in SCHEDULABLE_BUCKETS if bucket >= floor]
    assert coarser_or_equal, f"source floor {floor} exceeds every schedulable bucket"
    return min(coarser_or_equal)


def nearest_schedulable_bucket_at_most(cadence: timedelta) -> timedelta:
    """The coarsest schedulable bucket no coarser than `cadence` — round a non-bucket seed down to a
    finer bucket so "no older than `cadence`" stays honored (fresher is always safe). Falls back to
    the finest bucket for a sub-minute cadence, the finest anything can actually be scheduled at.
    """
    finer_or_equal = [bucket for bucket in SCHEDULABLE_BUCKETS if bucket <= cadence]
    return max(finer_or_equal) if finer_or_equal else min(SCHEDULABLE_BUCKETS)


@dataclasses.dataclass
class ClampedCadence:
    """A node whose effective cadence was coarsened to what its ancestor sources can deliver."""

    node_id: str
    demanded: timedelta  # cadence propagation or the seed asked for
    source_floor: timedelta  # slowest ancestor source
    clamped_to: timedelta  # the schedulable bucket it will actually run at


def clamp_to_source_floor(
    effective: dict[str, timedelta | None],
    *,
    edges: list[tuple[str, str]],
    source_intervals: dict[str, timedelta],
) -> tuple[dict[str, timedelta | None], list[ClampedCadence]]:
    """Coarsen every node scheduled finer than its sources can deliver to the nearest bucket >= its
    source floor, returning the adjusted cadences and the list of changes.

    Clamping each node independently stays consistent because the floor spans the whole ancestor
    cone (`all_source_floors`): a consumer that pulled an ancestor too fine shares that same
    source and clamps to the same bucket. Streaming/best-effort sources have a zero floor and are
    never clamped.
    """
    floors = all_source_floors(edges, source_intervals)
    clamped: dict[str, timedelta | None] = {}
    changes: list[ClampedCadence] = []
    for node_id, cadence in effective.items():
        if cadence is None:
            clamped[node_id] = None
            continue
        source_floor = floors.get(node_id, STREAMING)
        if is_finer_than(cadence, source_floor):
            target = nearest_schedulable_bucket_at_least(source_floor)
            clamped[node_id] = target
            changes.append(
                ClampedCadence(node_id=node_id, demanded=cadence, source_floor=source_floor, clamped_to=target)
            )
        else:
            clamped[node_id] = cadence
    return clamped, changes


def normalize_seed_target(seed: timedelta, source_floor: timedelta) -> timedelta:
    """Round a raw v1 seed cadence to a schedulable, satisfiable declared target.

    Snap a non-bucket seed down to a finer bucket (fresher honors "no older than X"), then coarsen
    to the source floor if the source cannot deliver that fast. So a go-live backfill persists a
    target that equals what the scheduler will run, rather than an unschedulable (45min) or
    unsatisfiable (finer than the source) one that reconcile would have to clamp anyway.
    """
    bucket = nearest_schedulable_bucket_at_most(seed)
    if is_finer_than(bucket, source_floor):
        return nearest_schedulable_bucket_at_least(source_floor)
    return bucket


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
    source_floor = all_source_floors(edges, source_intervals).get(node_id, STREAMING)
    consumer_ceiling = all_consumer_ceilings(edges, declared_targets).get(node_id)
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
    floors = all_source_floors(edges, source_intervals)
    ceilings = all_consumer_ceilings(edges, declared_targets)
    invalid: list[InvalidTarget] = []
    for node_id, declared in declared_targets.items():
        source_floor = floors.get(node_id, STREAMING)
        consumer_ceiling = ceilings.get(node_id)
        if is_finer_than(declared, source_floor) or (
            consumer_ceiling is not None and is_coarser_than(declared, consumer_ceiling)
        ):
            invalid.append(
                InvalidTarget(
                    node_id=node_id, declared=declared, source_floor=source_floor, consumer_ceiling=consumer_ceiling
                )
            )
    return invalid
