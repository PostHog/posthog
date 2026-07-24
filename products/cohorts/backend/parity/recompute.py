"""Recompute-oracle support screen, tree composition, and backfill-aware classification.

The ``--oracle recompute`` mode compares the folded shadow topic (``members(fold)``) against a
membership set recomputed from ``events`` with evaluator semantics (the "oracle"), instead of the
old-pipeline ``cohort_membership`` table the R-FRESH/R-STALE classifier uses. This module holds the
pure logic: which cohorts the oracle can reproduce, how leaf member-sets fold into a tree, and how
the fold-vs-oracle diff is segmented by backfill day-domain.

Oracle semantics are pinned to the Rust reference so the recompute matches what the processor emits:

- Window = INCLUSIVE ``[at_day - N .. at_day]`` in team tz = ``N + 1`` day-buckets
  (``rust/cohort-core/src/bucket_tz.rs``, via :mod:`.tzdates`).
- Membership floor = ``count >= 1 AND op(count)`` — zero-event persons are never members, even under
  ``lte``/``lt``/``eq 0`` (``rust/cohort-stream-processor/src/stage1/predicate.rs``).
- Operator mapping mirrors ``select.rs`` ``PredicateOp::from_leaf`` (``gte``/``lte``/``gt``/``lt`` else
  ``eq``; ``operator_value`` clamped ``>= 0``); ``performed_event`` ≡ ``Gte(1)``.
- Tree composition = AND/OR fold with per-leaf ``bit ^ negated``, absent leaf = ``false``
  (``rust/cohort-stream-processor/src/stage2/evaluator.rs``).

MVP scope: ``performed_event`` / ``performed_event_multiple`` leaves with a string event key, no
``event_filters`` (property matching is HogVM bytecode, not reproducible in SQL), and whole-day
sliding windows. Anything else SKIPs with a specific reason. Tree composition over supported leaves
is in scope (cheap set algebra); single-leaf (the canary shape) is segmentable per day-domain.

Pure — no ClickHouse, no Kafka, no Django. The ClickHouse member-set / segmentation reads and the
Django run-context load live in :mod:`.oracle`.
"""

from __future__ import annotations

import operator
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Optional, Union
from zoneinfo import ZoneInfo

from products.cohorts.backend.parity.classifier import VERDICT_FAIL, VERDICT_PASS, VERDICT_SKIP
from products.cohorts.backend.parity.eligibility import explain_unsupported_window, resolve_behavioral_window
from products.cohorts.backend.parity.fold import ReconcileRunCompleteness
from products.cohorts.backend.parity.tzdates import window_dates

_I32_MIN = -(2**31)
_I32_MAX = 2**31 - 1

# op string -> Python comparator, for the ``count >= 1 AND op(count)`` membership predicate.
_OP_EVAL: dict[str, Callable[[int, int], bool]] = {
    "gte": operator.ge,
    "lte": operator.le,
    "gt": operator.gt,
    "lt": operator.lt,
    "eq": operator.eq,
}
# Monotone ops (membership only grows with event count) — the only ones whose missing set can be
# segmented by day-domain. lte/lt/eq stay unsegmented (adding a day can flip membership either way).
_MONOTONE_OPS = frozenset({"gte", "gt"})

# Boundary buckets the segmentation query stamps per event (the remaining case is "pre_boundary").
_POST_BOUNDARY = "post_boundary"
_GRACE = "grace"


# ---------------------------------------------------------------------------
# Spec: the recompute-supported shape of one cohort.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OracleLeaf:
    """A recompute-reproducible behavioral leaf: one member-set ClickHouse query per condition hash."""

    condition_hash: str
    event_name: str
    op: str  # gte | lte | gt | lt | eq (whitelist keys, never user text)
    op_value: int  # clamped >= 0
    window_days: int  # whole-day sliding window N (inclusive [at_day - N .. at_day])

    @property
    def monotone(self) -> bool:
        return self.op in _MONOTONE_OPS


