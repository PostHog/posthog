from typing import Any

from unittest.mock import MagicMock, patch

from posthog.schema import (
    AlertCalculationInterval,
    BaseMathType,
    Breakdown,
    BreakdownFilter,
    ChartDisplayType,
    EventsNode,
    IntervalType,
    TrendsFilter,
    TrendsQuery,
)

from posthog.caching.fetch_from_cache import InsightResult
from posthog.models import AlertConfiguration, Insight
from posthog.tasks.alerts.detector import (
    MAX_DETECTOR_BREAKDOWN_VALUES,
    check_trends_alert_with_detector,
    simulate_detector_on_insight,
)


def _make_trend_result(label: str, data: list[float], breakdown_value: str = "") -> dict[str, Any]:
    days = [f"2024-06-{i + 1:02d}" for i in range(len(data))]
    return {
        "action": {},
        "actions": [],
        "count": sum(data),
        "data": data,
        "days": days,
        "dates": days,
        "label": label,
        "labels": days,
        "breakdown_value": breakdown_value or label,
        "status": None,
        "compare_label": None,
        "compare": False,
        "persons_urls": [],
        "persons": {},
        "filter": {},
    }


def _make_query_with_breakdown() -> TrendsQuery:
    return TrendsQuery(
        series=[EventsNode(event="signed_up", math=BaseMathType.TOTAL)],
        breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="origin")]),
        trendsFilter=TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
        interval=IntervalType.DAY,
    )


def _make_query_without_breakdown() -> TrendsQuery:
    return TrendsQuery(
        series=[EventsNode(event="signed_up", math=BaseMathType.TOTAL)],
        trendsFilter=TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
        interval=IntervalType.DAY,
    )


def _make_alert(team: MagicMock, detector_config: dict[str, Any], series_index: int = 0) -> MagicMock:
    alert = MagicMock(spec=AlertConfiguration)
    alert.id = "test-alert-id"
    alert.team = team
    alert.config = {"type": "TrendsAlertConfig", "series_index": series_index}
    alert.detector_config = detector_config
    alert.calculation_interval = AlertCalculationInterval.DAILY
    return alert


# Stable data: all values ~10, no anomaly expected
STABLE_DATA = [10.0, 11.0, 10.0, 9.0, 10.0, 11.0, 10.0, 9.0, 10.0, 11.0, 10.0, 9.0]
# Data with a clear anomaly spike near the end (penultimate position so it
# survives the "drop last incomplete interval" trim applied to time-series data)
ANOMALOUS_DATA = [10.0, 11.0, 10.0, 9.0, 10.0, 11.0, 10.0, 9.0, 10.0, 11.0, 100.0, 10.0]

ZSCORE_DETECTOR_CONFIG = {"type": "zscore", "threshold": 0.9, "window": 10}


