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
from collections.abc import Iterable, Mapping
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
from temporalio.service import RPCError, RPCStatusCode

from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.client import async_connect
from posthog.temporal.common.schedule import a_create_schedule, a_delete_schedule, a_update_schedule
from posthog.temporal.common.search_attributes import POSTHOG_DAG_ID_KEY

from products.data_modeling.backend.logic.cohort_scheduling import (
    MINUTES_PER_WEEK,
    ScheduleReconcilePlan,
    Tier,
    bucket_into_cadence_tiers,
    plan_schedule_reconciliation,
    tier_schedule_id,
)
from products.data_modeling.backend.logic.freshness import (
    SCHEDULABLE_BUCKETS,
    ClampedCadence,
    InvalidTarget,
    UnsupportedFrequencyTargetError,
    clamp_to_source_floor,
    compute_effective_cadences,
    find_invalid_targets,
    format_cadence,
    validate_declared_target,
)
from products.data_modeling.backend.logic.node_frequency import (
    FrequencyGraph,
    build_frequency_graph,
    persist_seed_targets,
    seed_targets,
    set_declared_anchor,
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
    from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery

logger = structlog.get_logger(__name__)


def maybe_reconcile_dag(dag: DAG) -> None:
    """Trigger hook for graph/target mutations: reconcile the DAG, best-effort.

    Runs after commit so the reconcile reads the mutated graph, and never raises past the
    commit — the user's write already succeeded.
    """
    transaction.on_commit(lambda: _reconcile_dag_best_effort(dag))


def _reconcile_dag_best_effort(dag: DAG) -> None:
    try:
        graph = build_frequency_graph(dag)
        _warn_on_invalid_targets(dag, graph)
        reconcile_dag_schedules(dag, graph=graph)
    except Exception as error:
        logger.exception("Freshness schedule reconcile failed", dag_id=str(dag.id), team_id=dag.team_id)
        capture_exception(error)


def bootstrap_dag_to_tiers(dag: DAG, *, requested_by: "DataWarehouseSavedQuery | None" = None) -> None:
    """Seed the DAG's targets and queue the reconcile that creates its first tier schedules.

    Everything here is a side effect, and `transaction.on_commit` runs the callback immediately
    for callers that are not inside an atomic block — so call this only once the v2 lookup has
    said the DAG has no `execute-dag` schedule, and only after whatever frequency validation the
    caller does, never before.

    `requested_by` is the saved query whose enable triggered this, and is marked not materialized
    if the reconcile fails.
    """
    persist_seed_targets(dag)
    transaction.on_commit(lambda: _bootstrap_dag_best_effort(dag, requested_by))


def _bootstrap_dag_best_effort(dag: DAG, requested_by: "DataWarehouseSavedQuery | None" = None) -> None:
    try:
        reconcile_dag_schedules(dag)
    except Exception as error:
        logger.exception("Freshness schedule bootstrap failed", dag_id=str(dag.id), team_id=dag.team_id)
        capture_exception(error)
        if requested_by is not None:
            # A bootstrap that fails creates no schedule, so nothing will ever run the query that
            # asked for one. Retract the claim here rather than re-raise: this runs after the
            # caller's transaction committed, so there is no longer a caller to catch it.
            requested_by.is_materialized = False
            requested_by.save(update_fields=["is_materialized"])


def _warn_on_invalid_targets(dag: DAG, graph: FrequencyGraph | None = None) -> None:
    """Surface declared targets that drifted outside their bounds; never blocks the mutation."""
    if graph is None:
        graph = build_frequency_graph(dag)
    for invalid in find_invalid_targets(
        edges=graph.edges, declared_targets=graph.declared_targets, source_intervals=graph.source_intervals
    ):
        logger.warning(
            "Declared freshness target outside its legal range",
            dag_id=str(dag.id),
            node_id=invalid.node_id,
            declared=str(invalid.declared),
            source_floor=str(invalid.source_floor),
            consumer_ceiling=str(invalid.consumer_ceiling),
        )


def apply_saved_query_frequency_target(
    saved_query: "DataWarehouseSavedQuery",
    target: timedelta | None,
    *,
    reconcile: bool = True,
    visible_names: Mapping[str, str] | None = None,
) -> int:
    """Write a frequency target through to the DAG node(s) carrying this saved query.

    On tiered v2 the node target is the only durable store of frequency intent. `target=None`
    clears it ("never" / revert) and must be a deliberate caller choice, never a default —
    otherwise a caller with no frequency opinion would silently wipe targets. Non-None targets
    are validated against the node's [floor, ceiling] bounds (raising for the caller to
    surface) before writing, then each affected DAG is queued for reconcile (skippable for
    callers batching many writes into one reconcile).

    Returns the number of nodes written (0 = no DAG node, so a non-None target was stored nowhere).

    `visible_names` is the set of node names a refusal is allowed to use. It defaults to naming
    nothing, because a refusal travels: `schedule_materialization` re-raises it and the endpoints
    API returns its text verbatim, so a default of "name everything" would hand a caller the name
    of a node they may not read. Callers holding a per-user map (the saved-query surfaces) pass it
    and get the better message; everything left out falls back to generic prose.

    Atomic because a saved query can still carry nodes in several DAGs while duplicates are being
    consolidated away: without it, a target rejected by the third node stays written on the first
    two, and their reconciles are already queued. One node per saved query is the end state, which
    makes this a no-op then rather than something to unwind later.
    """
    written = 0
    with transaction.atomic():
        # target and anchor share one JSON field and each setter rewrites the whole blob, so an
        # unlocked read-modify-write racing the anchor path would silently drop the other's key
        for node in (
            Node.objects.select_for_update(of=("self",))
            .filter(team=saved_query.team, saved_query=saved_query)
            .select_related("dag", "dag__team")
        ):
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
                    names=visible_names or {},
                )
                set_declared_target(node, target)
            written += 1
            if reconcile:
                maybe_reconcile_dag(node.dag)
    return written