@dataclass(frozen=True)
class _TreeLeaf:
    condition_hash: str
    negated: bool


@dataclass(frozen=True)
class _TreeGroup:
    op: str  # AND | OR
    children: tuple[_TreeNode, ...]


_TreeNode = Union[_TreeGroup, _TreeLeaf]


@dataclass(frozen=True)
class RecomputeSpec:
    cohort_id: int
    root: _TreeNode
    leaves: Mapping[str, OracleLeaf]  # deduped by condition hash
    single_leaf: bool  # exactly one distinct leaf/event → segmentable per day-domain

    @property
    def sole_leaf(self) -> OracleLeaf:
        if not self.single_leaf:
            raise ValueError("sole_leaf is only defined for a single-leaf spec")
        return next(iter(self.leaves.values()))


@dataclass(frozen=True)
class RecomputeUnsupported:
    reason: str


# ---------------------------------------------------------------------------
# Support screen.
# ---------------------------------------------------------------------------


def _clamp_op_value(raw: Any) -> int:
    """``operator_value`` -> clamped ``u32``, mirroring select.rs ``operator_value.unwrap_or(0).max(0)``.

    Non-i32 JSON (bool, float, numeric string, out-of-range) reads as absent (serde ``as_i64`` into
    ``i32``) and clamps to 0.
    """
    if isinstance(raw, bool) or not isinstance(raw, int):
        return 0
    if not (_I32_MIN <= raw <= _I32_MAX):
        return 0
    return max(raw, 0)


def _resolve_op(value: str, raw_operator: Any, raw_operator_value: Any) -> tuple[str, int]:
    """(op, op_value) for a leaf. ``performed_event`` ≡ ``Gte(1)``; multiple maps its comparator."""
    if value == "performed_event":
        return "gte", 1
    op = raw_operator if raw_operator in ("gte", "lte", "gt", "lt") else "eq"
    return op, _clamp_op_value(raw_operator_value)


class _ScreenCtx:
    def __init__(self, pinned_by_hash: Mapping[str, Mapping[str, Any]]) -> None:
        self.pinned = pinned_by_hash
        self.leaves: dict[str, OracleLeaf] = {}
        self.unsupported: Optional[str] = None

    def fail(self, reason: str) -> None:
        # Keep the first reason encountered (deterministic, left-to-right tree order).
        if self.unsupported is None:
            self.unsupported = reason


def _parse_behavioral_leaf(node: Mapping[str, Any], ctx: _ScreenCtx) -> Optional[_TreeLeaf]:
    condition_hash = node.get("conditionHash")
    if not isinstance(condition_hash, str) or not condition_hash:
        ctx.fail("parse_error")
        return None
    pinned = ctx.pinned.get(condition_hash)
    if pinned is None:
        ctx.fail("parse_error")
        return None
    # Property matching is HogVM bytecode; the SQL member-set query cannot reproduce it.
    if node.get("event_filters"):
        ctx.fail("has_event_property_filters")
        return None
    if pinned.get("is_action"):
        ctx.fail("action_leaf")
        return None
    value = pinned.get("value")
    if value not in ("performed_event", "performed_event_multiple"):
        ctx.fail("sequence_or_lifecycle_value")
        return None
    event_name = pinned.get("event_name")
    if not isinstance(event_name, str) or not event_name:
        ctx.fail("action_leaf")
        return None
    window = resolve_behavioral_window(pinned)
    if window is None:
        ctx.fail(explain_unsupported_window(pinned))
        return None
    if window.kind == "seconds":
        ctx.fail("sub_day_window")
        return None
    if window.kind == "explicit":
        ctx.fail("absolute_explicit_range")
        return None
    window_days = int(window.days)
    # A 0-day performed_event_multiple is hourly-deferred in the processor (select.rs), no realtime
    # state — treat as sub-day so the oracle SKIPs rather than over-counting a whole calendar day.
    if value == "performed_event_multiple" and window_days < 1:
        ctx.fail("sub_day_window")
        return None
    op, op_value = _resolve_op(value, pinned.get("operator"), pinned.get("operator_value"))
    ctx.leaves[condition_hash] = OracleLeaf(
        condition_hash=condition_hash,
        event_name=event_name,
        op=op,
        op_value=op_value,
        window_days=window_days,
    )
    return _TreeLeaf(condition_hash=condition_hash, negated=node.get("negation") is True)