class TestCheckTrendsAlertWithDetectorBreakdowns:
    @patch("posthog.tasks.alerts.detector.calculate_for_query_based_insight")
    def test_fires_when_one_breakdown_is_anomalous(self, mock_calc: MagicMock) -> None:
        mock_calc.return_value = InsightResult(
            result=[
                _make_trend_result("swap", STABLE_DATA, "swap"),
                _make_trend_result("staking", ANOMALOUS_DATA, "staking"),
            ],
            columns=[],
            timezone="UTC",
            last_refresh=None,
            cache_key="",
            is_cached=False,
        )

        team = MagicMock()
        alert = _make_alert(team, ZSCORE_DETECTOR_CONFIG)
        insight = MagicMock(spec=Insight)
        query = _make_query_with_breakdown()

        result = check_trends_alert_with_detector(alert, insight, query, ZSCORE_DETECTOR_CONFIG)

        assert result.breaches is not None and len(result.breaches) > 0
        assert "staking" in result.breaches[0]
        assert "Anomaly detected" in result.breaches[0]
        # "staking" is at index 1 in the breakdown results
        assert result.triggered_metadata == {"series_index": 1}

    @patch("posthog.tasks.alerts.detector.calculate_for_query_based_insight")
    def test_does_not_fire_when_all_breakdowns_are_normal(self, mock_calc: MagicMock) -> None:
        mock_calc.return_value = InsightResult(
            result=[
                _make_trend_result("swap", STABLE_DATA, "swap"),
                _make_trend_result("staking", STABLE_DATA, "staking"),
                _make_trend_result("lending", STABLE_DATA, "lending"),
            ],
            columns=[],
            timezone="UTC",
            last_refresh=None,
            cache_key="",
            is_cached=False,
        )

        team = MagicMock()
        alert = _make_alert(team, ZSCORE_DETECTOR_CONFIG)
        insight = MagicMock(spec=Insight)
        query = _make_query_with_breakdown()

        result = check_trends_alert_with_detector(alert, insight, query, ZSCORE_DETECTOR_CONFIG)

        assert result.breaches == []
        assert result.value is None

    @patch("posthog.tasks.alerts.detector.calculate_for_query_based_insight")
    def test_caps_at_max_breakdown_values(self, mock_calc: MagicMock) -> None:
        # Create more than MAX_DETECTOR_BREAKDOWN_VALUES breakdown results
        # Put the anomaly in the last one (beyond the cap)
        breakdown_results = [
            _make_trend_result(f"origin_{i}", STABLE_DATA, f"origin_{i}")
            for i in range(MAX_DETECTOR_BREAKDOWN_VALUES + 2)
        ]
        # Make the one beyond the cap anomalous
        breakdown_results[MAX_DETECTOR_BREAKDOWN_VALUES] = _make_trend_result(
            f"origin_{MAX_DETECTOR_BREAKDOWN_VALUES}", ANOMALOUS_DATA, f"origin_{MAX_DETECTOR_BREAKDOWN_VALUES}"
        )

        mock_calc.return_value = InsightResult(
            result=breakdown_results,
            columns=[],
            timezone="UTC",
            last_refresh=None,
            cache_key="",
            is_cached=False,
        )

        team = MagicMock()
        alert = _make_alert(team, ZSCORE_DETECTOR_CONFIG)
        insight = MagicMock(spec=Insight)
        query = _make_query_with_breakdown()

        result = check_trends_alert_with_detector(alert, insight, query, ZSCORE_DETECTOR_CONFIG)

        # The anomalous breakdown is beyond the cap, so it should NOT fire
        assert result.breaches == []

    @patch("posthog.tasks.alerts.detector.calculate_for_query_based_insight")
    def test_skips_breakdown_with_insufficient_data(self, mock_calc: MagicMock) -> None:
        mock_calc.return_value = InsightResult(
            result=[
                _make_trend_result("swap", [5.0], "swap"),  # only 1 data point — should be skipped
                _make_trend_result("staking", STABLE_DATA, "staking"),
            ],
            columns=[],
            timezone="UTC",
            last_refresh=None,
            cache_key="",
            is_cached=False,
        )

        team = MagicMock()
        alert = _make_alert(team, ZSCORE_DETECTOR_CONFIG)
        insight = MagicMock(spec=Insight)
        query = _make_query_with_breakdown()

        result = check_trends_alert_with_detector(alert, insight, query, ZSCORE_DETECTOR_CONFIG)

        # Should not error, and should not fire (stable data only)
        assert result.breaches == []

    @patch("posthog.tasks.alerts.detector.calculate_for_query_based_insight")
    def test_non_breakdown_still_works(self, mock_calc: MagicMock) -> None:
        mock_calc.return_value = InsightResult(
            result=[
                _make_trend_result("signed_up", ANOMALOUS_DATA, ""),
            ],
            columns=[],
            timezone="UTC",
            last_refresh=None,
            cache_key="",
            is_cached=False,
        )

        team = MagicMock()
        alert = _make_alert(team, ZSCORE_DETECTOR_CONFIG)
        insight = MagicMock(spec=Insight)
        query = _make_query_without_breakdown()

        result = check_trends_alert_with_detector(alert, insight, query, ZSCORE_DETECTOR_CONFIG)

        assert result.breaches is not None and len(result.breaches) > 0
        assert "Anomaly detected" in result.breaches[0]
        # Non-breakdown alerts should not set triggered_metadata
        assert result.triggered_metadata is None

    @patch("posthog.tasks.alerts.detector.calculate_for_query_based_insight")
    def test_breakdown_result_includes_anomaly_scores(self, mock_calc: MagicMock) -> None:
        mock_calc.return_value = InsightResult(
            result=[
                _make_trend_result("staking", ANOMALOUS_DATA, "staking"),
            ],
            columns=[],
            timezone="UTC",
            last_refresh=None,
            cache_key="",
            is_cached=False,
        )

        team = MagicMock()
        alert = _make_alert(team, ZSCORE_DETECTOR_CONFIG)
        insight = MagicMock(spec=Insight)
        query = _make_query_with_breakdown()

        result = check_trends_alert_with_detector(alert, insight, query, ZSCORE_DETECTOR_CONFIG)

        assert result.anomaly_scores is not None
        assert result.triggered_points is not None
        assert result.interval == "day"


