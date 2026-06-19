from datetime import datetime, timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from django.test import override_settings
from django.utils import timezone

from posthog.ducklake.backfill_telemetry import BACKFILL_DISTINCT_ID, BACKFILL_PARTITION_EVENT

from products.data_warehouse.backend.warehouse_sync.status import get_warehouse_sync_status


class TestWarehouseSyncStatus(ClickhouseTestMixin, APIBaseTest):
    def _emit(
        self, customer_team_id: int, partition_date: str, status: str, timestamp: datetime, **props: object
    ) -> None:
        # Telemetry lands in the internal team (self.team here) with the customer team as a property.
        _create_event(
            team=self.team,
            event=BACKFILL_PARTITION_EVENT,
            distinct_id=BACKFILL_DISTINCT_ID,
            timestamp=timestamp,
            properties={"team_id": customer_team_id, "partition_date": partition_date, "status": status, **props},
        )

    @override_settings(INTERNAL_TELEMETRY_TEAM_ID=None)
    def test_not_started_without_telemetry_team(self) -> None:
        dto = get_warehouse_sync_status(team_id=123)
        assert dto.state == "not_started"

    def test_not_started_when_no_events_for_team(self) -> None:
        now = timezone.now()
        self._emit(999, (now.date() - timedelta(days=1)).isoformat(), "success", timestamp=now)
        flush_persons_and_events()
        with override_settings(INTERNAL_TELEMETRY_TEAM_ID=self.team.id):
            dto = get_warehouse_sync_status(team_id=123)  # different customer team
        assert dto.state == "not_started"

    def test_caught_up_for_requested_team(self) -> None:
        now = timezone.now()
        yesterday = (now.date() - timedelta(days=1)).isoformat()
        self._emit(123, yesterday, "success", timestamp=now)
        flush_persons_and_events()
        with override_settings(INTERNAL_TELEMETRY_TEAM_ID=self.team.id):
            dto = get_warehouse_sync_status(team_id=123)
        assert dto.state == "caught_up"
        assert dto.fresh_through is not None

    def test_lagging_when_frontier_behind(self) -> None:
        now = timezone.now()
        self._emit(123, "2021-06-01", "success", timestamp=now)
        flush_persons_and_events()
        with override_settings(INTERNAL_TELEMETRY_TEAM_ID=self.team.id):
            dto = get_warehouse_sync_status(team_id=123)
        assert dto.state == "lagging"
        assert dto.lag_seconds is not None and dto.lag_seconds > 0

    def test_recent_failure_is_error_stale_is_not(self) -> None:
        now = timezone.now()
        yesterday = (now.date() - timedelta(days=1)).isoformat()
        # Recent failure for team 123 -> error.
        self._emit(123, "2020-01-01", "failed", timestamp=now, error_message="boom")
        with override_settings(INTERNAL_TELEMETRY_TEAM_ID=self.team.id):
            flush_persons_and_events()
            dto = get_warehouse_sync_status(team_id=123)
        assert dto.state == "error"
        assert dto.error is not None and dto.error.message == "boom"

        # A stale failure (old event) plus a recent success -> caught_up, no error.
        self._emit(456, "2020-01-01", "failed", timestamp=now - timedelta(days=400), error_message="old")
        self._emit(456, yesterday, "success", timestamp=now)
        flush_persons_and_events()
        with override_settings(INTERNAL_TELEMETRY_TEAM_ID=self.team.id):
            dto2 = get_warehouse_sync_status(team_id=456)
        assert dto2.state == "caught_up"
        assert dto2.error is None
