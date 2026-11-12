from unittest.mock import patch

from django.test import SimpleTestCase

import requests
from prometheus_client import REGISTRY

from posthog.egress.cloudflare_turnstile.transport import TURNSTILE_SITEVERIFY_URL, turnstile_siteverify_request


def _turnstile_samples() -> list:
    return [
        sample
        for metric in REGISTRY.collect()
        if metric.name.startswith("cloudflare_turnstile_api")
        for sample in metric.samples
    ]


def _request_count() -> float:
    labels = {
        "scope": "public",
        "method": "POST",
        "endpoint": "siteverify",
        "status_code": "200",
        "source": "test",
    }
    return REGISTRY.get_sample_value("cloudflare_turnstile_api_requests_total", labels) or 0


class TestCloudflareTurnstileTransport(SimpleTestCase):
    def test_siteverify_is_recorded_without_the_secret_or_token_in_labels(self) -> None:
        response = requests.Response()
        response.status_code = 200
        before = _request_count()

        with patch("requests.request", return_value=response) as request:
            turnstile_siteverify_request(
                {"secret": "sk_secret", "response": "tok_secret", "remoteip": "1.2.3.4"},
                source="test",
                timeout=2.0,
            )

        assert request.call_args.args[:2] == ("POST", TURNSTILE_SITEVERIFY_URL)
        assert request.call_args.kwargs["data"]["secret"] == "sk_secret"
        assert request.call_args.kwargs["timeout"] == 2.0
        assert _request_count() == before + 1
        label_values = [value for sample in _turnstile_samples() for value in sample.labels.values()]
        assert not any("sk_secret" in value or "tok_secret" in value for value in label_values)
