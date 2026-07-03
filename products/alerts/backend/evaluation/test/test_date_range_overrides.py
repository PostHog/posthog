from unittest import TestCase

import numpy as np
from parameterized import parameterized

from posthog.schema import DateRange, IntervalType, TrendsQuery

from posthog.tasks.alerts.detector import _date_range_override_for_detector
from posthog.tasks.alerts.trends import (
    _date_range_override_for_intervals,
    _drop_incomplete_current_interval,
    query_excludes_incomplete_periods,
)

from products.alerts.backend.evaluation.funnels import _trailing_date_range_override


class TestDateRangeOverrides(TestCase):
    @parameterized.expand(
        [
            (IntervalType.DAY, "-2d"),
            (IntervalType.WEEK, "-2w"),
            (IntervalType.MONTH, "-2m"),
            (IntervalType.QUARTER, "-2q"),
            (IntervalType.YEAR, "-2y"),
            (IntervalType.HOUR, "-2h"),
        ]
    )
    def test_interval_maps_to_matching_date_from_unit(self, interval, expected_date_from):
        query = TrendsQuery(series=[], interval=interval)

        self.assertEqual(
            _date_range_override_for_intervals(query, last_x_intervals=2), {"date_from": expected_date_from}
        )
        self.assertEqual(_date_range_override_for_detector(query, min_samples=2), {"date_from": expected_date_from})
        self.assertEqual(_trailing_date_range_override(interval, periods=2), {"date_from": expected_date_from})


class TestIncompletePeriodInteraction(TestCase):
    @parameterized.expand(
        [
            ("drops_ongoing_interval_by_default", True, [1.0, 2.0], ["d1", "d2"]),
            ("keeps_complete_trailing_interval_when_query_clips", False, [1.0, 2.0, 3.0], ["d1", "d2", "d3"]),
        ]
    )
    def test_drop_current_polarity(self, _name, drop_current, expected_data, expected_dates):
        data, dates = _drop_incomplete_current_interval(
            np.array([1.0, 2.0, 3.0]), ["d1", "d2", "d3"], False, drop_current=drop_current
        )
        self.assertEqual(list(data), expected_data)
        self.assertEqual(dates, expected_dates)

    @parameterized.expand(
        [
            ("flag_set", DateRange(date_from="-7d", excludeIncompletePeriods=True), True),
            ("flag_unset", DateRange(date_from="-7d"), False),
            ("no_date_range", None, False),
        ]
    )
    def test_query_excludes_incomplete_periods(self, _name, date_range, expected):
        query = TrendsQuery(series=[], dateRange=date_range)
        self.assertEqual(query_excludes_incomplete_periods(query), expected)