def check_saved_query_frequency_target(
    saved_query: "DataWarehouseSavedQuery", target: timedelta, *, visible_names: Mapping[str, str] | None = None
) -> None:
    """Raise if this target cannot be honored on any of the saved query's nodes, writing nothing.

    The write path validates too, but only after its caller has committed state it then has to undo
    by hand. Callers serving a user can ask first and refuse before touching anything. See
    `apply_saved_query_frequency_target` for `visible_names`.
    """
    for node in Node.objects.filter(team=saved_query.team, saved_query=saved_query).select_related("dag", "dag__team"):
        graph = build_frequency_graph(node.dag)
        validate_declared_target(
            node_id=str(node.id),
            target=target,
            edges=graph.edges,
            declared_targets=graph.declared_targets,
            source_intervals=graph.source_intervals,
            names=visible_names or {},
        )


def apply_saved_query_frequency_anchor(
    saved_query: "DataWarehouseSavedQuery", anchor_minutes: int | None, *, reconcile: bool = True
) -> int:
    """Write a schedule anchor through to the DAG node(s) carrying this saved query.

    The anchor pins the fire phase of whatever cohort the node lands in (minutes past
    Monday 00:00 UTC); `anchor_minutes=None` clears it back to hash-spread. Returns the
    number of nodes written (0 = no DAG node, so a non-None anchor was stored nowhere).
    """
    if anchor_minutes is not None and not 0 <= anchor_minutes < MINUTES_PER_WEEK:
        raise ValueError(f"anchor_minutes must be in [0, {MINUTES_PER_WEEK}), got {anchor_minutes}")
    written = 0
    # atomic + row locks for the same reasons as the target path: all-or-nothing across a
    # multi-DAG duplicate's nodes, and no lost update against a concurrent target write
    with transaction.atomic():
        for node in (
            Node.objects.select_for_update(of=("self",))
            .filter(team=saved_query.team, saved_query=saved_query)
            .select_related("dag", "dag__team")
        ):
            set_declared_anchor(node, anchor_minutes)
            written += 1
            if reconcile:
                maybe_reconcile_dag(node.dag)
    return written


def reconcile_dag_schedules(dag: DAG, *, graph: FrequencyGraph | None = None) -> None:
    """Make Temporal's schedules for this DAG match its nodes' effective cadences.

    An empty tier set is a deliberate wind-down (last target reverted/cleared), so the DAG's
    schedules are torn down.
    """
    team = dag.team
    if graph is None:
        graph = build_frequency_graph(dag)
    effective = compute_effective_cadences(
        nodes=graph.nodes, edges=graph.edges, declared_targets=graph.declared_targets
    )
    effective, _clamped = clamp_to_source_floor(effective, edges=graph.edges, source_intervals=graph.source_intervals)
    desired_tiers = bucket_into_cadence_tiers(effective, graph.declared_anchors)
    _apply_reconciliation(
        dag_id=str(dag.id),
        team_id=team.pk,
        organization_id=str(team.organization_id),
        team_timezone=team.timezone,
        desired_tiers=desired_tiers,
    )


