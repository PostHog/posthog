import pytest
from unittest.mock import MagicMock, patch

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
    NodeKind,
    TrendsFilter,
    TrendsQuery,
)

from posthog.api.services.query import ExecutionMode
from posthog.caching.fetch_from_cache import InsightResult

from products.alerts.backend.evaluation.contract import execution_mode_for_alert
from products.alerts.backend.evaluation.detector import extract_detector_series
from products.alerts.backend.evaluation.dispatcher import _resolve_execution_mode
from products.alerts.backend.evaluation.funnels import FunnelsExtractor
from products.alerts.backend.evaluation.hogql import HogQLExtractor
from products.alerts.backend.evaluation.trends import TrendsExtractor
from products.alerts.backend.models.alert import AlertConfiguration
from products.product_analytics.backend.models.insight import Insight

ALWAYS = ExecutionMode.CALCULATE_BLOCKING_ALWAYS
IF_STALE = ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE
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


@pytest.mark.parametrize(
    "interval,high_frequency,expected",
    [
        (IntervalType.HOUR, False, ALWAYS),  # hourly insight → always fresh (relative-time cache key)
        (IntervalType.HOUR, True, ALWAYS),
        (IntervalType.DAY, False, IF_STALE),  # daily insight, normal cadence → cache is fine
        (IntervalType.DAY, True, ALWAYS),  # high-frequency cadence forces fresh regardless of bucketing
        (None, False, IF_STALE),  # no time axis (funnels/hogql), normal cadence → cache
        (None, True, ALWAYS),  # no time axis but high-frequency → fresh
    ],
)
def test_execution_mode_for_alert(interval, high_frequency, expected):
    assert execution_mode_for_alert(interval, high_frequency=high_frequency) == expected


@pytest.mark.parametrize(
    "interval,expected",
    [
        (AlertCalculationInterval.EVERY_15_MINUTES, True),
        (AlertCalculationInterval.HOURLY, False),
        (AlertCalculationInterval.DAILY, False),
        (None, False),
    ],
)
def test_is_high_frequency_interval_property(interval, expected):
    assert AlertConfiguration(calculation_interval=interval).is_high_frequency_interval is expected


# The freshness decision lives in the dispatcher's _resolve_execution_mode — one site for every kind.
# Only trends/detector escalate on hourly buckets (real time axis); funnels/hogql have none, so for
# them the every-15-minutes cadence is the only fresh-recompute trigger.
@pytest.mark.parametrize(
    "kind,interval,high_frequency,expected",
    [
        (NodeKind.TRENDS_QUERY, "hour", False, ALWAYS),
        (NodeKind.TRENDS_QUERY, "day", False, IF_STALE),
        (NodeKind.TRENDS_QUERY, "day", True, ALWAYS),
        (NodeKind.TRENDS_QUERY, None, False, IF_STALE),  # missing interval reads as None → same as the DAY default
        (NodeKind.TRENDS_QUERY, None, True, ALWAYS),
        (NodeKind.FUNNELS_QUERY, None, False, IF_STALE),
        (NodeKind.FUNNELS_QUERY, None, True, ALWAYS),
        (NodeKind.HOG_QL_QUERY, None, False, IF_STALE),
        (NodeKind.HOG_QL_QUERY, None, True, ALWAYS),
    ],
)
def test_resolve_execution_mode(kind, interval, high_frequency, expected):
    alert = MagicMock()
    alert.is_high_frequency_interval = high_frequency
    query = {"kind": kind, "interval": interval} if interval is not None else {"kind": kind}
    assert _resolve_execution_mode(alert, kind, query) == expected


def _trends_forward(mode):
    TrendsExtractor().extract(_trends_alert(high_frequency=False), MagicMock(spec=Insight), _day_query(), mode)


def _detector_forward(mode):
    extract_detector_series(MagicMock(spec=Insight), MagicMock(), _day_query(), ZSCORE_DETECTOR_CONFIG, mode)


def _funnels_forward(mode):
    alert = MagicMock()
    alert.config = {"type": "FunnelsAlertConfig", "metric": "conversion_from_start", "funnel_step": None}
    alert.condition = {"type": AlertConditionType.ABSOLUTE_VALUE}
    query = {"kind": "FunnelsQuery", "series": [{"kind": "EventsNode", "event": "step_a"}]}
    FunnelsExtractor().extract(alert, MagicMock(), query, mode)


def _hogql_forward(mode):
    alert = MagicMock()
    alert.condition = {"type": AlertConditionType.ABSOLUTE_VALUE}
    alert.config = {"type": "HogQLAlertConfig", "evaluation": "last_row"}
    HogQLExtractor().extract(alert, MagicMock(), MagicMock(), mode)


# (calc-path to patch, the result that path returns, a thunk that drives the extractor for one kind).
EXTRACTOR_FORWARDING_CASES = [
    pytest.param(
        "products.alerts.backend.evaluation.trends.calculate_for_query_based_insight",
        EMPTY_RESULT,
        _trends_forward,
        id="trends",
    ),
    pytest.param(
        "products.alerts.backend.evaluation.detector.calculate_for_query_based_insight",
        EMPTY_RESULT,
        _detector_forward,
        id="detector",
    ),
    pytest.param(
        "products.alerts.backend.evaluation.funnels.calculate_for_query_based_insight",
        MagicMock(result=[{"order": 0, "count": 100, "breakdown_value": None}]),
        _funnels_forward,
        id="funnels",
    ),
    pytest.param(
        "products.alerts.backend.evaluation.hogql.calculate_for_query_based_insight",
        MagicMock(result=[[5.0], [6.0]], columns=["value"]),
        _hogql_forward,
        id="hogql",
    ),
]


# Every extractor forwards the mode it's handed (the dispatcher decides it) straight to the query layer.
@pytest.mark.parametrize("mode", [ALWAYS, IF_STALE])
@pytest.mark.parametrize("calc_path,calc_result,forward", EXTRACTOR_FORWARDING_CASES)
def test_extractor_forwards_execution_mode(calc_path, calc_result, forward, mode):
    with patch(calc_path) as mock_calc:
        mock_calc.return_value = calc_result
        forward(mode)
        assert mock_calc.call_args.kwargs["execution_mode"] == mode
