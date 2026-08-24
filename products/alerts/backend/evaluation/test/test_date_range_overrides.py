from unittest import TestCase
from unittest.mock import MagicMock, patch

import numpy as np
from parameterized import parameterized

from posthog.schema import AlertConditionType, DateRange, IntervalType, TrendsQuery

from posthog.api.services.query import ExecutionMode
from posthog.tasks.alerts.detector import _date_range_override_for_detector
from posthog.tasks.alerts.trends import (
    _date_range_override_for_intervals,
    _drop_incomplete_current_interval,
    query_excludes_incomplete_periods,
)

from products.alerts.backend.evaluation.funnels import _trailing_date_range_override
from products.alerts.backend.evaluation.trends import TrendsExtractor

TRENDS_CALC_PATH = "products.alerts.backend.evaluation.trends.calculate_for_query_based_insight"


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


def _trends_alert(condition_type: AlertConditionType, check_ongoing: bool = False) -> MagicMock:
    alert = MagicMock()
    alert.config = {"type": "TrendsAlertConfig", "series_index": 0, "check_ongoing_interval": check_ongoing}
    alert.condition = {"type": condition_type}
    threshold = MagicMock()
    threshold.configuration = {"type": "absolute", "bounds": {"upper": 100}}
    alert.threshold = threshold
    return alert


def _clipped_trends_query() -> dict:
    return {
        "kind": "TrendsQuery",
        "series": [{"kind": "EventsNode", "event": "$pageview"}],
        "interval": "day",
        "dateRange": {"date_from": "-7d", "excludeIncompletePeriods": True},
    }


class TestTrendsExtractorIncompletePeriods(TestCase):
    @parameterized.expand(
        [
            ("absolute", AlertConditionType.ABSOLUTE_VALUE),
            ("relative_increase", AlertConditionType.RELATIVE_INCREASE),
            ("relative_decrease", AlertConditionType.RELATIVE_DECREASE),
        ]
    )
    def test_clipped_query_anchors_last_point_worded_as_previous(self, _name, condition_type):
        # A clipped query's last returned point is the last complete interval: it must be the
        # comparison anchor (not one further back), but the breach wording must still call it a
        # previous interval, since the ongoing one was never queried.
        row = {"data": [1.0, 2.0, 3.0], "days": ["d1", "d2", "d3"], "label": "series"}
        with patch(TRENDS_CALC_PATH) as calc:
            calc.return_value = MagicMock(result=[row])
            result = TrendsExtractor().extract(
                _trends_alert(condition_type),
                MagicMock(),
                _clipped_trends_query(),
                ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
            )
        series = result.series[0]
        self.assertEqual(series.current_index, 2)
        self.assertFalse(series.is_current_interval)

    def test_check_ongoing_interval_conflicts_with_clipped_query(self):
        # The clip removes the ongoing interval from the results, so an alert asking to check it
        # can never do what it says: reject the configuration instead of silently degrading.
        with patch(TRENDS_CALC_PATH) as calc:
            calc.return_value = MagicMock(result=[{"data": [1.0, 2.0], "days": ["d1", "d2"], "label": "series"}])
            with self.assertRaisesRegex(ValueError, "excludes incomplete periods"):
                TrendsExtractor().extract(
                    _trends_alert(AlertConditionType.ABSOLUTE_VALUE, check_ongoing=True),
                    MagicMock(),
                    _clipped_trends_query(),
                    ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
                )
