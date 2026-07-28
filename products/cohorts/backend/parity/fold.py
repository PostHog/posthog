"""Fold a shadow-topic message stream into converged per-cohort membership state.

Max last_updated per (cohort_id, person_id) wins, matching the argMax convergence of the
old side's ClickHouse table. In practice that is also arrival order (messages are keyed
by person_id, so one person's transitions live in one partition), but the timestamp rule
keeps replays and clock regressions from shadowing a newer record.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Optional
from uuid import UUID

RECONCILE_COMPLETE_TYPE = "reconcile_complete"
RECONCILE_PARTITION_COUNT = 64
LIVE_ORIGIN = "live"


@dataclass(frozen=True)
class MembershipRecord:
    status: str  # "entered" | "left"
    last_updated: datetime
    origin: Optional[str] = None
    run_id: Optional[str] = None


@dataclass(frozen=True)
class ReconcileRunCompleteness:
    run_id: str
    cohort_id: int
    partitions_seen: int

    @property
    def expected_partitions(self) -> int:
        return RECONCILE_PARTITION_COUNT

    @property
    def complete(self) -> bool:
        return self.partitions_seen == RECONCILE_PARTITION_COUNT


@dataclass
class FoldStats:
    total: int = 0
    folded: int = 0
    dropped_wrong_team: int = 0
    dropped_before_since: int = 0
    dropped_malformed: int = 0
    cohorts_seen: set[int] = field(default_factory=set)
    reconcile_markers: dict[tuple[str, int], set[int]] = field(default_factory=dict)
    # Count of accepted marker messages, incl. duplicates — the reconcile_markers set dedups by
    # partition, so it undercounts. This keeps folded + drops + markers == total (markers land in
    # neither the folded nor the dropped buckets).
    reconcile_markers_recorded: int = 0
    folded_by_origin: dict[str, int] = field(default_factory=dict)


def parse_last_updated(raw: Any) -> Optional[datetime]:
    """Parse the wire `last_updated` (ClickHouse DateTime64 string, UTC) to an aware datetime.

    Accepts both the Rust `%.6f` and Python `%f` renderings, with or without fraction.
    """
    if not isinstance(raw, str):
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _parse_marker_run_id(raw: Any) -> Optional[str]:
    if not isinstance(raw, str):
        return None
    try:
        return str(UUID(raw))
    except ValueError:
        return None


def _optional_string(raw: Any) -> Optional[str]:
    return raw if isinstance(raw, str) and raw else None


def _record_marker(
    message: dict[str, Any],
    cohort_id: Any,
    last_updated: Optional[datetime],
    since: datetime,
    stats: FoldStats,
) -> None:
    run_id = _parse_marker_run_id(message.get("run_id"))
    partition = message.get("partition")
    if (
        run_id is None
        or not isinstance(cohort_id, int)
        or isinstance(cohort_id, bool)
        or not isinstance(partition, int)
        or isinstance(partition, bool)
        or not 0 <= partition < RECONCILE_PARTITION_COUNT
        or last_updated is None
    ):
        stats.dropped_malformed += 1
        return
    if last_updated < since:
        stats.dropped_before_since += 1
        return
    stats.reconcile_markers.setdefault((run_id, cohort_id), set()).add(partition)
    stats.reconcile_markers_recorded += 1
    stats.cohorts_seen.add(cohort_id)


def fold_membership_changes(
    messages: Iterable[dict[str, Any]],
    *,
    team_id: int,
    since: datetime,
) -> tuple[dict[int, dict[str, MembershipRecord]], FoldStats]:
    """Fold messages to {cohort_id: {person_id: final record}}, dropping other teams'
    messages and anything stamped before `since` (pre-wipe residue)."""
    stats = FoldStats()
    state: dict[int, dict[str, MembershipRecord]] = {}
    for message in messages:
        stats.total += 1
        message_team_id = message.get("team_id")
        if not isinstance(message_team_id, int) or isinstance(message_team_id, bool):
            stats.dropped_malformed += 1
            continue
        if message_team_id != team_id:
            stats.dropped_wrong_team += 1
            continue
        cohort_id = message.get("cohort_id")
        last_updated = parse_last_updated(message.get("last_updated"))

        if message.get("type") == RECONCILE_COMPLETE_TYPE:
            _record_marker(message, cohort_id, last_updated, since, stats)
            continue

        person_id = message.get("person_id")
        status = message.get("status")
        if (
            not isinstance(cohort_id, int)
            or isinstance(cohort_id, bool)
            or not isinstance(person_id, str)
            or not person_id
            or status not in ("entered", "left")
            or last_updated is None
        ):
            stats.dropped_malformed += 1
            continue
        if last_updated < since:
            stats.dropped_before_since += 1
            continue
        # Match the old side's argMax(status, last_updated): timestamp order, not arrival
        # order, so an out-of-order replay cannot shadow a newer record.
        bucket = state.setdefault(cohort_id, {})
        # Person ids compare case-insensitively: every membership source lowercases at
        # its boundary (here and both readers in snapshots.py) or the sets stop matching.
        key = person_id.lower()
        prior = bucket.get(key)
        origin = _optional_string(message.get("origin"))
        run_id = _optional_string(message.get("run_id"))
        if prior is None or last_updated >= prior.last_updated:
            bucket[key] = MembershipRecord(status=status, last_updated=last_updated, origin=origin, run_id=run_id)
        stats.cohorts_seen.add(cohort_id)
        stats.folded += 1
        origin_key = origin or LIVE_ORIGIN
        stats.folded_by_origin[origin_key] = stats.folded_by_origin.get(origin_key, 0) + 1
    return state, stats


def reconcile_completeness_by_cohort(stats: FoldStats) -> dict[int, tuple[ReconcileRunCompleteness, ...]]:
    """Group deterministic per-run marker completeness by cohort in a single sorted pass."""
    by_cohort: dict[int, list[ReconcileRunCompleteness]] = {}
    for (run_id, cohort_id), partitions in sorted(stats.reconcile_markers.items()):
        by_cohort.setdefault(cohort_id, []).append(
            ReconcileRunCompleteness(run_id=run_id, cohort_id=cohort_id, partitions_seen=len(partitions))
        )
    return {cohort_id: tuple(runs) for cohort_id, runs in by_cohort.items()}


def reconcile_completeness(stats: FoldStats, cohort_id: int) -> tuple[ReconcileRunCompleteness, ...]:
    """Return deterministic per-run marker completeness for one cohort."""
    return reconcile_completeness_by_cohort(stats).get(cohort_id, ())


def members(state: dict[str, MembershipRecord]) -> set[str]:
    """The currently-entered persons of one cohort's folded state."""
    return {person_id for person_id, record in state.items() if record.status == "entered"}


def observed(state: dict[str, MembershipRecord]) -> set[str]:
    """Every person the new pipeline emitted a decision for in this cohort.

    Live and seed processing can be flip-only, while reconcile snapshots emit every current
    decision. In either case, the presence of a key means the new pipeline has weighed in on
    that person, which is the universe the membership diff is bounded to.
    """
    return set(state.keys())
