import dataclasses

from structlog import get_logger
from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async

from products.data_modeling.backend.models import Node
from products.data_warehouse.backend.models import DataModelingJob
from products.data_warehouse.backend.models.data_modeling_job import DataModelingJobStatus
from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery

from .utils import strip_hostname_from_error, update_node_system_properties

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class FailMaterializationInputs:
    team_id: int
    node_id: str
    dag_id: str
    job_id: str
    error: str
    cancelled: bool = False
    update_node: bool = True


@database_sync_to_async
def _fail_node_and_data_modeling_job(inputs: FailMaterializationInputs):
    # strip hostnames from error for user-facing storage while preserving original for logging
    sanitized_error = strip_hostname_from_error(inputs.error)

    node = None
    if inputs.update_node:
        node = Node.objects.get(id=inputs.node_id, team_id=inputs.team_id, dag_id=inputs.dag_id)
        status = DataModelingJobStatus.CANCELLED if inputs.cancelled else DataModelingJobStatus.FAILED
        update_node_system_properties(
            node,
            status=status,
            job_id=inputs.job_id,
            error=sanitized_error,
        )
        node.save()

    job = DataModelingJob.objects.get(id=inputs.job_id)

    # if the job is already in a terminal state, don't overwrite it — preserves the first error
    if job.status in (DataModelingJobStatus.FAILED, DataModelingJobStatus.CANCELLED, DataModelingJobStatus.COMPLETED):
        return node, job

    job.status = DataModelingJobStatus.CANCELLED if inputs.cancelled else DataModelingJobStatus.FAILED
    job.rows_materialized = 0
    job.error = sanitized_error
    job.save()

    return node, job


@database_sync_to_async
def _get_saved_query_for_job(job: DataModelingJob) -> DataWarehouseSavedQuery | None:
    if not job.saved_query_id:
        return None
    return DataWarehouseSavedQuery.objects.exclude(deleted=True).filter(id=job.saved_query_id).first()


@database_sync_to_async
def _pause_schedule_on_timeout(job: DataModelingJob, saved_query: DataWarehouseSavedQuery) -> None:
    from products.data_warehouse.backend.data_load.saved_query_service import pause_saved_query_schedule

    saved_query.sync_frequency_interval = None
    saved_query.save(update_fields=["sync_frequency_interval"])
    pause_saved_query_schedule(saved_query)
    # we can use this specific language in the error to add these jobs to the daily email digest later
    job.error = f"This materialized view sync schedule has been paused until you modify the query and reset the sync schedule. Error: {job.error}"
    job.save(update_fields=["error"])


@database_sync_to_async
def _revert_materialization_on_unknown_table(job: DataModelingJob, saved_query: DataWarehouseSavedQuery) -> None:
    saved_query.revert_materialization()
    # we can use this specific language in the error to add these jobs to the daily email digest later
    job.error = (
        f"This materialized view has been reverted to a view because it referenced an unknown table. Error: {job.error}"
    )
    job.save(update_fields=["error"])


@activity.defn
async def fail_materialization_activity(inputs: FailMaterializationInputs) -> None:
    """Mark materialization as failed and update node properties."""
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()
    _, job = await _fail_node_and_data_modeling_job(inputs)
    await logger.aerror(
        f"Failed materialization job: node={inputs.node_id} dag={inputs.dag_id} job={job.id} "
        f"workflow={job.workflow_id} workflow_run={job.workflow_run_id} error={inputs.error}"
    )
    # error-specific recovery: pause schedule on timeout, revert materialization on unknown table
    if not inputs.update_node:
        return
    error = inputs.error
    if "Timeout exceeded" not in error and "Unknown table" not in error:
        return
    try:
        saved_query = await _get_saved_query_for_job(job)
        if saved_query is None:
            return

        if "Timeout exceeded" in error:
            await logger.ainfo(
                f"Pausing schedule for node {inputs.node_id} due to timeout",
            )
            await _pause_schedule_on_timeout(job, saved_query)
        elif "Unknown table" in error:
            await logger.ainfo(
                f"Reverting materialization for node {inputs.node_id} due to unknown table reference",
            )
            await _revert_materialization_on_unknown_table(job, saved_query)
    except Exception as e:
        capture_exception(e)
        await logger.aexception(f"Failed to run error-specific recovery for node {inputs.node_id}: {str(e)}")
