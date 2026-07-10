"""Replace-window persistence into the local duckgres usage mirror.

Because acks only ever happen at UTC day boundaries, every pull's response
carries complete day-so-far totals for the whole un-acked window. Applying a
response is therefore a pure replace — delete the window's dates, insert the
response's rows, one transaction. Idempotent for a fixed response, and
memoryless across responses: the mirror's open-window state is a function of
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

import structlog

from posthog.ducklake.models import DuckgresDailyStorageUsage, DuckgresDailyUsage
from posthog.temporal.duckgres_usage.client import UsageResponse

logger = structlog.get_logger(__name__)


def derive_window(watermark_low: dt.datetime, watermark_high: dt.datetime) -> tuple[dt.date, dt.date]:
    """The [first, last] UTC-date window whose rows a response may replace.

    Rows dated outside it are already-acked (below `window_first`) or beyond the
    served ceiling, and are never persisted — acked days are immutable. Deriving
    `window_first` from `watermark_low + 1s` (not `watermark_low.date()`) is what
    keeps the last acked day out of the window.
    """
    window_first = (watermark_low + dt.timedelta(seconds=1)).astimezone(dt.UTC).date()
    window_last = watermark_high.astimezone(dt.UTC).date()
    return window_first, window_last


def count_out_of_window_rows(response: UsageResponse) -> int:
    """Rows (either family) dated outside the replace window.

    A row outside the window means duckgres served data at or below its own
    cursor — a contract violation. `replace_window` drops these rather than
    mutate already-billed history; the caller alerts and withholds the ack so
    the ack can't delete the dropped rows' source buckets.
    """
    if response.watermark_high <= response.watermark_low:
        return 0
    first, last = derive_window(response.watermark_low, response.watermark_high)
    return sum(1 for row in response.rows if not first <= row.date <= last) + sum(
        1 for row in response.storage_rows if not first <= row.date <= last
    )


def replace_window(response: UsageResponse) -> int:
    """Replace the open window's mirror rows with the response's rows.

    Returns the number of rows written. Rows dated outside the window are dropped
    (see `count_out_of_window_rows`); the caller is responsible for alerting on
    and withholding the ack for them.
    """
    if response.watermark_high <= response.watermark_low:
        # Empty window (fresh cursor, or a pull racing right behind an ack).
        if response.rows or response.storage_rows:
            logger.warning(
                "duckgres_usage_rows_in_empty_window_skipped",
                watermark_low=response.watermark_low.isoformat(),
                row_count=len(response.rows) + len(response.storage_rows),
            )
        return 0

    window_first, window_last = derive_window(response.watermark_low, response.watermark_high)

    # Acked days are immutable: replace strictly within the window. Out-of-window
    # rows are dropped (the activity captures + withholds the ack for them).
    compute_rows = [row for row in response.rows if window_first <= row.date <= window_last]
    storage_rows = [row for row in response.storage_rows if window_first <= row.date <= window_last]

    # BOTH families commit in this one transaction: duckgres's ack deletes
    # compute AND storage buckets atomically, so persisting one family and
    # acking would permanently destroy the other's un-persisted data.
    with transaction.atomic():
        DuckgresDailyUsage.objects.filter(date__gte=window_first, date__lte=window_last).delete()
        DuckgresDailyStorageUsage.objects.filter(date__gte=window_first, date__lte=window_last).delete()
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
            for row in compute_rows
        )
        created_storage = DuckgresDailyStorageUsage.objects.bulk_create(
            DuckgresDailyStorageUsage(
                date=row.date,
                organization_id=row.org_id,
                team_id=row.team_id,
                gib_seconds=row.gib_seconds,
            )
            for row in storage_rows
        )
    return len(created) + len(created_storage)
