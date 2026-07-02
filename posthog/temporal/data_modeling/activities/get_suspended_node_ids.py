import dataclasses

from temporalio import activity

from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.logger import get_logger
from posthog.temporal.data_modeling.activities.utils import is_node_suspended

from products.data_modeling.backend.facade.models import Node

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class GetSuspendedNodeIDsInputs:
    team_id: int
    dag_id: str
    engine: str


@database_sync_to_async_pool
def _get_suspended_node_ids_async(team_id: int, dag_id: str, engine: str) -> list[str]:
    nodes = Node.objects.filter(team_id=team_id, dag_id=dag_id).only("id", "properties")
    return [str(node.id) for node in nodes if is_node_suspended(node, engine)]


@activity.defn
async def get_suspended_node_ids_activity(inputs: GetSuspendedNodeIDsInputs) -> list[str]:
    logger = LOGGER.bind()
    logger.info(
        "Retrieving suspended DAG nodes",
        team_id=inputs.team_id,
        dag_id=inputs.dag_id,
        engine=inputs.engine,
    )
    suspended_node_ids = await _get_suspended_node_ids_async(inputs.team_id, inputs.dag_id, inputs.engine)
    logger.info(
        "Retrieved suspended DAG nodes",
        team_id=inputs.team_id,
        dag_id=inputs.dag_id,
        engine=inputs.engine,
        num_suspended_nodes=len(suspended_node_ids),
    )
    return suspended_node_ids
