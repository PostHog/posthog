import dataclasses

from structlog import get_logger
from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.sync import database_sync_to_async

from products.data_modeling.backend.models import Node
from products.data_warehouse.backend.models import DataModelingJob

from .utils import update_node_system_properties

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class FailMaterializationInputs:
    team_id: int
    node_id: str
    dag_id: str
    job_id: str
    error: str


@database_sync_to_async
def _fail_node_and_data_modeling_job(inputs: FailMaterializationInputs):
    node = Node.objects.get(id=inputs.node_id, team_id=inputs.team_id, dag_id=inputs.dag_id)
    update_node_system_properties(
        node,
        status="failed",
        job_id=inputs.job_id,
        error=inputs.error,
    )
    node.save()

    job = DataModelingJob.objects.get(id=inputs.job_id)
    job.status = DataModelingJob.Status.FAILED
    job.error = inputs.error
    job.save()
    return node, job


@activity.defn
async def fail_materialization_activity(inputs: FailMaterializationInputs) -> None:
    """Mark materialization as failed and update node properties."""
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    node, job = await _fail_node_and_data_modeling_job(inputs)

    await logger.aerror(
        f"Failed materialization job: node={node.id} dag={inputs.dag_id} job={job.id} "
        f"workflow={job.workflow_id} workflow_run={job.workflow_run_id} error={inputs.error}"
    )
