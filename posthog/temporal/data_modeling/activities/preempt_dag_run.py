import dataclasses

from structlog import get_logger
from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async
from posthog.temporal.common.client import async_connect

from products.data_warehouse.backend.models import DataModelingJob
from products.data_warehouse.backend.models.data_modeling_job import DataModelingJobStatus

LOGGER = get_logger(__name__)

PREEMPTED_ERROR = "Preempted: a new DAG run started before this job completed"


@dataclasses.dataclass
class PreemptDAGRunInputs:
    team_id: int
    dag_id: str


@database_sync_to_async
def _get_running_jobs_for_dag(team_id: int, dag_id: str) -> list[DataModelingJob]:
    """Find RUNNING DataModelingJob records belonging to a previous run of this DAG.

    Child workflow IDs follow the pattern `materialize-view-{dag_id}-{node_id}-{timestamp}`,
    so we can match jobs by their workflow_id prefix.
    """
    return list(
        DataModelingJob.objects.filter(
            team_id=team_id,
            status=DataModelingJobStatus.RUNNING,
            workflow_id__startswith=f"materialize-view-{dag_id}-",
        )
    )


@database_sync_to_async
def _mark_jobs_as_preempted(job_ids: list[str]) -> int:
    return DataModelingJob.objects.filter(id__in=job_ids, status=DataModelingJobStatus.RUNNING).update(
        status=DataModelingJobStatus.FAILED,
        rows_materialized=0,
        error=PREEMPTED_ERROR,
    )


@activity.defn
async def preempt_dag_run_activity(inputs: PreemptDAGRunInputs) -> None:
    """Preempt a previous run of the same DAG by cancelling its parent workflow and marking jobs as failed.

    Cancelling the parent ExecuteDAGWorkflow cascades to all child MaterializeViewWorkflows
    (via ParentClosePolicy.REQUEST_CANCEL), which avoids a race where new children could be
    spawned after individual child cancellation.
    """
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    running_jobs = await _get_running_jobs_for_dag(inputs.team_id, inputs.dag_id)
    if not running_jobs:
        await logger.adebug("No previous DAG run to preempt")
        return

    await logger.ainfo(
        f"Preempting previous DAG run: found {len(running_jobs)} running jobs",
        dag_id=inputs.dag_id,
    )
    # collect unique parent workflow IDs — cancelling the parent cascades to all children
    parent_workflow_ids = {job.parent_workflow_id for job in running_jobs if job.parent_workflow_id}
    job_ids = [str(job.id) for job in running_jobs]
    # mark all running jobs as preempted
    updated_count = await _mark_jobs_as_preempted(job_ids)
    await logger.ainfo(f"Marked {updated_count} jobs as preempted", dag_id=inputs.dag_id)
    # request cancellation of parent workflows — this cascades to all children
    if parent_workflow_ids:
        try:
            temporal = await async_connect()
            for workflow_id in parent_workflow_ids:
                try:
                    handle = temporal.get_workflow_handle(workflow_id)
                    await handle.cancel()
                    await logger.ainfo(f"Requested cancellation of parent workflow {workflow_id}")
                except Exception as e:
                    # workflow may have already completed — that's fine
                    await logger.awarning(f"Could not cancel parent workflow {workflow_id}: {str(e)}")
        except Exception as e:
            capture_exception(e)
            await logger.aexception(f"Failed to connect to Temporal for workflow cancellation: {str(e)}")
