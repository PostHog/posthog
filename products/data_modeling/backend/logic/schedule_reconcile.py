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
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import transaction

import structlog
from asgiref.sync import async_to_sync
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleListActionStartWorkflow,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleState,
)
from temporalio.common import RetryPolicy

from posthog.exceptions_capture import capture_exception
from posthog.ph_client import feature_enabled_or_false
from posthog.temporal.common.client import async_connect
from posthog.temporal.common.schedule import a_create_schedule, a_delete_schedule, a_update_schedule
from posthog.temporal.common.search_attributes import POSTHOG_DAG_ID_KEY

from products.data_modeling.backend.logic.cohort_scheduling import (
    ScheduleReconcilePlan,
    bucket_into_cadence_tiers,
    is_tier_schedule_id,
    plan_schedule_reconciliation,
    tier_schedule_id,
)
from products.data_modeling.backend.logic.freshness import (
    SCHEDULABLE_BUCKETS,
    InvalidTarget,
    UnsupportedFrequencyTargetError,
    compute_effective_cadences,
    declared_target_bounds,
    find_invalid_targets,
    format_cadence,
    is_finer_than,
    validate_declared_target,
)
from products.data_modeling.backend.logic.node_frequency import (
    FrequencyGraph,
    build_frequency_graph,
    seed_targets,
    set_declared_target,
)
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.node import Node
from products.data_modeling.backend.schedule import (
    DATA_MODELING_EXECUTE_DAG_WORKFLOW,
    build_schedule_spec,
    dag_schedule_search_attributes,
)

if TYPE_CHECKING:
    from posthog.models.team import Team

    from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery

logger = structlog.get_logger(__name__)

TIERED_SCHEDULES_FLAG = "data-modeling-tiered-schedules"


def tiered_schedules_enabled(team: "Team") -> bool:
    """Whether per-node cadence tiers may drive this team's DAG schedules."""
    return feature_enabled_or_false(
        TIERED_SCHEDULES_FLAG,
        str(team.uuid),
        groups={"organization": str(team.organization_id), "project": str(team.id)},
        group_properties={
            "organization": {"id": str(team.organization_id)},
            "project": {"id": str(team.id)},
        },
        send_feature_flag_events=False,
    )


def maybe_reconcile_dag(dag: DAG) -> None:
    """Trigger hook for graph/target mutations: reconcile an already-tiered DAG, best-effort.

    Runs after commit so the reconcile reads the mutated graph, and never raises past the
    commit — the user's write already succeeded. Only DAGs already converted to cadence
    tiers are touched: legacy single-schedule DAGs are converted solely by the
    reconcile_freshness_schedules command, so a stray mutation can neither unschedule an
    unseeded DAG nor create tiers alongside live v1 schedules on an unmigrated team.
    """
    if not tiered_schedules_enabled(dag.team):
        return
    transaction.on_commit(lambda: _reconcile_dag_best_effort(dag))


def _reconcile_dag_best_effort(dag: DAG) -> None:
    try:
        _warn_on_invalid_targets(dag)
        reconcile_dag_schedules(dag, require_tiered=True)
    except Exception as error:
        logger.exception("Freshness schedule reconcile failed", dag_id=str(dag.id), team_id=dag.team_id)
        capture_exception(error)


def _warn_on_invalid_targets(dag: DAG) -> None:
    """Surface declared targets that drifted outside their bounds; never blocks the mutation."""
    graph = build_frequency_graph(dag)
    for invalid in find_invalid_targets(
        edges=graph.edges, declared_targets=graph.declared_targets, source_intervals=graph.source_intervals
    ):
        logger.warning(
            "Declared freshness target outside its legal range",
            dag_id=str(dag.id),
            node_id=invalid.node_id,
            target=str(invalid.target),
            floor=str(invalid.floor),
            ceiling=str(invalid.ceiling),
        )


def apply_saved_query_frequency_target(
    saved_query: "DataWarehouseSavedQuery", target: timedelta | None, *, reconcile: bool = True
) -> None:
    """Write a frequency target through to the DAG node(s) carrying this saved query.

    On tiered v2 the node target is the only durable store of frequency intent. `target=None`
    clears it ("never" / revert) and must be a deliberate caller choice, never a default —
    otherwise a caller with no frequency opinion would silently wipe targets. Non-None targets
    are validated against the node's [floor, ceiling] bounds (raising for the caller to
    surface) before writing, then each affected DAG is queued for reconcile (skippable for
    callers batching many writes into one reconcile).
    """
    for node in Node.objects.filter(saved_query=saved_query).select_related("dag", "dag__team"):
        if target is None:
            set_declared_target(node, None)
        else:
            graph = build_frequency_graph(node.dag)
            validate_declared_target(
                node_id=str(node.id),
                target=target,
                edges=graph.edges,
                declared_targets=graph.declared_targets,
                source_intervals=graph.source_intervals,
            )
            set_declared_target(node, target)
        if reconcile:
            maybe_reconcile_dag(node.dag)


def reconcile_dag_schedules(dag: DAG, *, allow_unschedule: bool = False, require_tiered: bool = False) -> None:
    """Make Temporal's schedules for this DAG match its nodes' effective cadences.

    Converging a covered DAG to zero schedules is refused unless `allow_unschedule` — an
    empty tier set on a DAG with live schedules almost always means unseeded targets, not
    a deliberate wind-down. With `require_tiered`, a DAG that has no tiered schedule yet
    (legacy single schedule or nothing) is left untouched.
    """
    team = dag.team
    graph = build_frequency_graph(dag)
    effective = compute_effective_cadences(
        nodes=graph.nodes, edges=graph.edges, declared_targets=graph.declared_targets
    )
    desired_tiers = bucket_into_cadence_tiers(effective)
    _apply_reconciliation(
        dag_id=str(dag.id),
        team_id=team.pk,
        organization_id=str(team.organization_id),
        team_timezone=team.timezone,
        desired_tiers=desired_tiers,
        allow_unschedule=allow_unschedule,
        require_tiered=require_tiered,
    )


