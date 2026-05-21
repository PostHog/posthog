from datetime import datetime
from zoneinfo import ZoneInfo

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event

from django.test import TestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.models.event import DEFAULT_EARLIEST_TIME_DELTA
from posthog.queries.util import (
    EARLIEST_TIMESTAMP_DATETIME,
    _earliest_timestamp_upper_bounds,
    correct_result_for_sampling,
    get_earliest_timestamp,
)


class TestQueriesUtil(TestCase):
    def test_correct_resullt_for_sampling(self):
        res = correct_result_for_sampling(1, 0.1, None)
        self.assertEqual(res, 10)

        res = correct_result_for_sampling(1, 0.01, None)
        self.assertEqual(res, 100)

        res = correct_result_for_sampling(1, None, None)
        self.assertEqual(res, 1)

        res = correct_result_for_sampling(1, 0.01, "max")
        self.assertEqual(res, 1)

        res = correct_result_for_sampling(1, 0.01, "p90_count_per_actor")
        self.assertEqual(res, 1)

        res = correct_result_for_sampling(1, 0.01, "sum")
        self.assertEqual(res, 100)


class TestEarliestTimestampUpperBounds(TestCase):
    @parameterized.expand(
        [
            ("recent_now", datetime(2024, 6, 15, tzinfo=ZoneInfo("UTC"))),
            ("now_just_above_floor", datetime(2015, 6, 1, tzinfo=ZoneInfo("UTC"))),
            ("now_at_floor", EARLIEST_TIMESTAMP_DATETIME),
        ]
    )
    def test_bounds_are_strictly_ascending_and_above_floor(self, _name, now):
        bounds = _earliest_timestamp_upper_bounds(now)

        self.assertTrue(all(EARLIEST_TIMESTAMP_DATETIME < bound for bound in bounds))
        self.assertEqual(bounds, sorted(bounds))
        self.assertEqual(len(bounds), len(set(bounds)), "bounds must be de-duplicated")

    def test_last_bound_covers_now(self):
        now = datetime(2024, 6, 15, 10, 30, tzinfo=ZoneInfo("UTC"))
        bounds = _earliest_timestamp_upper_bounds(now)

        self.assertGreater(bounds[-1], now)

    def test_includes_narrow_windows_at_the_floor(self):
        now = datetime(2024, 6, 15, tzinfo=ZoneInfo("UTC"))
        bounds = _earliest_timestamp_upper_bounds(now)

        # The two short windows just above the floor catch corrupt/legacy events clustered there.
        self.assertIn(EARLIEST_TIMESTAMP_DATETIME.replace(month=2), bounds)
        self.assertIn(EARLIEST_TIMESTAMP_DATETIME.replace(month=4), bounds)


class TestGetEarliestTimestamp(ClickhouseTestMixin, APIBaseTest):
    def _earliest(self) -> datetime:
        # use_cache=False so each scenario hits ClickHouse rather than the 2s memo
        return get_earliest_timestamp(self.team.pk, use_cache=False)

    @freeze_time("2024-06-15T12:00:00Z")
    def test_returns_earliest_event_timestamp(self):
        _create_event(team=self.team, event="$pageview", distinct_id="u1", timestamp="2023-03-04T09:10:11Z")
        _create_event(team=self.team, event="$pageview", distinct_id="u1", timestamp="2024-01-01T00:00:00Z")

        self.assertEqual(self._earliest(), datetime(2023, 3, 4, 9, 10, 11, tzinfo=ZoneInfo("UTC")))

    @freeze_time("2024-06-15T12:00:00Z")
    def test_returns_earliest_when_data_clustered_at_floor(self):
        # Corrupt/legacy events that land right at the epoch floor are the common heavy case.
        _create_event(team=self.team, event="$pageview", distinct_id="u1", timestamp="2015-01-01T00:01:04Z")
        _create_event(team=self.team, event="$pageview", distinct_id="u1", timestamp="2024-05-01T00:00:00Z")

        self.assertEqual(self._earliest(), datetime(2015, 1, 1, 0, 1, 4, tzinfo=ZoneInfo("UTC")))

    @freeze_time("2024-06-15T12:00:00Z")
    def test_returns_earliest_when_data_only_recent(self):
        # Teams whose first event is recent must still resolve to the exact earliest event.
        _create_event(team=self.team, event="$pageview", distinct_id="u1", timestamp="2024-05-20T08:00:00Z")
        _create_event(team=self.team, event="$pageview", distinct_id="u1", timestamp="2024-06-01T08:00:00Z")

        self.assertEqual(self._earliest(), datetime(2024, 5, 20, 8, 0, 0, tzinfo=ZoneInfo("UTC")))

    @freeze_time("2024-06-15T12:00:00Z")
    def test_ignores_events_before_the_floor(self):
        # Pre-2015 timestamps (e.g. epoch-zero corruption) are excluded, matching the floor filter.
        _create_event(team=self.team, event="$pageview", distinct_id="u1", timestamp="1970-01-01T00:00:00Z")
        _create_event(team=self.team, event="$pageview", distinct_id="u1", timestamp="2020-07-08T09:10:11Z")

        self.assertEqual(self._earliest(), datetime(2020, 7, 8, 9, 10, 11, tzinfo=ZoneInfo("UTC")))

    @freeze_time("2024-06-15T12:00:00Z")
    def test_returns_default_fallback_when_no_events(self):
        earliest = self._earliest()

        self.assertEqual(earliest, timezone.now() - DEFAULT_EARLIEST_TIME_DELTA)
