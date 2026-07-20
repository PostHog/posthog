import dataclasses

from structlog import get_logger
from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.sync import database_sync_to_async_pool

from products.data_modeling.backend.facade.models import DataModelingJob, DataModelingJobEngine, Node

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class CreateDataModelingJobInputs:
    team_id: int
    node_id: str
    dag_id: str
    engine: str = DataModelingJobEngine.CLICKHOUSE
    parent_workflow_id: str | None = None


@database_sync_to_async_pool
def _create_data_modeling_job(
    inputs: CreateDataModelingJobInputs, workflow_id: str, workflow_run_id: str
) -> str | None:
    try:
        node = Node.objects.prefetch_related("saved_query").get(
            id=inputs.node_id, team_id=inputs.team_id, dag_id=inputs.dag_id
        )
    except Node.DoesNotExist:
        # The node (or its DAG) was deleted between the DAG snapshot and this activity running —
        # both FKs cascade. There's nothing left to materialize, so treat it as an expected no-op
        # rather than raising, which would burn retries and page error tracking. The workflow
        # short-circuits gracefully when this returns None.
        return None
    job = DataModelingJob.objects.create(
        team_id=inputs.team_id,
        saved_query=node.saved_query,
        status=DataModelingJob.Status.RUNNING,
        engine=inputs.engine,
        workflow_id=workflow_id,
        workflow_run_id=workflow_run_id,
        parent_workflow_id=inputs.parent_workflow_id,
        created_by_id=node.saved_query.created_by_id if node.saved_query else None,
    )
    return str(job.id)


@activity.defn
async def create_data_modeling_job_activity(inputs: CreateDataModelingJobInputs) -> str | None:
    """Create a DataModelingJob record in RUNNING status.

    Returns None when the node no longer exists (deleted mid-run), signalling the workflow to
    skip materialization gracefully.
    """
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    workflow_id = activity.info().workflow_id
    workflow_run_id = activity.info().workflow_run_id

    # Will always be defined if this activity was started by a workflow
    assert workflow_id
    assert workflow_run_id

    job_id = await _create_data_modeling_job(inputs, workflow_id, workflow_run_id)
    if job_id is None:
        await logger.ainfo(f"Node {inputs.node_id} no longer exists, skipping job creation")
        return None
    await logger.ainfo(f"Created DataModelingJob {job_id} for node {inputs.node_id}")
    return job_id
