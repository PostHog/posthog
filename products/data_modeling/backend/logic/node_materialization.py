import math
import asyncio
from collections.abc import Set as AbstractSet
from dataclasses import asdict
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from django.conf import settings
from django.db import transaction
from django.utils import timezone

import structlog
from opentelemetry import trace
from rest_framework import exceptions
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.common import RetryPolicy, WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.service import RPCError

from posthog.hogql.database.database import Database

from posthog.models import User
from posthog.temporal.common.client import sync_connect

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.data_modeling.backend.facade.contracts import (
    ManagedWarehouseUnavailableError,
    MaterializationAlreadyRunningError,
    MaterializationForbiddenError,
    MaterializationRanRecentlyError,
    MaterializationRunDirection,
    MissingDagNodeError,
    SavedQueryNotFoundError,
    SavedQueryNotOnV2ScheduleError,
    SkippedRunNode,
    StartedNodeRun,
)
from products.data_modeling.backend.facade.enums import MaterializationRunTrigger
from products.data_modeling.backend.graph import Graph
from products.data_modeling.backend.logic.freshness import SCHEDULABLE_BUCKETS, humanize_cadence
from products.data_modeling.backend.logic.incremental import TRINO_INCREMENTAL_SCOPE, clear_incremental_state
from products.data_modeling.backend.logic.node_suspension import suspended_nodes, unsuspend_nodes
from products.data_modeling.backend.logic.read_access import assert_user_can_read_saved_query
from products.data_modeling.backend.models import (
    DataModelingJob,
    DataModelingJobEngine,
    DataModelingJobStatus,
    Node,
    NodeType,
)
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.node import SAVED_QUERY_NODE_TYPES
from products.data_modeling.backend.schedule import get_v2_saved_query_ids
from products.data_modeling.backend.temporal.activities.materialize_view_managed_warehouse import (
    is_managed_warehouse_shadow_enabled,
)
from products.data_modeling.backend.temporal.workflows.execute_dag import (
    TRINO_SHADOW_RUN_TIMEOUT,
    ExecuteDAGInputs,
    manual_trino_workflow_id,
    trino_build_workflow_id,
)
from products.data_modeling.backend.temporal.workflows.materialize_view import MaterializeViewWorkflowInputs

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)


RELATED_RUN_EDIT_ACCESS_REFUSAL = "You need edit access to every view in this run."
MANAGED_WAREHOUSE_UNAVAILABLE_REFUSAL = "This organization has no managed warehouse set up."
# A manual run gets the same floor as a schedule, so a script calling run in a loop cannot rebuild a view
# more often than the shortest schedule a person may pick.
MANUAL_RUN_MIN_INTERVAL = min(SCHEDULABLE_BUCKETS)
RAN_RECENTLY_REFUSAL = (
    f"This view ran less than {humanize_cadence(MANUAL_RUN_MIN_INTERVAL)} ago, so it can't run again yet."
)
RELATED_RUN_RAN_RECENTLY_REFUSAL = (
    f"Every view in this run ran less than {humanize_cadence(MANUAL_RUN_MIN_INTERVAL)} ago, so it can't run again yet. "
    "To retry a failed view now, run that view on its own."
)
UNRESOLVED_VIEW_SKIP_REASON = "Its query doesn't compile: {error}"
UPSTREAM_UNRESOLVED_SKIP_REASON = "It depends on {name}, whose query doesn't compile."
EMPTY_RUN_REFUSAL = "Every view in this run depends on {name}, whose query doesn't compile: {error}"
RUN_IN_PROGRESS_REFUSAL = "This view is still running. Try again when the run finishes."
RELATED_RUN_IN_PROGRESS_REFUSAL = "A view in this run is still running. Try again when that run finishes."
# A DAG run treats plain views as ephemeral and records no job for them, so they cannot show a recent run.
DAG_BUILT_NODE_TYPES = SAVED_QUERY_NODE_TYPES - {NodeType.VIEW}
# Long enough for the state changes that follow the start to commit before the workflow first reads them.
MANUAL_TRINO_RUN_START_DELAY = timedelta(seconds=5)
MAX_NAMED_BUILDING_MODELS = 5
BUILDING_LOOKUP_CONCURRENCY = 20
BUILDING_LOOKUP_TIMEOUT = timedelta(seconds=5)


