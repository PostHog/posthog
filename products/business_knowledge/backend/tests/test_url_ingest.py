"""
Tests for Stage 2a URL ingestion: SSRF hardening, fetch/parse/chunk happy
path, conditional-GET 304 behavior, cross-team isolation on refresh.

Design notes:
- We mock `requests.Session.get` at the module level of `url_fetch` rather
  than monkey-patching `requests` globally — keeps blast radius to this
  product's fetch path and matches how other PostHog tests isolate HTTP.
- SSRF is covered exhaustively in `posthog/security/test/test_url_validation.py`.
  We only smoke-test that our create path *routes through* it (one localhost
  attempt should fail fast).
"""

from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status

from products.business_knowledge.backend import url_fetch
from products.business_knowledge.backend.html_parse import _bs4_fallback, parse_html
from products.business_knowledge.backend.logic import (
    InvalidUrlError,
    QuotaExceededError,
    SourceBusyError,
    chunk_text,
    create_url_source,
    refresh_source,
    update_url_source,
)
from products.business_knowledge.backend.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSource,
    RefreshStatus,
    SourceStatus,
    SourceType,
)


def _mock_response(
    *,
    status_code: int = 200,
    body: bytes = b"",
    content_type: str = "text/html; charset=utf-8",
    etag: str | None = None,
    location: str | None = None,
) -> MagicMock:
    headers: dict[str, str] = {"Content-Type": content_type}
    if etag:
        headers["ETag"] = etag
    if location:
        headers["Location"] = location
    response = MagicMock()
    response.status_code = status_code
    response.headers = headers
    response.iter_content = MagicMock(return_value=iter([body] if body else []))
    response.close = MagicMock()
    return response


class TestNormalizeUrl(BaseTest):
    def test_strips_userinfo(self) -> None:
        assert url_fetch.strip_userinfo("https://user:pass@example.com/x") == "https://example.com/x"

    def test_lowercases_host_and_scheme(self) -> None:
        assert url_fetch.normalize_url("HTTPS://Example.COM/PATH") == "https://example.com/PATH"

    def test_drops_fragment(self) -> None:
        assert url_fetch.normalize_url("https://example.com/x#section") == "https://example.com/x"

    @parameterized.expand(
        [
            ("empty", ""),
            ("scheme_only", "http://"),
            ("missing_scheme", "example.com/x"),
        ]
    )
    def test_rejects_garbage(self, _name: str, raw: str) -> None:
        with self.assertRaises(url_fetch.UrlFetchError):
            url_fetch.normalize_url(raw)


class TestFetchUrl(BaseTest):
    @patch("products.business_knowledge.backend.url_fetch.validate_url_and_pin_ips", return_value=(True, None, set()))
    @patch("products.business_knowledge.backend.url_fetch.requests.Session")
    def test_happy_path_returns_body(self, mock_session_cls: MagicMock, _ssrf: MagicMock) -> None:
        session = mock_session_cls.return_value
        session.get.return_value = _mock_response(body=b"<html>hi</html>", etag='"abc"')
        result = url_fetch.fetch_url("https://example.com/x")
        assert result.status == 200
        assert result.body == b"<html>hi</html>"
        assert result.etag == '"abc"'

    @patch("products.business_knowledge.backend.url_fetch.validate_url_and_pin_ips", return_value=(True, None, set()))
    @patch("products.business_knowledge.backend.url_fetch.requests.Session")
    def test_conditional_get_returns_304(self, mock_session_cls: MagicMock, _ssrf: MagicMock) -> None:
        session = mock_session_cls.return_value
        session.get.return_value = _mock_response(status_code=304, body=b"")
        result = url_fetch.fetch_url("https://example.com/x", etag='"abc"')
        assert result.status == 304
        assert result.body is None

    @patch("products.business_knowledge.backend.url_fetch.validate_url_and_pin_ips", return_value=(True, None, set()))
    @patch("products.business_knowledge.backend.url_fetch.requests.Session")
    def test_size_cap_aborts(self, mock_session_cls: MagicMock, _ssrf: MagicMock) -> None:
        session = mock_session_cls.return_value
        # Bigger than URL_MAX_BYTES.
        big_chunk = b"x" * (10 * 1024 * 1024 + 1)
        response = _mock_response(body=b"")
        response.iter_content = MagicMock(return_value=iter([big_chunk]))
        session.get.return_value = response
        with self.assertRaises(url_fetch.UrlFetchError):
            url_fetch.fetch_url("https://example.com/x")

    @patch("products.business_knowledge.backend.url_fetch.validate_url_and_pin_ips")
    @patch("products.business_knowledge.backend.url_fetch.requests.Session")
    def test_redirect_revalidates_ssrf(self, mock_session_cls: MagicMock, mock_ssrf: MagicMock) -> None:
        # First hop allowed (public), second hop blocked (internal). If the
        # client blindly followed, the second Location would be fetched.
        mock_ssrf.side_effect = [(True, None, set()), (False, "Loopback", set())]
        session = mock_session_cls.return_value
        session.get.return_value = _mock_response(status_code=302, body=b"", location="http://127.0.0.1/admin")
        with self.assertRaises(url_fetch.UrlFetchError):
            url_fetch.fetch_url("https://example.com/x")
        # SSRF check was re-run on the redirect target.
        assert mock_ssrf.call_count == 2

    @patch(
        "products.business_knowledge.backend.url_fetch.validate_url_and_pin_ips",
        return_value=(False, "Loopback", set()),
    )
    def test_ssrf_blocked_upfront(self, _ssrf: MagicMock) -> None:
        with self.assertRaises(url_fetch.UrlFetchError):
            url_fetch.fetch_url("http://localhost/admin")


