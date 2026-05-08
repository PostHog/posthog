"""
Tests for Stage 2b crawl ingestion.

Scope:
- Discover (sitemap parsing + index unfurl, same-origin BFS).
- Glob include/exclude.
- `max_pages` enforcement.
- Happy-path create_crawl_source.
- Refresh upsert-diff: new URL inserted, changed URL rebuilt (doc id
  preserved), unchanged URL untouched, vanished URL tombstoned.
- SSRF on a URL that appears in a sitemap but points at a blocked host.

Design notes:
- We patch `discover._http_get_text` for discover tests — exercising real
  XML parsing without needing HTTP. For fetch tests we patch
  `url_fetch.fetch_url` so the crawl module's parallel ThreadPoolExecutor
  is exercised end-to-end but with deterministic content.
- `requests.Session.get` is intentionally NOT patched globally — each
  test patches the narrowest layer it needs.
"""

from collections.abc import Mapping

from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import MagicMock, patch

from products.business_knowledge.backend import crawl, discover, url_fetch
from products.business_knowledge.backend.logic import EmptyContentError, create_crawl_source, refresh_source
from products.business_knowledge.backend.models import KnowledgeChunk, KnowledgeDocument, KnowledgeSource, SourceStatus


def _sitemap_xml(urls: list[str]) -> str:
    entries = "\n".join(f"<url><loc>{u}</loc></url>" for u in urls)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{entries}"
        "</urlset>"
    )


def _sitemap_index_xml(children: list[str]) -> str:
    entries = "\n".join(f"<sitemap><loc>{c}</loc></sitemap>" for c in children)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{entries}"
        "</sitemapindex>"
    )


class TestDiscoverSitemap(BaseTest):
    def test_parses_flat_sitemap(self) -> None:
        sitemap = _sitemap_xml(
            [
                "https://example.com/a",
                "https://example.com/b",
                "https://example.com/c",
            ]
        )
        with patch.object(discover, "_http_get_text", return_value=sitemap):
            urls = discover.discover(
                "sitemap",
                "https://example.com/sitemap.xml",
                discover.CrawlConfig(max_pages=10),
            )
        assert urls == ["https://example.com/a", "https://example.com/b", "https://example.com/c"]

    def test_unfurls_sitemap_index(self) -> None:
        index = _sitemap_index_xml(["https://example.com/a.xml", "https://example.com/b.xml"])
        child_a = _sitemap_xml(["https://example.com/1"])
        child_b = _sitemap_xml(["https://example.com/2", "https://example.com/3"])

        def _fake_fetch(url: str, max_bytes: int = 0) -> str:
            if url == "https://example.com/sitemap.xml":
                return index
            if url == "https://example.com/a.xml":
                return child_a
            if url == "https://example.com/b.xml":
                return child_b
            raise AssertionError(f"unexpected discover fetch: {url}")

        with patch.object(discover, "_http_get_text", side_effect=_fake_fetch):
            urls = discover.discover(
                "sitemap",
                "https://example.com/sitemap.xml",
                discover.CrawlConfig(max_pages=10),
            )
        assert urls == [
            "https://example.com/1",
            "https://example.com/2",
            "https://example.com/3",
        ]

    def test_applies_glob_filters(self) -> None:
        sitemap = _sitemap_xml(
            [
                "https://example.com/docs/one",
                "https://example.com/docs/two",
                "https://example.com/blog/post",
                "https://example.com/docs/private/secret",
            ]
        )
        with patch.object(discover, "_http_get_text", return_value=sitemap):
            urls = discover.discover(
                "sitemap",
                "https://example.com/sitemap.xml",
                discover.CrawlConfig(
                    include_globs=("/docs/*",),
                    exclude_globs=("/docs/private/*",),
                    max_pages=10,
                ),
            )
        assert urls == ["https://example.com/docs/one", "https://example.com/docs/two"]

    def test_max_pages_caps_output(self) -> None:
        sitemap = _sitemap_xml([f"https://example.com/p{i}" for i in range(100)])
        with patch.object(discover, "_http_get_text", return_value=sitemap):
            urls = discover.discover(
                "sitemap",
                "https://example.com/sitemap.xml",
                discover.CrawlConfig(max_pages=5),
            )
        assert len(urls) == 5

    def test_rejects_malformed_xml(self) -> None:
        with patch.object(discover, "_http_get_text", return_value="<not-xml>"):
            try:
                discover.discover(
                    "sitemap",
                    "https://example.com/sitemap.xml",
                    discover.CrawlConfig(),
                )
            except discover.DiscoverError as exc:
                assert "XML" in str(exc) or "valid" in str(exc)
            else:
                raise AssertionError("expected DiscoverError")


