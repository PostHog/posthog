from collections.abc import Sequence

from django.db import transaction

import structlog

from posthog.models import Team

from products.data_modeling.backend.logic.saved_query_dag_sync import lineage_database, replace_incoming_edges
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.edge import CycleDetectionError
from products.data_modeling.backend.models.modeling import get_parents_from_model_query
from products.data_modeling.backend.models.node import Node, NodeType

logger = structlog.get_logger(__name__)


def sync_notebook_table_to_dag(
    team_id: int,
    table_name: str,
    warehouse_table_id: str,
    upstream_queries: Sequence[str],
    notebook_short_id: str,
    notebook_node_id: str,
) -> list[str]:
    """Put a table that a notebook cell saved into the default DAG, with edges from what the cell read.

    The node is a TABLE node under the table's own name. That is the node a view that reads the
    table resolves to, so its readers become its downstream edges with no extra work. The incoming
    edges come from the HogQL queries upstream of the cell. The DAG can't run a notebook, so the
    node stays a source for scheduling.

    Returns the dependency names that resolved to no node.
    """
    team = Team.objects.get(id=team_id)
    dag = DAG.get_or_create_default(team)
    database = lineage_database(team)

    dependencies: set[str] = set()
    parse_errors: list[str] = []
    for query in upstream_queries:
        try:
            dependencies |= get_parents_from_model_query(team, table_name, query, database=database)
        except Exception as e:
            parse_errors.append(str(e))
    # A cell that reads the table it writes would point the node at itself.
    dependencies.discard(table_name)

    with transaction.atomic():
        node, _ = Node.objects.get_or_create(
            team=team,
            dag=dag,
            name=table_name,
            type=NodeType.TABLE,
            saved_query=None,
            metric_id=None,
        )
        node.properties = {
            **(node.properties if isinstance(node.properties, dict) else {}),
            "origin": "warehouse",
            "warehouse_table_id": warehouse_table_id,
            "notebook": {"short_id": notebook_short_id, "node_id": notebook_node_id},
        }
        node.clear_lineage_markers()
        unresolved: list[str] = []
        try:
            unresolved = replace_incoming_edges(
                node,
                sorted(dependencies),
                team=team,
                dag=dag,
                database=database,
                on_unresolved="skip",
            )
        except CycleDetectionError as e:
            # The cell reads a view that reads this table. Keep the edges from the last good sync.
            parse_errors.append(str(e))
        if parse_errors:
            node.mark_lineage_sync_failed("; ".join(parse_errors))
        elif unresolved:
            node.mark_lineage_unresolved(unresolved)
        node.save(update_fields=["properties", "updated_at"])

    logger.info(
        "notebook_table_dag_synced",
        team_id=team_id,
        node_id=str(node.id),
        dependency_count=len(dependencies),
        unresolved_count=len(unresolved),
        failed=bool(parse_errors),
    )
    return unresolved
