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


def bucket_into_cadence_tiers(effective: dict[str, timedelta | None]) -> dict[timedelta, set[str]]:
    """Group schedulable nodes by effective cadence.

    Nodes with no effective cadence (`None` — unscheduled, ride-downstream) are omitted so
    they never get a schedule of their own.
    """
    tiers: dict[timedelta, set[str]] = defaultdict(set)
    for node_id, interval in effective.items():
        if interval is not None:
            tiers[interval].add(node_id)
    return dict(tiers)


def tier_schedule_id(dag_id: str, interval: timedelta) -> str:
    """Temporal schedule id for one cadence tier of a DAG: "{dag_id}:{interval_seconds}".

    A DAG UUID never contains a colon, so the dag id parses back off the prefix.
    """
    return f"{dag_id}:{int(interval.total_seconds())}"


def dag_id_from_schedule_id(schedule_id: str) -> str:
    """Recover the DAG id from a tier schedule id.

    A migration-era single schedule (id == dag_id, no colon) parses to itself, keeping the
    read side backward-compatible through the transition.
    """
    return schedule_id.rsplit(":", 1)[0]


def is_tier_schedule_id(schedule_id: str) -> bool:
    """Whether a schedule id is a cadence tier's (vs the pre-tier bare DAG id)."""
    return _TIER_SEPARATOR in schedule_id


@dataclasses.dataclass
class ScheduleReconcilePlan:
    """What to do to Temporal to make a DAG's schedules match its desired cadence tiers.

    Keyed by schedule id. `to_create`/`to_update` map a tier's schedule id to its
    (interval, node_ids); `to_delete` is the set of schedule ids to remove.
    """

    to_create: dict[str, tuple[timedelta, set[str]]]
    to_update: dict[str, tuple[timedelta, set[str]]]
    to_delete: set[str]


def plan_schedule_reconciliation(
    dag_id: str,
    desired_tiers: dict[timedelta, set[str]],
    existing_schedule_ids: set[str],
) -> ScheduleReconcilePlan:
    """Diff desired cadence tiers against a DAG's existing execute-dag schedules.

    Always rewrites tiers that persist (self-healing against drift) rather than diffing
    node_ids. `to_delete` is every existing schedule not backing a desired tier — which
    sweeps both removed tiers and the migration-era single `dag_id` schedule.
    """
    desired = {tier_schedule_id(dag_id, interval): (interval, node_ids) for interval, node_ids in desired_tiers.items()}
    return ScheduleReconcilePlan(
        to_create={sid: value for sid, value in desired.items() if sid not in existing_schedule_ids},
        to_update={sid: value for sid, value in desired.items() if sid in existing_schedule_ids},
        to_delete=set(existing_schedule_ids) - set(desired),
    )
