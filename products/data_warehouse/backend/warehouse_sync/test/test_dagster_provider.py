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

    @override_settings(LLM_ANALYTICS_INTERNAL_TEAM_ID=None)
    def test_not_started_without_telemetry_team(self) -> None:
        dto = DagsterBackfillStatusProvider().get_status()
        assert dto.state == "not_started"
        assert dto.initial_backfill is None

    def test_error_state_when_a_partition_failed(self) -> None:
        now = timezone.now()
        yesterday = (now.date() - timedelta(days=1)).isoformat()
        self._emit(yesterday, "success", timestamp=now, rows_exported=5)
        self._emit("2020-01-01", "failed", timestamp=now, error_message="boom")
        flush_persons_and_events()
        with override_settings(LLM_ANALYTICS_INTERNAL_TEAM_ID=self.team.id):
            dto = DagsterBackfillStatusProvider().get_status()
        assert dto.state == "error"
        assert dto.error is not None
        assert dto.error.message == "boom"
        assert dto.total_rows_synced == 5

    def test_stale_failure_does_not_pin_error(self) -> None:
        # An old failure (outside the recent-failure window) plus a recent success for yesterday
        # should NOT produce an error; the state should be caught_up.
        now = timezone.now()
        yesterday = (now.date() - timedelta(days=1)).isoformat()
        self._emit("2020-06-01", "failed", timestamp=now - timedelta(days=400), error_message="old error")
        self._emit(yesterday, "success", timestamp=now, rows_exported=7)
        flush_persons_and_events()
        with override_settings(LLM_ANALYTICS_INTERNAL_TEAM_ID=self.team.id):
            dto = DagsterBackfillStatusProvider().get_status()
        assert dto.state == "caught_up"
        assert dto.error is None

    def test_lagging_when_frontier_is_behind(self) -> None:
        # Latest success is far in the past, so the warehouse is behind the live edge.
        # The Dagster backend never reports initial-backfill progress (it can't prove completeness).
        now = timezone.now()
        self._emit("2021-06-01", "success", timestamp=now, rows_exported=3)
        flush_persons_and_events()
        with override_settings(LLM_ANALYTICS_INTERNAL_TEAM_ID=self.team.id):
            dto = DagsterBackfillStatusProvider().get_status()
        assert dto.state == "lagging"
        assert dto.initial_backfill is None
        assert dto.fresh_through is not None
        assert dto.lag_seconds is not None and dto.lag_seconds > 0

    def test_caught_up_when_frontier_reaches_yesterday(self) -> None:
        now = timezone.now()
        yesterday = (now.date() - timedelta(days=1)).isoformat()
        self._emit(yesterday, "success", timestamp=now, rows_exported=9)
        flush_persons_and_events()
        with override_settings(LLM_ANALYTICS_INTERNAL_TEAM_ID=self.team.id):
            dto = DagsterBackfillStatusProvider().get_status()
        assert dto.state == "caught_up"
        assert dto.initial_backfill is None

    def test_latest_event_per_partition_wins(self) -> None:
        d = "2020-01-01"
        now = timezone.now()
        # Emit the failure first with an earlier timestamp, then success with a later one.
        # argMax picks the row with the greatest timestamp, so success should win.
        self._emit(d, "failed", timestamp=now - timedelta(seconds=10), error_message="first")
        self._emit(d, "success", timestamp=now, rows_exported=10)
        flush_persons_and_events()
        with override_settings(LLM_ANALYTICS_INTERNAL_TEAM_ID=self.team.id):
            dto = DagsterBackfillStatusProvider().get_status()
        assert dto.error is None  # the success supersedes the earlier failure
        assert dto.total_rows_synced == 10
