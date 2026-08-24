import json
from collections.abc import Iterator
from contextlib import contextmanager

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

import requests
from parameterized import parameterized

from posthog.egress.firecrawl.client import FirecrawlNotConfigured, FirecrawlScrapeFailed, scrape
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
    response._content = body.encode()
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
    def test_scrape_sends_the_request_shape_firecrawl_documents(self) -> None:
        # Firecrawl reads camelCase body keys and ignores unknown ones, so a snake_case slip would
        # silently scrape whole-page boilerplate instead of the main content, with no error to notice.
        with _firecrawl_answers(_response(200, json.dumps(_SUCCESSFUL_SCRAPE))) as (request, _consume):
            scrape("https://example.com", source="test", formats=["summary"])

        assert request.call_args.args == ("POST", "https://api.firecrawl.dev/v2/scrape")
        kwargs = request.call_args.kwargs
        assert kwargs["headers"]["Authorization"] == f"Bearer {_FAKE_API_KEY}"
        assert kwargs["json"] == {"url": "https://example.com", "formats": ["summary"], "onlyMainContent": True}

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
