import datetime as dt
import dataclasses

from django.db import transaction

from celery import current_app
from structlog import get_logger
from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async_pool

from products.data_modeling.backend.facade.models import (
    DataModelingJob,
    DataModelingJobEngine,
    DataModelingJobStatus,
    Node,
)

from .utils import clear_node_suspension, update_node_system_properties

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class SucceedMaterializationInputs:
    team_id: int
    node_id: str
    dag_id: str
    job_id: str
    row_count: int
    duration_seconds: float
    update_node: bool = True


@database_sync_to_async_pool
def _succeed_node_and_data_modeling_job(inputs: SucceedMaterializationInputs):
    node = None
    if inputs.update_node:
        with transaction.atomic():
            node = Node.objects.select_for_update().get(id=inputs.node_id, team_id=inputs.team_id, dag_id=inputs.dag_id)
            status = DataModelingJobStatus.COMPLETED
            update_node_system_properties(
                node,
                status=status,
                job_id=inputs.job_id,
                rows=inputs.row_count,
                duration_seconds=inputs.duration_seconds,
            )
            clear_node_suspension(node, engine=DataModelingJobEngine.CLICKHOUSE)
            node.save()

    job = DataModelingJob.objects.get(id=inputs.job_id)

    # if the job is already in a terminal state, don't overwrite it
    if job.status in (DataModelingJobStatus.FAILED, DataModelingJobStatus.CANCELLED, DataModelingJobStatus.COMPLETED):
        return node, job

    job.status = DataModelingJobStatus.COMPLETED
    job.rows_materialized = inputs.row_count
    job.last_run_at = dt.datetime.now(dt.UTC)
    job.error = None
    job.save()

    if node is not None and node.saved_query_id is not None:
        saved_query_id = str(node.saved_query_id)
        team_id = inputs.team_id
        transaction.on_commit(lambda: _enqueue_custom_property_sync(team_id, saved_query_id))
    return node, job


def _enqueue_custom_property_sync(team_id: int, saved_query_id: str) -> None:
    try:
        current_app.send_task(
            "customer_analytics.process_custom_property_sync",
            kwargs={"team_id": team_id, "saved_query_id": saved_query_id},
        )
    except Exception as e:
        LOGGER.exception("custom_property_sync_enqueue_failed", team_id=team_id, saved_query_id=saved_query_id)
        capture_exception(e)


@activity.defn
async def succeed_materialization_activity(inputs: SucceedMaterializationInputs) -> None:
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    node, job = await _succeed_node_and_data_modeling_job(inputs)

    await logger.ainfo(
        f"Succeeded materialization job: node={inputs.node_id} dag={inputs.dag_id} job={job.id} "
        f"workflow={job.workflow_id} workflow_run={job.workflow_run_id}"
    )
