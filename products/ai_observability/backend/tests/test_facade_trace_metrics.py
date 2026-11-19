from dataclasses import replace
from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.cache import cache

from products.ai_observability.backend.facade import api, contracts
from products.ai_observability.backend.logic.traces.trace_metrics import PeriodTotals
from products.ai_observability.backend.logic.traces.trace_metrics_queries import NO_TRACES, TraceMetricsRows
from products.ai_observability.backend.logic.traces.trace_selection import TraceSelection, TraceWindow

DAY = datetime(2026, 10, 5, tzinfo=UTC)
READ = "products.ai_observability.backend.logic.traces.trace_metrics_queries.load_trace_metrics"


def selection_between(start: datetime, end: datetime, *, filter_test_accounts: bool | None = None) -> TraceSelection:
    return TraceSelection(window=TraceWindow(start=start, end=end), filter_test_accounts=filter_test_accounts)


def rows_with(buckets: dict[datetime, PeriodTotals]) -> TraceMetricsRows:
    return TraceMetricsRows(
        current=replace(NO_TRACES, traces=4, errored=1, cost=2.0, users=3), previous=NO_TRACES, buckets=buckets
    )


class TestLoadTraceMetrics(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    def test_load_trace_metrics_builds_tiles_and_buckets(self) -> None:
        busy_hour = replace(NO_TRACES, traces=4, errored=1)
        selection = selection_between(DAY, DAY + timedelta(hours=3))

        with patch(READ, return_value=rows_with({DAY + timedelta(hours=1): busy_hour})):
            metrics = api.load_trace_metrics(self.team, self.user, selection)()

        assert metrics.bucket_size == contracts.TraceMetricBucketSize.HOUR
        assert (metrics.previous_date_from, metrics.previous_date_to) == (DAY - timedelta(hours=3), DAY)
        tiles = {tile.key: tile for tile in metrics.tiles}
        assert set(tiles) == set(contracts.TraceMetricKey)
        assert (tiles[contracts.TraceMetricKey.TRACES].value, tiles[contracts.TraceMetricKey.ERROR_RATE].value) == (
            4,
            0.25,
        )
        assert [bucket.start for bucket in metrics.buckets] == [DAY + timedelta(hours=hour) for hour in range(3)]
        assert [bucket.values[contracts.TraceMetricKey.TRACES] for bucket in metrics.buckets] == [0, 4, 0]
        assert metrics.buckets[0].values[contracts.TraceMetricKey.ERROR_RATE] is None

    def test_load_trace_metrics_reads_once_within_cache_ttl(self) -> None:
        selection = selection_between(DAY, DAY + timedelta(hours=3))

        with patch(READ, return_value=rows_with({})) as read:
            first = api.load_trace_metrics(self.team, self.user, selection)()
            second = api.load_trace_metrics(self.team, self.user, selection)()

        assert read.call_count == 1
        assert first == second

    def test_cache_key_rounds_window_to_bucket(self) -> None:
        start, end = DAY + timedelta(minutes=7), DAY + timedelta(hours=3, minutes=7)
        selections = [
            selection_between(start, end),
            selection_between(start + timedelta(minutes=34), end + timedelta(minutes=34)),
            selection_between(start + timedelta(hours=1), end + timedelta(hours=1)),
            selection_between(start, end, filter_test_accounts=True),
        ]

        with patch(READ, return_value=rows_with({})) as read:
            for selection in selections:
                api.load_trace_metrics(self.team, self.user, selection)

        assert read.call_count == 3