def convert_dag_to_tiers(dag: DAG, default: timedelta | None = None) -> int:
    """Seed per-node targets from the DAG's current cadence, then reconcile it to per-cadence tier
    schedules. The shared conversion step of batch_reconcile_teams and reconcile_freshness_schedules.
    Also repairs nodes a table backs but the graph still calls ephemeral views.

    Returns how many targets were seeded.
    """
    from products.data_modeling.backend.logic.saved_query_dag_sync import (  # noqa: PLC0415 — saved_query_dag_sync imports this module
        promote_dag_view_nodes_to_matview,
    )

    promote_dag_view_nodes_to_matview(dag)
    seeded = persist_seed_targets(dag, default=default)
    reconcile_dag_schedules(dag)
    return seeded


@dataclasses.dataclass
class DagSchedulePreview:
    """What reconcile would do for a DAG, computed read-only (no schedule writes)."""

    effective: dict[str, timedelta | None]  # every schedulable node's resolved cadence (post-clamp)
    desired_tiers: dict[Tier, set[str]]
    plan: ScheduleReconcilePlan
    best_effort_source_ids: set[str]  # sources whose freshness is not actually guaranteed
    clamped: list[ClampedCadence]  # nodes coarsened to what their sources can deliver
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
    effective, clamped = clamp_to_source_floor(effective, edges=graph.edges, source_intervals=graph.source_intervals)
    desired_tiers = bucket_into_cadence_tiers(effective, graph.declared_anchors)
    existing_ids = list_existing_schedule_ids(str(dag.id))
    plan = plan_schedule_reconciliation(str(dag.id), desired_tiers, existing_ids)
    return DagSchedulePreview(
        effective=effective,
        desired_tiers=desired_tiers,
        plan=plan,
        best_effort_source_ids=graph.best_effort_source_ids,
        clamped=clamped,
        invalid_targets=find_invalid_targets(
            edges=graph.edges, declared_targets=declared, source_intervals=graph.source_intervals
        ),
        unsupported_tiers=sorted({tier.interval for tier in desired_tiers if tier.interval not in SCHEDULABLE_BUCKETS}),
        seeded=seed,
    )


@async_to_sync
async def list_existing_schedule_ids(dag_id: str) -> set[str]:
    temporal = await async_connect()
    return await _list_execute_dag_schedule_ids(temporal, dag_id)


@dataclasses.dataclass(frozen=True, kw_only=True)
class DagScheduleTeardown:
    """`ok` is False when the listing or any delete failed, so Temporal may still hold a schedule
    for this DAG. `deleted` holds the ids that are confirmed gone.
    """

    ok: bool
    deleted: tuple[str, ...]


@async_to_sync
async def delete_dag_schedules(dag_id: str) -> DagScheduleTeardown:
    """Delete every execute-dag schedule Temporal has for a DAG, from an authoritative listing
    (PostHogDagId search attribute) rather than an id formula, so a tier, legacy or off-scheme
    schedule cannot survive its DAG. NOT_FOUND means a concurrent delete won the race.

    Callers that own the DAG row must keep it when `ok` is False: the listing is the only way back
    to these schedules once the row is gone.
    """
    try:
        temporal = await async_connect()
        schedule_ids = await _list_execute_dag_schedule_ids(temporal, dag_id)
    except Exception as error:
        logger.exception("Failed to list execute-dag schedules", dag_id=dag_id)
        capture_exception(error)
        return DagScheduleTeardown(ok=False, deleted=())

    ok = True
    deleted: list[str] = []
    for schedule_id in sorted(schedule_ids):
        try:
            await a_delete_schedule(temporal, schedule_id=schedule_id)
        except Exception as error:
            if isinstance(error, RPCError) and error.status == RPCStatusCode.NOT_FOUND:
                continue
            ok = False
            logger.exception("Failed to delete execute-dag schedule", schedule_id=schedule_id, dag_id=dag_id)
            capture_exception(error)
            continue
        deleted.append(schedule_id)
    return DagScheduleTeardown(ok=ok, deleted=tuple(deleted))


class TeamScheduleTeardownError(Exception):
    pass


def delete_team_data_modeling_schedules(team_id: int) -> None:
    """Tear down every Temporal schedule data modeling owns for a team, before CASCADE removes the
    rows that name them.

    Raises `TeamScheduleTeardownError` if any delete failed, so the caller can retry. What outlives
    the retries is left to the orphan sweeps, which start from Temporal and so can still find a
    schedule after its rows are gone.
    """
    failed = 0

    for dag_id in DAG.objects.filter(team_id=team_id).values_list("id", flat=True):
        if not delete_dag_schedules(str(dag_id)).ok:
            failed += 1

    if failed:
        raise TeamScheduleTeardownError(f"Failed to delete {failed} data modeling schedules for team {team_id}")


