import asyncio
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from uuid import UUID

from django.conf import settings

import structlog
from temporalio.common import RetryPolicy, WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from posthog.temporal.common.client import sync_connect
from posthog.temporal.data_modeling.run_workflow import RunWorkflowInputs, Selector
from posthog.temporal.data_modeling.workflows.materialize_view import MaterializeViewWorkflowInputs

from products.data_modeling.backend.logic.node_suspension import resume_nodes
from products.data_modeling.backend.models import Node
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.schedule import get_v2_saved_query_ids

logger = structlog.get_logger(__name__)


def start_node_materialization(node: Node, *, is_v2: bool) -> None:
    """Start a one-off materialization workflow for a single node.

    Shared by node `materialize` and saved-query `run` so the v1/v2 dispatch lives in one place.
    """
    # An explicit run is a request to try again, so it gets a fresh failure window.
    resume_nodes([node], by="manual_run")
    if is_v2:
        inputs: MaterializeViewWorkflowInputs | RunWorkflowInputs = MaterializeViewWorkflowInputs(
            team_id=node.team_id,
            dag_id=str(node.dag_id),
            node_id=str(node.id),
        )
        workflow_name = "data-modeling-materialize-view"
        workflow_id = f"materialize-view-{node.id}"
    else:
        inputs = RunWorkflowInputs(
            team_id=node.team_id,
            select=[Selector(label=str(node.saved_query_id), ancestors=0, descendants=0)],
        )
        workflow_name = "data-modeling-run"
        # Mirror the scheduled-run id shape ({saved_query_id}-{iso timestamp}) so
        # resolve_log_source can recover the saved query id and the run's logs show up
        # in the materialization history UI.
        workflow_id = f"{node.saved_query_id}-{datetime.now(UTC).isoformat()}"

    temporal = sync_connect()
    asyncio.run(
        temporal.start_workflow(
            workflow_name,
            asdict(inputs),
            id=workflow_id,
            task_queue=str(settings.DATA_MODELING_TASK_QUEUE),
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=10),
                maximum_interval=timedelta(seconds=60),
                maximum_attempts=3,
                non_retryable_error_types=["NondeterminismError", "CancelledError"],
            ),
        )
    )


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


def materialize_saved_query(saved_query: DataWarehouseSavedQuery) -> None:
    """Materialize the saved query's backing node via the v2 workflow.

    Fire a single materialization — don't fan out over duplicate-DAG nodes, or two workers race to
    write the same backing table.
    """
    node = Node.objects.filter(saved_query_id=saved_query.id).first()
    if node is None:
        # v2 was already confirmed, so a node should exist; a missing one is a data inconsistency.
        # Skip rather than fall back to the v1 schedule, which no longer exists on a v2 team.
        logger.warning("materialize_saved_query_missing_node", saved_query_id=str(saved_query.id))
        return
    start_node_materialization(node, is_v2=True)
