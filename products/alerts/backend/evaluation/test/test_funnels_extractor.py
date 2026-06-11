import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import AlertConditionType

from products.alerts.backend.evaluation.contract import AlertExtractionError
from products.alerts.backend.evaluation.funnels import FunnelsExtractor

CALC_PATH = "products.alerts.backend.evaluation.funnels.calculate_for_query_based_insight"


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
        return FunnelsExtractor().extract(_alert(config, condition_type), MagicMock(), _query(viz))


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
        (_steps(100, 40), None, "time_to_convert", AlertConditionType.ABSOLUTE_VALUE, "steps funnel"),
        (_steps(100, 40), None, None, AlertConditionType.RELATIVE_INCREASE, "absolute value conditions"),
        (_steps(100, 40), None, None, AlertConditionType.RELATIVE_DECREASE, "absolute value conditions"),
        ([], None, None, AlertConditionType.ABSOLUTE_VALUE, "no steps"),
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


def test_breakdown_yields_one_series_per_value():
    # list-of-lists => breakdown; two breakdown values
    us = [{"order": 0, "count": 100, "breakdown_value": "US"}, {"order": 1, "count": 40, "breakdown_value": "US"}]
    de = [{"order": 0, "count": 80, "breakdown_value": "DE"}, {"order": 1, "count": 20, "breakdown_value": "DE"}]
    result = _extract([us, de])
    assert result.is_breakdown is True
    assert len(result.series) == 2
    assert result.series[0].label == "US" and result.series[0].points[0].value == 40.0
    assert result.series[1].label == "DE" and result.series[1].points[0].value == 25.0
