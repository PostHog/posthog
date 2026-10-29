import asyncio
from dataclasses import asdict
from datetime import timedelta
from uuid import UUID, uuid4

from django.conf import settings
from django.db import transaction

import structlog
from temporalio.common import RetryPolicy, WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.hogql.database.database import Database

from posthog.models import User
from posthog.rbac.query_access import assert_user_can_read_query
from posthog.temporal.common.client import sync_connect
from posthog.temporal.data_modeling.activities.materialize_view_managed_warehouse import (
    is_managed_warehouse_shadow_enabled,
)
from posthog.temporal.data_modeling.workflows.execute_dag import (
    TRINO_SHADOW_RUN_TIMEOUT,
    ExecuteDAGInputs,
    manual_trino_workflow_id,
    trino_runs_of_dag_query,
)
from posthog.temporal.data_modeling.workflows.materialize_view import MaterializeViewWorkflowInputs

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.data_modeling.backend.facade.contracts import (
    ManagedWarehouseUnavailableError,
    MaterializationAlreadyRunningError,
    MaterializationForbiddenError,
    MaterializationRunDirection,
)
from products.data_modeling.backend.graph import Graph
from products.data_modeling.backend.logic.incremental import TRINO_INCREMENTAL_SCOPE, clear_incremental_state
from products.data_modeling.backend.logic.node_suspension import unsuspend_nodes
from products.data_modeling.backend.logic.saved_query_dag_sync import MissingDagNodeError
from products.data_modeling.backend.models import DataModelingJobEngine, Node
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.schedule import get_v2_saved_query_ids

logger = structlog.get_logger(__name__)


RELATED_RUN_EDIT_ACCESS_REFUSAL = "You need edit access to every view in this run."
MANAGED_WAREHOUSE_UNAVAILABLE_REFUSAL = "This organization has no managed warehouse set up."
# Long enough for the state changes that follow the start to commit before the workflow first reads them.
MANUAL_TRINO_RUN_START_DELAY = timedelta(seconds=5)
TRINO_RUN_ALREADY_RUNNING_REFUSAL = (
    "A managed warehouse run is already in progress for this project's models. Try again once it finishes."
)


