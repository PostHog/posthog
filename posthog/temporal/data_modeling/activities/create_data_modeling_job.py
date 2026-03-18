import dataclasses

from structlog import get_logger
from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.sync import database_sync_to_async

from products.data_modeling.backend.models import Node

# TODO(andrew): migrate/recreate this model to data_modeling app
from products.data_warehouse.backend.models import DataModelingJob

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class CreateDataModelingJobInputs:
    team_id: int
    node_id: str
    dag_id: str


@database_sync_to_async
def _create_data_modeling_job(inputs: CreateDataModelingJobInputs, workflow_id: str, workflow_run_id: str) -> str:
    node = Node.objects.prefetch_related("saved_query").get(
        id=inputs.node_id, team_id=inputs.team_id, dag_id=inputs.dag_id
    )
    job = DataModelingJob.objects.create(
        team_id=inputs.team_id,
        saved_query=node.saved_query,
        status=DataModelingJob.Status.RUNNING,
        workflow_id=workflow_id,
        workflow_run_id=workflow_run_id,
        created_by_id=node.saved_query.created_by_id if node.saved_query else None,
    )
    return str(job.id)


@activity.defn
async def create_data_modeling_job_activity(inputs: CreateDataModelingJobInputs) -> str:
    """Create a DataModelingJob record in RUNNING status."""
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    workflow_id = activity.info().workflow_id
    workflow_run_id = activity.info().workflow_run_id

    job_id = await _create_data_modeling_job(inputs, workflow_id, workflow_run_id)
    await logger.ainfo(f"Created DataModelingJob {job_id} for node {inputs.node_id}")
    return job_id
