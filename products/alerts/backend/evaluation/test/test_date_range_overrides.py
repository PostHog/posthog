from unittest import TestCase

from parameterized import parameterized

from posthog.schema import IntervalType, TrendsQuery

from posthog.tasks.alerts.detector import _date_range_override_for_detector
from posthog.tasks.alerts.trends import _date_range_override_for_intervals

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