def start_node_materialization(node: Node, *, resume: bool = True, triggered_by_id: int | None = None) -> None:
    """Start a one-off materialization workflow for a single node.

    Shared by node `materialize` and saved-query `run`.

    `resume=False` is for automatic callers, such as a repair triggered by read traffic. The run
    still starts, but a suspended node keeps its marker and its failure window, so request traffic
    cannot hold the circuit breaker open.

    `triggered_by_id` is the person who asked for this run, and only they are told if it fails.
    Callers with no person behind them leave it unset.
    """
    if resume:
        # An explicit run is a request to try again, so it gets a fresh failure window.
        unsuspend_nodes([node], by="manual_run")
    inputs = MaterializeViewWorkflowInputs(
        team_id=node.team_id,
        dag_id=str(node.dag_id),
        node_id=str(node.id),
        manually_triggered_by_id=triggered_by_id,
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


def _get_node(team_id: int, node_id: UUID | str) -> Node:
    try:
        return Node.objects.select_related("team").get(team_id=team_id, id=node_id)
    except Node.DoesNotExist:
        raise MissingDagNodeError(f"Node {node_id} not found")


def _assert_user_can_run_nodes(node: Node, node_ids: set[str], user: User) -> None:
    # A run materializes every node it touches, so it needs the same edit and data access checks as
    # enabling materialization for each view.
    database = Database.create_for(team_id=node.team_id, user=user)
    access_control = UserAccessControl(user=user, team=node.team)
    saved_queries = DataWarehouseSavedQuery.objects.filter(
        team_id=node.team_id,
        node__id__in=node_ids,
    ).distinct()
    for saved_query in saved_queries:
        if not access_control.check_access_level_for_object(saved_query, "editor"):
            raise MaterializationForbiddenError(RELATED_RUN_EDIT_ACCESS_REFUSAL)
        assert_user_can_read_query(saved_query.query, node.team_id, user, database=database)


def _related_node_ids(
    node: Node,
    *,
    direction: MaterializationRunDirection | str,
    user: User,
    hidden_types: frozenset[str],
) -> set[str]:
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

    _assert_user_can_run_nodes(node, node_ids, user)
    return node_ids


def run_related_node_materializations(
    team_id: int,
    node_id: UUID | str,
    *,
    direction: MaterializationRunDirection | str,
    user: User,
    hidden_types: frozenset[str] = frozenset(),
) -> list[str]:
    node = _get_node(team_id, node_id)
    node_ids = _related_node_ids(node, direction=direction, user=user, hidden_types=hidden_types)

    # The workflow skips suspended nodes, so an explicit run must resume every selected node first.
    unsuspend_nodes(Node.objects.filter(team_id=node.team_id, id__in=node_ids), by="manual_run")

    inputs = ExecuteDAGInputs(
        team_id=node.team_id,
        dag_id=str(node.dag_id),
        node_ids=sorted(node_ids),
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
    return sorted(node_ids)


def run_trino_node_materializations(
    team_id: int,
    node_id: UUID | str,
    *,
    direction: MaterializationRunDirection | str | None,
    user: User,
    full_refresh: bool = False,
    hidden_types: frozenset[str] = frozenset(),
) -> list[str]:
    """Build the node, and optionally its upstreams or downstreams, on the managed warehouse only.

    Runs the same managed_warehouse_only DAG run as the scheduled Trino shadow, so ClickHouse is not
    touched. Refuses while any Trino run of the DAG is in progress, because two runs would write the
    same Trino tables at once.

    `full_refresh` drops the node's Trino watermark, and only after every refusal, including losing the
    race for the run slot, so a refused run does not turn the next scheduled shadow into a full rebuild.
    The run starts a few seconds late, so the state changes commit before the workflow reads them.
    """
    node = _get_node(team_id, node_id)
    if not is_managed_warehouse_shadow_enabled(node.team):
        raise ManagedWarehouseUnavailableError(MANAGED_WAREHOUSE_UNAVAILABLE_REFUSAL)
    if direction:
        node_ids = _related_node_ids(node, direction=direction, user=user, hidden_types=hidden_types)
    else:
        node_ids = {str(node.id)}
        # The managed warehouse reads source tables without the caller's access control, so check it here.
        _assert_user_can_run_nodes(node, node_ids, user)

    dag_id = str(node.dag_id)
    temporal = sync_connect()
    inputs = ExecuteDAGInputs(
        team_id=node.team_id,
        dag_id=dag_id,
        node_ids=sorted(node_ids),
        managed_warehouse_only=True,
        shadow=True,
        manually_triggered_by_id=user.pk,
    )
    # The scheduled shadow guards overlap only per tier, by its fixed id, so ask Temporal about every tier.
    running = asyncio.run(temporal.count_workflows(query=trino_runs_of_dag_query(dag_id)))
    if running.count > 0:
        raise MaterializationAlreadyRunningError(TRINO_RUN_ALREADY_RUNNING_REFUSAL)

    # Take the run slot before changing any state, so a run that loses the race for it changes nothing. The
    # start is delayed so that the changes below commit before the workflow reads them.
    try:
        handle = asyncio.run(
            temporal.start_workflow(
                "data-modeling-execute-dag",
                asdict(inputs),
                # A fixed id makes Temporal refuse a second manual run that slipped past the count above.
                id=manual_trino_workflow_id(dag_id),
                task_queue=str(settings.DATA_MODELING_TASK_QUEUE),
                id_conflict_policy=WorkflowIDConflictPolicy.FAIL,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                execution_timeout=TRINO_SHADOW_RUN_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=1),
                start_delay=MANUAL_TRINO_RUN_START_DELAY,
            )
        )
    except WorkflowAlreadyStartedError:
        raise MaterializationAlreadyRunningError(TRINO_RUN_ALREADY_RUNNING_REFUSAL)

    try:
        with transaction.atomic():
            if full_refresh and node.saved_query is not None:
                clear_incremental_state(node.saved_query, scope=TRINO_INCREMENTAL_SCOPE)
            unsuspend_nodes(
                Node.objects.filter(team_id=node.team_id, id__in=node_ids),
                by="manual_run",
                engine=DataModelingJobEngine.MANAGED_WAREHOUSE,
            )
    except Exception:
        # The run would otherwise start on state the caller did not ask for, while the caller sees an error.
        asyncio.run(handle.terminate("Could not prepare the models for the run"))
        raise
    return sorted(node_ids)


def is_saved_query_on_v2_schedule(saved_query: DataWarehouseSavedQuery) -> bool:
    """Whether the saved query's DAG already runs on a v2 schedule.

    Keys on the Temporal source of truth (get_v2_saved_query_ids), not the feature flag, since a
    team can be schedule-migrated without being flagged.
    """
    return saved_query.id in get_v2_saved_query_ids([saved_query.id])


class SavedQueryNotFoundError(Exception):
    """Raised by ``run_saved_query_materialization`` when the saved query no longer resolves."""


class SavedQueryNotOnV2ScheduleError(Exception):
    """Raised by ``run_saved_query_materialization`` when the saved query still runs on the older
    per-query schedule, whose frozen workflow lacks what the caller needs from a materialization."""


def run_saved_query_materialization(team_id: int, saved_query_id: UUID | str) -> None:
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
    materialize_saved_query(saved_query)


def materialize_saved_query(
    saved_query: DataWarehouseSavedQuery, *, resume: bool = True, triggered_by_id: int | None = None
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
    start_node_materialization(node, resume=resume, triggered_by_id=triggered_by_id)
    return node.id
