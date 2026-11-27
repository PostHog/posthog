from django.test import SimpleTestCase

import responses
from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.egress.vercel import vercel_request
from posthog.egress.vercel.observability import normalize_vercel_endpoint

ITEM_URL = "https://api.vercel.com/v1/installations/icfg_example/resources/42/experimentation/items/checkout-redesign"
ITEM_ENDPOINT = "/v1/installations/{id}/resources/{id}/experimentation/items/{id}"


def _request_count(installation: str, endpoint: str) -> float:
    labels = {
        "installation": installation,
        "method": "PATCH",
        "endpoint": endpoint,
        "status_code": "204",
        "source": "test",
    }
    return REGISTRY.get_sample_value("vercel_api_requests_total", labels) or 0


class TestVercelTransport(SimpleTestCase):
    @responses.activate
    def test_request_is_recorded_under_its_installation_without_ids_in_labels(self) -> None:
        responses.add(responses.PATCH, ITEM_URL, status=204)
        before = _request_count("icfg_example", ITEM_ENDPOINT)

        vercel_request(
            "PATCH",
            ITEM_URL,
            source="test",
            installation_id="icfg_example",
            headers={"Authorization": "Bearer vercel_secret_token"},
            data='{"name": "Checkout redesign"}',
        )

        assert responses.calls[0].request.headers["Authorization"] == "Bearer vercel_secret_token"
        assert _request_count("icfg_example", ITEM_ENDPOINT) == before + 1
        label_values = [
            value
            for metric in REGISTRY.collect()
            if metric.name.startswith("vercel_api")
            for sample in metric.samples
            for value in sample.labels.values()
        ]
        assert not any("checkout-redesign" in value or "vercel_secret_token" in value for value in label_values)

    @parameterized.expand(
        [
            ("item", ITEM_URL, ITEM_ENDPOINT),
            (
                "item_list",
                "https://api.vercel.com/v1/installations/icfg_example/resources/42/experimentation/items",
                "/v1/installations/{id}/resources/{id}/experimentation/items",
            ),
            (
                "invoice",
                "https://api.vercel.com/v1/installations/icfg_example/billing/invoices/inv_1/actions",
                "/v1/installations/{id}/billing/invoices/{id}/actions",
            ),
            ("token_exchange", "https://api.vercel.com/v2/oauth/access_token", "/v2/oauth/access_token"),
            ("no_url", None, "unknown"),
        ]
    )
    def test_endpoint_label_templates_identifiers(self, _name: str, url: str | None, expected: str) -> None:
        assert normalize_vercel_endpoint(url) == expected
