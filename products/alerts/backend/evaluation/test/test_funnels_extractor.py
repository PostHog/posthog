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


def test_conversion_from_start_last_step():
    # 100 → 40 → overall conversion = 40/100 = 40%
    result = _extract(_steps(100, 40))
    assert result.series[0].points[0].value == 40.0
    assert result.subject == "The funnel conversion rate" and result.framed is False and result.is_breakdown is False


def test_conversion_from_previous_middle_step():
    # 100 → 50 → 30; step 2 from_previous = 30/50 = 60%
    result = _extract(
        _steps(100, 50, 30),
        config={"type": "FunnelsAlertConfig", "metric": "conversion_from_previous", "funnel_step": 2},
    )
    assert result.series[0].points[0].value == 60.0


def test_conversion_from_start_explicit_step():
    # 200 → 50 → 10; step 1 from_start = 50/200 = 25%
    result = _extract(
        _steps(200, 50, 10),
        config={"type": "FunnelsAlertConfig", "metric": "conversion_from_start", "funnel_step": 1},
    )
    assert result.series[0].points[0].value == 25.0


def test_zero_base_is_zero_rate():
    result = _extract(_steps(0, 0))
    assert result.series[0].points[0].value == 0.0


def test_step_out_of_range_raises():
    with pytest.raises(AlertExtractionError, match="out of range"):
        _extract(
            _steps(100, 40), config={"type": "FunnelsAlertConfig", "metric": "conversion_from_start", "funnel_step": 5}
        )


def test_conversion_from_previous_at_step_zero_raises():
    with pytest.raises(AlertExtractionError, match="undefined at the first step"):
        _extract(
            _steps(100, 40),
            config={"type": "FunnelsAlertConfig", "metric": "conversion_from_previous", "funnel_step": 0},
        )


def test_non_steps_viz_raises():
    with pytest.raises(AlertExtractionError, match="steps funnel"):
        _extract(_steps(100, 40), viz="time_to_convert")


@pytest.mark.parametrize("condition_type", [AlertConditionType.RELATIVE_INCREASE, AlertConditionType.RELATIVE_DECREASE])
def test_relative_condition_raises(condition_type):
    with pytest.raises(AlertExtractionError, match="absolute value conditions"):
        _extract(_steps(100, 40), condition_type=condition_type)


def test_breakdown_yields_one_series_per_value():
    # list-of-lists => breakdown; two breakdown values
    us = [{"order": 0, "count": 100, "breakdown_value": "US"}, {"order": 1, "count": 40, "breakdown_value": "US"}]
    de = [{"order": 0, "count": 80, "breakdown_value": "DE"}, {"order": 1, "count": 20, "breakdown_value": "DE"}]
    result = _extract([us, de])
    assert result.is_breakdown is True
    assert len(result.series) == 2
    assert result.series[0].label == "US" and result.series[0].points[0].value == 40.0
    assert result.series[1].label == "DE" and result.series[1].points[0].value == 25.0


def test_empty_result_raises():
    with pytest.raises(AlertExtractionError, match="no steps"):
        _extract([])
