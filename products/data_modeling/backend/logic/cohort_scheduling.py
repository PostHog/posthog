"""Cadence-tier scheduling for the v2 data-modeling DAG.

Turns per-node effective cadences (from `freshness.compute_effective_cadences`) into
frequency cohorts, then reconciles them against Temporal schedules — one
`data-modeling-execute-dag` schedule per distinct cadence, each scoped to that tier's
node_ids. Replaces the single-schedule-per-DAG model.

The tier/plan computation here is pure; the Temporal reconcile that applies a plan lives
alongside it and is the only part that touches the schedule API.
"""

import dataclasses
from collections import defaultdict
from datetime import timedelta
from typing import NamedTuple

from products.data_modeling.backend.logic.freshness import format_cadence

# An anchor is minutes past Monday 00:00 UTC. Every sub-weekly bucket divides the day,
# so for those only `anchor % MINUTES_PER_DAY` (the time-of-day part) matters; a weekly
# cadence reads the full value and gets day-of-week pinning from the same mod rule.
MINUTES_PER_DAY = 24 * 60
MINUTES_PER_WEEK = 7 * MINUTES_PER_DAY


class Tier(NamedTuple):
    """One schedule cohort: a cadence, plus an optional pinned phase.

    `anchor_minutes=None` is the default hash-spread cohort; an anchored cohort fires at
    times t ≡ anchor (mod interval), with t counted from the start of the UTC week.
    """

    interval: timedelta
    anchor_minutes: int | None = None


def tier_sort_key(tier: Tier) -> tuple[timedelta, int]:
    """Display order: by cadence, the hash-spread cohort before anchored ones.

    Sorting raw Tier tuples raises when a cadence has both an anchored and an unanchored
    cohort, because `None` and `int` anchors don't compare.
    """
    return (tier.interval, -1 if tier.anchor_minutes is None else tier.anchor_minutes)


def canonical_anchor(interval: timedelta, anchor_minutes: int) -> int:
    """Reduce an anchor to the phase the schedule spec actually uses at this cadence.

    Sub-weekly buckets divide the day, so only `anchor mod interval` matters; weekly reads
    the full week offset; monthly pins time-of-day only (day of month stays hash-picked).
    Raw anchors equal after reduction describe the same fire calendar, so they must key the
    same cohort — one schedule, one run.
    """
    if interval <= timedelta(days=1):
        return anchor_minutes % max(1, int(interval.total_seconds() // 60))
    if interval <= timedelta(days=7):
        return anchor_minutes % MINUTES_PER_WEEK
    return anchor_minutes % MINUTES_PER_DAY


def format_tier(tier: Tier) -> str:
    """Human label for a tier: the cadence, plus the anchor phase when one is pinned.

    Shows only what the spec uses: a weekday appears for weekly tiers alone — sub-weekly
    specs ignore the day part, and monthly's day of month is hash-picked, not anchored.
    """
    if tier.anchor_minutes is None:
        return format_cadence(tier.interval)
    anchor = canonical_anchor(tier.interval, tier.anchor_minutes)
    day, time_of_day = divmod(anchor, MINUTES_PER_DAY)
    clock = f"{time_of_day // 60:02d}:{time_of_day % 60:02d}"
    if timedelta(days=1) < tier.interval <= timedelta(days=7):
        days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        return f"{format_cadence(tier.interval)}@{days[day]} {clock}"
    return f"{format_cadence(tier.interval)}@{clock}"


def bucket_into_cadence_tiers(
    effective: dict[str, timedelta | None],
    anchors: dict[str, int] | None = None,
) -> dict[Tier, set[str]]:
    """Group schedulable nodes into cohorts by (effective cadence, canonical anchor).

    Nodes with no effective cadence (`None` — unscheduled, ride-downstream) are omitted so
    they never get a schedule of their own; an anchor on such a node is stored but inert.
    Nodes sharing a cadence but not an anchor land in separate cohorts, because a cohort
    is one Temporal schedule with one fire phase.
    """
    tiers: dict[Tier, set[str]] = defaultdict(set)
    for node_id, interval in effective.items():
        if interval is not None:
            anchor = anchors.get(node_id) if anchors else None
            if anchor is not None:
                anchor = canonical_anchor(interval, anchor)
            tiers[Tier(interval, anchor)].add(node_id)
    return dict(tiers)


def tier_schedule_id(dag_id: str, interval: timedelta, anchor_minutes: int | None = None) -> str:
    """Temporal schedule id for one cohort of a DAG: "{dag_id}:{interval_seconds}", with
    ":{anchor_minutes}" appended for an anchored cohort.

    A DAG UUID never contains a colon, so the dag id parses back off the first segment.
    """
    schedule_id = f"{dag_id}:{int(interval.total_seconds())}"
    if anchor_minutes is not None:
        schedule_id += f":{anchor_minutes}"
    return schedule_id


def dag_id_from_schedule_id(schedule_id: str) -> str:
    """Recover the DAG id from a tier schedule id.

    A migration-era single schedule (id == dag_id, no colon) parses to itself, keeping the
    read side backward-compatible through the transition.
    """
    return schedule_id.split(":", 1)[0]


def is_tier_schedule_id(schedule_id: str) -> bool:
    """Whether a schedule id is a cadence tier's (vs the pre-tier bare DAG id)."""
    return ":" in schedule_id


def interval_seconds_from_schedule_id(schedule_id: str) -> int | None:
    """Recover the tier's cadence (seconds) from its schedule id, or None for the legacy
    single schedule. An anchored id's trailing anchor segment is ignored."""
    if is_tier_schedule_id(schedule_id):
        return int(schedule_id.split(":")[1])
    return None


def anchor_minutes_from_schedule_id(schedule_id: str) -> int | None:
    """The anchored cohort's pinned phase from its schedule id, or None when hash-spread."""
    parts = schedule_id.split(":")
    return int(parts[2]) if len(parts) > 2 else None


@dataclasses.dataclass
class ScheduleReconcilePlan:
    """What to do to Temporal to make a DAG's schedules match its desired cadence tiers.

    Keyed by schedule id. `to_create`/`to_update` map a tier's schedule id to its
    (tier, node_ids); `to_delete` is the set of schedule ids to remove.
    """

    to_create: dict[str, tuple[Tier, set[str]]]
    to_update: dict[str, tuple[Tier, set[str]]]
    to_delete: set[str]


def plan_schedule_reconciliation(
    dag_id: str,
    desired_tiers: dict[Tier, set[str]],
    existing_schedule_ids: set[str],
) -> ScheduleReconcilePlan:
    """Diff desired cadence tiers against a DAG's existing execute-dag schedules.

    Always rewrites tiers that persist (self-healing against drift) rather than diffing
    node_ids. `to_delete` is every existing schedule not backing a desired tier — which
    sweeps both removed tiers and the migration-era single `dag_id` schedule.
    """
    desired = {
        tier_schedule_id(dag_id, tier.interval, tier.anchor_minutes): (tier, node_ids)
        for tier, node_ids in desired_tiers.items()
    }
    return ScheduleReconcilePlan(
        to_create={sid: value for sid, value in desired.items() if sid not in existing_schedule_ids},
        to_update={sid: value for sid, value in desired.items() if sid in existing_schedule_ids},
        to_delete=set(existing_schedule_ids) - set(desired),
    )
