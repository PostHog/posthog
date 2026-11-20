import json

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

import httpx
from parameterized import parameterized

from posthog.llm.forecast_client import (
    FORECAST_MODEL,
    MAX_SERIES_PER_REQUEST,
    MAX_TOKENS_PER_REQUEST,
    ForecastError,
    ForecastNotConfiguredError,
    ForecastRejectedError,
    ForecastResponseError,
    ForecastSeries,
    ForecastUnavailableError,
    SeriesForecast,
    _tokens_per_series,
    forecast,
    split_into_requests,
)

GATEWAY = {"AI_GATEWAY_URL": "https://ai-gateway.example.com/v1", "AI_GATEWAY_API_KEY": "phs_test"}
LEVELS = [0.05, 0.5, 0.95]


def _series(count: int, length: int, prefix: str = "s") -> list[ForecastSeries]:
    return [ForecastSeries(item_id=f"{prefix}{index}", target=[float(index)] * length) for index in range(count)]


def _answer(request: httpx.Request, **_kwargs) -> httpx.Response:
    body = json.loads(request.content)
    return httpx.Response(
        200,
        json={
            "model": body["model"],
            "predictions": [
                {"item_id": item["item_id"], "0.05": [1.0], "0.5": [2.0], "0.95": [3.0]} for item in body["inputs"]
            ],
            "usage": {"input_tokens": 2, "output_tokens": 1},
        },
    )


def _run(series: list[ForecastSeries], **overrides) -> dict[str, SeriesForecast]:
    return forecast(series, **{"quantile_levels": LEVELS, "ai_product": "test_product", "team_id": 42, **overrides})


@override_settings(**GATEWAY)
class TestForecast(SimpleTestCase):
    def test_request_reaches_the_forecast_route_with_its_labels(self) -> None:
        series = [ForecastSeries(item_id="a", target=[100, 120, float("nan"), None, 110])]
        with patch.object(httpx.Client, "send", side_effect=_answer) as send:
            result = _run(series, trace_id="trace-1")

        request: httpx.Request = send.call_args.args[0]
        assert str(request.url) == "https://ai-gateway.example.com/v1/forecast"
        assert request.headers["Authorization"] == "Bearer phs_test"
        assert request.headers["X-PostHog-Product"] == "test_product"
        assert request.headers["X-PostHog-Distinct-Id"] == "team-42"
        assert request.headers["X-PostHog-Trace-Id"] == "trace-1"
        assert json.loads(request.headers["X-PostHog-Properties"]) == {"team_id": "42", "ai_product": "test_product"}
        assert json.loads(request.content) == {
            "model": FORECAST_MODEL,
            "inputs": [{"item_id": "a", "target": [100.0, 120.0, None, None, 110.0]}],
            "parameters": {"prediction_length": 1, "quantile_levels": LEVELS},
        }
        assert result == {"a": SeriesForecast(quantiles={0.05: (1.0,), 0.5: (2.0,), 0.95: (3.0,)})}

    def test_large_input_is_split_across_requests_and_merged(self) -> None:
        series = _series(MAX_SERIES_PER_REQUEST + 1, length=5)
        with patch.object(httpx.Client, "send", side_effect=_answer) as send:
            result = _run(series)

        assert send.call_count == 2
        assert set(result) == {item.item_id for item in series}

    @parameterized.expand(
        [
            ("no_gateway", {"AI_GATEWAY_URL": "", "AI_GATEWAY_API_KEY": ""}),
            ("remote_plain_http", {**GATEWAY, "AI_GATEWAY_URL": "http://ai-gateway.example.com/v1"}),
        ]
    )
    def test_unusable_gateway_raises_not_configured(self, _name: str, configured: dict) -> None:
        with (
            override_settings(**configured),
            patch.object(httpx.Client, "send") as send,
            self.assertRaises(ForecastNotConfiguredError),
        ):
            _run(_series(1, length=5))
        send.assert_not_called()

    @parameterized.expand(
        [
            ("unreachable", httpx.ConnectError("refused"), ForecastUnavailableError, None),
            ("timeout", httpx.ReadTimeout("slow"), ForecastUnavailableError, None),
            ("server_error", httpx.Response(503), ForecastUnavailableError, 503),
            ("rate_limited", httpx.Response(429), ForecastUnavailableError, 429),
            ("unauthorized", httpx.Response(401), ForecastRejectedError, 401),
            ("non_json", httpx.Response(200, text="<html>"), ForecastResponseError, None),
            ("missing_series", httpx.Response(200, json={"predictions": []}), ForecastResponseError, None),
            (
                "missing_quantile",
                httpx.Response(200, json={"predictions": [{"item_id": "s0", "0.5": [2.0]}]}),
                ForecastResponseError,
                None,
            ),
            (
                "wrong_horizon",
                httpx.Response(200, json={"predictions": [{"item_id": "s0", "0.05": [], "0.5": [2.0], "0.95": [3.0]}]}),
                ForecastResponseError,
                None,
            ),
        ]
    )
    def test_failures_raise_a_typed_error(
        self, _name: str, outcome, error: type[ForecastError], status_code: int | None
    ) -> None:
        mock = {"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome}
        with patch.object(httpx.Client, "send", **mock), self.assertRaises(error) as raised:
            _run(_series(1, length=5))

        assert raised.exception.status_code == status_code
        assert raised.exception.retryable == (error is not ForecastRejectedError)

    def test_rejection_carries_the_gateway_message(self) -> None:
        response = httpx.Response(400, json={"error": {"type": "invalid_request_error", "message": "too many tokens"}})
        with (
            patch.object(httpx.Client, "send", return_value=response),
            self.assertRaises(ForecastRejectedError) as raised,
        ):
            _run(_series(1, length=5))

        assert "too many tokens" in str(raised.exception)

    @parameterized.expand(
        [
            ("unserved_quantile", _series(1, length=5), {"quantile_levels": [0.42]}),
            ("duplicate_item_id", [*_series(1, length=5), *_series(1, length=6)], {}),
            ("empty_history", _series(1, length=0), {}),
            ("no_product", _series(1, length=5), {"ai_product": ""}),
            ("zero_horizon", _series(1, length=5), {"prediction_length": 0}),
        ]
    )
    def test_refuses_input_the_gateway_cannot_accept(self, _name: str, series: list[ForecastSeries], overrides) -> None:
        with patch.object(httpx.Client, "send") as send, self.assertRaises(ValueError):
            _run(series, **overrides)
        send.assert_not_called()


class TestSplitIntoRequests(SimpleTestCase):
    @parameterized.expand(
        [
            ("series_cap", _series(MAX_SERIES_PER_REQUEST + 1, length=5), 2),
            # A 512-point series costs 17 tokens with a one-step horizon, so 240 fit in one request.
            ("token_cap", _series(241, length=512), 2),
            ("mixed_lengths", [*_series(600, length=10, prefix="short"), *_series(200, length=512, prefix="long")], 2),
            ("fits_in_one", _series(3, length=40), 1),
            ("empty", [], 0),
        ]
    )
    def test_each_request_stays_inside_the_gateway_limits(
        self, _name: str, series: list[ForecastSeries], expected_requests: int
    ) -> None:
        requests = split_into_requests(series, prediction_length=1)

        assert len(requests) == expected_requests
        assert sorted(item.item_id for request in requests for item in request) == sorted(
            item.item_id for item in series
        )
        for request in requests:
            longest = max(len(item.target) for item in request)
            assert len(request) <= MAX_SERIES_PER_REQUEST
            assert len(request) * _tokens_per_series(longest, 1) <= MAX_TOKENS_PER_REQUEST
