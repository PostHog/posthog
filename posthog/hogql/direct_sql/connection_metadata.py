from typing import TYPE_CHECKING

from django.db.models import Q
from django.utils import timezone

from posthog.exceptions_capture import capture_exception

if TYPE_CHECKING:
    from posthog.hogql.direct_sql.adapter import DirectSQLAdapter

    from posthog.models.team import Team

    from products.warehouse_sources.backend.facade.models import ExternalDataSource


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
        # Conditional update: only write if still empty so concurrent first-queries don't race
        # to persist (the second write is idempotent but wastes a remote-DB connection).
        # Match both None and {} — the field default is {}, but NULL is possible on older rows.
        type(source).objects.filter(pk=source.pk).filter(
            Q(connection_metadata__isnull=True) | Q(connection_metadata={})
        ).update(connection_metadata=metadata, updated_at=timezone.now())
    except Exception as error:
        capture_exception(error)
