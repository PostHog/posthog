from datetime import timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from django.test import override_settings
from django.utils import timezone

from posthog.ducklake.backfill_telemetry import BACKFILL_DISTINCT_ID, BACKFILL_PARTITION_EVENT


class TestWarehouseSyncStatusAPI(ClickhouseTestMixin, APIBaseTest):
    def test_returns_neutral_contract(self) -> None:
        yesterday = (timezone.now().date() - timedelta(days=1)).isoformat()
        _create_event(
            team=self.team,
            event=BACKFILL_PARTITION_EVENT,
            distinct_id=BACKFILL_DISTINCT_ID,
            properties={"partition_date": yesterday, "status": "success", "rows_exported": 5},
        )
        flush_persons_and_events()

        with override_settings(LLM_ANALYTICS_INTERNAL_TEAM_ID=self.team.id):
            res = self.client.get(f"/api/environments/{self.team.id}/data_warehouse/warehouse_sync_status/")

        assert res.status_code == 200, res.json()
        body = res.json()
        assert set(body.keys()) >= {
            "backend",
            "state",
            "fresh_through",
            "lag_seconds",
            "last_activity_at",
            "initial_backfill",
            "total_rows_synced",
            "error",
            "updated_at",
        }
        assert body["initial_backfill"].keys() == {"complete", "progress_pct"}
        assert body["total_rows_synced"] == 5
