from collections.abc import Callable
from typing import Any

from unittest.mock import patch

from django.test import SimpleTestCase

import requests
from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.egress.npm_registry import npm_packument_url, npm_registry_request
from posthog.egress.pypi import pypi_release_url, pypi_request


def _request_count(counter: str, endpoint: str) -> float:
    labels = {"scope": "public", "method": "GET", "endpoint": endpoint, "status_code": "200", "source": "test"}
    return REGISTRY.get_sample_value(counter, labels) or 0


class TestPackageRegistryTransports(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "npm",
                npm_registry_request,
                npm_packument_url("@posthog/types"),
                "packument",
                "npm_registry_api_requests_total",
            ),
            ("pypi", pypi_request, pypi_release_url("requests", "2.33.0"), "release", "pypi_api_requests_total"),
        ]
    )
    def test_request_is_recorded_under_a_fixed_endpoint_label(
        self, _name: str, send: Callable[..., Any], url: str, endpoint: str, counter: str
    ) -> None:
        response = requests.Response()
        response.status_code = 200
        before = _request_count(counter, endpoint)

        with patch("requests.request", return_value=response) as request:
            send("GET", url, source="test", endpoint=endpoint)

        assert request.call_args.args[1] == url
        assert request.call_args.kwargs["headers"]["Accept"] == "application/json"
        assert _request_count(counter, endpoint) == before + 1

    def test_scoped_npm_name_encodes_the_scope_separator(self) -> None:
        assert npm_packument_url("@posthog/types") == "https://registry.npmjs.org/@posthog%2Ftypes"
