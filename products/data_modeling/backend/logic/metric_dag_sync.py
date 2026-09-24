from collections.abc import Sequence
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction

import structlog

from posthog.hogql.database.database import Database

from products.data_modeling.backend.facade.system_tables import DATA_MODELING_ALLOWED_SYSTEM_TABLES
from products.data_modeling.backend.logic.saved_query_dag_sync import replace_incoming_edges
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.node import Node, NodeType

if TYPE_CHECKING:
    from posthog.models import Team

logger = structlog.get_logger(__name__)


def sync_metric_to_dag(
    team: "Team",
    metric_id: UUID,
    name: str,
    dependency_names: Sequence[str],
    database: Database | None = None,
) -> list[str]:
    """Create or update the node for a data catalog metric and rebuild its incoming edges.

    A metric is a leaf: it reads tables and views and nothing reads it, so nothing schedulable
    changes and no reconcile follows. A dependency name that resolves to no node is skipped and
    recorded on the node, because one renamed table should not cost the metric every other edge.
    Those names are returned as well, so a caller reporting many metrics can separate a metric that
    synced with every edge from one that is missing some.

    `database` lets a caller syncing many metrics for one team build the schema once.
    """
    dag = DAG.get_or_create_default(team)

    if database is None:
        database = Database.create_for(
            team=team,
            bypass_warehouse_access_control=True,
            allowed_system_tables=DATA_MODELING_ALLOWED_SYSTEM_TABLES,
        )

    # The node is created inside the transaction too, so a resolution failure leaves no edge-less
    # node behind. A failure the caller catches recreates it carrying the degraded marker.
    with transaction.atomic():
        node, _ = Node.objects.get_or_create(
            team=team,
            dag=dag,
            metric_id=metric_id,
            defaults={"name": name, "type": NodeType.METRIC},
        )
        node.name = name
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


def mark_metric_node_degraded(team: "Team", metric_id: UUID, name: str, error: str) -> None:
    """Record on the metric's node that its last lineage refresh failed, so the graph can say so."""
    dag = DAG.get_or_create_default(team)
    # Atomic so a failed marker save rolls the creation back too: a node committed without its
    # marker reads as a healthy leaf with no dependencies, which is the state this function exists
    # to prevent.
    with transaction.atomic():
        node, _ = Node.objects.get_or_create(
            team=team,
            dag=dag,
            metric_id=metric_id,
            defaults={"name": name, "type": NodeType.METRIC},
        )
        node.name = name
        node.mark_lineage_sync_failed(error)
        node.save(update_fields=["name", "properties"])


def delete_metric_node(team: "Team", metric_id: UUID) -> int:
    deleted, _ = Node.objects.filter(team=team, metric_id=metric_id).delete()
    return deleted
