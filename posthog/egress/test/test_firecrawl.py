import json
import ipaddress
from collections.abc import Iterator
from contextlib import contextmanager
from io import BytesIO

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

import requests
from parameterized import parameterized
from prometheus_client import REGISTRY
from requests.structures import CaseInsensitiveDict

from posthog.egress.firecrawl.client import (
    MAX_FIRECRAWL_RESPONSE_BYTES,
    FirecrawlNotConfigured,
    FirecrawlPublicTargetRejected,
    FirecrawlScrape,
    FirecrawlScrapeFailed,
    FirecrawlSearchFailed,
    FirecrawlSearchResult,
    scrape,
    scrape_public_url,
    search_public_web,
)
from posthog.egress.firecrawl.limiter import consume_firecrawl_sync, firecrawl_account_key
from posthog.egress.firecrawl.observability import record_firecrawl_api_response
from posthog.egress.firecrawl.transport import FirecrawlEgressBudgetExhausted
from posthog.egress.limiter.policies import Priority, resolve_policy

_FAKE_API_KEY = "fake-key-for-tests"

_SUCCESSFUL_SCRAPE = {
    "success": True,
    "data": {
        "markdown": "# Example",
        "summary": "Example builds widgets.",
        "metadata": {
            "title": "Example",
            "description": "Widgets for everyone.",
            "statusCode": 200,
            "creditsUsed": 1,
        },
    },
}


def _response(status: int, body: str) -> requests.Response:
    response = requests.models.Response()
    response.status_code = status
    response.raw = BytesIO(body.encode())
    return response


def _response_with_rate_limit_headers(headers: dict[str, str], url: str) -> requests.Response:
    response = requests.models.Response()
    response.status_code = 200
    response.headers = CaseInsensitiveDict(headers)
    prepared = requests.models.PreparedRequest()
    prepared.method = "GET"
    prepared.url = url
    response.request = prepared
    return response


@contextmanager
def _firecrawl_answers(response: requests.Response) -> Iterator[tuple[MagicMock, MagicMock]]:
    """Yield the patched sender and limiter gate. The gate is patched so these tests never draw on
    the shared budget counter, which would couple them to each other's ordering."""
    with (
        patch("posthog.egress.firecrawl.transport.consume_firecrawl_sync", return_value=True) as consume,
        patch("requests.request", return_value=response) as request,
    ):
        yield request, consume