@async_to_sync
async def _apply_reconciliation(
    *,
    dag_id: str,
    team_id: int,
    organization_id: str,
    team_timezone: str,
    desired_tiers: dict[Tier, set[str]],
) -> None:
    unsupported = sorted({tier.interval for tier in desired_tiers if tier.interval not in SCHEDULABLE_BUCKETS})
    if unsupported:
        tiers = ", ".join(format_cadence(interval) for interval in unsupported)
        raise UnsupportedFrequencyTargetError(
            f"refusing to reconcile DAG {dag_id}: tiers ({tiers}) are not schedulable cadence buckets"
        )

    temporal = await async_connect()
    existing_ids = await _list_execute_dag_schedule_ids(temporal, dag_id)
    plan = plan_schedule_reconciliation(dag_id, desired_tiers, existing_ids)

    # Includes the schedule-type tag: get_v2_scheduled_dag_ids' unscoped sweep filters on
    # it server-side, so an untagged tier schedule would make its DAG look un-migrated.
    search_attributes = dag_schedule_search_attributes(team_id=team_id, organization_id=organization_id, dag_id=dag_id)

    # Create/update every desired tier before deleting stale schedules so nodes are never left
    # uncovered; on failure, best-effort-delete the tiers we created (already-applied updates
    # stay — a re-run converges) without letting a failed delete mask the original error.
    created: list[str] = []

    async def create_or_converge(schedule_id: str, schedule: Schedule) -> None:
        try:
            await a_create_schedule(temporal, id=schedule_id, schedule=schedule, search_attributes=search_attributes)
            created.append(schedule_id)
        except ScheduleAlreadyRunningError:
            # A concurrent reconcile of the same DAG created this tier from the same graph;
            # converge onto it. It is deliberately NOT in `created`: it isn't ours to roll back.
            await a_update_schedule(temporal, id=schedule_id, schedule=schedule, search_attributes=search_attributes)

    try:
        for schedule_id, (tier, node_ids) in plan.to_create.items():
            await create_or_converge(schedule_id, _build_tier_schedule(dag_id, team_id, team_timezone, tier, node_ids))
        for schedule_id, (tier, node_ids) in plan.to_update.items():
            schedule = _build_tier_schedule(dag_id, team_id, team_timezone, tier, node_ids)
            try:
                await a_update_schedule(
                    temporal, id=schedule_id, schedule=schedule, search_attributes=search_attributes
                )
            except RPCError as error:
                if error.status != RPCStatusCode.NOT_FOUND:
                    raise
                # The listing reads Temporal's eventually consistent visibility store, so it can
                # still name a tier that a teardown or a concurrent reconcile just deleted.
                await create_or_converge(schedule_id, schedule)
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
    dag_id: str, team_id: int, team_timezone: str, tier: Tier, node_ids: Iterable[str]
) -> Schedule:
    from posthog.temporal.data_modeling.workflows.execute_dag import (  # noqa: PLC0415 — the workflows package imports this product's models back; importing it lazily keeps this module importable from models code and temporal off django.setup()
        ExecuteDAGInputs,
    )

    inputs = ExecuteDAGInputs(team_id=team_id, dag_id=dag_id, node_ids=sorted(node_ids), managed_warehouse_only=False)
    spec = build_schedule_spec(
        entity_id=uuid.UUID(dag_id),
        interval=tier.interval,
        team_timezone=team_timezone,
        anchor_minutes=tier.anchor_minutes,
    )
    note = f"data-modeling DAG {dag_id} cadence tier {tier.interval}"
    if tier.anchor_minutes is not None:
        note += f" anchored at {tier.anchor_minutes}min past Monday 00:00 UTC"
    return Schedule(
        action=ScheduleActionStartWorkflow(
            DATA_MODELING_EXECUTE_DAG_WORKFLOW,
            dataclasses.asdict(inputs),
            id=f"execute-dag-{tier_schedule_id(dag_id, tier.interval, tier.anchor_minutes)}",
            task_queue=str(settings.DATA_MODELING_TASK_QUEUE),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=10),
                maximum_interval=timedelta(seconds=60),
                maximum_attempts=3,
                non_retryable_error_types=["NondeterminismError", "CancelledError"],
            ),
        ),
        spec=spec,
        state=ScheduleState(note=note),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )
