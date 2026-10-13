from unittest.mock import patch

from django.test import SimpleTestCase

import requests
from prometheus_client import REGISTRY

from posthog.egress.openai_auth.transport import OPENAI_OAUTH_TOKEN_URL, openai_auth_request


def _openai_auth_samples() -> list:
    return [
        sample
        for metric in REGISTRY.collect()
        if metric.name.startswith("openai_auth_api")
        for sample in metric.samples
    ]


def _request_count(status_code: str = "200") -> float:
    labels = {
        "scope": "codex-client",
        "method": "POST",
        "endpoint": "oauth/token",
        "status_code": status_code,
        "source": "test",
    }
    return REGISTRY.get_sample_value("openai_auth_api_requests_total", labels) or 0


class TestOpenAIAuthTransport(SimpleTestCase):
    def test_request_is_recorded_under_the_constant_client_scope(self) -> None:
        response = requests.Response()
        response.status_code = 200
        before = _request_count()

        with patch("requests.request", return_value=response) as request:
            openai_auth_request(
                "POST",
                OPENAI_OAUTH_TOKEN_URL,
                source="test",
                endpoint="oauth/token",
                json={"refresh_token": "rt_secret", "grant_type": "refresh_token"},
            )

        assert request.call_args.kwargs["json"]["refresh_token"] == "rt_secret"
        assert request.call_args.kwargs["headers"]["Accept"] == "application/json"
        assert _request_count() == before + 1
        assert not any("rt_secret" in value for sample in _openai_auth_samples() for value in sample.labels.values())