@override_settings(FIRECRAWL_API_KEY=_FAKE_API_KEY)
class TestFirecrawlEgress(SimpleTestCase):
    def test_scrape_translates_a_transport_failure(self) -> None:
        with (
            patch(
                "posthog.egress.firecrawl.client.firecrawl_request",
                side_effect=requests.ConnectionError("connection reset"),
            ),
            self.assertRaises(FirecrawlScrapeFailed),
        ):
            scrape("https://example.com", source="test")

    def test_scrape_sends_the_request_shape_firecrawl_documents(self) -> None:
        # Firecrawl reads camelCase body keys and ignores unknown ones, so a snake_case slip would
        # silently scrape whole-page boilerplate instead of the main content, with no error to notice.
        with _firecrawl_answers(_response(200, json.dumps(_SUCCESSFUL_SCRAPE))) as (request, _consume):
            scrape("https://example.com", source="test", formats=["summary"])

        assert request.call_args.args == ("POST", "https://api.firecrawl.dev/v2/scrape")
        kwargs = request.call_args.kwargs
        assert kwargs["headers"]["Authorization"] == f"Bearer {_FAKE_API_KEY}"
        assert kwargs["json"] == {"url": "https://example.com", "formats": ["summary"], "onlyMainContent": True}
        assert kwargs["stream"] is True

    def test_scrape_maps_the_documented_response_onto_the_result(self) -> None:
        # title, description and creditsUsed live under `metadata`, not alongside the formats, so
        # reading them from the wrong level hands callers a result that is silently all None.
        with _firecrawl_answers(_response(200, json.dumps(_SUCCESSFUL_SCRAPE))):
            result = scrape("https://example.com", source="test")

        assert result.markdown == "# Example"
        assert result.summary == "Example builds widgets."
        assert result.title == "Example"
        assert result.description == "Widgets for everyone."
        assert result.status_code == 200
        assert result.credits_used == 1

    def test_scrape_prefers_the_provider_final_url_for_redirect_validation(self) -> None:
        scrape_data = _SUCCESSFUL_SCRAPE["data"]
        assert isinstance(scrape_data, dict)
        scrape_metadata = scrape_data["metadata"]
        assert isinstance(scrape_metadata, dict)
        payload = {
            **_SUCCESSFUL_SCRAPE,
            "data": {
                **scrape_data,
                "metadata": {
                    **scrape_metadata,
                    "sourceURL": "https://example.com/requested",
                    "url": "https://example.com/final",
                },
            },
        }
        with _firecrawl_answers(_response(200, json.dumps(payload))):
            result = scrape("https://example.com/requested", source="test")

        assert result.url == "https://example.com/final"

    @parameterized.expand(
        [
            ("http_error", 402, json.dumps({"error": "Insufficient credits"})),
            ("unsuccessful_body", 200, json.dumps({"success": False, "error": "unreachable"})),
            ("missing_data", 200, json.dumps({"success": True})),
            ("non_json_body", 200, "<html>gateway timeout</html>"),
        ]
    )
    def test_scrape_raises_rather_than_returning_an_empty_result(self, _name: str, status: int, body: str) -> None:
        # Firecrawl answers 200 with `success: false` for pages it could not fetch, so a caller that
        # only checked the HTTP status would treat a failed scrape as a page with no content.
        with _firecrawl_answers(_response(status, body)), self.assertRaises(FirecrawlScrapeFailed):
            scrape("https://example.com", source="test")

    def test_scrape_rejects_a_response_over_its_decompressed_byte_budget(self) -> None:
        response = _response(200, "x" * (MAX_FIRECRAWL_RESPONSE_BYTES + 1))

        with _firecrawl_answers(response), self.assertRaisesRegex(FirecrawlScrapeFailed, "response budget"):
            scrape("https://example.com", source="test")

    def test_scrape_rejects_a_declared_response_over_its_byte_budget_without_reading_it(self) -> None:
        response = _response(200, json.dumps(_SUCCESSFUL_SCRAPE))
        response.headers["Content-Length"] = str(MAX_FIRECRAWL_RESPONSE_BYTES + 1)

        with _firecrawl_answers(response), self.assertRaisesRegex(FirecrawlScrapeFailed, "response budget"):
            scrape("https://example.com", source="test")

    @override_settings(FIRECRAWL_API_KEY="")
    def test_scrape_without_a_configured_key_never_calls_out(self) -> None:
        # Instances run without a key; sending `Bearer ` would spend a request to be told 401.
        with patch("requests.request") as request:
            with self.assertRaises(FirecrawlNotConfigured):
                scrape("https://example.com", source="test")
        request.assert_not_called()

    def test_scrape_defaults_to_a_sheddable_lane(self) -> None:
        # The scraped URL comes from user-influenced input, so this traffic must stay deniable as the
        # shared budget fills. CRITICAL is never shed, which would make the budget advisory.
        with _firecrawl_answers(_response(200, json.dumps(_SUCCESSFUL_SCRAPE))) as (_request, consume):
            scrape("https://example.com", source="test")

        assert consume.call_args.kwargs["priority"] is Priority.NORMAL

    def test_policy_is_registered_for_the_account_key(self) -> None:
        # consume raises for a domain with no registered policy, so this catches the registration side
        # effect being lost (e.g. an import shuffle dropping the register_policy call).
        assert firecrawl_account_key() == "firecrawl:account:default"
        assert consume_firecrawl_sync(source="test") is True

    @override_settings(FIRECRAWL_EGRESS_PER_MINUTE_BUDGET=7, FIRECRAWL_EGRESS_HOURLY_BUDGET=11)
    def test_budgets_come_from_the_settings_they_are_named_after(self) -> None:
        # The policy reads settings through getattr defaults, which would swallow a renamed or
        # misspelled setting and quietly pin the budget to the code default forever.
        assert resolve_policy(firecrawl_account_key()).limits == ((7, 60.0), (11, 3600.0))

    def test_record_response_keys_the_rate_limit_gauges_by_the_request_url(self) -> None:
        # Firecrawl is the one domain whose gauge resource comes from the request url rather than a
        # curated endpoint label. Losing that wiring silently freezes every gauge under "unknown"
        # regardless of which endpoint was actually called.
        record_firecrawl_api_response(
            _response_with_rate_limit_headers(
                {"X-RateLimit-Remaining": "7", "X-RateLimit-Limit": "60"},
                "https://api.firecrawl.dev/v2/scrape",
            ),
            source="unit-test",
        )
        assert (
            REGISTRY.get_sample_value(
                "firecrawl_api_rate_limit_remaining", {"account": "default", "resource": "/v2/scrape"}
            )
            == 7
        )
        assert (
            REGISTRY.get_sample_value(
                "firecrawl_api_rate_limit_limit", {"account": "default", "resource": "/v2/scrape"}
            )
            == 60
        )


