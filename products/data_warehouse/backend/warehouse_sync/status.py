from datetime import UTC, date, datetime, time, timedelta

from django.conf import settings
from django.utils import timezone

from posthog.clickhouse.client import sync_execute
from posthog.ducklake.backfill_telemetry import BACKFILL_PARTITION_EVENT

from products.data_warehouse.backend.warehouse_sync.contracts import SyncError, WarehouseSyncStatusDTO

RECENT_FAILURE_WINDOW = timedelta(days=7)
# A daily backfill is "up to date" once its frontier is within ~2 days of now.
CAUGHT_UP_LAG_SECONDS = 2 * 24 * 60 * 60

# Latest backfill telemetry event per partition_date, for one customer team. The events live in
# the internal telemetry project; the customer team is a property on each event.
_QUERY = """
SELECT
    JSONExtractString(properties, 'partition_date') AS partition_date,
    argMax(JSONExtractString(properties, 'status'), timestamp) AS status,
    argMax(JSONExtractString(properties, 'error_message'), timestamp) AS error_message,
    max(timestamp) AS last_event_at
FROM events
WHERE team_id = %(internal_team_id)s
  AND event = %(event)s
  AND JSONExtractInt(properties, 'team_id') = %(customer_team_id)s
GROUP BY partition_date
"""


def _empty(now: datetime, state: str) -> WarehouseSyncStatusDTO:
    return WarehouseSyncStatusDTO(
        state=state, fresh_through=None, lag_seconds=None, last_activity_at=None, error=None, updated_at=now
    )


def get_warehouse_sync_status(team_id: int) -> WarehouseSyncStatusDTO:
    """Freshness of one team's managed-warehouse event data, derived from backfill telemetry.

    Freshness is the latest successful partition date; it deliberately does not assert historical
    completeness, which sparse telemetry can't prove.
    """
    now = timezone.now()
    internal_team_id = settings.INTERNAL_TELEMETRY_TEAM_ID
    if not internal_team_id:
        return _empty(now, "not_started")

    rows = sync_execute(
        _QUERY,
        {"internal_team_id": int(internal_team_id), "event": BACKFILL_PARTITION_EVENT, "customer_team_id": team_id},
    )
    if not rows:
        return _empty(now, "not_started")

    done = 0
    fresh_date: date | None = None
    last_event_at: datetime | None = None
    latest_failure: tuple[datetime, str] | None = None

    for partition_date_str, status, error_message, event_at in rows:
        if last_event_at is None or event_at > last_event_at:
            last_event_at = event_at
        if status == "success":
            done += 1
            pd = date.fromisoformat(partition_date_str)
            if fresh_date is None or pd > fresh_date:
                fresh_date = pd
        elif status == "failed":
            if latest_failure is None or event_at > latest_failure[0]:
                latest_failure = (event_at, error_message or "Backfill partition failed")

    fresh_through = datetime.combine(fresh_date, time.max, tzinfo=UTC) if fresh_date is not None else None
    lag_seconds = int((now - fresh_through).total_seconds()) if fresh_through is not None else None

    recent_failure = latest_failure is not None and latest_failure[0] >= now - RECENT_FAILURE_WINDOW
    error = SyncError(message=latest_failure[1], since=latest_failure[0]) if recent_failure else None

    if recent_failure:
        state = "error"
    elif done == 0:
        state = "not_started"
    elif lag_seconds is not None and lag_seconds <= CAUGHT_UP_LAG_SECONDS:
        state = "caught_up"
    else:
        state = "lagging"

    return WarehouseSyncStatusDTO(
        state=state,
        fresh_through=fresh_through,
        lag_seconds=lag_seconds,
        last_activity_at=last_event_at,
        error=error,
        updated_at=now,
    )
