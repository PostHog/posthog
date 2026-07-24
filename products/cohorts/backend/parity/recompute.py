"""Recompute-oracle support screen, tree composition, and backfill-aware classification.

The ``--oracle recompute`` mode compares the folded shadow topic (``members(fold)``) against a
membership set recomputed from ``events`` with evaluator semantics (the "oracle"), instead of the
old-pipeline ``cohort_membership`` table the R-FRESH/R-STALE classifier uses. This module holds the
pure logic: which cohorts the oracle can reproduce, how leaf member-sets fold into a tree, and how
the fold-vs-oracle diff is segmented by backfill day-domain.

Oracle semantics are pinned to the Rust reference so the recompute matches what the processor emits:

- Leaf identity = the full ``BehavioralLeafKey`` tuple, not ``conditionHash``: the hash digests only
  the event matcher, so leaves differing in window or operator share it
  (``rust/cohort-core/src/leaf_state/key.rs``).
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
sliding windows within ``max_window_days``. Anything else SKIPs with a specific reason. Tree
composition over supported leaves is in scope (cheap set algebra); the under-count segmentation
additionally needs a single leaf and a monotone operator.

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

from products.cohorts.backend.models.leaf_shape import BehavioralLeafKey, behavioral_leaf_key
from products.cohorts.backend.parity.classifier import VERDICT_FAIL, VERDICT_PASS, VERDICT_SKIP
from products.cohorts.backend.parity.eligibility import explain_unsupported_window, resolve_behavioral_window
from products.cohorts.backend.parity.fold import MembershipRecord, ReconcileRunCompleteness, members
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

# Person ids carried per class in the JSON so an operator can triage a gating class or override/merge
# drift without re-deriving the diff. Bounded — the report is a summary, not a dump.
SAMPLE_LIMIT = 20


# ---------------------------------------------------------------------------
# Spec: the recompute-supported shape of one cohort.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OracleLeaf:
    """A recompute-reproducible behavioral leaf: one member-set ClickHouse query per leaf key."""

    key: BehavioralLeafKey
    event_name: str
    op: str  # gte | lte | gt | lt | eq (whitelist keys, never user text)
    op_value: int  # clamped >= 0
    window_days: int  # whole-day sliding window N (inclusive [at_day - N .. at_day])

    @property
    def monotone(self) -> bool:
        return self.op in _MONOTONE_OPS


@dataclass(frozen=True)
class _TreeLeaf:
    key: BehavioralLeafKey
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
    leaves: Mapping[BehavioralLeafKey, OracleLeaf]  # deduped by leaf key
    single_leaf: bool  # exactly one distinct leaf → the missing set is segmentable per day-domain

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


def _leaf_key(source: Mapping[str, Any], *, condition_hash: str) -> BehavioralLeafKey:
    """Build the leaf key from a raw filter node or a pinned condition row (same field names bar the
    condition hash, which each side spells differently)."""
    return behavioral_leaf_key(
        condition_hash=condition_hash,
        value=source.get("value"),
        time_value=source.get("time_value"),
        time_interval=source.get("time_interval"),
        explicit_datetime=source.get("explicit_datetime"),
        explicit_datetime_to=source.get("explicit_datetime_to"),
        operator=source.get("operator"),
        operator_value=source.get("operator_value"),
    )


class _ScreenCtx:
    def __init__(self, pinned_by_key: Mapping[BehavioralLeafKey, Mapping[str, Any]], max_window_days: int) -> None:
        self.pinned = pinned_by_key
        self.max_window_days = max_window_days
        self.leaves: dict[BehavioralLeafKey, OracleLeaf] = {}
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
    key = _leaf_key(node, condition_hash=condition_hash)
    pinned = ctx.pinned.get(key)
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
    if value == "performed_event_multiple":
        # select.rs: `effective_window_days == 0` (sub-day, or any explicit shape but a relative
        # lower bound) is HourlyDeferred — no realtime state at all, so the oracle must not
        # over-count a whole calendar day for it.
        if window.kind != "days" or window.days < 1:
            ctx.fail("hourly_deferred")
            return None
    elif window.kind == "seconds":
        ctx.fail("sub_day_window")
        return None
    elif window.kind == "explicit":
        ctx.fail("absolute_explicit_range")
        return None
    window_days = int(window.days)
    # Rust treats an astronomical window as "never evicts"; the oracle would have to scan `events`
    # over it, so screen instead of driving an unbounded read.
    if window_days > ctx.max_window_days:
        ctx.fail("window_exceeds_max_days")
        return None
    op, op_value = _resolve_op(value, pinned.get("operator"), pinned.get("operator_value"))
    ctx.leaves[key] = OracleLeaf(
        key=key,
        event_name=event_name,
        op=op,
        op_value=op_value,
        window_days=window_days,
    )
    return _TreeLeaf(key=key, negated=node.get("negation") is True)


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
    *,
    max_window_days: int,
) -> Union[RecomputeSpec, RecomputeUnsupported]:
    """Decide whether the oracle can reproduce this cohort, and build its :class:`RecomputeSpec`.

    ``filters`` is the current ``Cohort.filters`` (the fold reflects current definitions, so the
    oracle must too — never the run's frozen ``pinned``). ``pinned_conditions`` is
    ``pin_conditions_for_cohorts([cohort])`` output, joined on the full :class:`BehavioralLeafKey`
    for the seeder-parity event-name / action resolution; the raw tree walk supplies structure,
    negation, and ``event_filters`` presence. Assumes the cohort already passed the emit-eligibility
    screen (so the tree is non-top-level-negated and ref-free at the group level).
    """
    if not isinstance(filters, Mapping) or "properties" not in filters:
        return RecomputeUnsupported("parse_error")
    pinned_by_key = {
        _leaf_key(c, condition_hash=c["condition_hash"]): c for c in pinned_conditions if c.get("condition_hash")
    }
    ctx = _ScreenCtx(pinned_by_key, max_window_days)
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


def evaluate_tree(node: _TreeNode, leaf_bits: Mapping[BehavioralLeafKey, bool]) -> bool:
    """Fold the tree to one membership bit. Mirror of evaluator.rs ``evaluate_tree``: absent leaf =
    ``false``, then ``bit ^ negated``; empty AND = ``true``, empty OR = ``false``."""
    if isinstance(node, _TreeGroup):
        if node.op == "AND":
            return all(evaluate_tree(child, leaf_bits) for child in node.children)
        return any(evaluate_tree(child, leaf_bits) for child in node.children)
    return leaf_bits.get(node.key, False) ^ node.negated


def compute_oracle_members(
    spec: RecomputeSpec,
    leaf_members: Mapping[BehavioralLeafKey, set[str]],
) -> set[str]:
    """The oracle's member set: compose per-leaf member sets through the tree.

    A member must satisfy ``>= 1`` positive leaf (the all-absent evaluation is ``false`` for
    emit-eligible non-negated trees — evaluator.rs ``all_absent_invariant``), so the candidate
    universe is the union of the leaf member-sets; anyone outside it composes to ``false``.
    """
    if not leaf_members:
        return set()
    universe: set[str] = set().union(*leaf_members.values())
    result: set[str] = set()
    for person in universe:
        bits = {key: (person in ids) for key, ids in leaf_members.items()}
        if evaluate_tree(spec.root, bits):
            result.add(person)
    return result


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
    """One (person, team-tz day, boundary-bucket) match count from the segmentation query."""

    day: date
    bucket: str  # pre_boundary | post_boundary | grace
    matches: int


# person_id -> their per-(day, bucket) match counts, over the missing set.
PersonDayCounts = Mapping[str, Sequence[DayMatch]]
# leaf key -> {person_id: match count over the leaf's window slid back one day}, over the false set.
ExtendedLeafCounts = Mapping[BehavioralLeafKey, Mapping[str, int]]


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


def _sample(ids: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted(ids)[:SAMPLE_LIMIT])


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
    false_hard: int = 0  # false_members not explained by sweep lag
    eviction_pending: int = 0  # sweep lag: still a member one day back, or entered within grace
    missing: int = 0  # oracle - members(fold) (under-count)
    missing_grace: int = 0
    missing_seed_domain: int = 0  # qualified by confirmed seed days alone — gates FAIL
    missing_boundary_day: int = 0  # needs boundary-day pre-boundary events — the decaying gap
    missing_unseeded_day: int = 0  # needs a pre-boundary window day with no confirmed chunk — FAIL
    missing_post_boundary: int = 0  # needs post-boundary events the live path owns — gates FAIL
    missing_unsegmented: int = 0  # multi-leaf / non-monotone / no run context — not adjudicated
    expires_by_day: Mapping[str, int] = field(default_factory=dict)  # boundary-class decay prediction
    samples: Mapping[str, tuple[str, ...]] = field(default_factory=dict)  # bounded person ids per class
    run_id: Optional[str] = None
    run_status: Optional[str] = None
    boundary_at: Optional[str] = None
    boundary_day: Optional[str] = None
    run_timezone: Optional[str] = None
    chunk_days_confirmed: int = 0
    shape_hash_drift: bool = False
    reconcile_runs: tuple[ReconcileRunCompleteness, ...] = ()
    notes: tuple[str, ...] = ()


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
    rest (window days with no confirmed chunk). The scan and the window share one tz and one range,
    so the out-of-window skip is defensive only — a dropped in-window match would understate the
    total and misfile the person as lag noise.
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
    membership threshold. The classes are exhaustive — the final fall-through implies ``post > 0``,
    since the three preceding sums were all below the threshold the total clears."""
    grace, seed, boundary, unseeded, post = _domain_counts(matches, window=window, ctx=ctx)
    if seed + boundary + unseeded + post < min_count:
        return "missing_grace"  # crossing depends on the last grace-minutes — lag noise
    if seed >= min_count:
        return "missing_seed_domain"  # confirmed seed days alone qualify — unexpected, gates FAIL
    if seed + boundary >= min_count:
        return "missing_boundary_day"  # needs boundary-day pre-boundary events — decaying gap
    if seed + boundary + unseeded >= min_count:
        return "missing_unseeded_day"  # needs an unseeded pre-boundary window day — gates FAIL
    return "missing_post_boundary"  # needs post-boundary events the live path owns — gates FAIL


def _expiry_date(
    matches: Sequence[DayMatch], *, window: frozenset[date], window_days: int, min_count: int
) -> Optional[date]:
    """The smallest future date at which this person's window count drops below ``min_count`` absent
    new events: the day the oldest still-needed match ages out, ``+ window_days + 1``. ``None`` when
    no in-window match explains the membership, which leaves nothing to age out."""
    per_day: dict[date, int] = defaultdict(int)
    for match in matches:
        if match.day in window:
            per_day[match.day] += match.matches
    if not per_day:
        return None
    accumulated = 0
    critical_day = min(per_day)
    for day in sorted(per_day, reverse=True):  # newest first
        accumulated += per_day[day]
        if accumulated >= min_count:
            critical_day = day
            break
    return critical_day + timedelta(days=window_days + 1)


def _unsegmentable_note(leaf: Optional[OracleLeaf], ctx: Optional[RunContext]) -> str:
    if leaf is None:
        return "multi-leaf cohort: day-domain segmentation unavailable"
    if not leaf.monotone:
        return f"non-monotone op {leaf.op!r}: missing set left unsegmented (membership parity only)"
    return "no backfill run with a boundary; missing set left unsegmented"


def classify_recompute(
    *,
    spec: RecomputeSpec,
    name: str,
    fold_records: Mapping[str, MembershipRecord],
    oracle_members: set[str],
    day_counts: PersonDayCounts,
    extended_leaf_counts: ExtendedLeafCounts,
    ctx: Optional[RunContext],
    at: datetime,
    grace: timedelta,
    team_tz: ZoneInfo,
    segmentable: bool = True,
    reconcile_runs: Sequence[ReconcileRunCompleteness] = (),
    extra_notes: Sequence[str] = (),
) -> RecomputeComparison:
    fold_members = members(fold_records)
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
    per_class: dict[str, list[str]] = defaultdict(list)
    expires_by_day: dict[str, int] = defaultdict(int)

    # Over-count split. A false member is sweep lag, not over-inclusion, when either
    #   (a) the tree still evaluates true once every leaf window is slid back one day — the person is
    #       due for eviction but the tz-midnight sweep has not caught up; or
    #   (b) they entered within the grace window — the processor enters on the event and only leaves
    #       on a sweep tick, so a just-ingested historical event legitimately shows as a member
    #       (`event_path.rs` sets has_match on any match; only the sweep clears it).
    entered_after = at - grace
    eviction_pending: set[str] = set()
    for person in false_set:
        if fold_records[person].last_updated >= entered_after:
            eviction_pending.add(person)
            continue
        if not extended_leaf_counts:
            continue  # slid-back counts were not loaded (the caller says why); score the person hard
        extended_bits = {
            key: _member(extended_leaf_counts.get(key, {}).get(person, 0), leaf.op, leaf.op_value)
            for key, leaf in spec.leaves.items()
        }
        if evaluate_tree(spec.root, extended_bits):
            eviction_pending.add(person)

    # Under-count segmentation. Needs one leaf (a per-day scan of one event name), a monotone op (a
    # day's matches can only push a person toward membership), and a run to attribute days against.
    leaf = spec.sole_leaf if spec.single_leaf else None
    if segmentable and leaf is not None and leaf.monotone and ctx is not None:
        window = frozenset(window_dates(at, leaf.window_days, team_tz))
        min_count = _min_count(leaf.op, leaf.op_value)
        for person in missing_set:
            matches = day_counts.get(person, ())
            bucket = _classify_missing_person(matches, window=window, ctx=ctx, min_count=min_count)
            counts[bucket] += 1
            per_class[bucket].append(person)
            if bucket == "missing_boundary_day":
                day = _expiry_date(matches, window=window, window_days=leaf.window_days, min_count=min_count)
                if day is not None:
                    expires_by_day[day.isoformat()] += 1
    else:
        counts["missing_unsegmented"] = len(missing_set)
        per_class["missing_unsegmented"] = list(missing_set)
        # A caller that passed segmentable=False already recorded why in extra_notes.
        if segmentable:
            notes.append(_unsegmentable_note(leaf, ctx))

    false_hard_set = false_set - eviction_pending
    gated_missing = counts["missing_seed_domain"] + counts["missing_unseeded_day"] + counts["missing_post_boundary"]
    if false_hard_set or gated_missing:
        verdict = VERDICT_FAIL
    elif counts["missing_unsegmented"]:
        # Not a PASS: the over-count side is clean but the under-count was never adjudicated.
        verdict = VERDICT_SKIP
        notes.append(f"{counts['missing_unsegmented']} missing person(s) unadjudicated; parity not established")
    else:
        verdict = VERDICT_PASS

    samples = {
        "false_hard": _sample(list(false_hard_set)),
        "eviction_pending": _sample(list(eviction_pending)),
        **{cls: _sample(ids) for cls, ids in per_class.items()},
    }

    return RecomputeComparison(
        cohort_id=spec.cohort_id,
        name=name,
        supported=True,
        verdict=verdict,
        fold_count=len(fold_members),
        oracle_count=len(oracle_members),
        both=len(both),
        false_members=len(false_set),
        false_hard=len(false_hard_set),
        eviction_pending=len(eviction_pending),
        missing=len(missing_set),
        missing_grace=counts["missing_grace"],
        missing_seed_domain=counts["missing_seed_domain"],
        missing_boundary_day=counts["missing_boundary_day"],
        missing_unseeded_day=counts["missing_unseeded_day"],
        missing_post_boundary=counts["missing_post_boundary"],
        missing_unsegmented=counts["missing_unsegmented"],
        expires_by_day=dict(sorted(expires_by_day.items())),
        samples={cls: ids for cls, ids in sorted(samples.items()) if ids},
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
    post_boundary_total: int = 0
    unsegmented_total: int = 0
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
        summary.post_boundary_total += row.missing_post_boundary
        summary.unsegmented_total += row.missing_unsegmented
    return summary