@tracer.start_as_current_span("data_modeling.start_node_materialization")
def start_node_materialization(
    node: Node, *, trigger: MaterializationRunTrigger, resume: bool = True, triggered_by_id: int | None = None
) -> None:
    """Start a one-off materialization workflow for a single node.

    Shared by node `materialize` and saved-query `run`.

    `resume=False` is for automatic callers, such as a repair triggered by read traffic. The run
    still starts, but a suspended node keeps its marker and its failure window, so request traffic
    cannot hold the circuit breaker open.

    `triggered_by_id` is the person who asked for this run, and only they are told if it fails.
    Callers with no person behind them leave it unset.
    """
    requested_at = timezone.now()
    if resume:
        # An explicit run is a request to try again, so it gets a fresh failure window.
        unsuspend_nodes([node], by="manual_run")
    inputs = MaterializeViewWorkflowInputs(
        team_id=node.team_id,
        dag_id=str(node.dag_id),
        node_id=str(node.id),
        manually_triggered_by_id=triggered_by_id,
        trigger=trigger,
        requested_at=requested_at.isoformat(),
    )
    temporal = sync_connect()
    asyncio.run(
        temporal.start_workflow(
            "data-modeling-materialize-view",
            asdict(inputs),
            id=f"materialize-view-{node.id}",
            task_queue=str(settings.DATA_MODELING_TASK_QUEUE),
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            retry_policy=RetryPolicy(maximum_attempts=1),  # retries handled within the workflow
        )
    )


def _latest_runs_inside_limit(
    team_id: int,
    saved_query_ids: AbstractSet[UUID | str],
    *,
    now: datetime,
    ignored_statuses: frozenset[str] = frozenset(),
) -> list[tuple[str, datetime]]:
    """The status and start of the latest ClickHouse run of each view inside MANUAL_RUN_MIN_INTERVAL.

    A query edit after that run started removes the view, because that run did not build the new query.
    """
    latest_runs = (
        DataModelingJob.objects.filter(
            team_id=team_id,
            saved_query_id__in=saved_query_ids,
            engine=DataModelingJobEngine.CLICKHOUSE,
            created_at__gt=now - MANUAL_RUN_MIN_INTERVAL,
        )
        .exclude(status__in=ignored_statuses)
        .order_by("saved_query_id", "-created_at")
        .distinct("saved_query_id")
        .values_list("status", "created_at", "saved_query__query_updated_at")
    )
    return [
        (status, started_at)
        for status, started_at, query_updated_at in latest_runs
        if query_updated_at is None or query_updated_at <= started_at
    ]


def _seconds_until_limit_ends(started_at: datetime, now: datetime) -> int:
    return math.ceil((started_at + MANUAL_RUN_MIN_INTERVAL - now).total_seconds())


def raise_if_manual_run_is_refused(team_id: int, saved_query_id: UUID | str, *, from_browser_session: bool) -> None:
    """Refuse a manual run of one view inside the limit. A failed or cancelled latest run can retry at once."""
    if from_browser_session:
        if _any_view_is_running(team_id, {saved_query_id}):
            raise MaterializationAlreadyRunningError(RUN_IN_PROGRESS_REFUSAL)
        return
    now = timezone.now()
    for status, started_at in _latest_runs_inside_limit(
        team_id, {saved_query_id}, now=now, ignored_statuses=frozenset({DataModelingJobStatus.SKIPPED})
    ):
        if status in (DataModelingJobStatus.RUNNING, DataModelingJobStatus.COMPLETED):
            raise MaterializationRanRecentlyError(
                RAN_RECENTLY_REFUSAL, retry_after_seconds=_seconds_until_limit_ends(started_at, now)
            )


