import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import AlertConditionType

from posthog.api.services.query import ExecutionMode

from products.alerts.backend.evaluation.contract import AlertExtractionError
from products.alerts.backend.evaluation.funnels import FunnelsExtractor

CALC_PATH = "products.alerts.backend.evaluation.funnels.calculate_for_query_based_insight"
IF_STALE = ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE


def _steps(*counts: int) -> list[dict]:
    return [{"order": i, "count": c, "breakdown_value": None} for i, c in enumerate(counts)]


def _query(viz: str | None = None) -> dict:
    query: dict = {
        "kind": "FunnelsQuery",
        "series": [{"kind": "EventsNode", "event": "step_a"}, {"kind": "EventsNode", "event": "step_b"}],
    }
    if viz is not None:
        query["funnelsFilter"] = {"funnelVizType": viz}
    return query


def _alert(config: dict | None = None, condition_type: str = AlertConditionType.ABSOLUTE_VALUE) -> MagicMock:
    alert = MagicMock()
    alert.config = config or {"type": "FunnelsAlertConfig", "metric": "conversion_from_start", "funnel_step": None}
    alert.condition = {"type": condition_type}
    return alert


def _extract(
    result, *, config: dict | None = None, viz: str | None = None, condition_type=AlertConditionType.ABSOLUTE_VALUE
):
    with patch(CALC_PATH) as calc:
        calc.return_value = MagicMock(result=result)
        return FunnelsExtractor().extract(_alert(config, condition_type), MagicMock(), _query(viz), IF_STALE)


def _config(metric: str = "conversion_from_start", funnel_step: int | None = None) -> dict:
    return {"type": "FunnelsAlertConfig", "metric": metric, "funnel_step": funnel_step}


@pytest.mark.parametrize(
    "counts,config,expected",
    [
        ((100, 40), None, 40.0),  # from_start, last step: 40/100
        ((100, 50, 30), _config("conversion_from_previous", 2), 60.0),  # step-over-step: 30/50
        ((200, 50, 10), _config("conversion_from_start", 1), 25.0),  # from_start at step 1: 50/200
        ((0, 0), None, 0.0),  # zero base → 0 rate
    ],
)
def test_conversion_rate(counts, config, expected):
    result = _extract(_steps(*counts), config=config)
    assert result.series[0].points[0].value == expected


def test_result_is_unframed_single_series():
    result = _extract(_steps(100, 40))
    assert result.subject == "The funnel conversion rate"
    assert result.framed is False
    assert result.is_breakdown is False


@pytest.mark.parametrize(
    "result,config,viz,condition_type,match",
    [
        (_steps(100, 40), _config("conversion_from_start", 5), None, AlertConditionType.ABSOLUTE_VALUE, "out of range"),
        (
            _steps(100, 40),
            _config("conversion_from_previous", 0),
            None,
            AlertConditionType.ABSOLUTE_VALUE,
            "undefined at the first step",
        ),
        (_steps(100, 40), None, None, AlertConditionType.RELATIVE_INCREASE, "absolute value conditions"),
        (_steps(100, 40), None, None, AlertConditionType.RELATIVE_DECREASE, "absolute value conditions"),
        ([], None, None, AlertConditionType.ABSOLUTE_VALUE, "no data"),
        ([{"order": 0}, {"order": 1}], None, None, AlertConditionType.ABSOLUTE_VALUE, "non-numeric count"),
        ([{"order": 0, "count": 100}, "broken"], None, None, AlertConditionType.ABSOLUTE_VALUE, "malformed"),
    ],
)
def test_extract_raises_extraction_error(result, config, viz, condition_type, match):
    with pytest.raises(AlertExtractionError, match=match):
        _extract(result, config=config, viz=viz, condition_type=condition_type)


def test_none_result_raises_runtime_error():
    # A None result means the query layer swallowed an error — surface it as RuntimeError (not
    # AlertExtractionError) so it routes to the harder failure path, matching the other extractors.
    with pytest.raises(RuntimeError, match="No results found"):
        _extract(None)


# --- Trends funnel (historical conversion-rate time series) ---


def _trends_series(data: list[float], *, breakdown_value=None) -> dict:
    days = [f"2024-01-0{i + 1}" for i in range(len(data))]
    series: dict = {"count": len(data), "data": data, "days": days, "labels": days}
    if breakdown_value is not None:
        series["breakdown_value"] = breakdown_value
    return series


def test_trends_funnel_evaluates_latest_period():
    # A trends funnel is a time series of conversion rates; the alert evaluates the most recent period.
    result = _extract([_trends_series([10.0, 25.0, 40.0])], viz="trends")
    assert result.subject == "The funnel conversion rate"
    assert result.unit == "%"
    assert result.is_breakdown is False
    assert result.series[0].points[result.series[0].current_index].value == 40.0


