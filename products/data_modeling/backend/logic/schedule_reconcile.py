"""Reconcile a DAG's Temporal schedules to its per-node freshness targets.

Replaces the single per-DAG `data-modeling-execute-dag` schedule with one schedule per
distinct effective cadence (a "cohort"), each scoped to that tier's node_ids. Idempotent:
computes the desired tiers from the current graph and creates/updates/deletes schedules so
Temporal matches, converging a DAG whether it currently has the old single schedule or N
tiered ones.

The tier/plan math is pure (`cohort_scheduling`); this module is the only part that talks to
the Temporal schedule API.
"""

import uuid
import dataclasses
from collections.abc import Iterable
from datetime import timedelta

from django.conf import settings

import structlog
from asgiref.sync import async_to_sync
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleListActionStartWorkflow,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleState,
)
from temporalio.common import RetryPolicy, SearchAttributePair, TypedSearchAttributes

from posthog.temporal.common.client import async_connect
from posthog.temporal.common.schedule import a_create_schedule, a_delete_schedule, a_update_schedule
from posthog.temporal.common.search_attributes import POSTHOG_DAG_ID_KEY, POSTHOG_ORG_ID_KEY, POSTHOG_TEAM_ID_KEY
from posthog.temporal.data_modeling.workflows.execute_dag import ExecuteDAGInputs

from products.data_modeling.backend.logic.cohort_scheduling import (
    ScheduleReconcilePlan,
    bucket_into_cadence_tiers,
    plan_schedule_reconciliation,
    tier_schedule_id,
)
from products.data_modeling.backend.logic.freshness import (
    SUPPORTED_TARGETS,
    InvalidTarget,
    UnsupportedFrequencyTargetError,
    compute_effective_cadences,
    find_invalid_targets,
    format_cadence,
    frequency_target_bounds,
)
from products.data_modeling.backend.logic.node_frequency import FrequencyGraph, build_frequency_graph, seed_targets
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.schedule import DATA_MODELING_EXECUTE_DAG_WORKFLOW, build_schedule_spec

logger = structlog.get_logger(__name__)


def reconcile_dag_schedules(dag: DAG) -> None:
    """Make Temporal's schedules for this DAG match its nodes' effective cadences."""
    team = dag.team
    graph = build_frequency_graph(dag)
    effective = compute_effective_cadences(nodes=graph.nodes, edges=graph.edges, targets=graph.targets)
    desired_tiers = bucket_into_cadence_tiers(effective)
    _apply_reconciliation(
        dag_id=str(dag.id),
        team_id=team.pk,
        organization_id=str(team.organization_id),
        team_timezone=team.timezone,
        desired_tiers=desired_tiers,
    )


@dataclasses.dataclass
class UnsatisfiableTier:
    """A node scheduled finer than its slowest ancestor source can actually deliver."""

    node_id: str
    effective: timedelta  # cadence it would be scheduled at
    floor: timedelta  # coarsest cadence its sources can actually deliver


@dataclasses.dataclass
class DagSchedulePreview:
    """What reconcile would do for a DAG, computed read-only (no schedule writes)."""

    effective: dict[str, timedelta | None]  # every schedulable node's resolved cadence
    desired_tiers: dict[timedelta, set[str]]
    plan: ScheduleReconcilePlan
    best_effort_source_ids: set[str]  # sources whose freshness is not actually guaranteed
    unsatisfiable: list[UnsatisfiableTier]  # effective finer than the source floor can honor
    invalid_targets: list[InvalidTarget]  # declared targets that drifted outside their bounds
    unsupported_tiers: list[timedelta]  # tiers reconcile would refuse (non-bucket cadence)
    seeded: bool  # whether targets were seeded in-memory from current cadence


def preview_dag_schedules(dag: DAG, *, seed: bool = False) -> DagSchedulePreview:
    """Compute the reconciliation a DAG would undergo, without creating/updating/deleting anything.

    Reads the graph and lists the DAG's current schedules; never writes. This is the dry-run
    behind the preview management command. With `seed`, nodes lacking an explicit target fall
    back in memory to `seed_targets(dag)`, modelling the go-live plan once targets are
    backfilled, without persisting anything (explicit targets still win).
    """
    graph = build_frequency_graph(dag)
    targets = {**seed_targets(dag), **graph.targets} if seed else graph.targets
    effective = compute_effective_cadences(nodes=graph.nodes, edges=graph.edges, targets=targets)
    desired_tiers = bucket_into_cadence_tiers(effective)
    existing_ids = _list_existing_schedule_ids(str(dag.id))
    plan = plan_schedule_reconciliation(str(dag.id), desired_tiers, existing_ids)
    return DagSchedulePreview(
        effective=effective,
        desired_tiers=desired_tiers,
        plan=plan,
        best_effort_source_ids=graph.best_effort_source_ids,
        unsatisfiable=_find_unsatisfiable(graph, effective, targets),
        invalid_targets=find_invalid_targets(
            edges=graph.edges, targets=targets, source_intervals=graph.source_intervals
        ),
        unsupported_tiers=sorted(interval for interval in desired_tiers if interval not in SUPPORTED_TARGETS),
        seeded=seed,
    )


