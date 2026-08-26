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
  source_floor = how often a node's data can actually change: a source's own sync
  interval, and for a derived node the finest floor among its parents (its output
  changes whenever any input changes, so it can be as fresh as its freshest input);
  consumer_ceiling = the finest declared target among descendants (you cannot be
  staler than a consumer requires).
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
from collections.abc import Iterable, Mapping
from datetime import timedelta
from typing import Literal

# A streamed source (e.g. the events table) is continuously fresh, so it imposes no
# floor: a descendant may be as tight as the buckets allow. Imported sources instead
# carry their real sync interval.
#
# STREAMING overloads timedelta(0): it sorts below every real interval, so min/max
# propagation needs no special case. Compare against STREAMING rather than a bare
# timedelta(0) so the intent stays searchable; None (elsewhere) means "unscheduled".
STREAMING = timedelta(0)

# Intervals a model tier can run at. 15min is the floor: a model rebuild is not a source sync,
# and running one every minute costs more than the freshness is worth. Sources still sync as
# fast as 1min, so a floor derived from one rounds up into this set rather than escaping it.
# Spelled out literally so this module stays Django-free; a test pins each value to the
# canonical sync-frequency buckets in warehouse_sources.
SCHEDULABLE_BUCKETS: frozenset[timedelta] = frozenset(
    {
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
    """A declared target is not one of the cadences a person may pick (SCHEDULABLE_BUCKETS)."""


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


def humanize_cadence(interval: timedelta) -> str:
    """Plain-English cadence ("15 minutes", "6 hours", "1 day") for messages a user reads.

    Separate from `format_cadence`, whose output doubles as the API's `sync_frequency` values.
    """
    seconds = int(interval.total_seconds())
    for unit_seconds, unit in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if seconds >= unit_seconds and seconds % unit_seconds == 0:
            count = seconds // unit_seconds
            return f"{count} {unit}" if count == 1 else f"{count} {unit}s"
    return format_cadence(interval)


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class Adjacency:
    children: dict[str, list[str]]  # upstream id -> downstream ids
    parents: dict[str, list[str]]  # downstream id -> upstream ids


def _adjacency(edges: list[tuple[str, str]]) -> Adjacency:
    """Return the children/parents maps. Edges are (upstream, downstream)."""
    children: dict[str, list[str]] = defaultdict(list)
    parents: dict[str, list[str]] = defaultdict(list)
    for upstream, downstream in edges:
        children[upstream].append(downstream)
        parents[downstream].append(upstream)
    return Adjacency(children=children, parents=parents)


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
    adj = _adjacency(edges)
    # reverse-topological pass, iterative because recursion overflows on deep chains
    out_degree = {node: sum(1 for child in adj.children.get(node, []) if child in nodes) for node in nodes}
    queue = deque(node for node in nodes if out_degree[node] == 0)
    resolved: dict[str, timedelta | None] = {}
    while queue:
        node = queue.popleft()
        candidates: list[timedelta] = []
        if node in declared_targets:
            candidates.append(declared_targets[node])
        for child in adj.children.get(node, []):
            if child in nodes and (child_effective := resolved[child]) is not None:
                candidates.append(child_effective)
        # min = the finest demand wins (smaller timedelta = fresher)
        resolved[node] = min(candidates) if candidates else None
        for parent in adj.parents.get(node, []):
            if parent in nodes:
                out_degree[parent] -= 1
                if out_degree[parent] == 0:
                    queue.append(parent)

    if len(resolved) != len(nodes):
        raise ValueError(f"cycle detected in DAG; unresolved nodes: {sorted(nodes - resolved.keys())}")
    return resolved


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class Bound:
    """A bound and the node that set it, so a refusal can name what someone has to change.

    `blocker` is the node the value originates from, carried across the whole traversal rather
    than the immediate neighbour: a floor propagated down four views still points at the source
    that delivers slowly, which is the thing a person can act on.
    """

    value: timedelta
    blocker: str | None  # None when nothing set it (a derived node with no parents)


def _bound_sort_key(bound: Bound) -> tuple[timedelta, str]:
    """Order bounds by cadence, ties broken by blocker id so a graph always yields the same blame."""
    return (bound.value, bound.blocker or "")


def _finest(bounds: list[Bound]) -> Bound:
    return min(bounds, key=_bound_sort_key)


def ancestors_of(node_id: str, edges: list[tuple[str, str]]) -> set[str]:
    """Every node upstream of `node_id`, however far — the cone whose delivery it inherits."""
    parents: dict[str, list[str]] = defaultdict(list)
    for upstream, downstream in edges:
        parents[downstream].append(upstream)

    seen: set[str] = set()
    queue = deque(parents[node_id])
    while queue:
        current = queue.popleft()
        if current in seen:
            continue
        seen.add(current)
        queue.extend(parents[current])
    return seen


def all_source_floor_bounds(edges: list[tuple[str, str]], source_intervals: dict[str, timedelta]) -> dict[str, Bound]:
    """Every node's source floor, with the source that set it, in one forward pass.

    A source node's floor is its own sync interval. A derived node's floor is the finest (min)
    among its parents' floors, because its output changes whenever any input changes: a view
    joining events with a weekly import produces new rows continuously, so the weekly side must
    not drag the join to a weekly cadence. Only pure slow lineage keeps a coarse floor.

    One forward pass instead of a per-node ancestor walk, so a whole-graph check is O(N+E) rather
    than O(N^2). STREAMING for a derived node with no parents. Nodes in a cycle are omitted
    (callers default them to STREAMING; the scheduling path rejects cycles upstream).
    """
    adj = _adjacency(edges)
    all_ids = set(source_intervals) | {node for edge in edges for node in edge}
    in_degree = {node: len(adj.parents.get(node, [])) for node in all_ids}
    queue = deque(node for node in all_ids if in_degree[node] == 0)
    floor: dict[str, Bound] = {}
    while queue:
        node = queue.popleft()
        if node in source_intervals:
            floor[node] = Bound(value=source_intervals[node], blocker=node)
        else:
            inherited = [floor[parent] for parent in adj.parents.get(node, [])]
            floor[node] = _finest(inherited) if inherited else Bound(value=STREAMING, blocker=None)
        for child in adj.children.get(node, []):
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)
    return floor


def all_consumer_ceiling_bounds(
    edges: list[tuple[str, str]], declared_targets: dict[str, timedelta]
) -> dict[str, Bound | None]:
    """Every node's consumer ceiling, with the descendant that declared it, in one reverse pass.

    The ceiling is the finest declared target among strict descendants; None when no descendant
    declares one. Cyclic nodes are omitted.
    """
    adj = _adjacency(edges)
    all_ids = set(declared_targets) | {node for edge in edges for node in edge}
    out_degree = {node: len(adj.children.get(node, [])) for node in all_ids}
    queue = deque(node for node in all_ids if out_degree[node] == 0)
    ceiling: dict[str, Bound | None] = {}
    while queue:
        node = queue.popleft()
        candidates = [
            Bound(value=declared_targets[child], blocker=child)
            for child in adj.children.get(node, [])
            if child in declared_targets
        ]
        candidates += [bound for child in adj.children.get(node, []) if (bound := ceiling.get(child)) is not None]
        ceiling[node] = _finest(candidates) if candidates else None
        for parent in adj.parents.get(node, []):
            out_degree[parent] -= 1
            if out_degree[parent] == 0:
                queue.append(parent)
    return ceiling


def all_source_floors(edges: list[tuple[str, str]], source_intervals: dict[str, timedelta]) -> dict[str, timedelta]:
    """Every node's source floor, for callers that need the value and not the blame."""
    return {node: bound.value for node, bound in all_source_floor_bounds(edges, source_intervals).items()}


def all_consumer_ceilings(
    edges: list[tuple[str, str]], declared_targets: dict[str, timedelta]
) -> dict[str, timedelta | None]:
    """Every node's consumer ceiling, for callers that need the value and not the blame."""
    return {
        node: (bound.value if bound is not None else None)
        for node, bound in all_consumer_ceiling_bounds(edges, declared_targets).items()
    }


def nearest_schedulable_bucket_at_least(floor: timedelta) -> timedelta:
    """The finest schedulable bucket no finer than `floor` — coarsen up to a runnable cadence.

    A source delivering every 45min means running finer than 1hour recomputes identical data, so
    the meaningful cadence is the smallest bucket >= the floor. A floor coarser than every bucket
    (a rogue >30day source interval — the column is an unconstrained DurationField) clamps to the
    coarsest bucket: running more often than a source delivers only wastes a run, never breaks
    freshness. Mirrors nearest_schedulable_bucket_at_most's "fresher is always safe" fallback.
    """
    return _nearest_at_least(floor, SCHEDULABLE_BUCKETS)


def nearest_schedulable_bucket_at_most(cadence: timedelta) -> timedelta:
    """The coarsest schedulable bucket no coarser than `cadence` — round a non-bucket seed down to a
    finer bucket so "no older than `cadence`" stays honored (fresher is always safe). A cadence
    finer than every bucket falls back to the finest one, since nothing runs faster than that.
    """
    return _nearest_at_most(cadence, SCHEDULABLE_BUCKETS)


def _nearest_at_least(value: timedelta, buckets: frozenset[timedelta]) -> timedelta:
    coarser_or_equal = [bucket for bucket in buckets if bucket >= value]
    return min(coarser_or_equal) if coarser_or_equal else max(buckets)


def _nearest_at_most(value: timedelta, buckets: frozenset[timedelta]) -> timedelta:
    finer_or_equal = [bucket for bucket in buckets if bucket <= value]
    return max(finer_or_equal) if finer_or_equal else min(buckets)


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

    Clamping each node independently can leave a slow-lineage ancestor coarser than a mixed-lineage
    consumer, which is intended: the consumer's fast inputs keep it changing at its fine cadence,
    while the columns derived from the slow lineage update as often as that lineage delivers.
    Streaming/best-effort sources have a zero floor and are never clamped.
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

    A sub-15min v1 seed lands on 15min, the same coarsening migration 0031 applied to saved queries.
    """
    bucket = _nearest_at_most(seed, SCHEDULABLE_BUCKETS)
    if is_finer_than(bucket, source_floor):
        return _nearest_at_least(source_floor, SCHEDULABLE_BUCKETS)
    return bucket


BlockedBy = Literal["source", "consumer"]


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class TargetOption:
    """One cadence a person could pick, and why it is withheld when it is."""

    value: timedelta
    allowed: bool
    blocked_by: BlockedBy | None = None
    blocker: str | None = None  # node id of the source or consumer that withholds it


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class TargetBounds:
    """Every selectable cadence for one node, each marked allowed or blocked with its cause.

    `floor` and `ceiling` are reported only when they actually withhold an option. A 5min source
    delivers faster than any tier runs, so it withholds nothing, and reporting it would explain a
    restriction the person cannot see.
    """

    options: tuple[TargetOption, ...]  # ascending by cadence
    floor: Bound | None = None
    ceiling: Bound | None = None

    @property
    def allowed(self) -> tuple[timedelta, ...]:
        return tuple(option.value for option in self.options if option.allowed)

    @property
    def satisfiable(self) -> bool:
        """False when nothing is legal: bounds that cross, or a source slower than every target."""
        return bool(self.allowed)

    def option_for(self, target: timedelta) -> TargetOption | None:
        return next((option for option in self.options if option.value == target), None)


def compute_target_bounds(
    *,
    node_id: str,
    edges: list[tuple[str, str]],
    declared_targets: dict[str, timedelta],
    source_intervals: dict[str, timedelta],
) -> TargetBounds:
    """Resolve one node's selectable cadences, marking each blocked option with what blocks it.

    The single answer to "what may this node be set to, and why not the rest" — the validator, the
    API payload, and any UI that offers a choice all read this, so a refusal and a disabled option
    can never disagree about the same node.
    """
    floor = all_source_floor_bounds(edges, source_intervals).get(node_id, Bound(value=STREAMING, blocker=None))
    ceiling = all_consumer_ceiling_bounds(edges, declared_targets).get(node_id)
    return _bounds_from(floor=floor, ceiling=ceiling)


def _bounds_from(*, floor: Bound, ceiling: Bound | None) -> TargetBounds:
    """Mark every cadence against one pair of bounds, reporting each bound only if it blocks."""
    options: list[TargetOption] = []
    for value in sorted(SCHEDULABLE_BUCKETS):
        if is_finer_than(value, floor.value):
            options.append(TargetOption(value=value, allowed=False, blocked_by="source", blocker=floor.blocker))
        elif ceiling is not None and is_coarser_than(value, ceiling.value):
            options.append(TargetOption(value=value, allowed=False, blocked_by="consumer", blocker=ceiling.blocker))
        else:
            options.append(TargetOption(value=value, allowed=True))

    blocked = {option.blocked_by for option in options if not option.allowed}
    return TargetBounds(
        options=tuple(options),
        floor=floor if "source" in blocked else None,
        ceiling=ceiling if "consumer" in blocked else None,
    )


def intersect_target_bounds(bounds: Iterable[TargetBounds]) -> TargetBounds:
    """Fold one node's bounds across the several DAGs it can appear in, tightest side winning.

    A saved query duplicated into more than one DAG has a node in each, and the write path
    validates against every one of them. Offering the union of what any single DAG allows would
    hand someone an option their own save then refuses, so intersect: the coarsest floor and the
    finest ceiling. Bounds that block nothing are absent, and absent is the identity here.
    """
    per_dag = list(bounds)
    floors = [bound.floor for bound in per_dag if bound.floor is not None]
    ceilings = [bound.ceiling for bound in per_dag if bound.ceiling is not None]
    return _bounds_from(
        floor=max(floors, key=_bound_sort_key) if floors else Bound(value=STREAMING, blocker=None),
        ceiling=min(ceilings, key=_bound_sort_key) if ceilings else None,
    )


def _describe(node_id: str | None, names: Mapping[str, str] | None, fallback: str) -> str:
    """Name a blocking node when the caller supplied names, else fall back to a generic phrase."""
    name = (names or {}).get(node_id or "")
    return name or fallback


def _nothing_satisfiable_message(bounds: TargetBounds, names: Mapping[str, str] | None) -> str:
    """Explain a node with no legal cadence at all: crossed bounds, or a source slower than 30 days."""
    floor, ceiling = bounds.floor, bounds.ceiling
    source = _describe(floor.blocker, names, "an upstream source") if floor else ""
    consumer = _describe(ceiling.blocker, names, "a view or endpoint built on this one") if ceiling else ""
    if floor is not None and ceiling is not None:
        return (
            f"No cadence works here: {source} only syncs every {humanize_cadence(floor.value)},"
            f" but {consumer} refreshes every {humanize_cadence(ceiling.value)}."
            f" Slow down {consumer} or speed up {source}."
        )
    if floor is not None:
        return (
            f"No cadence works here: {source} only syncs every {humanize_cadence(floor.value)},"
            f" less often than anything this can refresh at. Speed up {source} first."
        )
    if ceiling is not None:
        return (
            f"No cadence works here: {consumer} refreshes every {humanize_cadence(ceiling.value)},"
            f" more often than anything this can refresh at. Slow down {consumer} first."
        )
    return "No cadence works here."


def validate_declared_target(
    *,
    node_id: str,
    target: timedelta,
    edges: list[tuple[str, str]],
    declared_targets: dict[str, timedelta],
    source_intervals: dict[str, timedelta],
    names: Mapping[str, str] | None = None,
) -> None:
    """Raise if `target` is not selectable or falls outside the node's bounds.

    `names` maps node ids to display names; supply it to have refusals name the source or view
    that blocks the target, which is the thing a person has to change to unblock it.
    """
    if target not in SCHEDULABLE_BUCKETS:
        supported = ", ".join(format_cadence(interval) for interval in sorted(SCHEDULABLE_BUCKETS))
        raise UnsupportedFrequencyTargetError(
            f"Can't refresh every {humanize_cadence(target)}. Pick one of: {supported}."
        )

    bounds = compute_target_bounds(
        node_id=node_id, edges=edges, declared_targets=declared_targets, source_intervals=source_intervals
    )
    option = bounds.option_for(target)
    if option is None or option.allowed:
        return

    # Nothing legal to fall back to, so no message here can end in "pick X instead"
    if not bounds.satisfiable:
        raise UnsatisfiableFrequencyError(_nothing_satisfiable_message(bounds, names))

    # Suggest a cadence the same call would accept, and name the bound itself rather than a
    # direction. Bounds are inclusive, so the bound is always a legal answer, while "or slower" /
    # "or faster" promises room that may not exist: a 15min ceiling has nothing fresher to offer.
    if option.blocked_by == "source" and bounds.floor is not None:
        source = _describe(option.blocker, names, "an upstream source")
        raise UnsatisfiableFrequencyError(
            f"Can't refresh every {humanize_cadence(target)}: {source} only syncs every"
            f" {humanize_cadence(bounds.floor.value)}."
            f" Pick {humanize_cadence(min(bounds.allowed))} instead."
        )
    if option.blocked_by == "consumer" and bounds.ceiling is not None:
        consumer = _describe(option.blocker, names, "a view or endpoint built on this one")
        raise UnsatisfiableFrequencyError(
            f"Can't refresh every {humanize_cadence(target)}: {consumer} refreshes every"
            f" {humanize_cadence(bounds.ceiling.value)}. Pick {humanize_cadence(max(bounds.allowed))} instead."
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
