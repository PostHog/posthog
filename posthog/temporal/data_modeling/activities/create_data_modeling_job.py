import dataclasses

from structlog import get_logger
from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.sync import database_sync_to_async_pool
from posthog.temporal.data_modeling.activities.utils import bind_data_modeling_log_context

from products.data_modeling.backend.facade.models import DataModelingJob, DataModelingJobEngine, Node

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class CreateDataModelingJobInputs:
    team_id: int
    node_id: str
    dag_id: str
    engine: str = DataModelingJobEngine.CLICKHOUSE
    parent_workflow_id: str | None = None


@dataclasses.dataclass(frozen=True, kw_only=True)
class CreatedDataModelingJob:
    job_id: str
    saved_query_id: str | None


@database_sync_to_async_pool
def _create_data_modeling_job(
    inputs: CreateDataModelingJobInputs, workflow_id: str, workflow_run_id: str
) -> CreatedDataModelingJob:
    node = Node.objects.prefetch_related("saved_query").get(
        id=inputs.node_id, team_id=inputs.team_id, dag_id=inputs.dag_id
    )
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
    return CreatedDataModelingJob(
        job_id=str(job.id),
        saved_query_id=str(node.saved_query.id) if node.saved_query else None,
    )


@activity.defn
async def create_data_modeling_job_activity(inputs: CreateDataModelingJobInputs) -> str:
    """Create a DataModelingJob record in RUNNING status."""
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    workflow_id = activity.info().workflow_id
    workflow_run_id = activity.info().workflow_run_id

    # Will always be defined if this activity was started by a workflow
    assert workflow_id
    assert workflow_run_id

    created = await _create_data_modeling_job(inputs, workflow_id, workflow_run_id)
    if created.saved_query_id is not None:
        bind_data_modeling_log_context(inputs.team_id, created.saved_query_id)
    await logger.ainfo(f"Created DataModelingJob {created.job_id} for node {inputs.node_id}")
    return created.job_id
