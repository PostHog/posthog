import asyncio
from dataclasses import asdict
from datetime import timedelta
from uuid import uuid4

from django.conf import settings

import structlog
from temporalio.common import RetryPolicy

from posthog.temporal.common.client import sync_connect
from posthog.temporal.data_modeling.run_workflow import RunWorkflowInputs, Selector
from posthog.temporal.data_modeling.workflows.materialize_view import MaterializeViewWorkflowInputs

from products.data_modeling.backend.models import Node
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.schedule import get_v2_saved_query_ids

logger = structlog.get_logger(__name__)


def start_node_materialization(node: Node, *, is_v2: bool) -> None:
    """Start a one-off materialization workflow for a single node.

    Shared by node `materialize` and saved-query `run` so the v1/v2 dispatch lives in one place.
    """
    if is_v2:
        inputs: MaterializeViewWorkflowInputs | RunWorkflowInputs = MaterializeViewWorkflowInputs(
            team_id=node.team_id,
            dag_id=str(node.dag_id),
            node_id=str(node.id),
        )
        workflow_name = "data-modeling-materialize-view"
        workflow_id = f"materialize-view-{node.id}-{uuid4()}"
    else:
        inputs = RunWorkflowInputs(
            team_id=node.team_id,
            select=[Selector(label=str(node.saved_query_id), ancestors=0, descendants=0)],
        )
        workflow_name = "data-modeling-run"
        workflow_id = f"data-modeling-run-{node.id}-{uuid4()}"

    temporal = sync_connect()
    asyncio.run(
        temporal.start_workflow(
            workflow_name,
            asdict(inputs),
            id=workflow_id,
            task_queue=str(settings.DATA_MODELING_TASK_QUEUE),
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
