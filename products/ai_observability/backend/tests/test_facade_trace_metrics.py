from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.cache import cache

from parameterized import parameterized

from posthog.models import User

from products.ai_observability.backend.facade import api, contracts
from products.ai_observability.backend.logic.traces.trace_metrics import NO_TRACES, MetricKey, PeriodTotals
from products.ai_observability.backend.logic.traces.trace_metrics_queries import (
    TraceMetricsRows,
    TraceMetricsTooHeavyError,
)
from products.ai_observability.backend.logic.traces.trace_selection import TraceSelection, TraceWindow

from .property_access import hide_event_property

DAY = datetime(2026, 10, 5, tzinfo=UTC)
READ = "products.ai_observability.backend.logic.traces.trace_metrics_queries.load_trace_metrics"


def selection_between(start: datetime, end: datetime, *, filter_test_accounts: bool | None = None) -> TraceSelection:
    return TraceSelection(window=TraceWindow(start=start, end=end), filter_test_accounts=filter_test_accounts)


def rows_with(buckets: dict[datetime, PeriodTotals]) -> TraceMetricsRows:
    return TraceMetricsRows(
        current=replace(NO_TRACES, traces=4, errored=1, cost=2.0, users=3),
        previous=NO_TRACES,
        buckets=buckets,
    )


class TestLoadTraceMetrics(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    def test_load_trace_metrics_builds_tiles_with_series(self) -> None:
        busy_hour = replace(NO_TRACES, traces=4, errored=1)
        selection = selection_between(DAY, DAY + timedelta(hours=3))

        with (
            patch(READ, return_value=rows_with({DAY + timedelta(hours=1): busy_hour})),
            patch.object(api, "metrics_insight_queries", return_value={key: f"SELECT '{key}'" for key in MetricKey}),
        ):
            metrics = api.load_trace_metrics(self.team, self.user, selection)()

        assert metrics.bucket_size == contracts.TraceMetricBucketSize.HOUR
        assert (metrics.previous_date_from, metrics.previous_date_to) == (DAY - timedelta(hours=3), DAY)
        assert metrics.bucket_starts == [DAY + timedelta(hours=hour) for hour in range(3)]
        tiles = {tile.key: tile for tile in metrics.tiles}
        assert set(tiles) == set(contracts.TraceMetricKey)
        traces = tiles[contracts.TraceMetricKey.TRACES]
        assert (traces.value, traces.series, traces.insight_query) == (4, [0, 4, 0], "SELECT 'traces'")

    def test_load_trace_metrics_reads_once_within_cache_ttl(self) -> None:
        selection = selection_between(DAY, DAY + timedelta(hours=3))
        busy_hour = replace(NO_TRACES, traces=4, errored=1)

        with patch(READ, return_value=rows_with({DAY + timedelta(hours=1): busy_hour})) as read:
            first = api.load_trace_metrics(self.team, self.user, selection)()
            second = api.load_trace_metrics(self.team, self.user, selection)()

        assert read.call_count == 1
        assert first == second

    def test_load_trace_metrics_refuses_a_too_heavy_range_again_without_reading(self) -> None:
        selection = selection_between(DAY, DAY + timedelta(days=90))

        with patch(READ, side_effect=TraceMetricsTooHeavyError()) as read:
            for _ in range(2):
                with pytest.raises(TraceMetricsTooHeavyError):
                    api.load_trace_metrics(self.team, self.user, selection)

        assert read.call_count == 1

    @parameterized.expand(
        [
            ("too_many_buckets", datetime(5000, 1, 1, tzinfo=UTC), datetime(8000, 1, 1, tzinfo=UTC)),
            ("previous_period_before_year_one", datetime(1, 6, 1, tzinfo=UTC), datetime(1, 12, 1, tzinfo=UTC)),
        ]
    )
    def test_load_trace_metrics_refuses_an_uncomputable_range_without_reading(
        self, _name: str, start: datetime, end: datetime
    ) -> None:
        selection = selection_between(start, end)

        with patch(READ) as read, pytest.raises(TraceMetricsTooHeavyError):
            api.load_trace_metrics(self.team, self.user, selection)

        assert read.call_count == 0

    def test_cache_key_is_the_window_to_the_minute(self) -> None:
        start, end = DAY + timedelta(minutes=7), DAY + timedelta(hours=3, minutes=7)
        base = selection_between(start, end)
        same_minute = [selection_between(start + timedelta(seconds=20), end + timedelta(seconds=20))]
        other_window = [
            selection_between(start + timedelta(minutes=1), end + timedelta(minutes=1)),
            selection_between(start, end, filter_test_accounts=True),
            replace(base, include_support_traces=True),
            # The same minutes, but one span takes hourly buckets and the other daily ones.
            selection_between(start, start + timedelta(hours=48)),
            selection_between(start, start + timedelta(hours=48, seconds=20)),
        ]

        with patch(READ, return_value=rows_with({})) as read:
            for selection in [base, *same_minute, *other_window]:
                api.load_trace_metrics(self.team, self.user, selection)

        assert read.call_count == 1 + len(other_window)

    def test_cache_key_separates_users_with_different_property_restrictions(self) -> None:
        selection = selection_between(DAY, DAY + timedelta(hours=3))

        with patch(READ, return_value=rows_with({})) as read:
            api.load_trace_metrics(self.team, self.user, selection)
            hide_event_property(self.team, self.user, "secret")
            api.load_trace_metrics(self.team, self.user, selection)

        assert read.call_count == 2

    def test_cache_key_separates_people_with_the_same_property_restrictions(self) -> None:
        selection = selection_between(DAY, DAY + timedelta(hours=3))
        colleague = User.objects.create_and_join(self.organization, "colleague@example.com", "password")

        with patch(READ, return_value=rows_with({})) as read:
            api.load_trace_metrics(self.team, self.user, selection)
            api.load_trace_metrics(self.team, colleague, selection)

        assert read.call_count == 2

    def test_buckets_start_at_midnight_in_the_project_zone(self) -> None:
        self.team.timezone = "America/Los_Angeles"
        self.team.save()
        zone = ZoneInfo("America/Los_Angeles")
        just_after_midnight = datetime(2026, 10, 6, 0, 2, tzinfo=zone)
        selection = selection_between(
            (just_after_midnight - timedelta(days=3)).astimezone(UTC), just_after_midnight.astimezone(UTC)
        )

        with patch(READ, return_value=rows_with({})):
            metrics = api.load_trace_metrics(self.team, self.user, selection)()

        assert metrics.bucket_starts[-1] == datetime(2026, 10, 6, tzinfo=zone)
