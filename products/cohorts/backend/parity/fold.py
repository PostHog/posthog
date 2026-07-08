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


@dataclass(frozen=True)
class MembershipRecord:
    status: str  # "entered" | "left"
    last_updated: datetime


@dataclass
class FoldStats:
    total: int = 0
    folded: int = 0
    dropped_wrong_team: int = 0
    dropped_before_since: int = 0
    dropped_malformed: int = 0
    cohorts_seen: set[int] = field(default_factory=set)


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
        if message.get("team_id") != team_id:
            stats.dropped_wrong_team += 1
            continue
        cohort_id = message.get("cohort_id")
        person_id = message.get("person_id")
        status = message.get("status")
        last_updated = parse_last_updated(message.get("last_updated"))
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
        key = person_id.lower()
        prior = bucket.get(key)
        if prior is None or last_updated >= prior.last_updated:
            bucket[key] = MembershipRecord(status=status, last_updated=last_updated)
        stats.cohorts_seen.add(cohort_id)
        stats.folded += 1
    return state, stats


def members(state: dict[str, MembershipRecord]) -> set[str]:
    """The currently-entered persons of one cohort's folded state."""
    return {person_id for person_id, record in state.items() if record.status == "entered"}