_BASIC_HTML = b"""<!doctype html>
<html><head><title>Billing</title></head>
<body>
<article>
<h1>Refund policy</h1>
<p>We issue full refunds within 30 days of purchase. No questions asked.</p>
<p>To request a refund, open a ticket with your order number.</p>
</article>
</body></html>"""


class TestParseHtml(BaseTest):
    def test_blocks_are_blank_line_separated_and_chunk_on_paragraphs(self) -> None:
        # Regression: txt extraction separated blocks with single newlines, so
        # the chunker (which splits on blank lines) saw one mega-paragraph and
        # hard-split mid-sentence. Markdown output must keep blank lines.
        paragraphs = "".join(
            f"<h2>Section {i}</h2><p>Paragraph {i} with realistic prose content that runs long enough "
            f"to matter for chunk packing and boundary checks in this regression test.</p>"
            for i in range(30)
        )
        html = f"<html><head><title>Doc</title></head><body><article>{paragraphs}</article></body></html>".encode()

        title, text = parse_html(html, "https://example.com/doc", content_type="text/html")
        assert title
        assert "\n\n" in text
        chunks = chunk_text(text)
        assert len(chunks) > 1
        # Paragraph-aligned packing — every chunk ends on a block boundary
        # (a full sentence or a heading line), never a mid-sentence hard split.
        for chunk in chunks:
            last_line = chunk.content.rstrip().splitlines()[-1]
            assert last_line.startswith("#") or last_line.endswith((".", "?", "!"))

    def test_fallback_strips_nav_and_footer(self) -> None:
        html = (
            "<html><body>"
            '<nav><a href="/pricing">Pricing</a><a href="/docs">Docs</a></nav>'
            "<main><p>Actual page content.</p></main>"
            '<footer><a href="/privacy">Privacy</a> Copyright</footer>'
            "</body></html>"
        )
        text = _bs4_fallback(html)
        assert "Actual page content." in text
        assert "Pricing" not in text
        assert "Privacy" not in text

    def test_non_utf8_page_decodes_correctly(self) -> None:
        html_str = (
            '<html><head><meta charset="windows-1251"><title>Тест</title></head>'
            "<body><article><p>Первый абзац с настоящим содержимым, достаточно длинный для извлечения.</p>"
            "<p>Второй абзац тоже с настоящим содержимым для проверки декодирования.</p></article></body></html>"
        )
        title, text = parse_html(html_str.encode("windows-1251"), "https://example.com/ru")
        assert "Первый абзац" in text
        assert "\ufffd" not in text
        assert title == "Тест"