def _raise_if_every_view_ran_recently(team_id: int, saved_query_ids: AbstractSet[UUID | str]) -> None:
    """Refuse a manual run when every view it would build had a run inside the limit, whatever that run's status.

    A failed or skipped view counts here, or one broken view would lift the limit for every view it runs with.
    The wait is for the view that leaves the limit first, because a retry can succeed from that moment.
    """
    now = timezone.now()
    latest_runs = _latest_runs_inside_limit(team_id, saved_query_ids, now=now)
    if latest_runs and len(latest_runs) == len(saved_query_ids):
        raise MaterializationRanRecentlyError(
            RELATED_RUN_RAN_RECENTLY_REFUSAL,
            retry_after_seconds=min(_seconds_until_limit_ends(started_at, now) for _, started_at in latest_runs),
        )


def _any_view_is_running(team_id: int, saved_query_ids: AbstractSet[UUID | str]) -> bool:
    """Whether any job of these views, latest or not, is a ClickHouse run in progress inside MANUAL_RUN_MIN_INTERVAL."""
    return DataModelingJob.objects.filter(
        team_id=team_id,
        saved_query_id__in=saved_query_ids,
        engine=DataModelingJobEngine.CLICKHOUSE,
        status=DataModelingJobStatus.RUNNING,
        created_at__gt=timezone.now() - MANUAL_RUN_MIN_INTERVAL,
    ).exists()


def _get_node(team_id: int, node_id: UUID | str) -> Node:
    try:
        return Node.objects.select_related("team").get(team_id=team_id, id=node_id)
    except Node.DoesNotExist:
        raise MissingDagNodeError(f"Node {node_id} not found")


@tracer.start_as_current_span("data_modeling.assert_user_can_run_nodes")
def _assert_user_can_run_nodes(node: Node, node_ids: set[str], user: User) -> dict[str, str]:
    """Refuse the run unless the user may edit every view in it and read every source those views read.

    Returns the compile error of each view whose query does not resolve, keyed by node id. Such a view
    cannot have its sources checked, so the caller must leave it out of the run. A denial in any view
    refuses the whole run, also when another view in it does not resolve.
    """
    trace.get_current_span().set_attribute("node_count", len(node_ids))
    # A run materializes every node it touches, so it needs the same edit and data access checks as
    # enabling materialization for each view.
    database = Database.create_for(team_id=node.team_id, user=user, trigger="node_run_access_check")
    access_control = UserAccessControl(user=user, team=node.team)
    nodes = Node.objects.filter(team_id=node.team_id, id__in=node_ids, saved_query__isnull=False).select_related(
        "saved_query"
    )
    unresolved: dict[str, str] = {}
    for run_node in nodes:
        saved_query = run_node.saved_query
        assert saved_query is not None
        if not access_control.check_access_level_for_object(saved_query, "editor"):
            raise MaterializationForbiddenError(RELATED_RUN_EDIT_ACCESS_REFUSAL)
        try:
            assert_user_can_read_saved_query(saved_query, user, database=database)
        except exceptions.ValidationError as error:
            # Resolution stops at the first error, so the sources after it stay unchecked. A denial can
            # also look like a compile error, because a saved expression the user is denied is left out
            # of their schema and reads as an unknown field. The managed warehouse reads sources without
            # the user's access control, and a rebuild of an upstream view in the same run can make this
            # query compile at run time, so letting it run could read what the user is denied.
            unresolved[str(run_node.id)] = _first_error_message(error)
    return unresolved


def _first_error_message(error: exceptions.ValidationError) -> str:
    detail = error.detail
    if isinstance(detail, list) and detail:
        return str(detail[0])
    return str(detail)


def _raise_if_picked_node_does_not_resolve(node: Node, unresolved: dict[str, str]) -> None:
    if str(node.id) in unresolved:
        raise exceptions.ValidationError(unresolved[str(node.id)])