@dataclasses.dataclass
class UnsatisfiableTier:
    """A node scheduled finer than its slowest ancestor source can actually deliver."""

    node_id: str
    effective: timedelta  # cadence it would be scheduled at
    source_floor: timedelta  # slowest cadence its sources can actually deliver


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
    declared = {**seed_targets(dag), **graph.declared_targets} if seed else graph.declared_targets
    effective = compute_effective_cadences(nodes=graph.nodes, edges=graph.edges, declared_targets=declared)
    desired_tiers = bucket_into_cadence_tiers(effective)
    existing_ids = _list_existing_schedule_ids(str(dag.id))
    plan = plan_schedule_reconciliation(str(dag.id), desired_tiers, existing_ids)
    return DagSchedulePreview(
        effective=effective,
        desired_tiers=desired_tiers,
        plan=plan,
        best_effort_source_ids=graph.best_effort_source_ids,
        unsatisfiable=_find_unsatisfiable(graph, effective, declared),
        invalid_targets=find_invalid_targets(
            edges=graph.edges, declared_targets=declared, source_intervals=graph.source_intervals
        ),
        unsupported_tiers=sorted(interval for interval in desired_tiers if interval not in SCHEDULABLE_BUCKETS),
        seeded=seed,
    )


def _find_unsatisfiable(
    graph: FrequencyGraph, effective: dict[str, timedelta | None], declared_targets: dict[str, timedelta]
) -> list[UnsatisfiableTier]:
    """Flag nodes whose scheduled cadence is finer than their ancestor sources can deliver."""
    flagged: list[UnsatisfiableTier] = []
    for node_id, node_effective in effective.items():
        if node_effective is None:
            continue
        source_floor, _consumer_ceiling = declared_target_bounds(
            node_id=node_id,
            edges=graph.edges,
            declared_targets=declared_targets,
            source_intervals=graph.source_intervals,
        )
        if is_finer_than(node_effective, source_floor):
            flagged.append(UnsatisfiableTier(node_id=node_id, effective=node_effective, source_floor=source_floor))
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
    allow_unschedule: bool = False,
    require_tiered: bool = False,
) -> None:
    unsupported = sorted(interval for interval in desired_tiers if interval not in SCHEDULABLE_BUCKETS)
    if unsupported:
        tiers = ", ".join(format_cadence(interval) for interval in unsupported)
        raise UnsupportedFrequencyTargetError(
            f"refusing to reconcile DAG {dag_id}: tiers ({tiers}) are not schedulable cadence buckets"
        )

    temporal = await async_connect()
    existing_ids = await _list_execute_dag_schedule_ids(temporal, dag_id)
    if require_tiered and not any(is_tier_schedule_id(schedule_id) for schedule_id in existing_ids):
        logger.debug("DAG not converted to cadence tiers yet, skipping reconcile", dag_id=dag_id)
        return
    if not desired_tiers and existing_ids and not allow_unschedule:
        logger.warning(
            "Refusing to unschedule a covered DAG with no cadence tiers (unseeded targets?)",
            dag_id=dag_id,
            existing_schedule_ids=sorted(existing_ids),
        )
        return
    plan = plan_schedule_reconciliation(dag_id, desired_tiers, existing_ids)

    # Includes the schedule-type tag: get_v2_scheduled_dag_ids' unscoped sweep filters on
    # it server-side, so an untagged tier schedule would make its DAG look un-migrated.
    search_attributes = dag_schedule_search_attributes(team_id=team_id, organization_id=organization_id, dag_id=dag_id)

    # Create/update every desired tier before deleting stale schedules so nodes are never left
    # uncovered; on failure, best-effort-delete the tiers we created (already-applied updates
    # stay — a re-run converges) without letting a failed delete mask the original error.
    created: list[str] = []
    try:
        for schedule_id, (interval, node_ids) in plan.to_create.items():
            schedule = _build_tier_schedule(dag_id, team_id, team_timezone, interval, node_ids)
            try:
                await a_create_schedule(
                    temporal, id=schedule_id, schedule=schedule, search_attributes=search_attributes
                )
                created.append(schedule_id)
            except ScheduleAlreadyRunningError:
                # A concurrent reconcile of the same DAG created this tier from the same graph;
                # converge onto it. It is deliberately NOT in `created`: it isn't ours to roll back.
                await a_update_schedule(
                    temporal, id=schedule_id, schedule=schedule, search_attributes=search_attributes
                )
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

    # A failed delete leaves transient dual coverage (e.g. the legacy whole-DAG schedule alongside
    # tiers); the next reconcile sweeps it, so log and keep going rather than fail the converge.
    for schedule_id in plan.to_delete:
        try:
            await a_delete_schedule(temporal, schedule_id=schedule_id)
        except Exception as error:
            logger.exception("Failed to delete stale schedule", schedule_id=schedule_id, dag_id=dag_id)
            capture_exception(error)


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
    from posthog.temporal.data_modeling.workflows.execute_dag import (  # noqa: PLC0415 — the workflows package imports this product's models back; importing it lazily keeps this module importable from models code and temporal off django.setup()
        ExecuteDAGInputs,
    )

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
