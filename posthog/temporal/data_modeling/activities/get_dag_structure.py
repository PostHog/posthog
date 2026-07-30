import dataclasses

from temporalio import activity

from posthog.models import Team
from posthog.ph_client import feature_enabled_or_false
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.logger import get_logger

from products.data_modeling.backend.facade.models import DataModelingJobEngine, Edge, Node, NodeType

from .utils import is_node_suspended

LOGGER = get_logger(__name__)

SUSPENSION_ENFORCEMENT_FLAG = "data-modeling-suspend-failing-nodes"


def _is_suspension_enforced(team_id: int) -> bool:
    try:
        team = Team.objects.only("organization_id").get(id=team_id)
        return feature_enabled_or_false(
            SUSPENSION_ENFORCEMENT_FLAG,
            str(team_id),
            groups={"organization": str(team.organization_id), "project": str(team_id)},
            group_properties={"organization": {"id": str(team.organization_id)}, "project": {"id": str(team_id)}},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    except Exception:
        LOGGER.warning("Failed to evaluate suspension enforcement flag; treating as disabled", team_id=team_id)
        return False


@dataclasses.dataclass
class GetDAGStructureInputs:
    """Inputs for retrieving a DAG's structure."""

    team_id: int
    dag_id: str


# TODO(andrew): make this a property / function on the actual DAG record
# maybe DAG().orchestration_plan() or similar
@dataclasses.dataclass
class DAG:
    """Structure of a DAG for orchestration.

    Attributes:
        nodes: list of node ids in the dag
        executable_nodes: list of node ids which must be executed in topological order (excludes source tables for example)
        edges: list of tuples of source node id and target node id
        ephemeral_nodes: list of node ids that are ephemeral views (no materialization needed)
    """

    nodes: list[str]
    executable_nodes: list[str]
    edges: list[tuple[str, str]]
    ephemeral_nodes: list[str] = dataclasses.field(default_factory=list)
    suspended_nodes: dict[str, list[str]] = dataclasses.field(default_factory=dict)


@database_sync_to_async_pool
def _get_dag_structure_async(team_id: int, dag_id: str) -> DAG:
    """Retrieve all nodes and edges for a DAG from the database."""
    nodes = Node.objects.filter(team_id=team_id, dag_id=dag_id)
    executable_nodes = nodes.filter(type__in=[NodeType.VIEW, NodeType.MAT_VIEW, NodeType.ENDPOINT])
    ephemeral_nodes = executable_nodes.filter(type=NodeType.VIEW)
    edges = (
        Edge.objects.prefetch_related("source", "target")
        .filter(team_id=team_id, dag_id=dag_id)
        .exclude(source__type=NodeType.TABLE)
    )
    if _is_suspension_enforced(team_id):
        suspended_nodes = {
            engine.value: [str(n.id) for n in executable_nodes if is_node_suspended(n, engine)]
            for engine in DataModelingJobEngine
        }
    else:
        suspended_nodes = {engine.value: [] for engine in DataModelingJobEngine}
    # ids are uuid objects by default. primitives are probably better
    return DAG(
        nodes=[str(n.id) for n in nodes],
        executable_nodes=[str(n.id) for n in executable_nodes],
        ephemeral_nodes=[str(n.id) for n in ephemeral_nodes],
        edges=[(str(e.source.id), str(e.target.id)) for e in edges],
        suspended_nodes=suspended_nodes,
    )


@activity.defn
async def get_dag_structure_activity(inputs: GetDAGStructureInputs) -> DAG:
    """Retrieve the structure of a DAG for orchestration."""
    logger = LOGGER.bind()
    logger.info("Retrieving DAG structure", team_id=inputs.team_id, dag_id=inputs.dag_id)
    dag_structure = await _get_dag_structure_async(inputs.team_id, inputs.dag_id)
    logger.info(
        "Retrieved DAG structure",
        team_id=inputs.team_id,
        dag_id=inputs.dag_id,
        num_nodes=len(dag_structure.nodes),
        num_executable_nodes=len(dag_structure.executable_nodes),
        num_edges=len(dag_structure.edges),
    )
    return dag_structure
