from dataclasses import dataclass
from datetime import datetime

from django.utils import timezone

from products.data_warehouse.backend.warehouse_sync.contracts import InitialBackfill, SyncError, WarehouseSyncStatusDTO


@dataclass
class ViaduckDestinationState:
    health: str  # healthy | buffering | flushing | lagging | error
    cursor_snapshot: int  # last_snapshot_id; 0 means seeding not yet complete
    lag_seconds: float | None
    rows_replicated: int | None
    last_replicated_at: datetime | None
    fresh_through: datetime | None
    last_error: str | None
    last_error_at: datetime | None


def viaduck_state_to_sync_state(health: str, cursor_snapshot: int, lag_seconds: float | None) -> str:
    if health == "error":
        return "error"
    if cursor_snapshot == 0:
        return "seeding"
    if health == "lagging":
        return "lagging"
    return "caught_up"  # healthy | buffering | flushing


class ViaduckSyncStatusProvider:
    backend = "viaduck"

    def _fetch_destination(self, organization_id: str) -> ViaduckDestinationState | None:
        # SWAP POINT: read viaduck.viaduck_state filtered by routing_value(organization_id),
        # or hit viaduck's /status endpoint. Returns None until that source is wired up.
        return None

    def get_status(self, organization_id: str) -> WarehouseSyncStatusDTO:
        now = timezone.now()
        dest = self._fetch_destination(organization_id)
        if dest is None:
            return WarehouseSyncStatusDTO(
                backend=self.backend,
                state="not_started",
                fresh_through=None,
                lag_seconds=None,
                last_activity_at=None,
                initial_backfill=InitialBackfill(complete=False, progress_pct=None),
                total_rows_synced=None,
                error=None,
                updated_at=now,
            )

        state = viaduck_state_to_sync_state(dest.health, dest.cursor_snapshot, dest.lag_seconds)
        error = (
            SyncError(message=dest.last_error, since=dest.last_error_at or now)
            if dest.health == "error" and dest.last_error
            else None
        )
        return WarehouseSyncStatusDTO(
            backend=self.backend,
            state=state,
            fresh_through=dest.fresh_through,
            lag_seconds=int(dest.lag_seconds) if dest.lag_seconds is not None else None,
            last_activity_at=dest.last_replicated_at,
            initial_backfill=InitialBackfill(complete=dest.cursor_snapshot > 0, progress_pct=None),
            total_rows_synced=dest.rows_replicated,
            error=error,
            updated_at=now,
        )
