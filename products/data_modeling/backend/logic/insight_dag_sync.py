from collections.abc import Collection, Sequence
from typing import TYPE_CHECKING

from django.db import transaction

from posthog.hogql.database.database import Database

from products.data_modeling.backend.facade.system_tables import DATA_MODELING_ALLOWED_SYSTEM_TABLES
from products.data_modeling.backend.logic.saved_query_dag_sync import replace_incoming_edges
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.node import INSIGHT_SHORT_ID_KEY, Node, NodeType

if TYPE_CHECKING:
    from posthog.models import Team


def sync_insight_to_dag(
    team: "Team",
    insight_id: int,
    short_id: str,
    name: str,
    dependency_names: Sequence[str],
    database: Database | None = None,
) -> list[str]:
    """Create or update the node for an insight and rebuild its incoming edges.

    An insight is a leaf, like a metric: it reads tables and views and nothing reads it, so nothing
    schedulable changes and no reconcile follows. The caller passes only the warehouse tables and
    views the insight reads. An insight that reads none of them gets no node, because an isolated
    node per insight would bury the graph. A name that resolves to no node is skipped and recorded on
    the node, and those names are returned.

    `database` lets a caller syncing many insights for one team build the schema once.
    """
    if not dependency_names:
        delete_insight_nodes(team.pk, [insight_id])
        return []

    dag = DAG.get_or_create_default(team)

    if database is None:
        database = Database.create_for(
            team=team,
            bypass_warehouse_access_control=True,
            allowed_system_tables=DATA_MODELING_ALLOWED_SYSTEM_TABLES,
        )

    # The node is created inside the transaction too, so a resolution failure leaves no edge-less
    # node behind.
    with transaction.atomic():
        node, _ = Node.objects.get_or_create(
            team=team,
            dag=dag,
            insight_id=insight_id,
            defaults={"name": name, "type": NodeType.INSIGHT},
        )
        node.name = name
        node.properties[INSIGHT_SHORT_ID_KEY] = short_id
        unresolved = replace_incoming_edges(
            node,
            dependency_names,
            team=team,
            dag=dag,
            database=database,
            on_unresolved="skip",
        )

        node.clear_lineage_markers()
        if unresolved:
            node.mark_lineage_unresolved(unresolved)
        node.save(update_fields=["name", "properties"])

    return unresolved


def insight_node_ids(team_id: int) -> dict[int, str]:
    """The team's insight nodes, keyed by the insight each one stands for."""
    rows = Node.objects.filter(team_id=team_id, type=NodeType.INSIGHT).values_list("insight_id", "id")
    return {insight_id: str(node_id) for insight_id, node_id in rows if insight_id is not None}


def delete_insight_nodes(team_id: int, insight_ids: Collection[int]) -> int:
    """Delete the nodes of these insights, and their edges with them. Returns how many nodes went."""
    _, deleted_by_model = Node.objects.filter(team_id=team_id, insight_id__in=insight_ids).delete()
    return deleted_by_model.get(Node._meta.label, 0)
