from unittest.mock import MagicMock

from django.test import SimpleTestCase

import requests
from parameterized import parameterized
from prometheus_client import REGISTRY
from requests.structures import CaseInsensitiveDict

from posthog.egress.github.observability import (
    _normalize_github_endpoint,
    record_github_api_exception,
    record_github_api_response,
)
from posthog.egress.observability.observability import (
    default_normalize_endpoint,
    record_outbound_api_response,
    resolve_egress_observability,
)

_COUNTER = "github_integration_api_requests_total"
_REMAINING = "github_integration_api_rate_limit_remaining"


def _response(
    *,
    status: int = 200,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    url: str = "https://api.github.com/repos/posthog/posthog/commits",
) -> requests.Response:
    response = requests.models.Response()
    response.status_code = status
    response.headers = CaseInsensitiveDict(headers or {})
    prepared = requests.models.PreparedRequest()
    prepared.method = method
    prepared.url = url
    response.request = prepared
    return response


class TestGithubObservability(SimpleTestCase):
    @parameterized.expand(
        [
            ("https://api.github.com/repos/posthog/posthog/commits", "/repos/{owner}/{repo}/commits"),
            (
                "https://api.github.com/repos/o/r/actions/runs/42/jobs",
                "/repos/{owner}/{repo}/actions/runs/{id}/jobs",
            ),
            ("https://api.github.com/repositories/12345", "/repositories/{id}"),
            ("https://api.github.com/search/code?q=x", "/search/code"),
            # Visual review's high-cardinality URLs: commit SHA, compare refs, and file path.
            (
                "https://api.github.com/repos/o/r/statuses/a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
                "/repos/{owner}/{repo}/statuses/{sha}",
            ),
            ("https://api.github.com/repos/o/r/compare/main...feature", "/repos/{owner}/{repo}/compare/{refs}"),
            (
                "https://api.github.com/repos/o/r/contents/.github/visual-review.yml",
                "/repos/{owner}/{repo}/contents/{path}",
            ),
            (None, "unknown"),
        ]
    )
    def test_normalize_endpoint_bounds_cardinality(self, url: str | None, expected: str) -> None:
        self.assertEqual(_normalize_github_endpoint(url), expected)

    @parameterized.expand(
        [
            ("https://example.com/v1/widgets/42", "/v1/widgets/{id}"),
            ("https://example.com/", "/"),
            (None, "unknown"),
        ]
    )
    def test_default_normalizer_collapses_numeric_ids(self, url: str | None, expected: str) -> None:
        self.assertEqual(default_normalize_endpoint(url), expected)

    def test_records_counter_and_gauges_when_installation_id_known(self) -> None:
        before = REGISTRY.get_sample_value(
            _COUNTER,
            {
                "installation_id": "42",
                "method": "GET",
                "endpoint": "/repos/{owner}/{repo}/commits",
                "status_code": "200",
                "source": "unit-known",
            },
        )
        record_github_api_response(
            _response(headers={"X-RateLimit-Remaining": "4321", "X-RateLimit-Resource": "core"}),
            source="unit-known",
            installation_id="42",
        )

        after = REGISTRY.get_sample_value(
            _COUNTER,
            {
                "installation_id": "42",
                "method": "GET",
                "endpoint": "/repos/{owner}/{repo}/commits",
                "status_code": "200",
                "source": "unit-known",
            },
        )
        self.assertEqual((after or 0) - (before or 0), 1)
        self.assertEqual(
            REGISTRY.get_sample_value(_REMAINING, {"installation_id": "42", "resource": "core"}),
            4321,
        )

    def test_skips_gauges_when_identity_unknown(self) -> None:
        # Identity-blind callers (raw-token sources) must not set the per-installation gauge — otherwise
        # many installations alias onto the empty installation_id and the last write wins, misleadingly.
        record_github_api_response(
            _response(headers={"X-RateLimit-Remaining": "10", "X-RateLimit-Resource": "core"}),
            source="unit-blind",
        )
        self.assertIsNone(REGISTRY.get_sample_value(_REMAINING, {"installation_id": "", "resource": "core"}))
        self.assertEqual(
            REGISTRY.get_sample_value(
                _COUNTER,
                {
                    "installation_id": "",
                    "method": "GET",
                    "endpoint": "/repos/{owner}/{repo}/commits",
                    "status_code": "200",
                    "source": "unit-blind",
                },
            ),
            1,
        )

    def test_generic_resolver_routes_to_github(self) -> None:
        self.assertIs(resolve_egress_observability("github").domain, "github")
        record_outbound_api_response(
            _response(status=403, url="https://api.github.com/search/code"),
            domain="github",
            source="unit-generic",
        )
        self.assertEqual(
            REGISTRY.get_sample_value(
                _COUNTER,
                {
                    "installation_id": "",
                    "method": "GET",
                    "endpoint": "/search/code",
                    "status_code": "403",
                    "source": "unit-generic",
                },
            ),
            1,
        )

    def test_unregistered_domain_raises(self) -> None:
        with self.assertRaises(ValueError):
            resolve_egress_observability("definitely-not-registered")

    def test_records_without_crashing_when_request_is_a_mock(self) -> None:
        # A MagicMock response auto-vivifies .request.url / .request.method as Mocks (non-str);
        # the recorder must coerce them to defaults, not raise urlparse(Mock) into the caller.
        response = MagicMock()
        response.status_code = 200
        response.headers = CaseInsensitiveDict({})
        record_github_api_response(response, source="unit-mockreq")
        self.assertEqual(
            REGISTRY.get_sample_value(
                _COUNTER,
                {
                    "installation_id": "",
                    "method": "GET",
                    "endpoint": "unknown",
                    "status_code": "200",
                    "source": "unit-mockreq",
                },
            ),
            1,
        )

    def test_exception_record_uppercases_method(self) -> None:
        record_github_api_exception(source="unit-exc", method="get", endpoint="/foo")
        self.assertEqual(
            REGISTRY.get_sample_value(
                _COUNTER,
                {
                    "installation_id": "",
                    "method": "GET",
                    "endpoint": "/foo",
                    "status_code": "exception",
                    "source": "unit-exc",
                },
            ),
            1,
        )
