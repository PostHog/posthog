from datetime import UTC, datetime

from posthog.test.base import BaseTest

from products.data_warehouse.backend.warehouse_sync.contracts import (
    SyncError,
    WarehouseSyncStatusDTO,
    WarehouseSyncStatusSerializer,
)


class TestWarehouseSyncStatusSerializer(BaseTest):
    def test_serializes_healthy(self) -> None:
        dto = WarehouseSyncStatusDTO(
            state="caught_up",
            fresh_through=datetime(2026, 6, 17, 23, 59, tzinfo=UTC),
            lag_seconds=3600,
            last_activity_at=datetime(2026, 6, 18, 1, 0, tzinfo=UTC),
            error=None,
            updated_at=datetime(2026, 6, 18, 2, 0, tzinfo=UTC),
        )
        data = WarehouseSyncStatusSerializer(dto).data
        assert data["state"] == "caught_up"
        assert data["lag_seconds"] == 3600
        assert data["error"] is None

    def test_serializes_error(self) -> None:
        dto = WarehouseSyncStatusDTO(
            state="error",
            fresh_through=None,
            lag_seconds=None,
            last_activity_at=None,
            error=SyncError(message="boom", since=datetime(2026, 6, 18, tzinfo=UTC)),
            updated_at=datetime(2026, 6, 18, 2, 0, tzinfo=UTC),
        )
        data = WarehouseSyncStatusSerializer(dto).data
        assert data["error"]["message"] == "boom"
