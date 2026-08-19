"""Contract-shaped reads of saved queries for consumers outside this product."""

from collections.abc import Iterable
from uuid import UUID

from ..facade.contracts import SavedQuerySummary
from ..models.datawarehouse_saved_query import DataWarehouseSavedQuery
from ..models.node import Node


def get_saved_query_summary(team_id: int, saved_query_id: UUID | str) -> SavedQuerySummary | None:
    """The saved query only if it still resolves, else None.

    Soft-deleted rows are excluded because ``soft_delete`` rewrites ``name`` to a tombstone -- a
    caller holding a stored reference must not query that name.
    """
    saved_query = (
        DataWarehouseSavedQuery.objects.filter(team_id=team_id, id=saved_query_id).exclude(deleted=True).first()
    )
    if saved_query is None:
        return None
    return SavedQuerySummary(
        id=str(saved_query.id),
        team_id=saved_query.team_id,
        name=saved_query.name,
        last_run_at=saved_query.last_run_at,
    )


def get_saved_query_ids_for_nodes(team_id: int, node_ids: Iterable[UUID | str]) -> list[str]:
    """The saved queries behind these DAG nodes. Source-table nodes have none and are dropped."""
    rows = Node.objects.filter(team_id=team_id, id__in=list(node_ids), saved_query__isnull=False).values_list(
        "saved_query_id", flat=True
    )
    return [str(saved_query_id) for saved_query_id in rows]