def _parse_node(node: Any, ctx: _ScreenCtx) -> Optional[_TreeNode]:
    if ctx.unsupported is not None:
        return None
    if not isinstance(node, Mapping):
        ctx.fail("parse_error")
        return None
    node_type = node.get("type")
    if node_type in ("AND", "OR") and isinstance(node.get("values"), list):
        children = tuple(c for c in (_parse_node(child, ctx) for child in node["values"]) if c is not None)
        return _TreeGroup(op=node_type, children=children)
    if node_type == "behavioral":
        return _parse_behavioral_leaf(node, ctx)
    if node_type == "person":
        ctx.fail("person_property_leaf")
        return None
    if node_type == "cohort":
        ctx.fail("cohort_ref_leaf")
        return None
    ctx.fail("parse_error")
    return None


def screen_for_recompute(
    cohort_id: int,
    filters: Any,
    pinned_conditions: Sequence[Mapping[str, Any]],
) -> Union[RecomputeSpec, RecomputeUnsupported]:
    """Decide whether the oracle can reproduce this cohort, and build its :class:`RecomputeSpec`.

    ``filters`` is the current ``Cohort.filters`` (the fold reflects current definitions, so the
    oracle must too — never the run's frozen ``pinned``). ``pinned_conditions`` is
    ``pin_conditions_for_cohorts([cohort])`` output, joined by ``conditionHash`` for the seeder-parity
    event-name / action / operator resolution; the raw tree walk supplies structure, negation, and
    ``event_filters`` presence. Assumes the cohort already passed the emit-eligibility screen (so the
    tree is non-top-level-negated and ref-free at the group level).
    """
    if not isinstance(filters, Mapping) or "properties" not in filters:
        return RecomputeUnsupported("parse_error")
    pinned_by_hash = {c["condition_hash"]: c for c in pinned_conditions if c.get("condition_hash")}
    ctx = _ScreenCtx(pinned_by_hash)
    root = _parse_node(filters["properties"], ctx)
    if ctx.unsupported is not None:
        return RecomputeUnsupported(ctx.unsupported)
    if root is None or not ctx.leaves:
        return RecomputeUnsupported("parse_error")
    return RecomputeSpec(
        cohort_id=cohort_id,
        root=root,
        leaves=dict(ctx.leaves),
        single_leaf=len(ctx.leaves) == 1,
    )


# ---------------------------------------------------------------------------
# Tree evaluation and oracle member-set composition.
# ---------------------------------------------------------------------------


def evaluate_tree(node: _TreeNode, leaf_bits: Mapping[str, bool]) -> bool:
    """Fold the tree to one membership bit. Mirror of evaluator.rs ``evaluate_tree``: absent leaf =
    ``false``, then ``bit ^ negated``; empty AND = ``true``, empty OR = ``false``."""
    if isinstance(node, _TreeGroup):
        if node.op == "AND":
            return all(evaluate_tree(child, leaf_bits) for child in node.children)
        return any(evaluate_tree(child, leaf_bits) for child in node.children)
    return leaf_bits.get(node.condition_hash, False) ^ node.negated


def compute_oracle_members(spec: RecomputeSpec, leaf_members: Mapping[str, set[str]]) -> set[str]:
    """The oracle's member set: compose per-leaf member sets through the tree.

    A member must satisfy ``>= 1`` positive leaf (the all-absent evaluation is ``false`` for
    emit-eligible non-negated trees — evaluator.rs ``all_absent_invariant``), so the candidate
    universe is the union of the leaf member-sets; anyone outside it composes to ``false``.
    """
    if not leaf_members:
        return set()
    universe: set[str] = set().union(*leaf_members.values())
    members: set[str] = set()
    for person in universe:
        bits = {condition_hash: (person in ids) for condition_hash, ids in leaf_members.items()}
        if evaluate_tree(spec.root, bits):
            members.add(person)
    return members