class TestPublicFirecrawlResearch(SimpleTestCase):
    def _public_dns_answers(self) -> object:
        return {ipaddress.ip_address("93.184.216.34")}

    @override_settings(FIRECRAWL_API_KEY=_FAKE_API_KEY, FORCE_URL_VALIDATION=True)
    def test_public_search_returns_at_most_three_validated_results(self) -> None:
        response = {
            "success": True,
            "data": {
                "web": [
                    {
                        "url": f"https://example.com/research-{index}",
                        "title": " Example research ",
                        "description": "A result",
                    }
                    for index in range(4)
                ]
            },
        }
        with (
            patch("posthog.security.url_validation.resolve_host_ips", return_value=self._public_dns_answers()),
            _firecrawl_answers(_response(200, json.dumps(response))) as (request, _consume),
        ):
            results = search_public_web("Example market trends", source="subscriptions_pulse_research")

        assert results == (
            FirecrawlSearchResult(
                url="https://example.com/research-0", title="Example research", description="A result"
            ),
            FirecrawlSearchResult(
                url="https://example.com/research-1", title="Example research", description="A result"
            ),
            FirecrawlSearchResult(
                url="https://example.com/research-2", title="Example research", description="A result"
            ),
        )
        assert request.call_args.args == ("POST", "https://api.firecrawl.dev/v2/search")
        assert request.call_args.kwargs["json"] == {"query": "Example market trends", "limit": 3, "sources": ["web"]}
        assert request.call_args.kwargs["stream"] is True

    @parameterized.expand(
        [
            ("private_ip", "http://127.0.0.1/latest/meta-data"),
            ("credentials", "https://user:password@example.com/research"),
            ("non_standard_port", "https://example.com:8443/research"),
            ("control_character", "https://example.com/research\nnext"),
            ("too_long", f"https://example.com/{'x' * 2048}"),
        ]
    )
    def test_public_search_discards_unsafe_result_urls(self, _name: str, url: str) -> None:
        response = {"success": True, "data": {"web": [{"url": url, "title": "Unsafe"}]}}
        with self.settings(FIRECRAWL_API_KEY=_FAKE_API_KEY, FORCE_URL_VALIDATION=True):
            with _firecrawl_answers(_response(200, json.dumps(response))):
                results = search_public_web("Example market trends", source="subscriptions_pulse_research")

        assert results == ()

    @override_settings(FIRECRAWL_API_KEY=_FAKE_API_KEY, FORCE_URL_VALIDATION=True)
    def test_public_scrape_rejects_provider_final_url_that_escapes_the_public_boundary(self) -> None:
        provider_result = FirecrawlScrape(url="http://127.0.0.1/latest/meta-data", markdown="Untrusted")
        with (
            patch("posthog.security.url_validation.resolve_host_ips", return_value=self._public_dns_answers()),
            patch("posthog.egress.firecrawl.client.scrape", return_value=provider_result) as scrape_mock,
            self.assertRaises(FirecrawlPublicTargetRejected),
        ):
            scrape_public_url("https://example.com/research", source="subscriptions_pulse_research")

        scrape_mock.assert_called_once_with(
            "https://example.com/research",
            source="subscriptions_pulse_research",
            formats=("markdown",),
            priority=Priority.NORMAL,
            timeout=(5.0, 45.0),
            lockdown=True,
        )

    @override_settings(FIRECRAWL_API_KEY="")
    def test_public_search_without_a_configured_provider_never_calls_out(self) -> None:
        with patch("requests.request") as request:
            with self.assertRaises(FirecrawlNotConfigured):
                search_public_web("Example market trends", source="subscriptions_pulse_research")
        request.assert_not_called()

    @override_settings(FIRECRAWL_API_KEY=_FAKE_API_KEY)
    def test_public_search_preserves_egress_exhaustion_for_the_caller(self) -> None:
        with (
            patch(
                "posthog.egress.firecrawl.client.firecrawl_request",
                side_effect=FirecrawlEgressBudgetExhausted("budget exhausted"),
            ),
            self.assertRaises(FirecrawlEgressBudgetExhausted),
        ):
            search_public_web("Example market trends", source="subscriptions_pulse_research")

    @override_settings(FIRECRAWL_API_KEY=_FAKE_API_KEY)
    def test_public_search_translates_provider_failures(self) -> None:
        with (
            patch(
                "posthog.egress.firecrawl.client.firecrawl_request",
                side_effect=requests.ConnectionError("connection reset"),
            ),
            self.assertRaises(FirecrawlSearchFailed),
        ):
            search_public_web("Example market trends", source="subscriptions_pulse_research")

    @override_settings(FIRECRAWL_API_KEY=_FAKE_API_KEY)
    def test_public_search_rejects_queries_over_its_budget_before_calling_provider(self) -> None:
        with (
            patch("posthog.egress.firecrawl.client.firecrawl_request") as request,
            self.assertRaises(FirecrawlPublicTargetRejected),
        ):
            search_public_web("x" * 501, source="subscriptions_pulse_research")
        request.assert_not_called()
