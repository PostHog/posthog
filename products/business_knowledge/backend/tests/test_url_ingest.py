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
from products.business_knowledge.backend.logic import (
    InvalidUrlError,
    SourceBusyError,
    UrlFetchFailedError,
    create_url_source,
    refresh_source,
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
    @patch("products.business_knowledge.backend.url_fetch.is_url_allowed", return_value=(True, None))
    @patch("products.business_knowledge.backend.url_fetch.requests.Session")
    def test_happy_path_returns_body(self, mock_session_cls: MagicMock, _ssrf: MagicMock) -> None:
        session = mock_session_cls.return_value
        session.get.return_value = _mock_response(body=b"<html>hi</html>", etag='"abc"')
        result = url_fetch.fetch_url("https://example.com/x")
        assert result.status == 200
        assert result.body == b"<html>hi</html>"
        assert result.etag == '"abc"'

    @patch("products.business_knowledge.backend.url_fetch.is_url_allowed", return_value=(True, None))
    @patch("products.business_knowledge.backend.url_fetch.requests.Session")
    def test_conditional_get_returns_304(self, mock_session_cls: MagicMock, _ssrf: MagicMock) -> None:
        session = mock_session_cls.return_value
        session.get.return_value = _mock_response(status_code=304, body=b"")
        result = url_fetch.fetch_url("https://example.com/x", etag='"abc"')
        assert result.status == 304
        assert result.body is None

    @patch("products.business_knowledge.backend.url_fetch.is_url_allowed", return_value=(True, None))
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

    @patch("products.business_knowledge.backend.url_fetch.is_url_allowed")
    @patch("products.business_knowledge.backend.url_fetch.requests.Session")
    def test_redirect_revalidates_ssrf(self, mock_session_cls: MagicMock, mock_ssrf: MagicMock) -> None:
        # First hop allowed (public), second hop blocked (internal). If the
        # client blindly followed, the second Location would be fetched.
        mock_ssrf.side_effect = [(True, None), (False, "Loopback")]
        session = mock_session_cls.return_value
        session.get.return_value = _mock_response(status_code=302, body=b"", location="http://127.0.0.1/admin")
        with self.assertRaises(url_fetch.UrlFetchError):
            url_fetch.fetch_url("https://example.com/x")
        # SSRF check was re-run on the redirect target.
        assert mock_ssrf.call_count == 2

    @patch("products.business_knowledge.backend.url_fetch.is_url_allowed", return_value=(False, "Loopback"))
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
        assert KnowledgeDocument.objects.filter(source=source).count() == 1
        assert KnowledgeChunk.objects.filter(source=source, team=self.team).count() >= 1

    @patch("products.business_knowledge.backend.logic.is_url_allowed", return_value=(False, "Loopback"))
    def test_ssrf_rejection_does_not_create_source(self, _ssrf: MagicMock) -> None:
        with self.assertRaises(InvalidUrlError):
            create_url_source(
                team_id=self.team.id,
                created_by_id=self.user.id,
                name="Bad",
                url="http://127.0.0.1/admin",
            )
        assert KnowledgeSource.objects.filter(team=self.team).count() == 0

    @patch("products.business_knowledge.backend.logic.url_fetch.fetch_url")
    @patch("products.business_knowledge.backend.logic.is_url_allowed", return_value=(True, None))
    def test_fetch_failure_persists_error_source(self, _ssrf: MagicMock, mock_fetch: MagicMock) -> None:
        mock_fetch.side_effect = url_fetch.UrlFetchError("Remote responded with status 503.")
        with self.assertRaises(UrlFetchFailedError):
            create_url_source(
                team_id=self.team.id,
                created_by_id=self.user.id,
                name="Flaky",
                url="https://flaky.example.com/",
            )
        # We want users to see the failed source in the UI, not have it
        # silently vanish.
        errored = KnowledgeSource.objects.get(team=self.team, name="Flaky")
        assert errored.status == SourceStatus.ERROR
        assert errored.last_refresh_status == RefreshStatus.ERROR


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
            KnowledgeChunk.objects.filter(source=source).order_by("ordinal").values_list("id", flat=True)
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
        new_chunks = list(KnowledgeChunk.objects.filter(source=source).order_by("ordinal").values_list("id", flat=True))
        assert new_chunks == original_chunks

    @patch("products.business_knowledge.backend.logic.url_fetch.fetch_url")
    @patch("products.business_knowledge.backend.logic.is_url_allowed", return_value=(True, None))
    def test_200_with_changed_content_rebuilds_chunks(self, _ssrf: MagicMock, mock_fetch: MagicMock) -> None:
        source = self._seed(etag='"v1"')
        old_contents = set(KnowledgeChunk.objects.filter(source=source).values_list("content", flat=True))
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
        new_contents = set(KnowledgeChunk.objects.filter(source=source).values_list("content", flat=True))
        # Chunk *content* must change. Chunk ids are deterministic in the url +
        # ordinal space, so they stay stable across refreshes — that's by design
        # so agents' cached citations keep resolving.
        assert new_contents != old_contents
        assert any("60-day" in c for c in new_contents)

    @patch("products.business_knowledge.backend.logic.url_fetch.fetch_url")
    @patch("products.business_knowledge.backend.logic.is_url_allowed", return_value=(True, None))
    def test_busy_source_rejects(self, _ssrf: MagicMock, _fetch: MagicMock) -> None:
        source = self._seed()
        KnowledgeSource.objects.filter(id=source.id).update(status=SourceStatus.PROCESSING)
        with self.assertRaises(SourceBusyError):
            refresh_source(source_id=source.id, team_id=self.team.id)

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
        self.url = f"/api/environments/{self.team.id}/business_knowledge/sources/"

    @patch("products.business_knowledge.backend.logic.url_fetch.fetch_url")
    @patch("products.business_knowledge.backend.logic.is_url_allowed", return_value=(True, None))
    @patch(
        "products.business_knowledge.backend.presentation.serializers.is_url_allowed",
        return_value=(True, None),
    )
    def test_create_url_source_api(
        self, _serializer_ssrf: MagicMock, _logic_ssrf: MagicMock, mock_fetch: MagicMock, _ff: MagicMock
    ) -> None:
        mock_fetch.return_value = url_fetch.FetchResult(
            status=200,
            body=_BASIC_HTML,
            content_type="text/html",
            etag='"v1"',
            final_url="https://docs.example.com/billing",
        )
        response = self.client.post(
            self.url,
            {"name": "Docs", "url": "https://docs.example.com/billing", "source_type": "url"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.content
        body = response.json()
        assert body["source_type"] == "url"
        assert body["status"] == "ready"
        assert body["source_url"] == "https://docs.example.com/billing"

    @patch(
        "products.business_knowledge.backend.presentation.serializers.is_url_allowed",
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
        theirs = KnowledgeSource.objects.create(
            team=other_team,
            name="Theirs",
            source_type=SourceType.URL,
            status=SourceStatus.READY,
            source_url="https://docs.example.com/",
        )
        response = self.client.post(f"{self.url}{theirs.id}/refresh/")
        assert response.status_code == status.HTTP_404_NOT_FOUND
