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

from products.alerts.backend.evaluation.contract import (
    INSIGHT_TYPE_CHANGED_MESSAGE,
    ONGOING_PERIOD_EXCLUDED_MESSAGE,
    AlertDataUnavailableError,
    AlertExtractionError,
)
from products.alerts.backend.evaluation.funnels import _trailing_date_range_override
from products.alerts.backend.evaluation.metrics import MetricsExtractor
from products.alerts.backend.evaluation.trends import (
    ONGOING_PERIOD_NEEDS_UPPER_THRESHOLD_MESSAGE,
    PERCENTAGE_THRESHOLD_ON_ABSOLUTE_VALUE_MESSAGE,
    RELATIVE_CONDITION_ON_NON_TIME_SERIES_MESSAGE,
    TrendsExtractor,
)

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


def _trends_alert(
    condition_type: AlertConditionType,
    check_ongoing: bool = False,
    threshold_configuration: dict | None = None,
    config_type: str = "TrendsAlertConfig",
) -> MagicMock:
    alert = MagicMock()
    alert.config = {"type": config_type, "series_index": 0, "check_ongoing_interval": check_ongoing}
    alert.condition = {"type": condition_type}
    alert.evaluation_delay_intervals = 0
    threshold = MagicMock()
    threshold.configuration = threshold_configuration or {"type": "absolute", "bounds": {"upper": 100}}
    alert.threshold = threshold
    return alert


def _ongoing_trends_query() -> dict:
    return {**_clipped_trends_query(), "dateRange": {"date_from": "-7d"}}


def _clipped_trends_query() -> dict:
    return {
        "kind": "TrendsQuery",
        "series": [{"kind": "EventsNode", "event": "$pageview"}],
        "interval": "day",
        "dateRange": {"date_from": "-7d", "excludeIncompletePeriods": True},
    }


class TestTrendsExtractorIncompletePeriods(TestCase):
    @parameterized.expand([(False,), (True,)])
    def test_evaluation_delay_skips_empty_completed_buckets(self, already_complete: bool) -> None:
        alert = _trends_alert(AlertConditionType.ABSOLUTE_VALUE)
        alert.evaluation_delay_intervals = 2
        query = _clipped_trends_query()
        query["interval"] = "hour"
        query["dateRange"]["excludeIncompletePeriods"] = already_complete
        row = {
            "data": [40.0, 42.0, 0.0, 0.0] + ([] if already_complete else [0.0]),
            "dates": [f"2026-01-15T{hour:02d}:00:00Z" for hour in range(6, 10 if already_complete else 11)],
            "label": "Orders",
        }
        with patch(TRENDS_CALC_PATH, return_value=MagicMock(result=[row])):
            result = TrendsExtractor().extract(alert, MagicMock(), query, ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
        selected = result.series[0].points[result.series[0].current_index]
        self.assertEqual(selected.value, 42.0)
        self.assertEqual(selected.date, "2026-01-15T07:00:00Z")

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

    @parameterized.expand(
        [
            (
                "check ongoing period on a query that clips it",
                _trends_alert(AlertConditionType.ABSOLUTE_VALUE, check_ongoing=True),
                _clipped_trends_query(),
                ONGOING_PERIOD_EXCLUDED_MESSAGE,
            ),
            (
                "relative increase on a non time series insight",
                _trends_alert(AlertConditionType.RELATIVE_INCREASE),
                {**_clipped_trends_query(), "trendsFilter": {"display": "BoldNumber"}},
                RELATIVE_CONDITION_ON_NON_TIME_SERIES_MESSAGE,
            ),
            (
                "relative decrease on a non time series insight",
                _trends_alert(AlertConditionType.RELATIVE_DECREASE),
                {**_clipped_trends_query(), "trendsFilter": {"display": "ActionsPie"}},
                RELATIVE_CONDITION_ON_NON_TIME_SERIES_MESSAGE,
            ),
            (
                "absolute value with check ongoing period and no upper bound",
                _trends_alert(
                    AlertConditionType.ABSOLUTE_VALUE,
                    check_ongoing=True,
                    threshold_configuration={"type": "absolute", "bounds": {"lower": 1}},
                ),
                _ongoing_trends_query(),
                ONGOING_PERIOD_NEEDS_UPPER_THRESHOLD_MESSAGE,
            ),
            (
                "relative increase with check ongoing period and no upper bound",
                _trends_alert(
                    AlertConditionType.RELATIVE_INCREASE,
                    check_ongoing=True,
                    threshold_configuration={"type": "absolute", "bounds": {"lower": 1}},
                ),
                _ongoing_trends_query(),
                ONGOING_PERIOD_NEEDS_UPPER_THRESHOLD_MESSAGE,
            ),
            (
                "absolute value with a percentage threshold",
                _trends_alert(
                    AlertConditionType.ABSOLUTE_VALUE,
                    threshold_configuration={"type": "percentage", "bounds": {"upper": 0.5}},
                ),
                _ongoing_trends_query(),
                PERCENTAGE_THRESHOLD_ON_ABSOLUTE_VALUE_MESSAGE,
            ),
            (
                "funnel settings on an insight changed to trends",
                _trends_alert(AlertConditionType.ABSOLUTE_VALUE, config_type="FunnelsAlertConfig"),
                _ongoing_trends_query(),
                INSIGHT_TYPE_CHANGED_MESSAGE,
            ),
        ]
    )
    def test_a_config_the_insight_no_longer_fits_is_a_broken_config(self, _name, alert, query, expected_message):
        with patch(TRENDS_CALC_PATH) as calc:
            calc.return_value = MagicMock(result=[{"data": [1.0, 2.0], "days": ["d1", "d2"], "label": "series"}])
            with self.assertRaises(AlertExtractionError) as raised:
                TrendsExtractor().extract(
                    alert, MagicMock(), query, ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE
                )
        self.assertNotIsInstance(raised.exception, AlertDataUnavailableError)
        self.assertEqual(str(raised.exception), expected_message)

    def test_metrics_settings_mismatch_is_a_broken_config(self):
        with self.assertRaisesRegex(AlertExtractionError, INSIGHT_TYPE_CHANGED_MESSAGE):
            MetricsExtractor().extract(
                _trends_alert(AlertConditionType.ABSOLUTE_VALUE),
                MagicMock(),
                {"kind": "MetricsQuery", "clauses": []},
                ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
            )