# ---------------------------------------------------------------------------
# Backfill run context + per-day segmentation input.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RunContext:
    """The backfill run the missing set is segmented against (loaded by :mod:`.oracle`)."""

    run_id: str
    status: str
    boundary_at: datetime
    run_timezone: str
    boundary_day: date  # day_of_instant(boundary_at, run tz)
    confirmed_days: frozenset[date]  # days whose seed chunks are all CONFIRMED (fully seeded)
    non_confirmed_chunks: int
    shape_hash_drift: bool  # run's pinned behavioral shape hash != current cohort's


@dataclass(frozen=True)
class DayMatch:
    """One (person, day-in-seg-tz, boundary-bucket) match count from the segmentation query."""

    day: date
    bucket: str  # pre_boundary | post_boundary | grace
    matches: int


# person_id -> their per-(day, bucket) match counts, over missing ∪ false_members.
PersonDayCounts = Mapping[str, Sequence[DayMatch]]


# ---------------------------------------------------------------------------
# Classification / segmentation / expiry.
# ---------------------------------------------------------------------------


def _member(count: int, op: str, op_value: int) -> bool:
    """The parity floor: zero matches is never a member, even under lte/lt/eq 0 (predicate.rs)."""
    return count >= 1 and _OP_EVAL[op](count, op_value)


def _min_count(op: str, op_value: int) -> int:
    """Smallest window count that satisfies a monotone op's membership floor."""
    if op == "gte":
        return max(1, op_value)
    if op == "gt":
        return max(1, op_value + 1)
    raise ValueError(f"non-monotone op {op!r} has no membership threshold")


