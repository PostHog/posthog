from django.test import SimpleTestCase

from products.conversations.backend.ai.evidence import hydrate_ai_sources, outbound_doc_url, parse_chunk_id


class TestAiSourceRefs(SimpleTestCase):
    def test_http_citation_is_outbound(self) -> None:
        assert outbound_doc_url("https://example.com/docs/sdk") == "https://example.com/docs/sdk"
        assert outbound_doc_url("http://example.com/a") == "http://example.com/a"

    def test_javascript_and_relative_refs_are_not_outbound(self) -> None:
        assert outbound_doc_url("javascript:alert(1)") is None
        assert outbound_doc_url("/business-knowledge/abc") is None
        assert outbound_doc_url("not a url") is None

    def test_uuid_refs_parse_and_other_strings_do_not(self) -> None:
        assert parse_chunk_id("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee") is not None
        assert parse_chunk_id("https://example.com/docs") is None

    def test_hydrate_keeps_url_citations_without_a_database(self) -> None:
        sources = hydrate_ai_sources(team_id=1, citations=["https://example.com/docs/sdk"])
        assert len(sources) == 1
        assert sources[0].url == "https://example.com/docs/sdk"
        assert sources[0].title == "example.com/docs/sdk"
        assert sources[0].source_id is None