def _leave_out_unresolved_nodes(
    team_id: int, graph: Graph, node_ids: set[str], unresolved: dict[str, str]
) -> tuple[set[str], list[SkippedRunNode]]:
    """Drop every view that does not resolve, and the views in the run that depend on it.

    A DAG run skips the downstream of a failed node, so the run left after this matches what the DAG
    would build had those views failed.
    """
    if not unresolved:
        return node_ids, []
    names = dict(Node.objects.filter(team_id=team_id, id__in=node_ids).values_list("id", "name"))
    name_of = {str(node_id): name for node_id, name in names.items()}
    reasons = {node_id: UNRESOLVED_VIEW_SKIP_REASON.format(error=error) for node_id, error in unresolved.items()}
    for root_id in sorted(unresolved, key=lambda node_id: name_of.get(node_id, "")):
        for descendant_id in graph.get_downstream(root_id) & node_ids:
            reasons.setdefault(descendant_id, UPSTREAM_UNRESOLVED_SKIP_REASON.format(name=name_of.get(root_id, "")))
    skipped = [
        SkippedRunNode(node_id=node_id, name=name_of.get(node_id, ""), reason=reason)
        for node_id, reason in sorted(reasons.items(), key=lambda item: name_of.get(item[0], ""))
    ]
    remaining = node_ids - reasons.keys()
    if not remaining:
        root_id = min(unresolved, key=lambda node_id: name_of.get(node_id, ""))
        raise exceptions.ValidationError(
            EMPTY_RUN_REFUSAL.format(name=name_of.get(root_id, ""), error=unresolved[root_id])
        )
    return remaining, skipped


def _related_node_ids(
    node: Node,
    *,
    direction: MaterializationRunDirection | str,
    user: User,
    hidden_types: frozenset[str],
) -> tuple[set[str], list[SkippedRunNode]]:
    graph = Graph(team_id=node.team_id, dag_id=node.dag_id, hidden_types=hidden_types)
    if direction == MaterializationRunDirection.UPSTREAM:
        node_ids = graph.get_upstream(node.id)
    else:
        node_ids = graph.get_downstream(node.id)

    managed_view_node_ids = {
        str(node_id)
        for node_id in Node.objects.filter(
            team_id=node.team_id,
            id__in=node_ids,
            saved_query__managed_viewset__isnull=False,
        ).values_list("id", flat=True)
    }
    node_ids = managed_view_node_ids if node.belongs_to_managed_viewset else node_ids - managed_view_node_ids
    node_ids.add(str(node.id))

    unresolved = _assert_user_can_run_nodes(node, node_ids, user)
    _raise_if_picked_node_does_not_resolve(node, unresolved)
    return _leave_out_unresolved_nodes(node.team_id, graph, node_ids, unresolved)


def run_related_node_materializations(
    team_id: int,
    node_id: UUID | str,
    *,
    direction: MaterializationRunDirection | str,
    user: User,
    from_browser_session: bool,
    hidden_types: frozenset[str] = frozenset(),
) -> StartedNodeRun:
    requested_at = timezone.now()
    node = _get_node(team_id, node_id)
    node_ids, skipped = _related_node_ids(node, direction=direction, user=user, hidden_types=hidden_types)
    built_saved_query_ids = set(
        Node.objects.filter(team_id=team_id, id__in=node_ids, type__in=DAG_BUILT_NODE_TYPES)
        .exclude(saved_query__deleted=True)
        .values_list("saved_query_id", flat=True)
    )
    if from_browser_session:
        if _any_view_is_running(team_id, built_saved_query_ids):
            raise MaterializationAlreadyRunningError(RELATED_RUN_IN_PROGRESS_REFUSAL)
    else:
        _raise_if_every_view_ran_recently(team_id, built_saved_query_ids)

    # The workflow skips suspended nodes, so an explicit run must resume every selected node first.
    unsuspend_nodes(suspended_nodes(Node.objects.filter(team_id=node.team_id, id__in=node_ids)), by="manual_run")

    inputs = ExecuteDAGInputs(
        team_id=node.team_id,
        dag_id=str(node.dag_id),
        node_ids=sorted(node_ids),
        manually_triggered_by_id=user.pk,
        trigger=MaterializationRunTrigger.MANUAL,
        requested_at=requested_at.isoformat(),
    )
    temporal = sync_connect()
    asyncio.run(
        temporal.start_workflow(
            "data-modeling-execute-dag",
            asdict(inputs),
            id=f"execute-dag-{uuid4()}",
            task_queue=str(settings.DATA_MODELING_TASK_QUEUE),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=10),
                maximum_interval=timedelta(seconds=60),
                maximum_attempts=3,
                non_retryable_error_types=["NondeterminismError", "CancelledError"],
            ),
        )
    )
    return StartedNodeRun(node_ids=sorted(node_ids), skipped=skipped)