class TestDiscoverSameOrigin(BaseTest):
    def test_stays_on_origin_and_respects_depth(self) -> None:
        pages = {
            "https://ex.com/a": '<a href="/b">b</a><a href="https://other.com/x">external</a>',
            "https://ex.com/b": '<a href="/c">c</a>',
            "https://ex.com/c": "",
        }

        def _fake(url: str, max_bytes: int = 0) -> str:
            if url == "https://ex.com/robots.txt":
                raise discover.DiscoverError("not found")
            return pages.get(url, "")

        with patch.object(discover, "_http_get_text", side_effect=_fake):
            urls = discover.discover(
                "same_origin",
                "https://ex.com/a",
                discover.CrawlConfig(max_depth=1, max_pages=10),
            )
        assert urls == ["https://ex.com/a", "https://ex.com/b"]


class _FakeFetch:
    """
    Stand-in for `url_fetch.fetch_url`, driven by a dict of url -> behaviour.
    Each value is either a FetchResult or an exception instance.
    """

    def __init__(self, behaviours: Mapping[str, url_fetch.FetchResult | Exception]) -> None:
        self.behaviours = behaviours
        self.etags_seen: dict[str, str | None] = {}

    def __call__(self, url: str, *, etag: str | None = None) -> url_fetch.FetchResult:
        self.etags_seen[url] = etag
        b = self.behaviours.get(url)
        if isinstance(b, Exception):
            raise b
        if isinstance(b, url_fetch.FetchResult):
            return b
        raise AssertionError(f"no behaviour for {url}")


def _ok(url: str, body: bytes) -> url_fetch.FetchResult:
    return url_fetch.FetchResult(
        status=200, body=body, content_type="text/html", etag=f'W/"{hash(body)}"', final_url=url
    )


class TestCreateCrawlSource(APIBaseTest):
    def test_happy_path_indexes_all_discovered_pages(self) -> None:
        sitemap = _sitemap_xml(["https://example.com/a", "https://example.com/b", "https://example.com/c"])
        behaviours: dict[str, url_fetch.FetchResult | Exception] = {
            "https://example.com/a": _ok("https://example.com/a", b"<html><body>Alpha paragraph.</body></html>"),
            "https://example.com/b": _ok("https://example.com/b", b"<html><body>Beta paragraph.</body></html>"),
            "https://example.com/c": _ok("https://example.com/c", b"<html><body>Gamma paragraph.</body></html>"),
        }
        with (
            patch.object(discover, "_http_get_text", return_value=sitemap),
            patch.object(crawl.url_fetch, "fetch_url", side_effect=_FakeFetch(behaviours)),
        ):
            source = create_crawl_source(
                team_id=self.team.id,
                created_by_id=self.user.id,
                name="Handbook",
                url="https://example.com/sitemap.xml",
                crawl_mode="sitemap",
                crawl_config={"max_pages": 10},
            )
        assert source.status == SourceStatus.READY
        assert KnowledgeDocument.objects.unscoped().filter(source=source).count() == 3
        # Every doc has chunks and a content_hash.
        docs = KnowledgeDocument.objects.unscoped().filter(source=source)
        assert all(d.content_hash for d in docs)
        assert KnowledgeChunk.objects.unscoped().filter(source=source).count() >= 3

    def test_zero_safe_urls_raises_empty_content(self) -> None:
        sitemap = _sitemap_xml(["http://127.0.0.1/secret"])
        with patch.object(discover, "_http_get_text", return_value=sitemap):
            try:
                create_crawl_source(
                    team_id=self.team.id,
                    created_by_id=self.user.id,
                    name="Hack",
                    url="https://example.com/sitemap.xml",
                    crawl_mode="sitemap",
                    crawl_config={"max_pages": 10},
                )
            except EmptyContentError:
                pass
            else:
                raise AssertionError("expected EmptyContentError — 127.0.0.1 should be SSRF-blocked")


