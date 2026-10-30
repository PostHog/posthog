from datetime import UTC, datetime, timedelta

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
from posthog.caching.insight_result import InsightResult
from posthog.interval_specs import interval_spec

from products.alerts.backend.evaluation.contract import cache_age_seconds_for_alert, execution_mode_for_alert
from products.alerts.backend.evaluation.detector import extract_detector_series
from products.alerts.backend.evaluation.dispatcher import _resolve_cache_age_seconds, _resolve_execution_mode
from products.alerts.backend.evaluation.funnels import FunnelsExtractor
from products.alerts.backend.evaluation.hogql import HogQLExtractor
from products.alerts.backend.evaluation.trends import TrendsExtractor
from products.alerts.backend.models.alert import AlertConfiguration
from products.product_analytics.backend.facade.models import Insight

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
    alert.evaluation_delay_intervals = 0
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


def _trends_forward(mode, cache_age_seconds):
    TrendsExtractor().extract(
        _trends_alert(high_frequency=False), MagicMock(spec=Insight), _day_query(), mode, cache_age_seconds
    )


def _detector_forward(mode, cache_age_seconds):
    extract_detector_series(
        MagicMock(spec=Insight),
        MagicMock(),
        _day_query(),
        ZSCORE_DETECTOR_CONFIG,
        mode,
        cache_age_seconds=cache_age_seconds,
    )


def _funnels_forward(mode, cache_age_seconds):
    alert = MagicMock()
    alert.config = {"type": "FunnelsAlertConfig", "metric": "conversion_from_start", "funnel_step": None}
    alert.condition = {"type": AlertConditionType.ABSOLUTE_VALUE}
    query = {"kind": "FunnelsQuery", "series": [{"kind": "EventsNode", "event": "step_a"}]}
    FunnelsExtractor().extract(alert, MagicMock(), query, mode, cache_age_seconds)


def _hogql_forward(mode, cache_age_seconds):
    alert = MagicMock()
    alert.condition = {"type": AlertConditionType.ABSOLUTE_VALUE}
    alert.config = {"type": "HogQLAlertConfig", "evaluation": "last_row"}
    HogQLExtractor().extract(alert, MagicMock(), MagicMock(), mode, cache_age_seconds)


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
        MagicMock(result=[[5.0], [6.0]], columns=["value"], has_more=False),
        _hogql_forward,
        id="hogql",
    ),
]


# Every extractor forwards the mode and cache age it's handed straight to the query layer.
@pytest.mark.parametrize("mode", [ALWAYS, IF_STALE])
@pytest.mark.parametrize("calc_path,calc_result,forward", EXTRACTOR_FORWARDING_CASES)
def test_extractor_forwards_execution_mode(calc_path, calc_result, forward, mode):
    with patch(calc_path) as mock_calc:
        mock_calc.return_value = calc_result
        forward(mode, 73)
        assert mock_calc.call_args.kwargs["execution_mode"] == mode
        assert mock_calc.call_args.kwargs["cache_age_seconds"] == 73


def _team(timezone: str) -> MagicMock:
    team = MagicMock()
    team.timezone = timezone
    team.week_start_day = None
    return team


@pytest.mark.parametrize(
    "previous_check,current_check,reusable",
    [
        pytest.param(
            datetime(2026, 10, 28, 21, 1, 20, tzinfo=UTC),
            datetime(2026, 10, 28, 22, 1, 13, tzinfo=UTC),
            False,
            id="gap-just-under-an-hour",
        ),
        pytest.param(
            datetime(2026, 10, 28, 4, 50, 5, tzinfo=UTC),
            datetime(2026, 10, 28, 5, 0, 30, tzinfo=UTC),
            False,
            id="gap-compressed-by-a-quiet-window",
        ),
        pytest.param(
            datetime(2026, 10, 28, 22, 1, 13, tzinfo=UTC),
            datetime(2026, 10, 28, 22, 1, 40, tzinfo=UTC),
            True,
            id="retry-inside-the-same-bucket",
        ),
    ],
)
def test_hourly_cache_age_tracks_the_bucket_not_the_gap(previous_check, current_check, reusable):
    limit = cache_age_seconds_for_alert(IntervalType.HOUR, now=current_check, team=_team("UTC"))
    assert limit is not None
    assert ((current_check - previous_check).total_seconds() <= limit) is reusable


@pytest.mark.parametrize(
    "interval,timezone,now,expected",
    [
        (IntervalType.HOUR, "UTC", datetime(2026, 10, 28, 22, 1, 13, tzinfo=UTC), 73),
        # Half-hour offset: hour buckets open at :30 past the UTC hour.
        (IntervalType.HOUR, "Asia/Kolkata", datetime(2026, 10, 28, 22, 1, 13, tzinfo=UTC), 1873),
        (IntervalType.HOUR, "Asia/Kolkata", datetime(2026, 10, 28, 22, 31, 13, tzinfo=UTC), 73),
        (IntervalType.DAY, "Asia/Bangkok", datetime(2026, 10, 28, 22, 1, 13, tzinfo=UTC), 18073),
        (None, "UTC", datetime(2026, 10, 28, 22, 1, 13, tzinfo=UTC), None),
        (IntervalType.SECOND, "UTC", datetime(2026, 10, 28, 22, 1, 13, tzinfo=UTC), None),
    ],
)
def test_cache_age_seconds_for_alert(interval, timezone, now, expected):
    assert cache_age_seconds_for_alert(interval, now=now, team=_team(timezone)) == expected


@pytest.mark.parametrize("interval", [i for i in IntervalType if interval_spec(i).staleness_default is not None])
@pytest.mark.parametrize("hours_into_bucket", [0, 5, 23, 24 * 20])
def test_cache_age_never_exceeds_the_shared_threshold(interval, hours_into_bucket):
    shared_threshold = interval_spec(interval).staleness_default
    assert shared_threshold is not None
    now = datetime(2026, 3, 1, tzinfo=UTC) + timedelta(hours=hours_into_bucket)
    limit = cache_age_seconds_for_alert(interval, now=now, team=_team("UTC"))
    assert limit is not None
    assert limit <= shared_threshold.total_seconds()


@pytest.mark.parametrize(
    "kind,interval,execution_mode,expects_limit,date_to",
    [
        (NodeKind.FUNNELS_QUERY, "hour", IF_STALE, True, None),
        (NodeKind.TRENDS_QUERY, "day", IF_STALE, True, None),
        (NodeKind.FUNNELS_QUERY, "hour", IF_STALE, True, "-1d"),
        (NodeKind.FUNNELS_QUERY, "hour", IF_STALE, False, "2020-01-01"),
        (NodeKind.METRICS_QUERY, "hour", IF_STALE, False, None),
        (NodeKind.METRICS_QUERY, "day", IF_STALE, False, None),
        (NodeKind.METRICS_QUERY, "minute_5", IF_STALE, False, None),
        (NodeKind.METRICS_QUERY, "$window", IF_STALE, False, None),
        (NodeKind.HOG_QL_QUERY, None, IF_STALE, False, None),
        (NodeKind.FUNNELS_QUERY, "hour", ALWAYS, False, None),
    ],
)
def test_resolve_cache_age_seconds(kind, interval, execution_mode, expects_limit, date_to):
    alert = MagicMock()
    alert.team = _team("UTC")
    query: dict = {"kind": kind}
    if interval is not None:
        query["interval"] = interval
    if date_to is not None:
        query["dateRange"] = {"date_to": date_to}
    assert (_resolve_cache_age_seconds(alert, query, execution_mode) is not None) is expects_limit