async def _nodes_building_on_trino(temporal: Client, dag_id: str, node_ids: list[str]) -> list[str]:
    """The nodes whose fixed Trino build id has a running workflow.

    This check only gives a clear error before the run starts. The fixed build id is the lock, so a node
    whose build cannot be read counts as free, and the run skips that node if another run holds it.
    Lookups are bounded in number and time, so a large selection cannot flood Temporal or stall the request.
    """

    limit = asyncio.Semaphore(BUILDING_LOOKUP_CONCURRENCY)

    async def is_building(node_id: str) -> bool:
        try:
            async with limit:
                description = await temporal.get_workflow_handle(trino_build_workflow_id(dag_id, node_id)).describe(
                    rpc_timeout=BUILDING_LOOKUP_TIMEOUT
                )
        except RPCError:
            return False
        return description.status == WorkflowExecutionStatus.RUNNING

    building = await asyncio.gather(*(is_building(node_id) for node_id in node_ids))
    return [node_id for node_id, is_busy in zip(node_ids, building) if is_busy]


def _models_building_refusal(team_id: int, node_ids: list[str]) -> str:
    names = sorted(Node.objects.filter(team_id=team_id, id__in=node_ids).values_list("name", flat=True))
    named = ", ".join(names[:MAX_NAMED_BUILDING_MODELS])
    if len(names) > MAX_NAMED_BUILDING_MODELS:
        named += f" and {len(names) - MAX_NAMED_BUILDING_MODELS} more"
    return f"Another managed warehouse run is building {named}. Try again once it finishes."


