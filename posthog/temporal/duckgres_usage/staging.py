"""Replace-window persistence for duckgres usage pulls.

Because acks only ever happen at UTC day boundaries, every pull's response
carries complete day-so-far totals for the whole un-acked window. Applying a
response is therefore a pure replace — delete the window's dates, insert the
response's rows, one transaction. Idempotent for a fixed response, and
memoryless across responses: the table's open-window state is a function of
the latest response only, so any bad write self-heals on the next pull.

Watermark subtlety: duckgres watermarks are bucket-START labels and ack
deletes `bucket_start <= watermark`, so our day-boundary acks are
`start_of_open_day - 1s` (23:59:59 of the last complete day). The window's
first date is derived as `(watermark_low + 1s).date()` — deriving from
`watermark_low.date()` would delete the already-acked previous day, which
duckgres will never re-serve.
"""

import datetime as dt

from django.db import transaction
from django.db.models import Q

import structlog

from posthog.ducklake.models import DuckgresDailyStorageUsage, DuckgresDailyUsage
from posthog.temporal.duckgres_usage.client import UsageResponse

logger = structlog.get_logger(__name__)


def replace_window(response: UsageResponse) -> int:
    """Replace the open window's mirror rows with the response's rows.

    Returns the number of rows written.
    """
    if response.watermark_high <= response.watermark_low:
        # Empty window (fresh cursor, or a pull racing right behind an ack).
        if response.rows:
            logger.warning(
                "duckgres_usage_rows_in_empty_window_skipped",
                watermark_low=response.watermark_low.isoformat(),
                row_count=len(response.rows),
            )
        return 0

    window_first = (response.watermark_low + dt.timedelta(seconds=1)).astimezone(dt.UTC).date()
    window_last = response.watermark_high.astimezone(dt.UTC).date()
    # Defensive union with the row dates: if duckgres's cursor regressed and
    # re-serves an already-acked day, its rows must replace ours rather than
    # collide with the unique key.
    row_dates = {row.date for row in response.rows} | {row.date for row in response.storage_rows}
    window = Q(date__gte=window_first, date__lte=window_last) | Q(date__in=row_dates)

    # BOTH families commit in this one transaction: duckgres's ack deletes
    # compute AND storage buckets atomically, so persisting one family and
    # acking would permanently destroy the other's un-persisted data.
    with transaction.atomic():
        DuckgresDailyUsage.objects.filter(window).delete()
        DuckgresDailyStorageUsage.objects.filter(window).delete()
        created = DuckgresDailyUsage.objects.bulk_create(
            DuckgresDailyUsage(
                date=row.date,
                organization_id=row.org_id,
                team_id=row.team_id,
                query_source=row.query_source,
                cpu=row.cpu,
                mem_gib=row.mem_gib,
                cpu_seconds=row.cpu_seconds,
                memory_seconds=row.memory_seconds,
            )
            for row in response.rows
        )
        created_storage = DuckgresDailyStorageUsage.objects.bulk_create(
            DuckgresDailyStorageUsage(
                date=row.date,
                organization_id=row.org_id,
                team_id=row.team_id,
                gib_seconds=row.gib_seconds,
            )
            for row in response.storage_rows
        )
    return len(created) + len(created_storage)