class TestCreateUrlSource(BaseTest):
    @patch("products.business_knowledge.backend.logic.url_fetch.fetch_url")
    @patch("products.business_knowledge.backend.logic.is_url_allowed", return_value=(True, None))
    def test_happy_path_creates_document_and_chunks(self, _ssrf: MagicMock, mock_fetch: MagicMock) -> None:
        mock_fetch.return_value = url_fetch.FetchResult(
            status=200,
            body=_BASIC_HTML,
            content_type="text/html",
            etag='"v1"',
            final_url="https://docs.example.com/billing",
        )
        source = create_url_source(
            team_id=self.team.id,
            created_by_id=self.user.id,
            name="Billing docs",
            url="https://docs.example.com/billing",
        )
        assert source.status == SourceStatus.READY
        assert source.source_type == SourceType.URL
        assert source.source_url == "https://docs.example.com/billing"
        assert source.last_refresh_status == RefreshStatus.SUCCESS
        assert source.last_etag == '"v1"'
        assert KnowledgeDocument.objects.unscoped().filter(source=source).count() == 1
        assert KnowledgeChunk.objects.unscoped().filter(source=source, team=self.team).count() >= 1

    @patch("products.business_knowledge.backend.logic.is_url_allowed", return_value=(False, "Loopback"))
    def test_ssrf_rejection_does_not_create_source(self, _ssrf: MagicMock) -> None:
        with self.assertRaises(InvalidUrlError):
            create_url_source(
                team_id=self.team.id,
                created_by_id=self.user.id,
                name="Bad",
                url="http://127.0.0.1/admin",
            )
        assert KnowledgeSource.objects.unscoped().filter(team=self.team).count() == 0

    @patch("products.business_knowledge.backend.logic.url_fetch.fetch_url")
    @patch("products.business_knowledge.backend.logic.is_url_allowed", return_value=(True, None))
    def test_fetch_failure_persists_error_source(self, _ssrf: MagicMock, mock_fetch: MagicMock) -> None:
        mock_fetch.side_effect = url_fetch.UrlFetchError("Remote responded with status 503.")
        source = create_url_source(
            team_id=self.team.id,
            created_by_id=self.user.id,
            name="Flaky",
            url="https://flaky.example.com/",
        )
        assert source.status == SourceStatus.ERROR
        assert source.last_refresh_status == RefreshStatus.ERROR
        assert source.error_message == "Remote responded with status 503."

    @patch("products.business_knowledge.backend.logic.url_fetch.fetch_url")
    @patch("products.business_knowledge.backend.logic.is_url_allowed", return_value=(True, None))
    def test_quota_exceeded_during_chunk_insert_marks_error(self, _ssrf: MagicMock, mock_fetch: MagicMock) -> None:
        mock_fetch.return_value = url_fetch.FetchResult(
            status=200,
            body=_BASIC_HTML,
            content_type="text/html",
            etag='"v1"',
            final_url="https://docs.example.com/billing",
        )
        with patch(
            "products.business_knowledge.backend.logic._replace_source_content",
            side_effect=QuotaExceededError("Team already near the 100000 chunk cap."),
        ):
            with self.assertRaises(QuotaExceededError):
                create_url_source(
                    team_id=self.team.id,
                    created_by_id=self.user.id,
                    name="Over quota",
                    url="https://docs.example.com/billing",
                )
        source = KnowledgeSource.objects.unscoped().get(team_id=self.team.id, name="Over quota")
        assert source.status == SourceStatus.ERROR
        assert "Quota exceeded" in source.error_message

    @patch("products.business_knowledge.backend.logic.url_fetch.fetch_url")
    @patch("products.business_knowledge.backend.logic.is_url_allowed", return_value=(True, None))
    def test_concurrent_create_blocked_by_processing_claim(self, _ssrf: MagicMock, mock_fetch: MagicMock) -> None:
        mock_fetch.return_value = url_fetch.FetchResult(
            status=200,
            body=_BASIC_HTML,
            content_type="text/html",
            etag='"v1"',
            final_url="https://docs.example.com/billing",
        )
        create_url_source(
            team_id=self.team.id,
            created_by_id=self.user.id,
            name="First",
            url="https://docs.example.com/billing",
        )
        # Simulate a PROCESSING row left by a concurrent in-flight request.
        KnowledgeSource.objects.unscoped().create(
            team_id=self.team.id,
            name="In-flight",
            source_type=SourceType.URL,
            status=SourceStatus.PROCESSING,
            source_url="https://other.example.com/",
        )
        with self.assertRaises(SourceBusyError):
            create_url_source(
                team_id=self.team.id,
                created_by_id=self.user.id,
                name="Second",
                url="https://other.example.com/",
            )
        # The fetch should never be called for the second create.
        assert mock_fetch.call_count == 1


