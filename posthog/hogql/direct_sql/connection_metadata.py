from typing import TYPE_CHECKING

from posthog.exceptions_capture import capture_exception

if TYPE_CHECKING:
    from posthog.hogql.direct_sql.adapter import DirectSQLAdapter

    from posthog.models.team import Team

    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource


def hydrate_and_persist_connection_metadata(
    source: "ExternalDataSource", adapter: "DirectSQLAdapter", team: "Team"
) -> None:
    """Cache a synced source's connection metadata on its first successful direct query.

    Pure-direct sources are populated at creation, so they are skipped here; synced sources start
    empty and hydrate on first query. Discovery failures are swallowed — the printer falls back to
    static allowlists when metadata is absent.
    """
    if source.is_direct_query or source.connection_metadata:
        return

    # Best-effort cache write: neither discovery nor the save may fail a query whose results are
    # already computed. A failed save just leaves the metadata empty for the next query to retry.
    try:
        metadata = adapter.fetch_connection_metadata(source, team)
        if not metadata:
            return
        source.connection_metadata = metadata
        source.save(update_fields=["connection_metadata", "updated_at"])
    except Exception as error:
        capture_exception(error)
