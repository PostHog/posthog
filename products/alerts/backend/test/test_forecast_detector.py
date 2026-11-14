import json
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

import httpx
from parameterized import parameterized

from posthog.schema import AlertCalculationInterval

from posthog.models.team import Team
from posthog.models.user import User

from products.alerts.backend.evaluation.contract import ComparableSeries, ExtractionResult, SeriesPoint
from products.alerts.backend.evaluation.detector import evaluate_with_detector
from products.alerts.backend.forecast.rules import EXPECTED_ZERO_REASON, compare, forecast_rule
from products.alerts.backend.judge.contract import (
    FORECAST_DETECTOR_NOT_CONFIGURED_ERROR_CODE,
    FORECAST_DETECTOR_PAUSED_ERROR_CODE,
    FORECAST_DETECTOR_REJECTED_ERROR_CODE,
    FORECAST_DETECTOR_UNAVAILABLE_ERROR_CODE,
    ForecastDetectorUnavailableError,
    LLMDetectorError,
    LLMDetectorPausedError,
)
from products.alerts.backend.llm_detector_limits import LLMAlertWrite, admit_llm_alert_write

GATEWAY = {"AI_GATEWAY_URL": "https://ai-gateway.example.com/v1", "AI_GATEWAY_API_KEY": "phs_test"}

FAKE_ORGANIZATION = MagicMock(id="0190f2a4-0000-0000-0000-000000000001", is_ai_data_processing_approved=True)
FAKE_TEAM = MagicMock(spec=Team, id=42, organization=FAKE_ORGANIZATION, organization_id=FAKE_ORGANIZATION.id)
FAKE_USER = MagicMock(spec=User, distinct_id="creator-distinct-id")


class _FakeInsight:
    id = 7
    name = "Daily signups"
    query = {
        "kind": "InsightVizNode",
        "source": {"kind": "TrendsQuery", "interval": "day", "series": [{"kind": "EventsNode", "event": "signed_up"}]},
    }
    team = FAKE_TEAM


class _FakeAlert:
    id = "b8f3a1e0-0000-0000-0000-000000000002"
    config: dict[str, Any] = {"type": "TrendsAlertConfig", "series_index": 0}
    created_by: Any = FAKE_USER


def _series(values: list[float], label: str = "signed_up") -> ComparableSeries:
    points = [SeriesPoint(date=f"day-{index}", value=value) for index, value in enumerate(values)]
    return ComparableSeries(label=label, points=points, current_index=len(points) - 1)


def _forecast_answer(expected: float = 100.0, lower: float = 80.0, upper: float = 120.0):
    def answer(request: httpx.Request, **_kwargs: Any) -> httpx.Response:
        body = json.loads(request.content)
        levels = body["parameters"]["quantile_levels"]
        values = dict(zip(levels, (lower, expected, upper)))
        return httpx.Response(
            200,
            json={
                "predictions": [
                    {"item_id": item["item_id"], **{str(level): [values[level]] for level in levels}}
                    for item in body["inputs"]
                ]
            },
        )

    return answer


def _evaluate(
    series: list[ComparableSeries],
    detector_config: dict[str, Any],
    *,
    send: Any,
    rolled_out: bool | None = True,
    ai_processing_approved: bool = True,
) -> tuple[Any, MagicMock]:
    mock = {"side_effect": send} if callable(send) or isinstance(send, Exception) else {"return_value": send}
    with (
        override_settings(**GATEWAY),
        patch.object(FAKE_ORGANIZATION, "is_ai_data_processing_approved", ai_processing_approved),
        patch("posthoganalytics.feature_enabled", return_value=rolled_out),
        patch("ee.hogai.utils.feature_flags.is_privacy_mode_enabled", return_value=True),
        patch.object(httpx.Client, "send", **mock) as sent,
    ):
        result = evaluate_with_detector(
            ExtractionResult(series=series, is_breakdown=len(series) > 1, interval_type=None),
            detector_config,
            insight=_FakeInsight(),  # type: ignore[arg-type]
            alert=_FakeAlert(),  # type: ignore[arg-type]
        )
    return result, sent


class TestCompare(SimpleTestCase):
    @parameterized.expand(
        [
            ("band_above", {}, 130, True),
            ("band_below", {}, 70, True),
            ("band_inside", {}, 110, False),
            ("band_above_watching_below", {"direction": "below"}, 130, False),
            ("band_below_watching_below", {"direction": "below"}, 70, True),
            ("band_below_watching_above", {"direction": "above"}, 70, False),
            ("relative_above", {"mode": "relative", "relative_threshold": 0.5}, 160, True),
            ("relative_below", {"mode": "relative", "relative_threshold": 0.5}, 40, True),
            ("relative_inside", {"mode": "relative", "relative_threshold": 0.5}, 140, False),
            (
                "relative_below_watching_above",
                {"mode": "relative", "relative_threshold": 0.5, "direction": "above"},
                40,
                False,
            ),
            ("absolute_above", {"mode": "absolute", "absolute_threshold": 25}, 130, True),
            ("absolute_inside", {"mode": "absolute", "absolute_threshold": 25}, 120, False),
            (
                "absolute_below_watching_below",
                {"mode": "absolute", "absolute_threshold": 25, "direction": "below"},
                70,
                True,
            ),
        ]
    )
    def test_fires_by_mode_and_direction(self, _name: str, config: dict[str, Any], actual: float, fires: bool) -> None:
        comparison = compare(forecast_rule(config), expected=100.0, lower=80.0, upper=120.0, actual=actual)

        assert comparison.fires is fires
        assert comparison.reason is None

    def test_relative_mode_with_a_zero_forecast_never_fires_and_says_why(self) -> None:
        rule = forecast_rule({"mode": "relative", "relative_threshold": 0.1})

        comparison = compare(rule, expected=0.0, lower=0.0, upper=3.0, actual=500.0)

        assert comparison.fires is False
        assert comparison.persisted_metadata()["reason"] == EXPECTED_ZERO_REASON


