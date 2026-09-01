import json
from collections.abc import Iterator
from contextlib import contextmanager
from io import BytesIO
from time import monotonic, sleep

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

import requests
from parameterized import parameterized

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

    def test_scrape_stops_reading_when_the_total_deadline_expires(self) -> None:
        response = _response(200, json.dumps(_SUCCESSFUL_SCRAPE))

        def slow_body(chunk_size: int | None = 1, decode_unicode: bool = False) -> Iterator[bytes]:
            del chunk_size, decode_unicode
            sleep(0.1)
            yield b"{}"

        started_at = monotonic()
        with (
            patch("posthog.egress.firecrawl.client.firecrawl_request", return_value=response),
            patch.object(response, "iter_content", side_effect=slow_body),
            self.assertRaisesRegex(FirecrawlScrapeFailed, "total deadline"),
        ):
            scrape(
                "https://example.com",
                source="test",
                deadline=monotonic() + 0.02,
            )

        assert monotonic() - started_at < 0.08

    def test_scrape_stops_waiting_for_response_headers_when_the_total_deadline_expires(self) -> None:
        response = _response(200, json.dumps(_SUCCESSFUL_SCRAPE))

        def slow_request(*_args: object, **_kwargs: object) -> requests.Response:
            sleep(0.1)
            return response

        started_at = monotonic()
        with (
            patch("posthog.egress.firecrawl.client.firecrawl_request", side_effect=slow_request),
            self.assertRaisesRegex(FirecrawlScrapeFailed, "total deadline"),
        ):
            scrape(
                "https://example.com",
                source="test",
                deadline=monotonic() + 0.02,
            )

        assert monotonic() - started_at < 0.08

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


class TestPublicFirecrawlTargets(SimpleTestCase):
    @override_settings(FIRECRAWL_API_KEY=_FAKE_API_KEY)
    def test_public_search_translates_a_transport_failure(self) -> None:
        with (
            patch(
                "posthog.egress.firecrawl.client.firecrawl_request",
                side_effect=requests.ConnectionError("connection reset"),
            ),
            self.assertRaises(FirecrawlSearchFailed),
        ):
            search_public_web(
                "Example market trends",
                source="subscriptions_pulse_research",
                allowed_domains=("example.com",),
            )

    @override_settings(FIRECRAWL_API_KEY=_FAKE_API_KEY)
    def test_public_search_accepts_any_public_domain_without_scraping_results(self) -> None:
        response = {
            "success": True,
            "data": {
                "web": [
                    {
                        "url": "https://www.example.com/research",
                        "title": "  Example research  ",
                        "description": "A public result",
                    }
                ]
            },
        }
        with (
            patch(
                "posthog.egress.firecrawl.client.socket.getaddrinfo",
                return_value=[(2, 1, 6, "", ("93.184.216.34", 443))],
            ),
            _firecrawl_answers(_response(200, json.dumps(response))) as (request, _consume),
        ):
            results = search_public_web(
                "Example market trends",
                source="subscriptions_pulse_research",
                limit=3,
            )

        assert results == (
            FirecrawlSearchResult(
                url="https://www.example.com/research",
                title="Example research",
                description="A public result",
            ),
        )
        assert request.call_args.args == ("POST", "https://api.firecrawl.dev/v2/search")
        assert request.call_args.kwargs["json"] == {
            "query": "Example market trends",
            "limit": 3,
            "sources": ["web"],
        }
        assert "scrapeOptions" not in request.call_args.kwargs["json"]
        assert request.call_args.kwargs["stream"] is True

    @override_settings(FIRECRAWL_API_KEY=_FAKE_API_KEY)
    def test_public_search_discards_private_results(self) -> None:
        response = {
            "success": True,
            "data": {"web": [{"url": "http://127.0.0.1/research", "title": "Private"}]},
        }
        with _firecrawl_answers(_response(200, json.dumps(response))):
            results = search_public_web(
                "Example market trends",
                source="subscriptions_pulse_research",
            )

        assert results == ()

    def test_public_scrape_rejects_private_hosts_before_calling_provider(self) -> None:
        with (
            self.assertRaises(FirecrawlPublicTargetRejected),
            patch("posthog.egress.firecrawl.client.scrape") as scrape_mock,
        ):
            scrape_public_url(
                "http://127.0.0.1/latest/meta-data",
                source="subscriptions_pulse_research",
            )

        scrape_mock.assert_not_called()

    def test_public_scrape_stops_waiting_for_dns_when_the_total_deadline_expires(self) -> None:
        def slow_dns(*_args: object, **_kwargs: object) -> list[tuple[int, int, int, str, tuple[str, int]]]:
            sleep(0.1)
            return [(2, 1, 6, "", ("93.184.216.34", 443))]

        started_at = monotonic()
        with (
            patch("posthog.egress.firecrawl.client.socket.getaddrinfo", side_effect=slow_dns),
            patch("posthog.egress.firecrawl.client.scrape") as scrape_mock,
            self.assertRaisesRegex(FirecrawlScrapeFailed, "total deadline"),
        ):
            scrape_public_url(
                "https://example.com/research",
                source="subscriptions_pulse_research",
                deadline=monotonic() + 0.02,
            )

        assert monotonic() - started_at < 0.08
        scrape_mock.assert_not_called()

    def test_public_scrape_checks_each_dns_answer_and_the_provider_final_url(self) -> None:
        provider_result = FirecrawlScrape(url="https://www.example.com/market", markdown="Bounded public content")
        with (
            patch(
                "posthog.egress.firecrawl.client.socket.getaddrinfo",
                return_value=[(2, 1, 6, "", ("93.184.216.34", 443))],
            ),
            patch("posthog.egress.firecrawl.client.scrape", return_value=provider_result) as scrape_mock,
        ):
            result = scrape_public_url(
                "https://example.com/market",
                source="subscriptions_pulse_research",
                timeout=(2.0, 10.0),
            )

        assert result == provider_result
        scrape_mock.assert_called_once_with(
            "https://example.com/market",
            source="subscriptions_pulse_research",
            formats=("markdown",),
            lockdown=True,
            timeout=(2.0, 10.0),
            deadline=None,
        )

    def test_public_scrape_rejects_provider_redirect_to_a_private_host(self) -> None:
        provider_result = FirecrawlScrape(url="http://127.0.0.1/redirect", markdown="Untrusted")
        with (
            patch(
                "posthog.egress.firecrawl.client.socket.getaddrinfo",
                return_value=[(2, 1, 6, "", ("93.184.216.34", 443))],
            ),
            patch("posthog.egress.firecrawl.client.scrape", return_value=provider_result),
            self.assertRaises(FirecrawlPublicTargetRejected),
        ):
            scrape_public_url(
                "https://example.com/market",
                source="subscriptions_pulse_research",
            )
