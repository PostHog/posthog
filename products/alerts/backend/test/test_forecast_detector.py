import json
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

import httpx
import numpy as np
from parameterized import parameterized

from posthog.schema import AlertCalculationInterval

from posthog.models.team import Team
from posthog.models.user import User

from products.alerts.backend.evaluation.contract import ComparableSeries, ExtractionResult, SeriesPoint
from products.alerts.backend.evaluation.detector import evaluate_with_detector
from products.alerts.backend.forecast.rules import EXPECTED_ZERO_REASON, compare, forecast_rule
from products.alerts.backend.forecast.scorer import RollingForecast, score_every_point
from products.alerts.backend.judge.contract import (
    FORECAST_DETECTOR_NOT_CONFIGURED_ERROR_CODE,
    FORECAST_DETECTOR_PAUSED_ERROR_CODE,
    FORECAST_DETECTOR_REJECTED_ERROR_CODE,
    FORECAST_DETECTOR_UNAVAILABLE_ERROR_CODE,
    ForecastDetectorUnavailableError,
    JudgeAttribution,
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


def _preview(
    series: list[list[float]], *, send: Any, rolled_out: bool | None = True
) -> tuple[RollingForecast, MagicMock]:
    mock = {"side_effect": send} if callable(send) or isinstance(send, Exception) else {"return_value": send}
    with (
        override_settings(**GATEWAY),
        patch("posthoganalytics.feature_enabled", return_value=rolled_out),
        patch("ee.hogai.utils.feature_flags.is_privacy_mode_enabled", return_value=True),
        patch.object(httpx.Client, "send", **mock) as sent,
    ):
        rolling = score_every_point(
            [np.array(values) for values in series],
            {"type": "forecast"},
            attribution=JudgeAttribution(team=FAKE_TEAM, user=FAKE_USER, evaluation_id=None, is_agent_billable=True),
        )
    return rolling, sent


def _sent_inputs(sent: MagicMock) -> dict[str, list[float]]:
    return {
        item["item_id"]: item["target"]
        for call in sent.call_args_list
        for item in json.loads(call.args[0].content)["inputs"]
    }


class TestCompare(SimpleTestCase):
    # The forecast is 100 expected, with 80 and 120 at the rule's lower and upper quantiles.
    @parameterized.expand(
        [
            ("default_range_either_side", {}, [(130, "above"), (70, "below"), (110, None)]),
            ("extreme_spike_only", {"above": {"quantile": 0.99}}, [(130, "above"), (10, None)]),
            (
                "extreme_spike_or_moderate_drop",
                {"above": {"quantile": 0.99}, "below": {"quantile": 0.2}},
                [(130, "above"), (70, "below"), (90, None)],
            ),
            ("at_least_double", {"above": {"min_relative_change": 1}}, [(200, "above"), (199, None), (0, None)]),
            ("at_least_half_below", {"below": {"min_relative_change": 0.5}}, [(50, "below"), (51, None), (300, None)]),
            (
                "range_and_both_minimums",
                {"above": {"quantile": 0.95, "min_relative_change": 0.2, "min_absolute_change": 50}},
                [(150, "above"), (125, None), (70, None)],
            ),
            (
                "absolute_either_side",
                {"above": {"min_absolute_change": 500}, "below": {"min_absolute_change": 500}},
                [(600, "above"), (-400, "below"), (500, None)],
            ),
            (
                "relative_spike_or_range_drop_with_minimum",
                {"above": {"min_relative_change": 0.5}, "below": {"quantile": 0.05, "min_absolute_change": 100}},
                [(150, "above"), (-10, "below"), (70, None), (140, None)],
            ),
        ]
    )
    def test_fires_on_the_side_whose_conditions_all_hold(
        self, _name: str, config: dict[str, Any], cases: list[tuple[float, str | None]]
    ) -> None:
        rule = forecast_rule({"type": "forecast", **config})

        for actual, side in cases:
            comparison = compare(rule, expected=100.0, lower=80.0, upper=120.0, actual=actual)

            assert (comparison.fires, comparison.side, comparison.reason) == (side is not None, side, None), actual

    def test_a_relative_rule_with_a_zero_forecast_never_fires_and_says_why(self) -> None:
        rule = forecast_rule({"above": {"min_relative_change": 0.1}})

        comparison = compare(rule, expected=0.0, lower=0.0, upper=3.0, actual=500.0)

        assert comparison.fires is False
        assert comparison.persisted_metadata()["reason"] == EXPECTED_ZERO_REASON

    @parameterized.expand(
        [
            ("default", {}, [0.01, 0.5, 0.99]),
            ("both_quantiles", {"above": {"quantile": 0.99}, "below": {"quantile": 0.2}}, [0.2, 0.5, 0.99]),
            # A side with no quantile, or an ignored side, shows the default end of the range.
            ("one_side_no_quantile", {"above": {"min_absolute_change": 5}}, [0.01, 0.5, 0.99]),
            ("one_side_quantile", {"below": {"quantile": 0.2}}, [0.2, 0.5, 0.99]),
        ]
    )
    def test_requests_the_expected_value_and_the_shown_range(
        self, _name: str, config: dict[str, Any], levels: list[float]
    ) -> None:
        assert forecast_rule(config).quantile_levels.as_list() == levels


class TestForecastCheck(SimpleTestCase):
    def test_breach_names_the_forecast_and_the_check_keeps_it_without_a_score(self) -> None:
        history = [100.0] * 600

        result, sent = _evaluate([_series([*history, 180.0])], {"type": "forecast"}, send=_forecast_answer())

        request = sent.call_args.args[0]
        assert request.headers["X-PostHog-Privacy-Mode"] == "true"
        body = json.loads(request.content)
        # At most 512 points of history, and the checked point is never part of its own history.
        assert body["inputs"][0]["target"] == [100.0] * 512
        assert body["parameters"]["quantile_levels"] == [0.01, 0.5, 0.99]
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
            "lower_quantile": 0.01,
            "upper_quantile": 0.99,
            "side": "above",
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


class TestForecastPreview(SimpleTestCase):
    def test_each_point_is_forecast_from_only_the_points_before_it(self) -> None:
        spiky = [100.0] * 45
        spiky[40], spiky[42] = 200.0, 10.0
        too_short = [100.0] * 30

        rolling, sent = _preview([spiky, too_short], send=_forecast_answer())

        sent.assert_called_once()
        assert _sent_inputs(sent) == {f"0:{index}": spiky[:index] for index in range(30, 45)}
        scored, unscored = rolling.comparisons
        assert scored[:30] == (None,) * 30
        assert [
            (index, comparison.side) for index, comparison in enumerate(scored) if comparison and comparison.fires
        ] == [
            (40, "above"),
            (42, "below"),
        ]
        latest = scored[44]
        assert latest is not None
        assert (latest.expected, latest.lower, latest.upper) == (100.0, 80.0, 120.0)
        assert unscored == (None,) * 30

    def test_a_long_preview_scores_the_latest_points_in_batched_requests(self) -> None:
        rolling, sent = _preview([[100.0] * 600] * 3, send=_forecast_answer())

        # 500 points shared by 3 series is 166 each. A request holds 240 inputs of 512 points.
        assert sent.call_count == 3
        assert set(_sent_inputs(sent)) == {f"{series}:{index}" for series in range(3) for index in range(434, 600)}
        for comparisons in rolling.comparisons:
            assert comparisons[:434] == (None,) * 434
            assert all(comparison is not None for comparison in comparisons[434:])

    @parameterized.expand(
        [
            ("unreachable", httpx.ConnectError("refused"), True, ForecastDetectorUnavailableError, ""),
            ("out_of_credits", httpx.Response(402), True, LLMDetectorPausedError, "not accepting previews"),
            ("invalid_request", httpx.Response(400), True, LLMDetectorPausedError, "refused this preview"),
            ("rollout_off", _forecast_answer(), False, LLMDetectorPausedError, "not enabled for your account"),
        ]
    )
    def test_a_failed_preview_errors_with_a_message_about_the_preview(
        self, _name: str, send: Any, rolled_out: bool, error: type[LLMDetectorError], message: str
    ) -> None:
        with pytest.raises(error, match=message) as raised:
            _preview([[100.0] * 40], send=send, rolled_out=rolled_out)

        assert "alert is still on" not in str(raised.value)


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
