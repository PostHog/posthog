from datetime import UTC, datetime

from posthog.test.base import BaseTest

from products.data_warehouse.backend.warehouse_sync.contracts import (
    InitialBackfill,
    WarehouseSyncStatusDTO,
    WarehouseSyncStatusSerializer,
)


class TestWarehouseSyncStatusSerializer(BaseTest):
    def test_serializes_nested_shape(self) -> None:
        dto = WarehouseSyncStatusDTO(
            backend="dagster",
            state="caught_up",
            fresh_through=datetime(2026, 6, 17, 23, 59, tzinfo=UTC),
            lag_seconds=3600,
            last_activity_at=datetime(2026, 6, 18, 1, 0, tzinfo=UTC),
            initial_backfill=InitialBackfill(complete=True, progress_pct=100),
            total_rows_synced=8_900_000_000,
            error=None,
            updated_at=datetime(2026, 6, 18, 2, 0, tzinfo=UTC),
        )
        data = WarehouseSyncStatusSerializer(dto).data
        assert data["backend"] == "dagster"
        assert data["state"] == "caught_up"
        assert data["initial_backfill"] == {"complete": True, "progress_pct": 100}
        assert data["error"] is None
        assert data["total_rows_synced"] == 8_900_000_000