class TestForecastCheck(SimpleTestCase):
    def test_breach_names_the_forecast_and_the_check_keeps_it_without_a_score(self) -> None:
        history = [100.0] * 600

        result, sent = _evaluate([_series([*history, 180.0])], {"type": "forecast"}, send=_forecast_answer())

        request = sent.call_args.args[0]
        assert request.headers["X-PostHog-Privacy-Mode"] == "true"
        body = json.loads(request.content)
        # At most 512 points of history, and the checked point is never part of its own history.
        assert body["inputs"][0]["target"] == [100.0] * 512
        assert body["parameters"]["quantile_levels"] == [0.05, 0.5, 0.95]
        assert result.breaches == [
            "Anomaly detected in signed_up: value 180.00 using forecast detector: expected about 100 (80 to 120), got 180"
        ]
        assert result.anomaly_scores is None
        assert result.triggered_points == [600]
        assert result.triggered_metadata == {
            "detector_type": "forecast",
            "series_index": 0,
            "insight_id": 7,
            "expected": 100.0,
            "lower": 80.0,
            "upper": 120.0,
            "actual": 180.0,
            "mode": "band",
        }

    def test_a_history_too_short_to_forecast_leaves_the_check_uncomputed(self) -> None:
        result, sent = _evaluate([_series([100.0] * 30)], {"type": "forecast"}, send=_forecast_answer())

        sent.assert_not_called()
        assert (result.value, result.breaches, result.triggered_metadata) == (None, [], None)

    def test_each_breakdown_series_gets_its_own_forecast(self) -> None:
        breakdown = [_series([100.0] * 40, label=label) for label in ("Chrome", "Firefox", "Safari")]

        result, sent = _evaluate(breakdown, {"type": "forecast"}, send=_forecast_answer())

        assert sent.call_count == 3
        assert result.breaches == []

    @parameterized.expand(
        [
            (
                "unreachable",
                httpx.ConnectError("refused"),
                True,
                ForecastDetectorUnavailableError,
                FORECAST_DETECTOR_UNAVAILABLE_ERROR_CODE,
            ),
            (
                "unreadable_body",
                httpx.Response(200, text="<html>"),
                True,
                ForecastDetectorUnavailableError,
                FORECAST_DETECTOR_UNAVAILABLE_ERROR_CODE,
            ),
            (
                "rollout_lookup_failed",
                _forecast_answer(),
                None,
                ForecastDetectorUnavailableError,
                FORECAST_DETECTOR_UNAVAILABLE_ERROR_CODE,
            ),
            ("rollout_off", _forecast_answer(), False, LLMDetectorPausedError, FORECAST_DETECTOR_PAUSED_ERROR_CODE),
            ("out_of_credits", httpx.Response(402), True, LLMDetectorPausedError, FORECAST_DETECTOR_PAUSED_ERROR_CODE),
            ("forbidden", httpx.Response(403), True, LLMDetectorPausedError, FORECAST_DETECTOR_PAUSED_ERROR_CODE),
            (
                "invalid_request",
                httpx.Response(400, json={"error": {"type": "invalid_request_error", "message": "internal detail"}}),
                True,
                LLMDetectorPausedError,
                FORECAST_DETECTOR_REJECTED_ERROR_CODE,
            ),
        ]
    )
    def test_a_failed_forecast_errors_with_its_own_code(
        self, _name: str, send: Any, rolled_out: bool | None, error: type[LLMDetectorError], code: str
    ) -> None:
        with pytest.raises(error) as raised:
            _evaluate([_series([100.0] * 40)], {"type": "forecast"}, send=send, rolled_out=rolled_out)

        assert raised.value.error_code == code  # type: ignore[attr-defined]
        assert "internal detail" not in str(raised.value)

    def test_withdrawn_ai_processing_approval_pauses_the_check_before_any_call(self) -> None:
        with pytest.raises(LLMDetectorPausedError, match="AI data processing is turned off") as raised:
            _evaluate(
                [_series([100.0] * 40)], {"type": "forecast"}, send=_forecast_answer(), ai_processing_approved=False
            )

        assert raised.value.error_code == FORECAST_DETECTOR_PAUSED_ERROR_CODE

    def test_a_plain_http_gateway_pauses_the_check_before_the_key_is_sent(self) -> None:
        with (
            override_settings(**{**GATEWAY, "AI_GATEWAY_URL": "http://ai-gateway.example.com/v1"}),
            pytest.raises(LLMDetectorPausedError) as raised,
            patch.object(httpx.Client, "send") as sent,
            patch("posthoganalytics.feature_enabled", return_value=True),
        ):
            evaluate_with_detector(
                ExtractionResult(series=[_series([100.0] * 40)], interval_type=None),
                {"type": "forecast"},
                insight=_FakeInsight(),  # type: ignore[arg-type]
                alert=_FakeAlert(),  # type: ignore[arg-type]
            )

        sent.assert_not_called()
        assert raised.value.error_code == FORECAST_DETECTOR_NOT_CONFIGURED_ERROR_CODE


class TestForecastAlertWrite(SimpleTestCase):
    def test_refuses_the_real_time_cadence(self) -> None:
        refusal = admit_llm_alert_write(
            LLMAlertWrite(
                team_id=42,
                organization=MagicMock(),
                principal=FAKE_USER,
                detector_config={"type": "forecast"},
                enabled=True,
                calculation_interval=AlertCalculationInterval.REAL_TIME,
            )
        )

        assert refusal is not None
        assert (refusal.reason, refusal.field) == ("cadence", "calculation_interval")
