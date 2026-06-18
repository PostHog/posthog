from datetime import UTC, date, datetime, time

from django.conf import settings
from django.utils import timezone

from posthog.clickhouse.client import sync_execute
from posthog.ducklake.backfill_telemetry import BACKFILL_PARTITION_EVENT

from products.data_warehouse.backend.warehouse_sync.contracts import InitialBackfill, SyncError, WarehouseSyncStatusDTO

PARTITION_START = date(2019, 1, 1)
CAUGHT_UP_LAG_SECONDS = 2 * 24 * 60 * 60

# Latest event per partition_date for the telemetry team.
_QUERY = """
SELECT
    JSONExtractString(properties, 'partition_date') AS partition_date,
    argMax(JSONExtractString(properties, 'status'), timestamp) AS status,
    argMax(JSONExtractInt(properties, 'rows_exported'), timestamp) AS rows_exported,
    argMax(JSONExtractString(properties, 'error_message'), timestamp) AS error_message,
    max(timestamp) AS last_event_at
FROM events
WHERE team_id = %(team_id)s AND event = %(event)s
GROUP BY partition_date
"""


def _empty(now: datetime, state: str) -> WarehouseSyncStatusDTO:
    return WarehouseSyncStatusDTO(
        backend="dagster",
        state=state,
        fresh_through=None,
        lag_seconds=None,
        last_activity_at=None,
        initial_backfill=InitialBackfill(complete=False, progress_pct=None),
        total_rows_synced=None,
        error=None,
        updated_at=now,
    )


class DagsterBackfillStatusProvider:
    backend = "dagster"

    def get_status(self, organization_id: str) -> WarehouseSyncStatusDTO:
        now = timezone.now()
        team_id = getattr(settings, "WAREHOUSE_BACKFILL_TELEMETRY_TEAM_ID", None)
        if not team_id:
            return _empty(now, "not_started")

        rows = sync_execute(_QUERY, {"team_id": int(team_id), "event": BACKFILL_PARTITION_EVENT})
        if not rows:
            return _empty(now, "not_started")

        done = 0
        failed = 0
        total_rows = 0
        fresh_date: date | None = None
        last_event_at: datetime | None = None
        latest_failure: tuple[datetime, str] | None = None

        for partition_date_str, status, row_count, error_message, event_at in rows:
            if last_event_at is None or event_at > last_event_at:
                last_event_at = event_at
            if status == "success":
                done += 1
                total_rows += int(row_count or 0)
                pd = date.fromisoformat(partition_date_str)
                if fresh_date is None or pd > fresh_date:
                    fresh_date = pd
            elif status == "failed":
                failed += 1
                if latest_failure is None or event_at > latest_failure[0]:
                    latest_failure = (event_at, error_message or "Backfill partition failed")

        today = now.date()
        total_days = max((today - PARTITION_START).days, 1)
        complete = done >= total_days
        progress_pct = min(round(100 * done / total_days), 100)

        fresh_through = datetime.combine(fresh_date, time.max, tzinfo=UTC) if fresh_date is not None else None
        lag_seconds = int((now - fresh_through).total_seconds()) if fresh_through is not None else None

        error = SyncError(message=latest_failure[1], since=latest_failure[0]) if latest_failure else None

        if failed:
            state = "error"
        elif done == 0:
            state = "not_started"
        elif not complete:
            state = "seeding"
        elif lag_seconds is not None and lag_seconds > CAUGHT_UP_LAG_SECONDS:
            state = "lagging"
        else:
            state = "caught_up"

        return WarehouseSyncStatusDTO(
            backend=self.backend,
            state=state,
            fresh_through=fresh_through,
            lag_seconds=lag_seconds,
            last_activity_at=last_event_at,
            initial_backfill=InitialBackfill(complete=complete, progress_pct=progress_pct),
            total_rows_synced=total_rows or None,
            error=error,
            updated_at=now,
        )
