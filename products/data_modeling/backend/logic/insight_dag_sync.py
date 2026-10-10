from collections import defaultdict
from collections.abc import Collection, Sequence
from typing import TYPE_CHECKING, cast

from django.db import transaction

from posthog.hogql.database.database import Database

from products.data_modeling.backend.facade.system_tables import DATA_MODELING_ALLOWED_SYSTEM_TABLES
from products.data_modeling.backend.logic.saved_query_dag_sync import replace_incoming_edges
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.node import INSIGHT_SHORT_ID_KEY, Node, NodeType

if TYPE_CHECKING:
    from posthog.models import Team

    from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery


def sync_insight_to_dag(
    team: "Team",
    insight_id: int,
    short_id: str,
    name: str,
    dependency_names: Sequence[str],
    database: Database | None = None,
) -> list[str]:
    """Create or update the insight's reader nodes in each dependency's DAG.

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

    if database is None:
        database = Database.create_for(
            team=team,
            bypass_warehouse_access_control=True,
            allowed_system_tables=DATA_MODELING_ALLOWED_SYSTEM_TABLES,
        )

    dependencies_by_dag: dict[DAG, list[str]] = defaultdict(list)
    placed_names: set[str] = set()
    view_nodes = Node.objects.filter(
        team=team, saved_query__name__in=dependency_names, saved_query__deleted=False
    ).select_related("dag", "saved_query")
    for view_node in view_nodes:
        dependency_name = cast("DataWarehouseSavedQuery", view_node.saved_query).name
        dependencies_by_dag[view_node.dag].append(dependency_name)
        placed_names.add(dependency_name)
    unplaced_names = set(dependency_names) - placed_names
    if unplaced_names:
        dependencies_by_dag[DAG.get_or_create_default(team)].extend(sorted(unplaced_names))

    unresolved: list[str] = []
    # The node is created inside the transaction too, so a resolution failure leaves no edge-less
    # node behind.
    with transaction.atomic():
        # Edges cannot cross DAGs, so each view's DAG needs its own reader node.
        for dag, names in sorted(dependencies_by_dag.items(), key=lambda entry: str(entry[0].id)):
            node, _ = Node.objects.get_or_create(
                team=team,
                dag=dag,
                insight_id=insight_id,
                defaults={"name": name, "type": NodeType.INSIGHT},
            )
            node.name = name
            node.properties[INSIGHT_SHORT_ID_KEY] = short_id
            missing = replace_incoming_edges(
                node,
                names,
                team=team,
                dag=dag,
                database=database,
                on_unresolved="skip",
            )

            node.clear_lineage_markers()
            if missing:
                node.mark_lineage_unresolved(missing)
            node.save(update_fields=["name", "properties"])
            unresolved.extend(missing)
        Node.objects.filter(team=team, insight_id=insight_id).exclude(
            dag_id__in=[dag.id for dag in dependencies_by_dag]
        ).delete()

    return sorted(set(unresolved))


def insight_node_ids(team_id: int) -> dict[int, list[str]]:
    """The team's insight nodes, keyed by the insight each one stands for."""
    rows = Node.objects.filter(team_id=team_id, type=NodeType.INSIGHT).values_list("insight_id", "id")
    ids: dict[int, list[str]] = defaultdict(list)
    for insight_id, node_id in rows:
        if insight_id is not None:
            ids[insight_id].append(str(node_id))
    return dict(ids)


def delete_insight_nodes(team_id: int, insight_ids: Collection[int]) -> int:
    """Delete the nodes of these insights, and their edges with them. Returns how many nodes went."""
    _, deleted_by_model = Node.objects.filter(team_id=team_id, insight_id__in=insight_ids).delete()
    return deleted_by_model.get(Node._meta.label, 0)
