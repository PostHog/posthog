from datetime import datetime, timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from django.test import override_settings
from django.utils import timezone

from posthog.ducklake.backfill_telemetry import BACKFILL_DISTINCT_ID, BACKFILL_PARTITION_EVENT

from products.data_warehouse.backend.warehouse_sync.dagster_provider import DagsterBackfillStatusProvider


class TestDagsterProvider(ClickhouseTestMixin, APIBaseTest):
    def _emit(
        self,
        partition_date: str,
        status: str,
        timestamp: datetime | None = None,
        **props: object,
    ) -> None:
        kwargs: dict[str, object] = {
            "team": self.team,
            "event": BACKFILL_PARTITION_EVENT,
            "distinct_id": BACKFILL_DISTINCT_ID,
            "properties": {"partition_date": partition_date, "status": status, **props},
        }
        if timestamp is not None:
            kwargs["timestamp"] = timestamp
        _create_event(**kwargs)

    @override_settings(WAREHOUSE_BACKFILL_TELEMETRY_TEAM_ID=None)
    def test_not_started_without_telemetry_team(self) -> None:
        dto = DagsterBackfillStatusProvider().get_status("org-1")
        assert dto.state == "not_started"

    def test_error_state_when_a_partition_failed(self) -> None:
        yesterday = (timezone.now().date() - timedelta(days=1)).isoformat()
        self._emit(yesterday, "success", rows_exported=5)
        self._emit("2020-01-01", "failed", error_message="boom")
        flush_persons_and_events()
        with override_settings(WAREHOUSE_BACKFILL_TELEMETRY_TEAM_ID=self.team.id):
            dto = DagsterBackfillStatusProvider().get_status("org-1")
        assert dto.state == "error"
        assert dto.error is not None
        assert dto.error.message == "boom"
        assert dto.total_rows_synced == 5

    def test_latest_event_per_partition_wins(self) -> None:
        d = "2020-01-01"
        now = timezone.now()
        # Emit the failure first with an earlier timestamp, then success with a later one.
        # argMax picks the row with the greatest timestamp, so success should win.
        self._emit(d, "failed", timestamp=now - timedelta(seconds=10), error_message="first")
        self._emit(d, "success", timestamp=now, rows_exported=10)
        flush_persons_and_events()
        with override_settings(WAREHOUSE_BACKFILL_TELEMETRY_TEAM_ID=self.team.id):
            dto = DagsterBackfillStatusProvider().get_status("org-1")
        assert dto.error is None  # the success supersedes the earlier failure
        assert dto.total_rows_synced == 10
