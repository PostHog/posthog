from typing import Any

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

import requests
from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.egress.limiter.policies import Priority, resolve_policy
from posthog.egress.perplexity.limiter import PERPLEXITY_ACCOUNT_KEY, consume_perplexity_sync
from posthog.egress.perplexity.observability import _parse_perplexity_rate_limit
from posthog.egress.perplexity.transport import (
    AGENT_ENDPOINT,
    PERPLEXITY_API_BASE,
    PerplexityEgressBudgetExhausted,
    perplexity_request,
)

_FAKE_API_KEY = "pplx-fake-key-for-tests"


def _response(status: int, headers: dict[str, str] | None = None) -> requests.Response:
    response = requests.models.Response()
    response.status_code = status
    response._content = b"{}"
    response.headers.update(headers or {})
    return response


def _request_count(status_code: str, source: str) -> float:
    labels = {
        "account": "default",
        "method": "POST",
        "endpoint": AGENT_ENDPOINT,
        "status_code": status_code,
        "source": source,
    }
    return REGISTRY.get_sample_value("perplexity_api_requests_total", labels) or 0.0


class TestPerplexityEgress(SimpleTestCase):
    def test_request_is_gated_on_the_account_scope_and_recorded_without_the_key(self) -> None:
        source = "test_perplexity_wiring"
        before = _request_count("200", source)
        consume = MagicMock(return_value=True)
        with (
            patch("posthog.egress.perplexity.transport.consume_perplexity_sync", consume),
            patch("requests.request", return_value=_response(200)) as request,
        ):
            perplexity_request(
                "POST",
                f"{PERPLEXITY_API_BASE}{AGENT_ENDPOINT}",
                api_key=_FAKE_API_KEY,
                source=source,
                endpoint=AGENT_ENDPOINT,
                json={"input": "q"},
            )

        assert request.call_args.args == ("POST", "https://api.perplexity.ai/v1/agent")
        assert request.call_args.kwargs["headers"]["Authorization"] == f"Bearer {_FAKE_API_KEY}"
        assert consume.call_args.kwargs["priority"] is Priority.BATCH
        assert _request_count("200", source) == before + 1
        samples = [
            sample.labels
            for metric in REGISTRY.collect()
            if metric.name.startswith("perplexity_api")
            for sample in metric.samples
        ]
        assert not any(_FAKE_API_KEY in str(labels) for labels in samples)

    def test_denied_budget_raises_before_any_request(self) -> None:
        with (
            patch("posthog.egress.perplexity.transport.consume_perplexity_sync", return_value=False),
            patch("requests.request") as request,
        ):
            with self.assertRaises(PerplexityEgressBudgetExhausted):
                perplexity_request(
                    "POST",
                    f"{PERPLEXITY_API_BASE}{AGENT_ENDPOINT}",
                    api_key=_FAKE_API_KEY,
                    source="test",
                    endpoint=AGENT_ENDPOINT,
                )
        request.assert_not_called()

    def test_policy_is_registered_for_the_account_key(self) -> None:
        assert PERPLEXITY_ACCOUNT_KEY == "perplexity:account:default"
        assert consume_perplexity_sync(source="test") is True

    @override_settings(PERPLEXITY_EGRESS_PER_MINUTE_BUDGET=7, PERPLEXITY_EGRESS_HOURLY_BUDGET=11)
    def test_budgets_come_from_the_settings_they_are_named_after(self) -> None:
        assert resolve_policy(PERPLEXITY_ACCOUNT_KEY).limits == ((7, 60.0), (11, 3600.0))

    @parameterized.expand(
        [
            (
                "documented_headers",
                {"x-ratelimit-limit": "3", "x-ratelimit-remaining": "2", "x-ratelimit-reset": "1793000000"},
                (3.0, 2.0, 1793000000.0),
            ),
            ("mixed_case", {"X-RateLimit-Remaining": "1"}, (None, 1.0, None)),
            ("garbage_values", {"x-ratelimit-limit": "lots", "x-ratelimit-remaining": ""}, (None, None, None)),
            ("throttled_response_has_only_retry_after", {"Retry-After": "1"}, (None, None, None)),
        ]
    )
    def test_rate_limit_headers(
        self, _name: str, headers: dict[str, str], expected: tuple[float | None, float | None, float | None]
    ) -> None:
        response_headers: Any = _response(200, headers).headers
        snapshot = _parse_perplexity_rate_limit(response_headers, None)
        assert (snapshot.limit, snapshot.remaining, snapshot.reset_at) == expected
        assert snapshot.resource == "agent_requests"
