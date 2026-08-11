"""Answer "is this node actually on a cadence-tier schedule?" from the source of truth.

Neither the warehouse mirror nor the node's stored `target_seconds` is reliable for this: the
mirror lags on deletes, and a node can carry a target the last reconcile never wrote into a live
schedule. The only authoritative record of what a tier will materialize is the `node_ids` list in
the tier's Temporal schedule payload — which is Fernet-encrypted, so it must be read through a
codec-configured client (the standard PostHog Temporal client decodes it transparently).

This module reads those live `node_ids` and compares them against what reconcile *would* schedule
(`compute_effective_cadences`), so a node that has a target but is missing from every live tier is
reported as needing a reconcile rather than silently unscheduled.
"""

import dataclasses
from datetime import timedelta

from temporalio.client import Client, ScheduleActionStartWorkflow, ScheduleListActionStartWorkflow

from posthog.temporal.common.search_attributes import POSTHOG_DAG_ID_KEY

from products.data_modeling.backend.logic.cohort_scheduling import (
    Tier,
    anchor_minutes_from_schedule_id,
    bucket_into_cadence_tiers,
    interval_seconds_from_schedule_id,
)
from products.data_modeling.backend.logic.freshness import (
    SCHEDULABLE_BUCKETS,
    clamp_to_source_floor,
    compute_effective_cadences,
)
from products.data_modeling.backend.logic.node_frequency import build_frequency_graph
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.node import NodeType
from products.data_modeling.backend.schedule import DATA_MODELING_EXECUTE_DAG_WORKFLOW


@dataclasses.dataclass(frozen=True)
class LiveTier:
    """One execute-dag schedule for a DAG, as it exists in Temporal right now."""

    schedule_id: str
    interval_seconds: int | None  # None = migration-era single schedule (no cadence tier)
    covers_whole_dag: bool  # True when node_ids is unset — the schedule materializes every node
    node_ids: frozenset[str] | None  # the exact set the tier will materialize; None when whole-DAG
    anchor_minutes: int | None = None  # the cohort's pinned phase; None = hash-spread


@dataclasses.dataclass
class NodeScheduleStatus:
    node_id: str
    name: str
    node_type: str
    dag_id: str
    dag_name: str
    live_intervals: list[int | None]  # tiers whose live node_ids include this node (None = whole-DAG)
    expected_interval: int | None  # what reconcile would put it on now (None = ride-downstream opt-out)
    verdict: str
    dag_reconcile_blocked: bool = False  # a non-bucket tier anywhere in the DAG makes reconcile refuse it
    expected_anchor: int | None = None  # the expected cohort's pinned phase; None = hash-spread


# Verdict values — a node's live scheduling vs what reconcile would currently schedule.
SCHEDULED = "scheduled"  # on a live tier, matching expectation
SCHEDULED_WRONG_TIER = "scheduled_wrong_tier"  # on a live tier, but at a different cadence than expected
STALE_NEEDS_RECONCILE = "stale_needs_reconcile"  # has a target but no live tier covers it — reconcile
OVER_SCHEDULED = "over_scheduled"  # on a live tier but reconcile would drop it (no effective cadence)
CORRECTLY_UNSCHEDULED = "correctly_unscheduled"  # no target and no live tier — the opt-out, working
# Reconcile refuses the *whole DAG* when any desired tier is not a schedulable bucket, so this must
# never be reported as stale_needs_reconcile: running reconcile would change nothing and raise.
UNSUPPORTED_TARGET = "unsupported_target"
# Typed VIEW while a table backs the query, so `get_dag_structure` calls it ephemeral and every tier
# run skips it — reporting success and writing no job. Outranks every tier verdict: the node can sit
# in exactly the right tier and still never materialize, and reconcile cannot fix a node's type.
EPHEMERAL_SKIPPED = "ephemeral_skipped"


async def _decode_node_ids(temporal: Client, action: object) -> list[str] | None:
    """Read `node_ids` from a schedule's start-workflow args, decoding the encrypted payload.

    Returns None when the schedule carries no node_ids (a whole-DAG single schedule) or the args are
    shaped unexpectedly. `describe()` hands back raw Payloads; the client's data converter runs the
    Fernet codec on decode. We also accept already-decoded dicts so tests can mock without a codec.
    """
    if not isinstance(action, ScheduleActionStartWorkflow):
        return None
    args = list(action.args)
    if not args:
        return None
    first = args[0]
    if isinstance(first, dict):
        return first.get("node_ids")
    decoded = await temporal.data_converter.decode(args)
    if decoded and isinstance(decoded[0], dict):
        return decoded[0].get("node_ids")
    return None