def _find_unsatisfiable(
    graph: FrequencyGraph, effective: dict[str, timedelta | None], targets: dict[str, timedelta]
) -> list[UnsatisfiableTier]:
    """Flag nodes whose scheduled cadence is finer than their ancestor sources can deliver."""
    flagged: list[UnsatisfiableTier] = []
    for node_id, node_effective in effective.items():
        if node_effective is None:
            continue
        floor, _ceiling = frequency_target_bounds(
            node_id=node_id, edges=graph.edges, targets=targets, source_intervals=graph.source_intervals
        )
        if node_effective < floor:
            flagged.append(UnsatisfiableTier(node_id=node_id, effective=node_effective, floor=floor))
    return flagged


@async_to_sync
async def _list_existing_schedule_ids(dag_id: str) -> set[str]:
    temporal = await async_connect()
    return await _list_execute_dag_schedule_ids(temporal, dag_id)


@async_to_sync
async def _apply_reconciliation(
    *,
    dag_id: str,
    team_id: int,
    organization_id: str,
    team_timezone: str,
    desired_tiers: dict[timedelta, set[str]],
) -> None:
    unsupported = sorted(interval for interval in desired_tiers if interval not in SUPPORTED_TARGETS)
    if unsupported:
        tiers = ", ".join(format_cadence(interval) for interval in unsupported)
        raise UnsupportedFrequencyTargetError(
            f"refusing to reconcile DAG {dag_id}: tiers ({tiers}) are not schedulable cadence buckets"
        )

    temporal = await async_connect()
    existing_ids = await _list_execute_dag_schedule_ids(temporal, dag_id)
    plan = plan_schedule_reconciliation(dag_id, desired_tiers, existing_ids)

    search_attributes = TypedSearchAttributes(
        search_attributes=[
            SearchAttributePair(key=POSTHOG_TEAM_ID_KEY, value=team_id),
            SearchAttributePair(key=POSTHOG_ORG_ID_KEY, value=organization_id),
            SearchAttributePair(key=POSTHOG_DAG_ID_KEY, value=dag_id),
        ]
    )

    # Create/update every desired tier before deleting stale schedules so nodes are never left
    # uncovered; on failure, best-effort-delete the tiers we created (already-applied updates
    # stay — a re-run converges) without letting a failed delete mask the original error.
    created: list[str] = []
    try:
        for schedule_id, (interval, node_ids) in plan.to_create.items():
            schedule = _build_tier_schedule(dag_id, team_id, team_timezone, interval, node_ids)
            await a_create_schedule(temporal, id=schedule_id, schedule=schedule, search_attributes=search_attributes)
            created.append(schedule_id)
        for schedule_id, (interval, node_ids) in plan.to_update.items():
            schedule = _build_tier_schedule(dag_id, team_id, team_timezone, interval, node_ids)
            await a_update_schedule(temporal, id=schedule_id, schedule=schedule, search_attributes=search_attributes)
    except Exception:
        for schedule_id in created:
            try:
                await a_delete_schedule(temporal, schedule_id=schedule_id)
            except Exception:
                logger.exception("Failed to roll back created schedule", schedule_id=schedule_id, dag_id=dag_id)
        raise

    for schedule_id in plan.to_delete:
        await a_delete_schedule(temporal, schedule_id=schedule_id)


async def _list_execute_dag_schedule_ids(temporal: Client, dag_id: str) -> set[str]:
    schedules = await temporal.list_schedules(query=f"{POSTHOG_DAG_ID_KEY.name} = '{dag_id}'")
    ids: set[str] = set()
    async for listing in schedules:
        action = listing.schedule.action if listing.schedule else None
        if (
            isinstance(action, ScheduleListActionStartWorkflow)
            and action.workflow == DATA_MODELING_EXECUTE_DAG_WORKFLOW
        ):
            ids.add(listing.id)
    return ids


def _build_tier_schedule(
    dag_id: str, team_id: int, team_timezone: str, interval: timedelta, node_ids: Iterable[str]
) -> Schedule:
    inputs = ExecuteDAGInputs(team_id=team_id, dag_id=dag_id, node_ids=sorted(node_ids), duckgres_only=False)
    spec = build_schedule_spec(entity_id=uuid.UUID(dag_id), interval=interval, team_timezone=team_timezone)
    return Schedule(
        action=ScheduleActionStartWorkflow(
            DATA_MODELING_EXECUTE_DAG_WORKFLOW,
            dataclasses.asdict(inputs),
            id=f"execute-dag-{tier_schedule_id(dag_id, interval)}",
            task_queue=str(settings.DATA_MODELING_TASK_QUEUE),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=10),
                maximum_interval=timedelta(seconds=60),
                maximum_attempts=3,
                non_retryable_error_types=["NondeterminismError", "CancelledError"],
            ),
        ),
        spec=spec,
        state=ScheduleState(note=f"data-modeling DAG {dag_id} cadence tier {interval}"),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )
