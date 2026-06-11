from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import (
    AlertCalculationInterval,
    AlertCondition,
    AlertConditionType,
    BaseMathType,
    ChartDisplayType,
    EventsNode,
    InsightsThresholdBounds,
    InsightThreshold,
    InsightThresholdType,
    IntervalType,
    TrendsFilter,
    TrendsQuery,
)

from posthog.api.services.query import ExecutionMode
from posthog.caching.fetch_from_cache import InsightResult

from products.alerts.backend.evaluation.detector import extract_detector_series
from products.alerts.backend.evaluation.trends import TrendsExtractor
from products.alerts.backend.models.alert import AlertConfiguration
from products.product_analytics.backend.models.insight import Insight

ZSCORE_DETECTOR_CONFIG = {"type": "zscore", "threshold": 0.9, "window": 10}
EMPTY_RESULT = InsightResult(result=[], columns=[], timezone="UTC", last_refresh=None, cache_key="", is_cached=False)


def _day_query() -> TrendsQuery:
    # Daily bucketing: without the high-frequency cadence this would reuse the recent-results cache.
    return TrendsQuery(
        series=[EventsNode(event="signed_up", math=BaseMathType.TOTAL)],
        trendsFilter=TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
        interval=IntervalType.DAY,
    )


def _trends_alert(*, high_frequency: bool) -> MagicMock:
    alert = MagicMock(spec=AlertConfiguration)
    alert.team = MagicMock()
    alert.config = {"type": "TrendsAlertConfig", "series_index": 0}
    alert.condition = AlertCondition(type=AlertConditionType.ABSOLUTE_VALUE).model_dump()
    threshold = MagicMock()
    threshold.configuration = InsightThreshold(
        type=InsightThresholdType.ABSOLUTE, bounds=InsightsThresholdBounds(lower=1)
    ).model_dump()
    alert.threshold = threshold
    alert.is_high_frequency_interval = high_frequency
    return alert


class TestHighFrequencyFreshness:
    @parameterized.expand(
        [
            (AlertCalculationInterval.EVERY_15_MINUTES, True),
            (AlertCalculationInterval.HOURLY, False),
            (AlertCalculationInterval.DAILY, False),
        ]
    )
    def test_is_high_frequency_interval_property(self, interval: AlertCalculationInterval, expected: bool) -> None:
        assert AlertConfiguration(calculation_interval=interval).is_high_frequency_interval is expected

    @parameterized.expand(
        [
            (True, ExecutionMode.CALCULATE_BLOCKING_ALWAYS),
            (False, ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE),
        ]
    )
    @patch("products.alerts.backend.evaluation.trends.calculate_for_query_based_insight")
    def test_trends_extractor_forces_fresh_for_high_frequency(
        self, high_frequency: bool, expected_mode: ExecutionMode, mock_calc: MagicMock
    ) -> None:
        # A daily-bucketed insight would otherwise use the cache; the 15-min cadence forces fresh.
        mock_calc.return_value = EMPTY_RESULT
        TrendsExtractor().extract(_trends_alert(high_frequency=high_frequency), MagicMock(spec=Insight), _day_query())
        assert mock_calc.call_args.kwargs["execution_mode"] == expected_mode

    @parameterized.expand(
        [
            (True, ExecutionMode.CALCULATE_BLOCKING_ALWAYS),
            (False, ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE),
        ]
    )
    @patch("products.alerts.backend.evaluation.detector.calculate_for_query_based_insight")
    def test_detector_extractor_forces_fresh_for_high_frequency(
        self, high_frequency: bool, expected_mode: ExecutionMode, mock_calc: MagicMock
    ) -> None:
        mock_calc.return_value = EMPTY_RESULT
        extract_detector_series(
            MagicMock(spec=Insight),
            MagicMock(),
            _day_query(),
            ZSCORE_DETECTOR_CONFIG,
            high_frequency=high_frequency,
        )
        assert mock_calc.call_args.kwargs["execution_mode"] == expected_mode