def run_trino_node_materializations(
    team_id: int,
    node_id: UUID | str,
    *,
    direction: MaterializationRunDirection | str | None,
    user: User,
    full_refresh: bool = False,
    hidden_types: frozenset[str] = frozenset(),
) -> StartedNodeRun:
    """Build the node, and optionally its upstreams or downstreams, on the managed warehouse only.

    Runs the same managed_warehouse_only DAG run as the scheduled Trino shadow, so ClickHouse is not
    touched. Refuses while another run builds one of the selected models on Trino. Runs of other
    models can overlap, because the fixed build id of each node already stops two runs from writing
    one Trino table at once.

    `full_refresh` drops the node's Trino watermark, and only after every refusal, so a refused run
    does not turn the next scheduled shadow into a full rebuild.
    The run starts a few seconds late, so the state changes commit before the workflow reads them.
    """
    requested_at = timezone.now()
    node = _get_node(team_id, node_id)
    if not is_managed_warehouse_shadow_enabled(node.team):
        raise ManagedWarehouseUnavailableError(MANAGED_WAREHOUSE_UNAVAILABLE_REFUSAL)
    if direction:
        node_ids, skipped = _related_node_ids(node, direction=direction, user=user, hidden_types=hidden_types)
    else:
        node_ids, skipped = {str(node.id)}, []
        # The managed warehouse reads source tables without the caller's access control, so check it here.
        _raise_if_picked_node_does_not_resolve(node, _assert_user_can_run_nodes(node, node_ids, user))

    dag_id = str(node.dag_id)
    temporal = sync_connect()
    inputs = ExecuteDAGInputs(
        team_id=node.team_id,
        dag_id=dag_id,
        node_ids=sorted(node_ids),
        managed_warehouse_only=True,
        shadow=True,
        manually_triggered_by_id=user.pk,
        trigger=MaterializationRunTrigger.MANUAL,
        requested_at=requested_at.isoformat(),
    )
    building = asyncio.run(_nodes_building_on_trino(temporal, dag_id, sorted(node_ids)))
    if building:
        raise MaterializationAlreadyRunningError(_models_building_refusal(node.team_id, building))

    # The start is delayed so that the changes below commit before the workflow reads them.
    handle = asyncio.run(
        temporal.start_workflow(
            "data-modeling-execute-dag",
            asdict(inputs),
            id=manual_trino_workflow_id(dag_id),
            task_queue=str(settings.DATA_MODELING_TASK_QUEUE),
            execution_timeout=TRINO_SHADOW_RUN_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=1),
            start_delay=MANUAL_TRINO_RUN_START_DELAY,
        )
    )

    try:
        with transaction.atomic():
            if full_refresh and node.saved_query is not None:
                clear_incremental_state(node.saved_query, scope=TRINO_INCREMENTAL_SCOPE)
            unsuspend_nodes(
                suspended_nodes(Node.objects.filter(team_id=node.team_id, id__in=node_ids)),
                by="manual_run",
                engine=DataModelingJobEngine.MANAGED_WAREHOUSE,
            )
    except Exception:
        # The run would otherwise start on state the caller did not ask for, while the caller sees an error.
        asyncio.run(handle.terminate("Could not prepare the models for the run"))
        raise
    return StartedNodeRun(node_ids=sorted(node_ids), skipped=skipped)


def is_saved_query_on_v2_schedule(saved_query: DataWarehouseSavedQuery) -> bool:
    """Whether the saved query's DAG already runs on a v2 schedule.

    Keys on the Temporal source of truth (get_v2_saved_query_ids), not the feature flag, since a
    team can be schedule-migrated without being flagged.
    """
    return saved_query.id in get_v2_saved_query_ids([saved_query.id])


def run_saved_query_materialization(
    team_id: int, saved_query_id: UUID | str, *, trigger: MaterializationRunTrigger
) -> None:
    """Materialize one saved query now, for a caller outside this product.

    Restricted to the v2 workflow, and raising rather than falling back, because a caller reaching
    here wants what only a v2 materialization does. Keeps the saved-query model inside this product:
    the caller passes ids and handles the two errors above.
    """
    saved_query = (
        DataWarehouseSavedQuery.objects.exclude(deleted=True).filter(id=saved_query_id, team_id=team_id).first()
    )
    if saved_query is None:
        raise SavedQueryNotFoundError(f"Saved query {saved_query_id} not found for team {team_id}")
    if not is_saved_query_on_v2_schedule(saved_query):
        raise SavedQueryNotOnV2ScheduleError(f"Saved query {saved_query_id} is not on the v2 schedule")
    materialize_saved_query(saved_query, trigger=trigger)


def materialize_saved_query(
    saved_query: DataWarehouseSavedQuery,
    *,
    trigger: MaterializationRunTrigger,
    resume: bool = True,
    triggered_by_id: int | None = None,
) -> UUID:
    """Materialize the saved query's backing node via the v2 workflow.

    Fire a single materialization — don't fan out over duplicate-DAG nodes, or two workers race to
    write the same backing table.
    """
    node = (
        Node.objects.filter(team_id=saved_query.team_id, saved_query_id=saved_query.id).order_by("created_at").first()
    )
    if node is None:
        # v2 was already confirmed, so a node should exist; a missing one is a data inconsistency.
        # Raise rather than return: returning reports a materialization the caller can then find no
        # trace of, and there is no v1 schedule left to fall back to.
        raise MissingDagNodeError(f"Saved query {saved_query.id} has no DAG node to materialize")
    start_node_materialization(node, trigger=trigger, resume=resume, triggered_by_id=triggered_by_id)
    return node.id