@dataclass(frozen=True)
class RecomputeComparison:
    cohort_id: int
    name: str
    supported: bool
    verdict: str
    skip_reason: str = ""
    fold_count: int = 0
    oracle_count: int = 0
    both: int = 0
    false_members: int = 0  # members(fold) - oracle (over-count; hard invariant)
    false_hard: int = 0  # false_members not explained by pending eviction
    eviction_pending: int = 0  # still a member if the just-slid-out day were included (sweep lag)
    missing: int = 0  # oracle - members(fold) (under-count)
    missing_grace: int = 0
    missing_seed_domain: int = 0  # qualified by confirmed seed days alone — gates FAIL
    missing_boundary_day: int = 0  # needs boundary-day pre-boundary events — the decaying gap
    missing_unseeded_day: int = 0  # needs a pre-boundary window day with no confirmed chunk — FAIL
    missing_post_boundary: int = 0  # needs post-boundary events — live-path timing
    missing_unsegmented: int = 0  # multi-leaf / non-monotone / no run context
    expires_by_day: Mapping[str, int] = field(default_factory=dict)  # boundary-class decay prediction
    run_id: Optional[str] = None
    run_status: Optional[str] = None
    boundary_at: Optional[str] = None
    boundary_day: Optional[str] = None
    run_timezone: Optional[str] = None
    chunk_days_confirmed: int = 0
    shape_hash_drift: bool = False
    reconcile_runs: tuple[ReconcileRunCompleteness, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def gated(self) -> bool:
        return self.verdict in (VERDICT_PASS, VERDICT_FAIL)


def skip_comparison(
    *,
    cohort_id: int,
    name: str,
    reason: str,
    reconcile_runs: Sequence[ReconcileRunCompleteness] = (),
    notes: Sequence[str] = (),
) -> RecomputeComparison:
    return RecomputeComparison(
        cohort_id=cohort_id,
        name=name,
        supported=False,
        verdict=VERDICT_SKIP,
        skip_reason=reason,
        reconcile_runs=tuple(reconcile_runs),
        notes=(*notes, f"unsupported by recompute oracle: {reason}"),
    )


def _person_day_totals(matches: Sequence[DayMatch]) -> dict[tuple[date, str], int]:
    totals: dict[tuple[date, str], int] = defaultdict(int)
    for match in matches:
        totals[(match.day, match.bucket)] += match.matches
    return totals


def _domain_counts(
    matches: Sequence[DayMatch],
    *,
    window: frozenset[date],
    ctx: RunContext,
) -> tuple[int, int, int, int, int]:
    """(grace, seed, boundary, unseeded, post) in-window match counts for one person.

    ``seed`` / ``boundary`` / ``unseeded`` partition the pre-boundary window days: boundary-day first
    (the seed/live handoff day, even if a chunk exists for it), then confirmed-seed days, then the
    rest (window days with no confirmed chunk).
    """
    grace = seed = boundary = unseeded = post = 0
    for (day, bucket), count in _person_day_totals(matches).items():
        if day not in window:
            continue
        if bucket == _GRACE:
            grace += count
        elif bucket == _POST_BOUNDARY:
            post += count
        elif day == ctx.boundary_day:
            boundary += count
        elif day in ctx.confirmed_days:
            seed += count
        else:
            unseeded += count
    return grace, seed, boundary, unseeded, post


def _classify_missing_person(
    matches: Sequence[DayMatch],
    *,
    window: frozenset[date],
    ctx: RunContext,
    min_count: int,
) -> str:
    """Assign a missing (oracle - fold) person to a day-domain class. Precedence grace ≻ seed ≻
    boundary ≻ unseeded ≻ post: the highest-precedence domain whose cumulative count crosses the
    membership threshold."""
    grace, seed, boundary, unseeded, post = _domain_counts(matches, window=window, ctx=ctx)
    if seed + boundary + unseeded + post < min_count:
        return "missing_grace"  # crossing depends on the last grace-minutes — lag noise
    if seed >= min_count:
        return "missing_seed_domain"  # confirmed seed days alone qualify — unexpected, gates FAIL
    if seed + boundary >= min_count:
        return "missing_boundary_day"  # needs boundary-day pre-boundary events — decaying gap
    if seed + boundary + unseeded >= min_count:
        return "missing_unseeded_day"  # needs an unseeded pre-boundary window day — gates FAIL
    return "missing_post_boundary"  # needs post-boundary events — live-path timing


def _expiry_date(matches: Sequence[DayMatch], *, window: frozenset[date], window_days: int, min_count: int) -> date:
    """The smallest future date at which this person's window count drops below ``min_count`` absent
    new events: the day the oldest still-needed match ages out, ``+ window_days + 1``."""
    per_day: dict[date, int] = defaultdict(int)
    for match in matches:
        if match.day in window:
            per_day[match.day] += match.matches
    accumulated = 0
    critical_day = min(per_day)
    for day in sorted(per_day, reverse=True):  # newest first
        accumulated += per_day[day]
        if accumulated >= min_count:
            critical_day = day
            break
    return critical_day + timedelta(days=window_days + 1)


def classify_recompute(
    *,
    spec: RecomputeSpec,
    name: str,
    fold_members: set[str],
    oracle_members: set[str],
    day_counts: PersonDayCounts,
    ctx: Optional[RunContext],
    at: datetime,
    seg_tz: ZoneInfo,
    reconcile_runs: Sequence[ReconcileRunCompleteness] = (),
    extra_notes: Sequence[str] = (),
) -> RecomputeComparison:
    both = fold_members & oracle_members
    false_set = fold_members - oracle_members
    missing_set = oracle_members - fold_members
    notes = list(extra_notes)

    counts = {
        "missing_grace": 0,
        "missing_seed_domain": 0,
        "missing_boundary_day": 0,
        "missing_unseeded_day": 0,
        "missing_post_boundary": 0,
        "missing_unsegmented": 0,
    }
    eviction_pending: set[str] = set()
    expires_by_day: dict[str, int] = defaultdict(int)

    if spec.single_leaf:
        leaf = spec.sole_leaf
        window = frozenset(window_dates(at, leaf.window_days, seg_tz))

        # Eviction split: a false member still a member once the just-slid-out day (at_day - N - 1) is
        # included is sweep-lag noise, not over-inclusion. The segmentation scan reaches that extra day.
        for person in false_set:
            extended = sum(match.matches for match in day_counts.get(person, ()))
            if _member(extended, leaf.op, leaf.op_value):
                eviction_pending.add(person)

        if leaf.monotone and ctx is not None:
            min_count = _min_count(leaf.op, leaf.op_value)
            for person in missing_set:
                matches = day_counts.get(person, ())
                bucket = _classify_missing_person(matches, window=window, ctx=ctx, min_count=min_count)
                counts[bucket] += 1
                if bucket == "missing_boundary_day":
                    day = _expiry_date(matches, window=window, window_days=leaf.window_days, min_count=min_count)
                    expires_by_day[day.isoformat()] += 1
        else:
            counts["missing_unsegmented"] = len(missing_set)
            if ctx is None:
                notes.append("no backfill run with a boundary; missing set left unsegmented")
            else:
                notes.append(f"non-monotone op {leaf.op!r}: missing set left unsegmented (membership parity only)")
    else:
        counts["missing_unsegmented"] = len(missing_set)
        notes.append(
            "multi-leaf cohort: domain segmentation and eviction split unavailable; false members counted hard"
        )

    false_hard = len(false_set) - len(eviction_pending)
    fail = false_hard > 0 or (counts["missing_seed_domain"] + counts["missing_unseeded_day"]) > 0
    verdict = VERDICT_FAIL if fail else VERDICT_PASS

    return RecomputeComparison(
        cohort_id=spec.cohort_id,
        name=name,
        supported=True,
        verdict=verdict,
        fold_count=len(fold_members),
        oracle_count=len(oracle_members),
        both=len(both),
        false_members=len(false_set),
        false_hard=false_hard,
        eviction_pending=len(eviction_pending),
        missing=len(missing_set),
        missing_grace=counts["missing_grace"],
        missing_seed_domain=counts["missing_seed_domain"],
        missing_boundary_day=counts["missing_boundary_day"],
        missing_unseeded_day=counts["missing_unseeded_day"],
        missing_post_boundary=counts["missing_post_boundary"],
        missing_unsegmented=counts["missing_unsegmented"],
        expires_by_day=dict(sorted(expires_by_day.items())),
        run_id=ctx.run_id if ctx else None,
        run_status=ctx.status if ctx else None,
        boundary_at=ctx.boundary_at.isoformat() if ctx else None,
        boundary_day=ctx.boundary_day.isoformat() if ctx else None,
        run_timezone=ctx.run_timezone if ctx else None,
        chunk_days_confirmed=len(ctx.confirmed_days) if ctx else 0,
        shape_hash_drift=ctx.shape_hash_drift if ctx else False,
        reconcile_runs=tuple(reconcile_runs),
        notes=tuple(notes),
    )


@dataclass
class RecomputeSummary:
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    false_hard_total: int = 0
    eviction_pending_total: int = 0
    missing_total: int = 0
    seed_domain_total: int = 0
    unseeded_total: int = 0
    boundary_total: int = 0
    warnings: list[str] = field(default_factory=list)


def summarize_recompute(rows: Sequence[RecomputeComparison]) -> RecomputeSummary:
    summary = RecomputeSummary()
    for row in rows:
        if row.verdict == VERDICT_PASS:
            summary.passed += 1
        elif row.verdict == VERDICT_FAIL:
            summary.failed += 1
        else:
            summary.skipped += 1
        summary.false_hard_total += row.false_hard
        summary.eviction_pending_total += row.eviction_pending
        summary.missing_total += row.missing
        summary.seed_domain_total += row.missing_seed_domain
        summary.unseeded_total += row.missing_unseeded_day
        summary.boundary_total += row.missing_boundary_day
    return summary
