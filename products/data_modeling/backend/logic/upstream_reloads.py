"""Whether a sync is loading again a table that a saved query reads."""

from datetime import datetime
from uuid import UUID

from products.warehouse_sources.backend.facade.api import tables_being_replaced

from .saved_query_reads import upstream_table_refs


def upstream_tables_being_replaced(team_id: int, saved_query_id: UUID | str, *, started_after: datetime) -> list[str]:
    """The names of the synced tables this saved query reads that a running sync is loading again from empty."""
    names_by_table_id = {
        UUID(ref.warehouse_table_id): ref.name
        for ref in upstream_table_refs(team_id, saved_query_id)
        if ref.warehouse_table_id is not None
    }
    replaced = tables_being_replaced(team_id, names_by_table_id.keys(), started_after=started_after)
    return sorted(names_by_table_id[table_id] for table_id in replaced)
