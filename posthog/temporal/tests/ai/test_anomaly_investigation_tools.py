from typing import Any

from unittest.mock import MagicMock, patch

from posthog.schema import BaseMathType, ChartDisplayType, EventsNode, IntervalType, TrendsFilter, TrendsQuery

from posthog.caching.fetch_from_cache import InsightResult
from posthog.temporal.ai.anomaly_investigation.tools import _run_detector_simulation

from products.alerts.backend.models.alert import AlertConfiguration
from products.product_analytics.backend.models.insight import Insight


def _trend_result(label: str, data: list[float]) -> dict[str, Any]:
    dates = [f"2026-07-{day:02d}" for day in range(1, len(data) + 1)]
    return {"data": data, "days": dates, "label": label}


@patch("products.alerts.backend.evaluation.detector.calculate_for_query_based_insight")
def test_run_detector_simulation_returns_the_alerts_configured_series(mock_calculate: MagicMock) -> None:
    configured_series = [1000.0, 1100.0, 1000.0, 900.0] * 3
    mock_calculate.return_value = InsightResult(
        result=[
            _trend_result("series 0", [10.0, 11.0, 10.0, 9.0] * 3),
            _trend_result("series 1", [100.0, 110.0, 100.0, 90.0] * 3),
            _trend_result("series 2", configured_series),
        ],
        columns=[],
        timezone="UTC",
        last_refresh=None,
        cache_key="",
        is_cached=False,
    )

    insight = MagicMock(spec=Insight)
    insight.query = TrendsQuery(
        series=[
            EventsNode(event="series_0", math=BaseMathType.TOTAL),
            EventsNode(event="series_1", math=BaseMathType.TOTAL),
            EventsNode(event="series_2", math=BaseMathType.TOTAL),
        ],
        trendsFilter=TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
        interval=IntervalType.DAY,
    ).model_dump()
    alert = MagicMock(spec=AlertConfiguration)
    alert.insight = insight
    alert.config = {"type": "TrendsAlertConfig", "series_index": 2}
    alert.detector_config = {"type": "zscore", "threshold": 0.9, "window": 10}
    alert.created_by = None

    result = _run_detector_simulation(alert=alert, team=MagicMock(), date_from=None)

    assert not isinstance(result, str)
    assert result["data"] == configured_series[:-1]