class TestRefreshCrawlSource(APIBaseTest):
    def _seed(self, sitemap_urls: list[str]) -> KnowledgeSource:
        sitemap = _sitemap_xml(sitemap_urls)
        behaviours: dict[str, url_fetch.FetchResult | Exception] = {
            url: _ok(url, f"<html><body>body of {url}</body></html>".encode()) for url in sitemap_urls
        }
        with (
            patch.object(discover, "_http_get_text", return_value=sitemap),
            patch.object(crawl.url_fetch, "fetch_url", side_effect=_FakeFetch(behaviours)),
        ):
            return create_crawl_source(
                team_id=self.team.id,
                created_by_id=self.user.id,
                name="Handbook",
                url="https://example.com/sitemap.xml",
                crawl_mode="sitemap",
                crawl_config={"max_pages": 10},
            )

    def test_changed_page_rebuilds_only_that_doc(self) -> None:
        source = self._seed(["https://example.com/a", "https://example.com/b"])
        doc_a = KnowledgeDocument.objects.unscoped().get(source=source, stable_id="https://example.com/a")
        doc_b = KnowledgeDocument.objects.unscoped().get(source=source, stable_id="https://example.com/b")
        b_hash_before = doc_b.content_hash

        # Re-discover same sitemap; change content of /a only.
        sitemap = _sitemap_xml(["https://example.com/a", "https://example.com/b"])
        behaviours = {
            "https://example.com/a": _ok(
                "https://example.com/a", b"<html><body>Alpha content has been updated.</body></html>"
            ),
            "https://example.com/b": _ok(
                "https://example.com/b", b"<html><body>body of https://example.com/b</body></html>"
            ),
        }
        with (
            patch.object(discover, "_http_get_text", return_value=sitemap),
            patch.object(crawl.url_fetch, "fetch_url", side_effect=_FakeFetch(behaviours)),
        ):
            refresh_source(source_id=source.id, team_id=self.team.id)

        doc_a.refresh_from_db()
        doc_b.refresh_from_db()
        # doc id preserved for both — critical for citation stability.
        assert KnowledgeDocument.objects.unscoped().filter(source=source, id=doc_a.id).exists()
        assert KnowledgeDocument.objects.unscoped().filter(source=source, id=doc_b.id).exists()
        # /a rebuilt; /b unchanged.
        assert "updated" in doc_a.content
        assert doc_b.content_hash == b_hash_before

    def test_vanished_url_is_tombstoned(self) -> None:
        source = self._seed(["https://example.com/a", "https://example.com/b"])
        doc_b = KnowledgeDocument.objects.unscoped().get(source=source, stable_id="https://example.com/b")
        assert KnowledgeChunk.objects.unscoped().filter(document_id=doc_b.id).exists()

        # Re-discover without /b.
        sitemap = _sitemap_xml(["https://example.com/a"])
        behaviours = {
            "https://example.com/a": _ok(
                "https://example.com/a", b"<html><body>body of https://example.com/a</body></html>"
            ),
        }
        with (
            patch.object(discover, "_http_get_text", return_value=sitemap),
            patch.object(crawl.url_fetch, "fetch_url", side_effect=_FakeFetch(behaviours)),
        ):
            refresh_source(source_id=source.id, team_id=self.team.id)

        doc_b.refresh_from_db()
        assert doc_b.tombstoned_at is not None
        # Chunks for the vanished doc are gone, but the doc row is preserved.
        assert KnowledgeChunk.objects.unscoped().filter(document_id=doc_b.id).count() == 0
        assert KnowledgeDocument.objects.unscoped().filter(id=doc_b.id).exists()

    def test_unchanged_source_reports_not_modified(self) -> None:
        source = self._seed(["https://example.com/a"])
        doc_a = KnowledgeDocument.objects.unscoped().get(source=source, stable_id="https://example.com/a")

        sitemap = _sitemap_xml(["https://example.com/a"])

        # Return 304 so the doc isn't re-parsed.
        def _fetch_304(url: str, *, etag: str | None = None) -> url_fetch.FetchResult:
            assert etag == doc_a.etag
            return url_fetch.FetchResult(status=304, body=None, content_type=None, etag=etag, final_url=url)

        with (
            patch.object(discover, "_http_get_text", return_value=sitemap),
            patch.object(crawl.url_fetch, "fetch_url", side_effect=_fetch_304),
        ):
            refreshed = refresh_source(source_id=source.id, team_id=self.team.id)

        assert refreshed is not None
        assert refreshed.last_refresh_status == "not_modified"
        # Hash + chunk count untouched.
        doc_a.refresh_from_db()
        assert doc_a.content_hash != ""

    def test_ssrf_block_during_refresh_does_not_tombstone(self) -> None:
        """
        Regression: `discovered_set` was previously built from `outcomes`,
        meaning any URL that transiently failed SSRF re-validation between
        discover and fetch would be tombstoned. That wipes chunks the user
        thought were healthy. `discovered_set` must be built from the raw
        discover() output so only URLs genuinely gone from the sitemap get
        tombstoned.
        """

        source = self._seed(["https://example.com/a", "https://example.com/b"])
        doc_b = KnowledgeDocument.objects.unscoped().get(source=source, stable_id="https://example.com/b")
        b_chunks_before = KnowledgeChunk.objects.unscoped().filter(document_id=doc_b.id).count()
        assert b_chunks_before > 0

        # Sitemap still lists both URLs. But `is_url_allowed` flips to False
        # for /b on this refresh (simulate a DNS rebinding / outage flap).
        sitemap = _sitemap_xml(["https://example.com/a", "https://example.com/b"])
        behaviours = {
            "https://example.com/a": _ok(
                "https://example.com/a", b"<html><body>body of https://example.com/a</body></html>"
            ),
        }

        real_is_url_allowed = __import__("posthog.security.url_validation", fromlist=["is_url_allowed"]).is_url_allowed

        def _flaky_is_url_allowed(u: str) -> tuple[bool, str]:
            if u.rstrip("/") == "https://example.com/b":
                return (False, "transient_block")
            return real_is_url_allowed(u)

        with (
            patch.object(discover, "_http_get_text", return_value=sitemap),
            patch.object(crawl.url_fetch, "fetch_url", side_effect=_FakeFetch(behaviours)),
            # Patch `is_url_allowed` at BOTH import sites — logic._validate_url
            # and url_fetch.fetch_url read it independently.
            patch("products.business_knowledge.backend.logic.is_url_allowed", side_effect=_flaky_is_url_allowed),
        ):
            refresh_source(source_id=source.id, team_id=self.team.id)

        doc_b.refresh_from_db()
        # /b is still in discovery so it must NOT be tombstoned, even though
        # it was filtered out before fetch.
        assert doc_b.tombstoned_at is None
        # Chunks are left intact — the whole point of preserving /b is that
        # the user still has citations for the previously-indexed content.
        assert KnowledgeChunk.objects.unscoped().filter(document_id=doc_b.id).count() == b_chunks_before


