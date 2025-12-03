import dataclasses
from collections import defaultdict

from temporalio import activity

from posthog.sync import database_sync_to_async
from posthog.temporal.common.logger import get_logger

from products.data_modeling.backend.models import Edge, Node, NodeType

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class GetDAGStructureInputs:
    """Inputs for retrieving a DAG's structure."""

    team_id: int
    dag_id: str


@dataclasses.dataclass
class DAG:
    """Structure of a DAG for orchestration.

    Attributes:
        node_set: set of node ids in the dag
        executable_node_set: set of node ids which must be executed (excludes source tables for example)
        edge_lookup: map from target_id to a set of source_id where target depends on source
    """

    node_set: set[str]
    executable_node_set: set[str]
    edge_lookup: dict


@database_sync_to_async
def _get_dag_structure_async(team_id: int, dag_id: str) -> DAG:
    """Retrieve all nodes and edges for a DAG from the database."""
    nodes = Node.objects.filter(team_id=team_id, dag_id=dag_id)
    executable_nodes = nodes.filter(type__in=[NodeType.VIEW, NodeType.MAT_VIEW])
    edges = Edge.objects.prefetch_related("source", "target").filter(
        team_id=team_id, dag_id=dag_id, source__type__not_in=[NodeType.TABLE]
    )

    node_set = set(nodes.values_list("id", flat=True))
    executable_node_set = set(executable_nodes.values_list("id", flat=True))
    edge_lookup = defaultdict(set)
    for e in edges:
        edge_lookup[e.target.id].add(e.source.id)

    return DAG(
        node_set=node_set,
        executable_node_set=executable_node_set,
        edge_lookup=edge_lookup,
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
        num_nodes=len(dag_structure.node_set),
        num_executable_nodes=len(dag_structure.executable_node_set),
        num_edges=len(dag_structure.edge_lookup),
    )

    return dag_structure
