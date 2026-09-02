import json
from datetime import datetime, timedelta
from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

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
from posthog.temporal.ai.anomaly_investigation.tools import (
    MAX_SERIES_POINTS,
    FetchMetricSeriesArgs,
    InvestigationToolkit,
    _run_detector_simulation,
    _seasonal_baselines,
)

from products.alerts.backend.models.alert import AlertConfiguration
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


def _hourly_series(days: int) -> tuple[list[Any], list[float]]:
    # One bucket per hour, ending on a midnight bucket. Each value encodes its own day and hour,
    # so a baseline read off the wrong bucket is visible in the value.
    start = datetime(2026, 8, 17)
    labels: list[Any] = [start + timedelta(hours=hour) for hour in range(days * 24 + 1)]
    values = [float(hour // 24 * 100 + hour % 24) for hour in range(days * 24 + 1)]
    return labels, values


@parameterized.expand([("contiguous", None), ("one bucket missing", 250)])
def test_seasonal_baselines_read_the_same_hour_on_prior_days(_name: str, dropped_index: int | None) -> None:
    labels, values = _hourly_series(days=14)
    if dropped_index is not None:
        del labels[dropped_index]
        del values[dropped_index]

    baselines = _seasonal_baselines(labels, values, "hour")

    assert baselines is not None
    assert baselines["newest_bucket"]["value"] == 1400.0
    # Midnight on each of the 14 prior days — never a daytime bucket of a nearby day.
    assert [p["value"] for p in baselines["same_time_of_day_prior_days"]] == [day * 100.0 for day in range(14)]
    # Reaches 7 and 14 days back, both further than MAX_SERIES_POINTS hourly buckets.
    assert [p["value"] for p in baselines["same_weekday_prior_weeks"]] == [0.0, 700.0]


async def test_fetch_metric_series_flags_truncation_and_keeps_baselines_from_the_dropped_span() -> None:
    labels, values = _hourly_series(days=14)
    alert = MagicMock(spec=AlertConfiguration)
    alert.insight_id = 7
    toolkit = InvestigationToolkit(team=MagicMock(), alert=alert)

    with patch(
        "posthog.temporal.ai.anomaly_investigation.tools._run_detector_simulation",
        return_value={"dates": labels, "data": values, "interval": "hour"},
    ):
        payload = json.loads(await toolkit.fetch_metric_series(FetchMetricSeriesArgs()))

    assert payload["truncated"] is True
    assert len(payload["values"]) == MAX_SERIES_POINTS
    assert payload["point_count"] == len(values)
    # The same-weekday buckets sit outside the returned window, so the agent could not have
    # recovered them from `values`.
    assert [p["value"] for p in payload["seasonal_baselines"]["same_weekday_prior_weeks"]] == [0.0, 700.0]
    assert payload["values"][0] not in (0.0, 700.0)