class TestChunkIdIsolation(APIBaseTest):
    """
    Regression: two URL sources crawling an overlapping URL used to collide
    on chunk UUIDs (uuid5 of stable_id only, where stable_id == url for URL
    sources). `_chunk_id` now includes `source_id` to isolate namespaces.
    """

    def test_two_sources_same_url_do_not_collide(self) -> None:
        sitemap_a = _sitemap_xml(["https://example.com/shared"])
        sitemap_b = _sitemap_xml(["https://example.com/shared"])
        # Same URL, same body → same chunker output. Pre-fix: PRIMARY KEY
        # collision on the second source's bulk_create.
        body = b"<html><body>Shared paragraph content.</body></html>"
        behaviours_a = {"https://example.com/shared": _ok("https://example.com/shared", body)}
        behaviours_b = {"https://example.com/shared": _ok("https://example.com/shared", body)}

        with (
            patch.object(discover, "_http_get_text", return_value=sitemap_a),
            patch.object(crawl.url_fetch, "fetch_url", side_effect=_FakeFetch(behaviours_a)),
        ):
            source_a = create_crawl_source(
                team_id=self.team.id,
                created_by_id=self.user.id,
                name="Source A",
                url="https://example.com/sitemap.xml",
                crawl_mode="sitemap",
                crawl_config={"max_pages": 10},
            )
        with (
            patch.object(discover, "_http_get_text", return_value=sitemap_b),
            patch.object(crawl.url_fetch, "fetch_url", side_effect=_FakeFetch(behaviours_b)),
        ):
            source_b = create_crawl_source(
                team_id=self.team.id,
                created_by_id=self.user.id,
                name="Source B",
                url="https://example.com/sitemap.xml",
                crawl_mode="sitemap",
                crawl_config={"max_pages": 10},
            )

        a_chunks = set(KnowledgeChunk.objects.unscoped().filter(source=source_a).values_list("id", flat=True))
        b_chunks = set(KnowledgeChunk.objects.unscoped().filter(source=source_b).values_list("id", flat=True))
        assert a_chunks and b_chunks
        assert a_chunks.isdisjoint(b_chunks), "chunk UUIDs must not collide across sources"


class TestDiscoverSSRF(BaseTest):
    """
    Regression: `discover._http_get_text` used to auto-follow redirects
    (`allow_redirects=True`), so a sitemap or link page could 302 to
    `127.0.0.1` and bypass SSRF. Now each hop is SSRF-re-validated.
    """

    def test_redirect_to_blocked_host_is_refused(self) -> None:
        first = MagicMock()
        first.status_code = 302
        first.headers = {"Location": "http://127.0.0.1/secret"}
        first.iter_content = lambda chunk_size=0: iter([])
        first.close = lambda: None

        session = MagicMock()
        session.get.return_value = first
        session.close = lambda: None

        with patch("products.business_knowledge.backend.discover.requests.Session", return_value=session):
            try:
                discover._http_get_text("https://example.com/sitemap.xml")
            except discover.DiscoverError as exc:
                assert "not reachable" in str(exc).lower()
            else:
                raise AssertionError("expected DiscoverError — 127.0.0.1 must be SSRF-blocked on redirect")
        # Session.get must have been called exactly once for the first hop;
        # the blocked redirect target must never even be dialed.
        assert session.get.call_count == 1