class TestUpdateUrlSource(BaseTest):
    def _seed(self) -> KnowledgeSource:
        with (
            patch(
                "products.business_knowledge.backend.logic.url_fetch.fetch_url",
                return_value=url_fetch.FetchResult(
                    status=200,
                    body=_BASIC_HTML,
                    content_type="text/html",
                    etag='"v1"',
                    final_url="https://docs.example.com/billing",
                ),
            ),
            patch("products.business_knowledge.backend.logic.is_url_allowed", return_value=(True, None)),
        ):
            return create_url_source(
                team_id=self.team.id,
                created_by_id=self.user.id,
                name="Billing",
                url="https://docs.example.com/billing",
            )

    @patch("products.business_knowledge.backend.logic.url_fetch.fetch_url")
    @patch("products.business_knowledge.backend.logic.is_url_allowed", return_value=(True, None))
    def test_busy_reverts_url_change(self, _ssrf: MagicMock, _fetch: MagicMock) -> None:
        source = self._seed()
        KnowledgeSource.objects.unscoped().create(
            team_id=self.team.id,
            name="Blocker",
            source_type=SourceType.URL,
            status=SourceStatus.PROCESSING,
            source_url="https://blocker.example.com/",
        )
        with self.assertRaises(SourceBusyError):
            update_url_source(
                source_id=source.id,
                team_id=self.team.id,
                url="https://new.example.com/docs",
            )
        source.refresh_from_db()
        assert source.source_url == "https://docs.example.com/billing"


class TestRefreshSource(BaseTest):
    def _seed(self, etag: str = '"old"') -> KnowledgeSource:
        with (
            patch(
                "products.business_knowledge.backend.logic.url_fetch.fetch_url",
                return_value=url_fetch.FetchResult(
                    status=200,
                    body=_BASIC_HTML,
                    content_type="text/html",
                    etag=etag,
                    final_url="https://docs.example.com/billing",
                ),
            ),
            patch("products.business_knowledge.backend.logic.is_url_allowed", return_value=(True, None)),
        ):
            return create_url_source(
                team_id=self.team.id,
                created_by_id=self.user.id,
                name="Billing",
                url="https://docs.example.com/billing",
            )

    @patch("products.business_knowledge.backend.logic.url_fetch.fetch_url")
    @patch("products.business_knowledge.backend.logic.is_url_allowed", return_value=(True, None))
    def test_304_keeps_chunks_marks_not_modified(self, _ssrf: MagicMock, mock_fetch: MagicMock) -> None:
        source = self._seed(etag='"v1"')
        original_chunks = list(
            KnowledgeChunk.objects.unscoped().filter(source=source).order_by("ordinal").values_list("id", flat=True)
        )
        mock_fetch.return_value = url_fetch.FetchResult(
            status=304,
            body=None,
            content_type=None,
            etag='"v1"',
            final_url="https://docs.example.com/billing",
        )
        refreshed = refresh_source(source_id=source.id, team_id=self.team.id)
        assert refreshed is not None
        assert refreshed.last_refresh_status == RefreshStatus.NOT_MODIFIED
        # Chunks preserved identity — agents with cached chunk ids are still valid.
        new_chunks = list(
            KnowledgeChunk.objects.unscoped().filter(source=source).order_by("ordinal").values_list("id", flat=True)
        )
        assert new_chunks == original_chunks

    @patch("products.business_knowledge.backend.logic.url_fetch.fetch_url")
    @patch("products.business_knowledge.backend.logic.is_url_allowed", return_value=(True, None))
    def test_200_with_changed_content_rebuilds_chunks(self, _ssrf: MagicMock, mock_fetch: MagicMock) -> None:
        source = self._seed(etag='"v1"')
        old_contents = set(KnowledgeChunk.objects.unscoped().filter(source=source).values_list("content", flat=True))
        new_html = b"""<!doctype html><html><body><article>
<h1>Refund policy</h1>
<p>BRAND NEW: 60-day refunds are now available.</p>
</article></body></html>"""
        mock_fetch.return_value = url_fetch.FetchResult(
            status=200,
            body=new_html,
            content_type="text/html",
            etag='"v2"',
            final_url="https://docs.example.com/billing",
        )
        refreshed = refresh_source(source_id=source.id, team_id=self.team.id)
        assert refreshed is not None
        assert refreshed.last_refresh_status == RefreshStatus.SUCCESS
        assert refreshed.last_etag == '"v2"'
        new_contents = set(KnowledgeChunk.objects.unscoped().filter(source=source).values_list("content", flat=True))
        # Chunk *content* must change. Chunk ids are deterministic in the url +
        # ordinal space, so they stay stable across refreshes — that's by design
        # so agents' cached citations keep resolving.
        assert new_contents != old_contents
        assert any("60-day" in c for c in new_contents)

    @patch("products.business_knowledge.backend.logic.url_fetch.fetch_url")
    @patch("products.business_knowledge.backend.logic.is_url_allowed", return_value=(True, None))
    def test_busy_source_rejects(self, _ssrf: MagicMock, _fetch: MagicMock) -> None:
        source = self._seed()
        KnowledgeSource.objects.unscoped().filter(id=source.id).update(status=SourceStatus.PROCESSING)
        with self.assertRaises(SourceBusyError):
            refresh_source(source_id=source.id, team_id=self.team.id)

    @patch("products.business_knowledge.backend.logic.url_fetch.fetch_url")
    @patch("products.business_knowledge.backend.logic.is_url_allowed", return_value=(True, None))
    def test_refresh_blocked_when_another_source_processing(self, _ssrf: MagicMock, _fetch: MagicMock) -> None:
        source_a = self._seed()
        source_b = self._seed()
        KnowledgeSource.objects.unscoped().filter(id=source_a.id).update(status=SourceStatus.PROCESSING)
        with self.assertRaises(SourceBusyError):
            refresh_source(source_id=source_b.id, team_id=self.team.id)

    def test_cross_team_refresh_returns_none(self) -> None:
        from posthog.models.team import Team

        source = self._seed()
        other_team = Team.objects.create_with_data(
            organization=self.organization, initiating_user=self.user, name="Other"
        )
        assert refresh_source(source_id=source.id, team_id=other_team.id) is None


