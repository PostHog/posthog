from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

import requests
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from parameterized import parameterized
from requests.structures import CaseInsensitiveDict

from posthog.egress.github.limiter import GitHubRateResource
from posthog.egress.github.transport import GitHubClient, github_request


def _response(status: int = 200) -> requests.Response:
    response = requests.models.Response()
    response.status_code = status
    response.headers = CaseInsensitiveDict({})
    prepared = requests.models.PreparedRequest()
    prepared.method = "GET"
    prepared.url = "https://api.github.com/search/code"
    response.request = prepared
    return response


class TestGitHubTransport(SimpleTestCase):
    @parameterized.expand([("success", 200, "UNSET"), ("http_error", 429, "ERROR")])
    def test_request_records_normalized_client_span(self, _name: str, status_code: int, span_status: str) -> None:
        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))

        with (
            patch("posthog.egress.github.transport.tracer", provider.get_tracer("test")),
            patch("posthog.egress.github.transport.consume_github_installation_sync", return_value=True),
            patch("requests.request", return_value=_response(status_code)),
        ):
            github_request(
                "GET",
                "https://api.github.com/repos/example/repo/branches?page=1",
                source="integration",
                installation_id="42",
                endpoint="/repos/{owner}/{repo}/branches",
            )

        span = exporter.get_finished_spans()[0]
        assert span.name == "github.http.request"
        assert span.kind.name == "CLIENT"
        assert span.attributes == {
            "http.request.method": "GET",
            "server.address": "api.github.com",
            "github.endpoint": "/repos/{owner}/{repo}/branches",
            "github.resource": "core",
            "github.source": "integration",
            "github.priority": "critical",
            "github.installation_scoped": True,
            "http.response.status_code": status_code,
        }
        assert span.status.status_code.name == span_status

    @parameterized.expand(
        [
            ("code_search", "https://api.github.com/search/code?q=x", GitHubRateResource.CODE_SEARCH),
            ("core", "https://api.github.com/repos/o/r/pulls/1", GitHubRateResource.CORE),
        ]
    )
    def test_consume_routes_resource_by_url(self, _name: str, url: str, expected: GitHubRateResource) -> None:
        # The gate must charge each URL to the meter GitHub bills it against — the whole point of the
        # per-resource split. A regression here reverts /search/code to the core envelope.
        client = GitHubClient()
        with patch("posthog.egress.github.transport.consume_github_installation_sync", return_value=True) as consume:
            client._consume("42", MagicMock(), "test", url)
        assert consume.call_args.kwargs["resource"] == expected

    def test_identity_blind_call_never_touches_the_limiter(self) -> None:
        # A None installation_id (public token / raw PAT) records volume only and must skip the gate,
        # or unrelated tokens would share and clobber one phantom budget.
        with (
            patch("posthog.egress.github.transport.consume_github_installation_sync") as consume,
            patch("requests.request", return_value=_response()),
        ):
            github_request("GET", "https://api.github.com/search/code?q=x", source="test", installation_id=None)
        consume.assert_not_called()

    def test_span_uses_the_request_host_for_raw_github_urls(self) -> None:
        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))

        with (
            patch("posthog.egress.github.transport.tracer", provider.get_tracer("test")),
            patch("requests.request", return_value=_response()),
        ):
            github_request("GET", "https://raw.githubusercontent.com/PostHog/posthog/main/README.md", source="test")

        attributes = exporter.get_finished_spans()[0].attributes
        assert attributes is not None
        assert attributes["server.address"] == "raw.githubusercontent.com"

    def test_span_matches_identity_blind_request_without_explicit_endpoint(self) -> None:
        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))

        with (
            patch("posthog.egress.github.transport.tracer", provider.get_tracer("test")),
            patch("requests.request", return_value=_response()),
        ):
            github_request(
                "GET",
                "https://api.github.com/repos/example/repo/branches?page=1",
                source="test",
                installation_id="",
            )

        attributes = exporter.get_finished_spans()[0].attributes
        assert attributes is not None
        assert attributes["github.endpoint"] == "/repos/{owner}/{repo}/branches"
        assert attributes["github.installation_scoped"] is False