class TestSimulateDetectorBreakdowns:
    @patch("posthog.tasks.alerts.detector.upgrade_query")
    @patch("posthog.tasks.alerts.detector.calculate_for_query_based_insight")
    def test_returns_breakdown_results(self, mock_calc: MagicMock, _mock_upgrade: MagicMock) -> None:
        mock_calc.return_value = InsightResult(
            result=[
                _make_trend_result("swap", STABLE_DATA, "swap"),
                _make_trend_result("staking", ANOMALOUS_DATA, "staking"),
            ],
            columns=[],
            timezone="UTC",
            last_refresh=None,
            cache_key="",
            is_cached=False,
        )

        insight = MagicMock(spec=Insight)
        insight.query = _make_query_with_breakdown().model_dump()
        team = MagicMock()

        result = simulate_detector_on_insight(
            insight=insight,
            team=team,
            detector_config=ZSCORE_DETECTOR_CONFIG,
        )

        assert "breakdown_results" in result
        assert len(result["breakdown_results"]) == 2
        assert result["breakdown_results"][0]["label"] == "swap"
        assert result["breakdown_results"][1]["label"] == "staking"
        # Aggregated totals (each series has 1 point dropped for the incomplete current interval)
        assert result["total_points"] == (len(STABLE_DATA) - 1) + (len(ANOMALOUS_DATA) - 1)

    @patch("posthog.tasks.alerts.detector.upgrade_query")
    @patch("posthog.tasks.alerts.detector.calculate_for_query_based_insight")
    def test_non_breakdown_has_no_breakdown_results(self, mock_calc: MagicMock, _mock_upgrade: MagicMock) -> None:
        mock_calc.return_value = InsightResult(
            result=[
                _make_trend_result("signed_up", STABLE_DATA, ""),
            ],
            columns=[],
            timezone="UTC",
            last_refresh=None,
            cache_key="",
            is_cached=False,
        )

        insight = MagicMock(spec=Insight)
        insight.query = _make_query_without_breakdown().model_dump()
        team = MagicMock()

        result = simulate_detector_on_insight(
            insight=insight,
            team=team,
            detector_config=ZSCORE_DETECTOR_CONFIG,
        )

        assert "breakdown_results" not in result

    @patch("posthog.tasks.alerts.detector.upgrade_query")
    @patch("posthog.tasks.alerts.detector.calculate_for_query_based_insight")
    def test_caps_breakdown_simulations(self, mock_calc: MagicMock, _mock_upgrade: MagicMock) -> None:
        breakdown_results = [
            _make_trend_result(f"origin_{i}", STABLE_DATA, f"origin_{i}")
            for i in range(MAX_DETECTOR_BREAKDOWN_VALUES + 5)
        ]

        mock_calc.return_value = InsightResult(
            result=breakdown_results,
            columns=[],
            timezone="UTC",
            last_refresh=None,
            cache_key="",
            is_cached=False,
        )

        insight = MagicMock(spec=Insight)
        insight.query = _make_query_with_breakdown().model_dump()
        team = MagicMock()

        result = simulate_detector_on_insight(
            insight=insight,
            team=team,
            detector_config=ZSCORE_DETECTOR_CONFIG,
        )

        assert len(result["breakdown_results"]) == MAX_DETECTOR_BREAKDOWN_VALUES
