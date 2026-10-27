"""Whether a sync is loading again a table that a saved query reads."""

from datetime import datetime
from uuid import UUID

from products.warehouse_sources.backend.facade.api import tables_being_replaced

from ..models.edge import Edge
from ..models.node import Node, NodeType
from .saved_query_reads import WAREHOUSE_TABLE_ID_PROPERTY


def _synced_tables_read(team_id: int, saved_query_id: UUID | str) -> dict[UUID, str]:
    """The synced tables this saved query reads, directly or through views that are not materialized.

    The walk stops at a materialized view, because a query reads its stored table, and that table
    keeps its previous complete data until the view itself materializes again.
    """
    frontier = {
        str(node_id)
        for node_id in Node.objects.filter(team_id=team_id, saved_query_id=saved_query_id).values_list("id", flat=True)
    }
    visited = set(frontier)
    names_by_table_id: dict[UUID, str] = {}
    while frontier:
        source_ids = Edge.objects.filter(team_id=team_id, target_id__in=frontier).values_list("source_id", flat=True)
        sources = Node.objects.filter(team_id=team_id, id__in=source_ids).exclude(id__in=visited)
        frontier = set()
        for node_id, node_type, name, properties in sources.values_list("id", "type", "name", "properties"):
            visited.add(str(node_id))
            if node_type == NodeType.VIEW:
                frontier.add(str(node_id))
            elif node_type == NodeType.TABLE and (table_id := (properties or {}).get(WAREHOUSE_TABLE_ID_PROPERTY)):
                names_by_table_id[UUID(str(table_id))] = name
    return names_by_table_id


def upstream_tables_being_replaced(team_id: int, saved_query_id: UUID | str, *, started_after: datetime) -> list[str]:
    """The names of the synced tables this saved query reads that a running sync is loading again from empty."""
    names_by_table_id = _synced_tables_read(team_id, saved_query_id)
    replaced = tables_being_replaced(team_id, names_by_table_id.keys(), started_after=started_after)
    return sorted(names_by_table_id[table_id] for table_id in replaced)