def test_trends_funnel_breakdown_yields_one_series_per_value():
    result = _extract(
        [
            _trends_series([10.0, 40.0], breakdown_value=["Chrome"]),
            _trends_series([5.0, 20.0], breakdown_value=["Safari"]),
        ],
        viz="trends",
    )
    assert result.is_breakdown is True
    assert {s.label: s.points[s.current_index].value for s in result.series} == {"Chrome": 40.0, "Safari": 20.0}


def test_trends_funnel_compare_evaluates_current_period_only():
    current = {**_trends_series([10.0, 40.0]), "compare_label": "current"}
    previous = {**_trends_series([8.0, 30.0]), "compare_label": "previous"}
    result = _extract([current, previous], viz="trends")
    assert len(result.series) == 1
    assert result.series[0].points[result.series[0].current_index].value == 40.0


def test_trends_funnel_empty_result_raises_extraction_error():
    with pytest.raises(AlertExtractionError, match="no data"):
        _extract([], viz="trends")


# --- Time-to-convert funnel (average conversion time) ---


def test_time_to_convert_funnel_evaluates_average_seconds():
    result = _extract(
        {"bins": [[600, 3], [1200, 1]], "average_conversion_time": 840.0, "median_conversion_time": 600.0},
        viz="time_to_convert",
    )
    assert result.subject == "The funnel average time to convert"
    assert result.unit == "s"
    assert result.is_breakdown is False
    assert result.series[0].points[0].value == 840.0


def test_time_to_convert_funnel_no_conversions_yields_no_data_point():
    # No conversions → average is None; the comparator treats a None anchor as "no data this interval".
    result = _extract({"bins": [], "average_conversion_time": None}, viz="time_to_convert")
    assert result.series[0].points[0].value is None


def test_time_to_convert_funnel_compare_evaluates_current_period_only():
    result = _extract(
        [
            {"bins": [[600, 1]], "average_conversion_time": 600.0, "compare_label": "current"},
            {"bins": [[1200, 1]], "average_conversion_time": 1200.0, "compare_label": "previous"},
        ],
        viz="time_to_convert",
    )
    assert result.series[0].points[0].value == 600.0


def test_breakdown_yields_one_series_per_value():
    # list-of-lists => breakdown; two breakdown values
    us = [{"order": 0, "count": 100, "breakdown_value": "US"}, {"order": 1, "count": 40, "breakdown_value": "US"}]
    de = [{"order": 0, "count": 80, "breakdown_value": "DE"}, {"order": 1, "count": 20, "breakdown_value": "DE"}]
    result = _extract([us, de])
    assert result.is_breakdown is True
    assert len(result.series) == 2
    assert result.series[0].label == "US" and result.series[0].points[0].value == 40.0
    assert result.series[1].label == "DE" and result.series[1].points[0].value == 25.0


def test_compared_funnel_evaluates_current_period_only():
    # A compare-enabled funnel concatenates current + previous rows (tagged compare_label); the
    # extractor evaluates the current period only.
    compared = [
        {"order": 0, "count": 1000, "compare_label": "current"},
        {"order": 1, "count": 100, "compare_label": "current"},
        {"order": 0, "count": 800, "compare_label": "previous"},
        {"order": 1, "count": 120, "compare_label": "previous"},
    ]
    result = _extract(compared)
    assert result.is_breakdown is False
    assert len(result.series) == 1
    assert result.series[0].points[0].value == 10.0  # current period: 100/1000


def test_breakdown_compared_funnel_evaluates_current_breakdowns_only():
    # Breakdown + compare: the runner emits the current breakdown groups followed by the previous
    # ones. The previous groups filter to empty and must be dropped — an empty group previously made
    # funnel_step resolve to -1 and raised "out of range" instead of evaluating the current breakdowns.
    us_current = [
        {"order": 0, "count": 100, "breakdown_value": "US", "compare_label": "current"},
        {"order": 1, "count": 40, "breakdown_value": "US", "compare_label": "current"},
    ]
    de_current = [
        {"order": 0, "count": 80, "breakdown_value": "DE", "compare_label": "current"},
        {"order": 1, "count": 20, "breakdown_value": "DE", "compare_label": "current"},
    ]
    us_previous = [
        {"order": 0, "count": 90, "breakdown_value": "US", "compare_label": "previous"},
        {"order": 1, "count": 30, "breakdown_value": "US", "compare_label": "previous"},
    ]
    de_previous = [
        {"order": 0, "count": 70, "breakdown_value": "DE", "compare_label": "previous"},
        {"order": 1, "count": 10, "breakdown_value": "DE", "compare_label": "previous"},
    ]
    result = _extract([us_current, de_current, us_previous, de_previous])
    assert result.is_breakdown is True
    assert {s.label for s in result.series} == {"US", "DE"}  # current breakdowns only, no crash
    assert {s.label: s.points[0].value for s in result.series} == {"US": 40.0, "DE": 25.0}
