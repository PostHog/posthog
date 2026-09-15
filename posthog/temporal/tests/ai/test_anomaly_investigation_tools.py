from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import (
    BaseMathType,
    ChartDisplayType,
    EventsNode,
    HogQLQuery,
    IntervalType,
    TrendsFilter,
    TrendsQuery,
)

from posthog.caching.insight_result import InsightResult
from posthog.temporal.ai.anomaly_investigation.tools import _run_detector_simulation
from posthog.temporal.ai.anomaly_investigation.workflow import _build_multimodal_context, _evaluated_series_index

from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration
from products.product_analytics.backend.facade.models import Insight


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


@pytest.mark.parametrize("triggered_dates,expected_indices", [(["2026-07-09"], [8]), (["2026-06-01"], [])])
@pytest.mark.parametrize("current_detector_type", ["llm", "mad"])
@patch("products.alerts.backend.judge.llm.LLMSeriesJudge._ask_model")
@patch("products.alerts.backend.evaluation.detector.calculate_for_query_based_insight")
def test_run_detector_simulation_never_rescores_an_ai_alert(
    mock_calculate: MagicMock,
    mock_ask: MagicMock,
    triggered_dates: list[str],
    expected_indices: list[int],
    current_detector_type: str,
) -> None:
    series = [10.0, 11.0, 10.0, 9.0] * 3
    mock_calculate.return_value = InsightResult(
        result=[_trend_result("series 0", series)],
        columns=[],
        timezone="UTC",
        last_refresh=None,
        cache_key="",
        is_cached=False,
    )
    insight = MagicMock(spec=Insight)
    insight.query = TrendsQuery(
        series=[EventsNode(event="series_0", math=BaseMathType.TOTAL)],
        trendsFilter=TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
        interval=IntervalType.DAY,
    ).model_dump()
    alert = MagicMock(spec=AlertConfiguration)
    alert.insight = insight
    alert.config = {"type": "TrendsAlertConfig", "series_index": 0}
    alert.detector_config = {"type": "llm", "threshold": 0.7, "window": 10}
    alert.created_by = None

    result = _run_detector_simulation(alert=alert, team=MagicMock(), date_from=None)

    assert not isinstance(result, str)
    assert result["data"] == series[:-1]
    assert result["triggered_indices"] == []
    alert.detector_config = {"type": current_detector_type, "threshold": 0.7, "window": 10}
    with patch(
        "posthog.temporal.ai.anomaly_investigation.workflow.render_series_chart", return_value=b"chart"
    ) as render:
        context = _build_multimodal_context(
            alert=alert, context_text="Investigate the change.", triggered_dates=triggered_dates
        )
    assert isinstance(context, list)
    assert render.call_args.kwargs["triggered_indices"] == expected_indices
    mock_ask.assert_not_called()


@pytest.mark.parametrize(
    "triggered_metadata,expected_index",
    [({"series_index": 1, "kind": "drop"}, 1), ({"kind": "drop"}, 2), ({"series_index": True}, 2)],
)
def test_investigation_reads_the_series_the_check_judged(triggered_metadata: dict, expected_index: int) -> None:
    # The alert can be repointed while the investigation waits, so the check's own record wins.
    alert = MagicMock(spec=AlertConfiguration)
    alert.config = {"type": "TrendsAlertConfig", "series_index": 2}
    check = MagicMock(spec=AlertCheck)
    check.triggered_metadata = triggered_metadata

    assert _evaluated_series_index(alert, check) == expected_index


@patch("products.alerts.backend.evaluation.hogql.calculate_for_query_based_insight")
def test_run_detector_simulation_scores_the_configured_column_of_a_multi_numeric_sql_result(
    mock_calculate: MagicMock,
) -> None:
    # zscore needs 31 samples; give the series headroom so it scores.
    failure_rate = [10.0 + (i % 7) for i in range(40)]
    run_count = [1800.0 + i for i in range(len(failure_rate))]
    days = [f"2026-07-{(i % 30) + 1:02d}" for i in range(len(failure_rate))]
    # Two numeric columns: without the alert's config the simulation can't pick which one to score.
    rows = [[days[i], failure_rate[i], run_count[i]] for i in range(len(failure_rate))]
    mock_calculate.return_value = InsightResult(
        result=rows,
        columns=["day", "failure_rate_pct", "run_count"],
        timezone="UTC",
        last_refresh=None,
        cache_key="",
        is_cached=False,
    )

    insight = MagicMock(spec=Insight)
    insight.query = HogQLQuery(query="SELECT day, failure_rate_pct, run_count FROM ci_runs").model_dump()
    alert = MagicMock(spec=AlertConfiguration)
    alert.insight = insight
    alert.config = {"type": "HogQLAlertConfig", "column": "failure_rate_pct", "evaluation": "last_row"}
    alert.detector_config = {"type": "zscore", "threshold": 0.9, "window": 7}
    alert.created_by = None

    result = _run_detector_simulation(alert=alert, team=MagicMock(), date_from=None)

    assert not isinstance(result, str)
    # Scores failure_rate_pct, not run_count. The data is the tail of the configured column.
    assert result["data"] == failure_rate[-len(result["data"]) :]