async def read_live_tiers(temporal: Client, dag_id: str) -> list[LiveTier]:
    """List a DAG's execute-dag schedules and read each one's live node set from Temporal."""
    tiers: list[LiveTier] = []
    schedules = await temporal.list_schedules(query=f"{POSTHOG_DAG_ID_KEY.name} = '{dag_id}'")
    async for listing in schedules:
        action = listing.schedule.action if listing.schedule else None
        if not (
            isinstance(action, ScheduleListActionStartWorkflow)
            and action.workflow == DATA_MODELING_EXECUTE_DAG_WORKFLOW
        ):
            continue
        described = await temporal.get_schedule_handle(listing.id).describe()
        node_ids = await _decode_node_ids(temporal, described.schedule.action)
        tiers.append(
            LiveTier(
                schedule_id=listing.id,
                interval_seconds=interval_seconds_from_schedule_id(listing.id),
                covers_whole_dag=node_ids is None,
                node_ids=frozenset(node_ids) if node_ids is not None else None,
                anchor_minutes=anchor_minutes_from_schedule_id(listing.id),
            )
        )
    return tiers


def _desired_tiers(dag: DAG) -> dict[Tier, set[str]]:
    """The tiers reconcile would want for this DAG: effective cadences → clamp to floor → buckets."""
    graph = build_frequency_graph(dag)
    effective = compute_effective_cadences(
        nodes=graph.nodes, edges=graph.edges, declared_targets=graph.declared_targets
    )
    effective, _clamped = clamp_to_source_floor(effective, edges=graph.edges, source_intervals=graph.source_intervals)
    return bucket_into_cadence_tiers(effective, graph.declared_anchors)


def expected_tier_by_node(dag: DAG) -> dict[str, Tier]:
    """The cohort reconcile would currently schedule each schedulable node on.

    Mirrors `reconcile_dag_schedules` exactly (effective cadences → clamp to source floor → buckets)
    so a node absent from this map is one reconcile would leave unscheduled (the ride-downstream
    opt-out), not a bug.
    """
    return {node_id: tier for tier, node_ids in _desired_tiers(dag).items() for node_id in node_ids}


def dag_reconcile_would_refuse(dag: DAG) -> bool:
    """Whether reconcile would refuse this DAG outright because a desired tier is not a bucket.

    `_apply_reconciliation` raises `UnsupportedFrequencyTargetError` for the *whole* DAG when any
    desired tier falls outside `SCHEDULABLE_BUCKETS`, leaving every schedule untouched. Without
    this, such a node reads as `stale_needs_reconcile` — advice that would raise rather than fix.
    """
    return any(tier.interval not in SCHEDULABLE_BUCKETS for tier in _desired_tiers(dag))


def classify_node(
    *,
    node_id: str,
    name: str,
    node_type: str,
    dag_id: str,
    dag_name: str,
    live_tiers: list[LiveTier],
    expected_tier: Tier | None,
    reconcile_blocked: bool = False,
    has_backing_table: bool = False,
) -> NodeScheduleStatus:
    """Compare a node's live tier membership against what reconcile would schedule for it."""
    covering = [
        tier for tier in live_tiers if tier.covers_whole_dag or (tier.node_ids is not None and node_id in tier.node_ids)
    ]
    live_intervals = [tier.interval_seconds for tier in covering]
    covered_live = bool(covering)
    expected_interval = int(expected_tier.interval.total_seconds()) if expected_tier is not None else None

    if node_type == NodeType.VIEW and has_backing_table:
        verdict = EPHEMERAL_SKIPPED
    elif covered_live and expected_tier is not None:
        # A whole-DAG (interval None) schedule always satisfies expectation. A tier matches on
        # cadence AND anchor — a hash-spread schedule does not satisfy an anchored expectation,
        # else the exact drift anchors exist to escape reads as healthy.
        verdict = (
            SCHEDULED
            if any(
                tier.interval_seconds is None
                or (tier.interval_seconds, tier.anchor_minutes) == (expected_interval, expected_tier.anchor_minutes)
                for tier in covering
            )
            else SCHEDULED_WRONG_TIER
        )
    elif covered_live and expected_tier is None:
        verdict = OVER_SCHEDULED
    elif not covered_live and expected_tier is not None:
        # Reconcile is the remediation for stale_needs_reconcile, so only report it when reconcile
        # would actually run. A blocked DAG needs its unschedulable target fixed first.
        verdict = UNSUPPORTED_TARGET if reconcile_blocked else STALE_NEEDS_RECONCILE
    else:
        verdict = CORRECTLY_UNSCHEDULED

    return NodeScheduleStatus(
        node_id=node_id,
        name=name,
        node_type=node_type,
        dag_id=dag_id,
        dag_name=dag_name,
        live_intervals=sorted(live_intervals, key=lambda i: (i is None, i or 0)),
        expected_interval=expected_interval,
        expected_anchor=expected_tier.anchor_minutes if expected_tier is not None else None,
        verdict=verdict,
        dag_reconcile_blocked=reconcile_blocked,
    )


def format_interval(seconds: int | None) -> str:
    if seconds is None:
        return "whole-DAG"
    return str(timedelta(seconds=seconds))
