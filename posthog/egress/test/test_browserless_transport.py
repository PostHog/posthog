from unittest.mock import patch

from django.test import SimpleTestCase

import requests
from parameterized import parameterized

from posthog.egress.browserless.transport import BrowserlessEgressBudgetExhausted, browserless_request, fleet_scope
from posthog.egress.limiter.policies import Priority

_TOKEN = "s3cret-fleet-token"
_URL = "https://browserless.example.com/screenshot?token=s3cret-fleet-token"


def _ok_response() -> requests.Response:
    response = requests.Response()
    response.status_code = 200
    return response


class TestBrowserlessFleetScope(SimpleTestCase):
    def test_the_token_never_reaches_the_scope_label(self) -> None:
        # The scope is a Prometheus label, so it travels to dashboards and alerts.
        scope = fleet_scope(_URL, _TOKEN)

        assert _TOKEN not in scope
        assert len(scope) == 16

    @parameterized.expand(
        [
            # Same credential, different fleet: separate pools of workers, so separate budgets.
            ("different_host", "https://other.example.com/screenshot", _TOKEN),
            # Same fleet, rotated credential. Splitting here costs one window of over-admission,
            # which beats keying on the host alone and merging two unrelated deployments.
            ("different_token", _URL, "rotated-token"),
        ]
    )
    def test_a_different_fleet_gets_a_different_budget(self, _name: str, url: str, token: str) -> None:
        assert fleet_scope(url, token) != fleet_scope(_URL, _TOKEN)

    def test_a_tokenless_fleet_is_still_identified_by_host(self) -> None:
        # Self-hosted Browserless often runs with no token. Falling back to an empty scope would
        # make the base client identity-blind and drop every such deployment out of the budget.
        assert fleet_scope("https://browserless.internal/screenshot", "") != ""


class TestBrowserlessTransport(SimpleTestCase):
    def test_a_call_is_gated_on_its_fleet_and_recorded(self) -> None:
        with (
            patch("posthog.egress.browserless.transport.consume_browserless_sync", return_value=True) as consume,
            patch("requests.request", return_value=_ok_response()) as request,
            patch("posthog.egress.browserless.transport.record_browserless_response") as record,
        ):
            browserless_request(
                "POST",
                _URL,
                token=_TOKEN,
                source="heatmap_screenshot",
                endpoint="screenshot",
                priority=Priority.NORMAL,
                json={"url": "https://example.com"},
            )

        assert consume.call_args.args[0] == fleet_scope(_URL, _TOKEN)
        assert consume.call_args.kwargs["priority"] is Priority.NORMAL
        # The token stays in the query string: Browserless rejects it as an Authorization header.
        assert "Authorization" not in request.call_args.kwargs["headers"]
        assert request.call_args.args[1] == _URL
        assert record.called

    def test_a_sheddable_call_raises_when_the_fleet_budget_is_spent(self) -> None:
        # The whole point of one budget per fleet: a background consumer is turned away before it
        # takes the session a waiting render needs.
        with (
            patch("posthog.egress.browserless.transport.consume_browserless_sync", return_value=False),
            patch("requests.request") as request,
        ):
            with self.assertRaises(BrowserlessEgressBudgetExhausted):
                browserless_request(
                    "POST",
                    _URL,
                    token=_TOKEN,
                    source="signals_lighthouse",
                    endpoint="performance",
                    priority=Priority.BATCH,
                    json={"url": "https://posthog.com/pricing"},
                )

        request.assert_not_called()