@patch("posthoganalytics.feature_enabled", return_value=True)
class TestUrlApi(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/business_knowledge/sources/"

    @patch("products.business_knowledge.backend.api.views.KnowledgeSourceViewSet._start_background_ingest")
    @patch("products.business_knowledge.backend.logic.is_url_allowed", return_value=(True, None))
    @patch(
        "products.business_knowledge.backend.api.serializers.is_url_allowed",
        return_value=(True, None),
    )
    def test_create_url_source_api_claims_and_backgrounds(
        self, _serializer_ssrf: MagicMock, _logic_ssrf: MagicMock, mock_ingest: MagicMock, _ff: MagicMock
    ) -> None:
        # Creation must return immediately in PROCESSING and hand ingestion off
        # to the background — the request never blocks on the fetch.
        response = self.client.post(
            self.url,
            {"name": "Docs", "url": "https://docs.example.com/billing", "source_type": "url"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.content
        body = response.json()
        assert body["source_type"] == "url"
        assert body["status"] == "processing"
        assert body["source_url"] == "https://docs.example.com/billing"
        assert body["chunk_count"] == 0
        mock_ingest.assert_called_once()

    @patch("products.business_knowledge.backend.logic.ingest_source")
    @patch("products.business_knowledge.backend.api.views.sync_connect", side_effect=Exception("temporal unavailable"))
    @patch("products.business_knowledge.backend.logic.is_url_allowed", return_value=(True, None))
    @patch(
        "products.business_knowledge.backend.api.serializers.is_url_allowed",
        return_value=(True, None),
    )
    def test_create_url_source_api_falls_back_to_inline_ingest(
        self,
        _serializer_ssrf: MagicMock,
        _logic_ssrf: MagicMock,
        _sync_connect: MagicMock,
        mock_ingest: MagicMock,
        _ff: MagicMock,
    ) -> None:
        # If the background workflow can't start, ingestion must still run inline
        # so the source doesn't hang in PROCESSING.
        response = self.client.post(
            self.url,
            {"name": "Docs", "url": "https://docs.example.com/billing", "source_type": "url"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.content
        mock_ingest.assert_called_once()
        assert mock_ingest.call_args.kwargs["team_id"] == self.team.id

    @patch(
        "products.business_knowledge.backend.api.serializers.is_url_allowed",
        return_value=(False, "Loopback"),
    )
    def test_create_url_source_rejects_internal(self, _ssrf: MagicMock, _ff: MagicMock) -> None:
        response = self.client.post(
            self.url,
            {"name": "Bad", "url": "http://127.0.0.1/admin", "source_type": "url"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content

    def test_cross_team_refresh_returns_404(self, _ff: MagicMock) -> None:
        from posthog.models.team import Team

        other_team = Team.objects.create_with_data(
            organization=self.organization, initiating_user=self.user, name="Other"
        )
        theirs = KnowledgeSource.objects.unscoped().create(
            team=other_team,
            name="Theirs",
            source_type=SourceType.URL,
            status=SourceStatus.READY,
            source_url="https://docs.example.com/",
        )
        response = self.client.post(f"{self.url}{theirs.id}/refresh/")
        assert response.status_code == status.HTTP_404_NOT_FOUND
