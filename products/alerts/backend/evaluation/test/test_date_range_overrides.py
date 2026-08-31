from typing import cast

from unittest import TestCase
from unittest.mock import MagicMock, patch

import numpy as np
from parameterized import parameterized

from posthog.schema import (
    AlertConditionType,
    ChartDisplayType,
    DateRange,
    EventsNode,
    IntervalType,
    TrendsFilter,
    TrendsQuery,
)

from posthog.api.services.query import ExecutionMode
from posthog.caching.insight_result import InsightResult
from posthog.tasks.alerts.detector import (
    _compute_min_samples_for_detector,
    _date_range_override_for_detector,
    _prepare_series,
    _resolve_maturation_lag,
)
from posthog.tasks.alerts.trends import (
    TrendResult,
    _date_range_override_for_intervals,
    _drop_incomplete_current_interval,
    query_excludes_incomplete_periods,
)

from products.alerts.backend.evaluation.detector import extract_detector_series
from products.alerts.backend.evaluation.funnels import _trailing_date_range_override
from products.alerts.backend.evaluation.trends import TrendsExtractor

TRENDS_CALC_PATH = "products.alerts.backend.evaluation.trends.calculate_for_query_based_insight"
DETECTOR_CALC_PATH = "products.alerts.backend.evaluation.detector.calculate_for_query_based_insight"


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


class TestMaturationLag(TestCase):
    @parameterized.expand(
        [
            ("missing_uses_default", {}, 1),
            ("null_uses_default", {"maturation_lag_n": None}, 1),
            ("explicit_zero_opts_out", {"maturation_lag_n": 0}, 0),
            ("explicit_value", {"maturation_lag_n": 3}, 3),
            ("negative_clamped_to_zero", {"maturation_lag_n": -2}, 0),
        ]
    )
    def test_resolve_maturation_lag(self, _name, config, expected):
        self.assertEqual(_resolve_maturation_lag(config), expected)

    @parameterized.expand(
        [
            # The default lag drops the in-progress interval and one more settled interval, so the
            # scored last point is the one before the just-closed one.
            ("default_drops_just_closed", True, 1, [1.0, 2.0, 3.0]),
            # Lag 0 restores the pre-fix behavior: only the in-progress interval is dropped.
            ("zero_keeps_just_closed", True, 0, [1.0, 2.0, 3.0, 4.0]),
            # A clipped query has no in-progress interval, but the freshest complete point is still
            # censored, so the lag drops it.
            ("applies_when_current_already_clipped", False, 1, [1.0, 2.0, 3.0, 4.0]),
            ("larger_lag_drops_more", True, 2, [1.0, 2.0]),
        ]
    )
    def test_prepare_series_trims_maturation_tail(self, _name, drop_current, maturation_lag, expected_data):
        row = cast(
            TrendResult, {"data": [1.0, 2.0, 3.0, 4.0, 5.0], "days": ["d1", "d2", "d3", "d4", "d5"], "label": "s"}
        )
        prepared = _prepare_series(row, False, drop_current=drop_current, maturation_lag=maturation_lag)
        assert prepared is not None
        self.assertEqual(list(prepared.data), expected_data)
        self.assertEqual(prepared.dates, [f"d{i + 1}" for i in range(len(expected_data))])

    def test_prepare_series_keeps_at_least_one_point(self):
        # A short series must still reach the detector's own minimum-length guard, not be emptied here.
        row = cast(TrendResult, {"data": [1.0, 2.0], "days": ["d1", "d2"], "label": "s"})
        prepared = _prepare_series(row, False, drop_current=True, maturation_lag=5)
        assert prepared is not None
        self.assertEqual(list(prepared.data), [1.0])

    def test_extract_detector_series_scores_settled_point_and_widens_window(self):
        # End-to-end wiring: the default lag makes the detector score the settled point (drops the
        # in-progress interval plus one more), and the fetched window grows to keep the training set.
        query = TrendsQuery(
            series=[EventsNode(event="signed_up")],
            trendsFilter=TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
            interval=IntervalType.DAY,
        )
        config = {"type": "zscore", "window": 10}
        row = {"data": [float(i) for i in range(40)], "days": [f"d{i}" for i in range(40)], "label": "s"}
        with patch(DETECTOR_CALC_PATH) as calc:
            calc.return_value = InsightResult(
                result=[row], columns=[], timezone="UTC", last_refresh=None, cache_key="", is_cached=False
            )
            result = extract_detector_series(
                MagicMock(), MagicMock(), query, config, ExecutionMode.CALCULATE_BLOCKING_ALWAYS
            )

        # 40 points, minus the in-progress (39.0) and one settled interval (38.0).
        self.assertEqual(result.series[0].points[-1].value, 37.0)
        expected_days = _compute_min_samples_for_detector(config) + 1 + 1
        self.assertEqual(calc.call_args.kwargs["filters_override"], {"date_from": f"-{expected_days}d"})


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
