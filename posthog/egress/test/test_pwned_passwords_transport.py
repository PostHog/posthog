from contextlib import suppress

from unittest.mock import patch

from django.test import SimpleTestCase

import requests
from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.egress.pwned_passwords import pwned_passwords_request

PREFIX = "21BD1"


def _request_count(status_code: str) -> float:
    labels = {
        "scope": "public",
        "method": "GET",
        "endpoint": "range/{prefix}",
        "status_code": status_code,
        "source": "test",
    }
    return REGISTRY.get_sample_value("pwned_passwords_api_requests_total", labels) or 0


def _label_values() -> list[str]:
    return [
        value
        for metric in REGISTRY.collect()
        if metric.name.startswith("pwned_passwords_api")
        for sample in metric.samples
        for value in sample.labels.values()
    ]


class TestPwnedPasswordsTransport(SimpleTestCase):
    @parameterized.expand(
        [
            ("response", "200", None),
            ("exception", "exception", requests.Timeout("read timed out")),
        ]
    )
    def test_request_is_padded_and_recorded_without_the_hash_prefix(
        self, _name: str, status_code: str, error: Exception | None
    ) -> None:
        response = requests.Response()
        response.status_code = 200
        before = _request_count(status_code)

        with patch("requests.request", return_value=response, side_effect=error) as request:
            with suppress(requests.Timeout):
                pwned_passwords_request(f"https://api.pwnedpasswords.com/range/{PREFIX}", source="test", timeout=1.0)

        assert request.call_args.kwargs["headers"]["Add-Padding"] == "true"
        assert _request_count(status_code) == before + 1
        assert not any(PREFIX in value for value in _label_values())
