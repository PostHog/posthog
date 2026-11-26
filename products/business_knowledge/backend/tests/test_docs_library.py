import json
from typing import Any

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from django.urls import resolve

import httpx
from parameterized import parameterized

from products.business_knowledge.backend import docs_library
from products.business_knowledge.backend.docs_library import pages_from_results, search_docs_library
from products.business_knowledge.backend.facade.contracts import DocsPage

LIBRARY_SETTINGS = {
    "DOCS_SEARCH_LIBRARY_API_KEY": "phs_docs_library_test_key",
    "DOCS_SEARCH_LIBRARY_HOST": "https://docs-library.example.com",
    "DOCS_SEARCH_LIBRARY_PROJECT_ID": "2",
    "DOCS_SEARCH_LIBRARY_ID": "0193c1f0-0000-7000-8000-000000000001",
}
ORGANIZATION_ID = "0193c1f0-0000-7000-8000-0000000000aa"


def _chunk(document_id: str, ordinal: int, content: str, url: str, title: str = "Feature flags") -> dict[str, Any]:
    return {"document_id": document_id, "ordinal": ordinal, "content": content, "url": url, "document_title": title}


class TestPagesFromResults(SimpleTestCase):
    def test_chunks_of_one_document_become_one_page_in_reading_order(self) -> None:
        flags = "https://posthog.com/docs/feature-flags"
        replay = "https://posthog.com/docs/session-replay"

        pages = pages_from_results(
            [
                _chunk("doc-flags", 4, "Roll out to a percentage.", flags),
                _chunk("doc-replay", 0, "Record sessions.", replay, title="Session replay"),
                _chunk("doc-flags", 3, "Create a flag.", flags),
            ]
        )

        assert pages == [
            DocsPage(title="Feature flags", url=flags, text="Create a flag.\n\nRoll out to a percentage."),
            DocsPage(title="Session replay", url=replay, text="Record sessions."),
        ]

    @parameterized.expand(
        [
            ("docs_page", "https://posthog.com/docs/feature-flags", True),
            ("www", "https://www.posthog.com/docs/api", True),
            ("other_subdomain", "https://wiki.posthog.com/runbook", False),
            ("internal_wiki", "https://wiki.internal.example.com/runbook", False),
            ("lookalike_host", "https://posthog.com.example.com/docs", False),
            ("plain_http", "http://posthog.com/docs/feature-flags", False),
            ("no_url", "", False),
        ]
    )
    def test_only_public_docs_hosts_are_returned(self, _name: str, url: str, expected: bool) -> None:
        pages = pages_from_results([_chunk("doc-1", 0, "Some text.", url)])

        assert bool(pages) is expected


@override_settings(**LIBRARY_SETTINGS)
class TestSearchDocsLibrary(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.requests: list[httpx.Request] = []
        flag = patch("posthoganalytics.feature_enabled", return_value=True)
        self.feature_enabled = flag.start()
        self.addCleanup(flag.stop)
        throttle = patch.object(docs_library, "_throttled_until", 0.0)
        throttle.start()
        self.addCleanup(throttle.stop)

    def _transport(self, response: httpx.Response | Exception) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            if isinstance(response, Exception):
                raise response
            return response

        return httpx.MockTransport(handler)

    async def test_searches_the_configured_library_with_the_key(self) -> None:
        url = "https://posthog.com/docs/feature-flags"
        transport = self._transport(httpx.Response(200, json=[_chunk("doc-1", 0, "Create a flag.", url)]))

        pages = await search_docs_library("how do flags work", organization_id=ORGANIZATION_ID, transport=transport)

        assert pages == [DocsPage(title="Feature flags", url=url, text="Create a flag.")]
        request = self.requests[0]
        assert request.url.host == "docs-library.example.com"
        assert request.headers["Authorization"] == "Bearer phs_docs_library_test_key"
        assert request.method == "POST"
        assert request.url.query == b""
        assert json.loads(request.content) == {
            "query": "how do flags work",
            "limit": 10,
            "library_id": LIBRARY_SETTINGS["DOCS_SEARCH_LIBRARY_ID"],
        }
        assert resolve(request.url.path).url_name == "project_business_knowledge_documents-search"

    @parameterized.expand(
        [
            ("throttled", httpx.Response(429, json={"detail": "Request was throttled."})),
            ("library_deleted", httpx.Response(404, json={"detail": "Not found."})),
            ("server_error", httpx.Response(500, text="oops")),
            ("not_a_list", httpx.Response(200, json={"detail": "unexpected"})),
            ("timeout", httpx.ReadTimeout("timed out")),
        ]
    )
    async def test_a_failed_search_returns_no_pages(self, _name: str, response: httpx.Response | Exception) -> None:
        pages = await search_docs_library(
            "how do flags work", organization_id=ORGANIZATION_ID, transport=self._transport(response)
        )

        assert pages == []
        assert len(self.requests) == 1

    async def test_a_throttled_library_gets_no_request_until_the_wait_ends(self) -> None:
        transport = self._transport(httpx.Response(429, headers={"Retry-After": "30"}, json={"detail": "Throttled."}))

        for _ in range(2):
            pages = await search_docs_library("how do flags work", organization_id=ORGANIZATION_ID, transport=transport)
            assert pages == []

        assert len(self.requests) == 1

    @parameterized.expand(
        [
            ("flag_off", {}, False),
            ("no_key", {"DOCS_SEARCH_LIBRARY_API_KEY": ""}, True),
            ("no_library_id", {"DOCS_SEARCH_LIBRARY_ID": ""}, True),
        ]
    )
    async def test_no_request_is_sent_when_the_library_is_off(
        self, _name: str, settings_override: dict[str, str], flag_on: bool
    ) -> None:
        self.feature_enabled.return_value = flag_on
        transport = self._transport(httpx.Response(200, json=[]))

        with override_settings(**settings_override):
            pages = await search_docs_library("how do flags work", organization_id=ORGANIZATION_ID, transport=transport)

        assert pages == []
        assert self.requests == []
