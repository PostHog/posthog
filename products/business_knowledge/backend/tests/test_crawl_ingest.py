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
- We patch `discover._http_get_text` for sitemap/robots fetches and
  `discover.fetch_url` for BFS page fetches — exercising real XML/link
  parsing without needing HTTP. For fetch tests we patch
  `url_fetch.fetch_url` so the crawl module's parallel ThreadPoolExecutor
  is exercised end-to-end but with deterministic content.
- `requests.Session.get` is intentionally NOT patched globally — each
  test patches the narrowest layer it needs.
"""

from collections.abc import Mapping

from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.business_knowledge.backend import crawl, discover, logic, url_fetch
from products.business_knowledge.backend.logic import create_crawl_source, ingest_source, refresh_source
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
            ).urls
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
            ).urls
        assert urls == [
            "https://example.com/1",
            "https://example.com/2",
            "https://example.com/3",
        ]

    def test_unfurls_nested_sitemap_indexes(self) -> None:
        # Three index levels yield the page. The sitemap past that is not fetched.
        root = _sitemap_index_xml(["https://example.com/section.xml"])
        section = _sitemap_index_xml(["https://example.com/pages.xml"])
        pages = _sitemap_index_xml(["https://example.com/leaf.xml", "https://example.com/more-index.xml"])
        leaf = _sitemap_xml(["https://example.com/docs/start"])
        more_index = _sitemap_index_xml(["https://example.com/too-deep.xml"])
        documents = {
            "https://example.com/sitemap.xml": root,
            "https://example.com/section.xml": section,
            "https://example.com/pages.xml": pages,
            "https://example.com/leaf.xml": leaf,
            "https://example.com/more-index.xml": more_index,
        }
        fetched: list[str] = []

        def _fake_fetch(url: str, max_bytes: int = 0) -> str:
            fetched.append(url)
            try:
                return documents[url]
            except KeyError as exc:
                raise AssertionError(f"unexpected discover fetch: {url}") from exc

        with patch.object(discover, "_http_get_text", side_effect=_fake_fetch):
            urls = discover.discover(
                "sitemap",
                "https://example.com/sitemap.xml",
                discover.CrawlConfig(max_pages=10),
            ).urls
        assert urls == ["https://example.com/docs/start"]
        assert "https://example.com/more-index.xml" in fetched
        assert "https://example.com/too-deep.xml" not in fetched

    def test_stops_at_the_discover_cap(self) -> None:
        sitemap = _sitemap_xml([f"https://example.com/{i}" for i in range(10)])
        with (
            patch.object(discover, "_http_get_text", return_value=sitemap),
            patch.object(discover, "HARD_DISCOVER_CAP", 3),
        ):
            urls = discover.discover(
                "sitemap",
                "https://example.com/sitemap.xml",
                discover.CrawlConfig(max_pages=10),
            ).urls
        assert urls == ["https://example.com/0", "https://example.com/1", "https://example.com/2"]

    def test_sitemap_index_fetches_stop_at_the_fetch_cap(self) -> None:
        children = [f"https://example.com/{i}.xml" for i in range(5)]
        index = _sitemap_index_xml(children)
        page = _sitemap_xml(["https://example.com/docs"])

        def _fake_fetch(url: str, max_bytes: int = 0) -> str:
            if url == "https://example.com/sitemap.xml":
                return index
            return page

        with (
            patch.object(discover, "_http_get_text", side_effect=_fake_fetch) as fetch,
            patch.object(discover, "MAX_SITEMAP_FETCHES", 3),
        ):
            discover.discover(
                "sitemap",
                "https://example.com/sitemap.xml",
                discover.CrawlConfig(max_pages=1),
            )
        assert fetch.call_count == 3

    def test_nested_index_pages_are_found_before_broad_siblings_use_the_fetch_cap(self) -> None:
        root = _sitemap_index_xml(
            ["https://example.com/section.xml"] + [f"https://example.com/{i}.xml" for i in range(5)]
        )
        section = _sitemap_index_xml(["https://example.com/leaf.xml"])
        leaf = _sitemap_xml(["https://example.com/docs/start"])
        documents = {
            "https://example.com/sitemap.xml": root,
            "https://example.com/section.xml": section,
            "https://example.com/leaf.xml": leaf,
        }

        with (
            patch.object(
                discover, "_http_get_text", side_effect=lambda url, max_bytes=0: documents.get(url, _sitemap_xml([]))
            ),
            patch.object(discover, "MAX_SITEMAP_FETCHES", 3),
        ):
            urls = discover.discover(
                "sitemap",
                "https://example.com/sitemap.xml",
                discover.CrawlConfig(max_pages=10),
            ).urls
        assert urls == ["https://example.com/docs/start"]

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
            ).urls
        assert urls == ["https://example.com/docs/one", "https://example.com/docs/two"]

    def test_max_pages_caps_output(self) -> None:
        sitemap = _sitemap_xml([f"https://example.com/p{i}" for i in range(100)])
        with patch.object(discover, "_http_get_text", return_value=sitemap):
            urls = discover.discover(
                "sitemap",
                "https://example.com/sitemap.xml",
                discover.CrawlConfig(max_pages=5),
            ).urls
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


def _page_fetcher(pages: Mapping[str, str]):
    """Stand-in for `discover.fetch_url` (BFS page fetches), driven by url -> html."""

    def _fake(url: str, *, etag: str | None = None) -> url_fetch.FetchResult:
        return url_fetch.FetchResult(
            status=200,
            body=pages.get(url, "").encode(),
            content_type="text/html",
            etag=None,
            final_url=url,
        )

    return _fake


def _no_robots(url: str, max_bytes: int = 0) -> str:
    if url.endswith("/robots.txt"):
        raise discover.DiscoverError("not found")
    raise AssertionError(f"unexpected metadata fetch: {url}")


class TestDiscoverSameOrigin(BaseTest):
    def test_stays_on_origin_and_respects_depth(self) -> None:
        pages = {
            "https://ex.com/a": '<a href="/b">b</a><a href="https://other.com/x">external</a>',
            "https://ex.com/b": '<a href="/c">c</a>',
            "https://ex.com/c": "",
        }

        with (
            patch.object(discover, "_http_get_text", side_effect=_no_robots),
            patch.object(discover, "fetch_url", side_effect=_page_fetcher(pages)),
        ):
            result = discover.discover(
                "same_origin",
                "https://ex.com/a",
                discover.CrawlConfig(max_depth=1, max_pages=10),
            )
        assert result.urls == ["https://ex.com/a", "https://ex.com/b"]
        # Traversed pages (those we fetched for links) are carried over for reuse.
        assert "https://ex.com/a" in result.prefetched

    def test_include_glob_collects_matching_pages_not_just_entry_links(self) -> None:
        # Mirrors the reported bug: crawl `/` for `/handbook/*`. The cap must
        # count handbook pages (reached at depth 2), not be spent on the
        # homepage's many non-handbook links.
        pages = {
            "https://ex.com/": '<a href="/handbook">hb</a><a href="/pricing">p</a><a href="/docs">d</a>',
            "https://ex.com/handbook": (
                '<a href="/handbook/a">a</a><a href="/handbook/b">b</a><a href="/handbook/c">c</a>'
            ),
            "https://ex.com/handbook/a": "",
            "https://ex.com/handbook/b": "",
            "https://ex.com/handbook/c": "",
            "https://ex.com/pricing": '<a href="/pricing/x">x</a>',
            "https://ex.com/docs": '<a href="/docs/y">y</a>',
        }
        fetched: list[str] = []
        page_fetch = _page_fetcher(pages)

        def _fake(url: str, *, etag: str | None = None) -> url_fetch.FetchResult:
            fetched.append(url)
            return page_fetch(url, etag=etag)

        with (
            patch.object(discover, "_http_get_text", side_effect=_no_robots),
            patch.object(discover, "fetch_url", side_effect=_fake),
        ):
            urls = discover.discover(
                "same_origin",
                "https://ex.com/",
                discover.CrawlConfig(include_globs=("/handbook/*",), max_depth=3, max_pages=50),
            ).urls

        assert set(urls) == {
            "https://ex.com/handbook/a",
            "https://ex.com/handbook/b",
            "https://ex.com/handbook/c",
        }
        # Focused traversal: never fetched the unrelated subtrees.
        assert "https://ex.com/pricing" not in fetched
        assert "https://ex.com/docs" not in fetched

    def test_include_glob_caps_on_matching_pages(self) -> None:
        # 5 handbook pages exist but max_pages=3 → exactly 3 matching collected.
        links = "".join(f'<a href="/handbook/{i}">{i}</a>' for i in range(5))
        pages = {
            "https://ex.com/handbook": links,
            **{f"https://ex.com/handbook/{i}": "" for i in range(5)},
        }

        with (
            patch.object(discover, "_http_get_text", side_effect=_no_robots),
            patch.object(discover, "fetch_url", side_effect=_page_fetcher(pages)),
        ):
            urls = discover.discover(
                "same_origin",
                "https://ex.com/handbook",
                discover.CrawlConfig(include_globs=("/handbook/*",), max_depth=2, max_pages=3),
            ).urls
        assert len(urls) == 3
        assert all(u.startswith("https://ex.com/handbook/") for u in urls)


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


class TestIterFetch(SimpleTestCase):
    def test_submits_at_most_max_in_flight_before_the_first_outcome(self) -> None:
        urls = [f"https://example.com/{i}" for i in range(10)]
        fake = _FakeFetch({url: _ok(url, f"<html><body>Page {url}.</body></html>".encode()) for url in urls})
        submitted: list[str] = []

        def _etag_for(url: str) -> None:
            submitted.append(url)
            return None

        with patch.object(crawl.url_fetch, "fetch_url", side_effect=fake):
            outcomes = crawl.iter_fetch(urls, etag_for=_etag_for, max_workers=4, max_in_flight=2)
            first = next(outcomes)
            assert len(submitted) == 2
            rest = list(outcomes)

        assert sorted(o.url for o in [first, *rest]) == sorted(urls)
        assert all(o.status == "ok" for o in [first, *rest])


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

    def test_chunk_cap_hit_in_a_later_batch_leaves_no_documents(self) -> None:
        urls = ["https://example.com/a", "https://example.com/b"]
        behaviours = {url: _ok(url, f"<html><body>Body of {url}.</body></html>".encode()) for url in urls}
        with (
            patch.object(discover, "_http_get_text", return_value=_sitemap_xml(urls)),
            patch.object(crawl.url_fetch, "fetch_url", side_effect=_FakeFetch(behaviours)),
            patch.object(logic, "CRAWL_WRITE_BATCH_SIZE", 1),
            patch.object(logic, "MAX_CHUNKS_PER_TEAM", 1),
        ):
            source = create_crawl_source(
                team_id=self.team.id,
                created_by_id=self.user.id,
                name="Handbook",
                url="https://example.com/sitemap.xml",
                crawl_mode="sitemap",
                crawl_config={"max_pages": 10},
            )
        assert source.status == SourceStatus.ERROR
        assert "would exceed" in source.error_message
        assert not KnowledgeDocument.objects.unscoped().filter(source=source).exists()
        assert not KnowledgeChunk.objects.unscoped().filter(source=source).exists()

    @parameterized.expand(
        [
            ("retry_succeeds", False, SourceStatus.READY, 2),
            ("retry_fails_discovery", True, SourceStatus.ERROR, 0),
        ]
    )
    def test_retried_ingest_replaces_rows_from_the_attempt_before(
        self, _name: str, discovery_fails: bool, expected_status: str, expected_docs: int
    ) -> None:
        urls = ["https://example.com/a", "https://example.com/b"]
        behaviours = {url: _ok(url, f"<html><body>Body of {url}.</body></html>".encode()) for url in urls}
        with (
            patch.object(discover, "_http_get_text", return_value=_sitemap_xml(urls)),
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
        chunks_before = KnowledgeChunk.objects.unscoped().filter(source=source).count()
        KnowledgeSource.objects.unscoped().filter(id=source.id).update(status=SourceStatus.PROCESSING)

        discovery_effect = discover.DiscoverError("Sitemap unreachable.") if discovery_fails else None
        with (
            patch.object(discover, "_http_get_text", return_value=_sitemap_xml(urls), side_effect=discovery_effect),
            patch.object(crawl.url_fetch, "fetch_url", side_effect=_FakeFetch(behaviours)),
        ):
            retried = ingest_source(source_id=source.id, team_id=self.team.id)

        assert retried is not None
        assert retried.status == expected_status
        assert KnowledgeDocument.objects.unscoped().filter(source=source).count() == expected_docs
        assert KnowledgeChunk.objects.unscoped().filter(source=source).count() == (
            chunks_before if expected_docs else 0
        )

    def test_ingest_of_a_finished_source_keeps_its_rows(self) -> None:
        urls = ["https://example.com/a"]
        behaviours = {url: _ok(url, f"<html><body>Body of {url}.</body></html>".encode()) for url in urls}
        with (
            patch.object(discover, "_http_get_text", return_value=_sitemap_xml(urls)),
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
        chunks_before = KnowledgeChunk.objects.unscoped().filter(source=source).count()

        with patch.object(discover, "_http_get_text", side_effect=AssertionError("must not rediscover")):
            again = ingest_source(source_id=source.id, team_id=self.team.id)

        assert again is not None
        assert again.status == SourceStatus.READY
        assert KnowledgeChunk.objects.unscoped().filter(source=source).count() == chunks_before

    def test_zero_safe_urls_returns_error_source(self) -> None:
        sitemap = _sitemap_xml(["http://127.0.0.1/secret"])
        with patch.object(discover, "_http_get_text", return_value=sitemap):
            source = create_crawl_source(
                team_id=self.team.id,
                created_by_id=self.user.id,
                name="Hack",
                url="https://example.com/sitemap.xml",
                crawl_mode="sitemap",
                crawl_config={"max_pages": 10},
            )
        assert source.status == SourceStatus.ERROR
        assert "no safe URLs" in source.error_message

    def test_concurrent_crawl_create_blocked_by_processing_claim(self) -> None:
        from products.business_knowledge.backend.logic import SourceBusyError
        from products.business_knowledge.backend.models import SourceType

        KnowledgeSource.objects.unscoped().create(
            team_id=self.team.id,
            name="In-flight",
            source_type=SourceType.URL,
            status=SourceStatus.PROCESSING,
            source_url="https://other.example.com/",
        )
        with self.assertRaises(SourceBusyError):
            create_crawl_source(
                team_id=self.team.id,
                created_by_id=self.user.id,
                name="Second",
                url="https://example.com/sitemap.xml",
                crawl_mode="sitemap",
                crawl_config={"max_pages": 10},
            )

    def test_stale_processing_row_auto_recovered(self) -> None:
        import datetime

        from django.utils import timezone

        from products.business_knowledge.backend.models import SourceType

        stale = KnowledgeSource.objects.unscoped().create(
            team_id=self.team.id,
            name="Stale",
            source_type=SourceType.URL,
            status=SourceStatus.PROCESSING,
            source_url="https://stale.example.com/",
        )
        KnowledgeSource.objects.unscoped().filter(id=stale.id).update(
            updated_at=timezone.now() - datetime.timedelta(minutes=15),
        )
        sitemap = _sitemap_xml(["https://example.com/a"])
        behaviours = {
            "https://example.com/a": _ok("https://example.com/a", b"<html><body>Alpha.</body></html>"),
        }
        with (
            patch.object(discover, "_http_get_text", return_value=sitemap),
            patch.object(crawl.url_fetch, "fetch_url", side_effect=_FakeFetch(behaviours)),
        ):
            source = create_crawl_source(
                team_id=self.team.id,
                created_by_id=self.user.id,
                name="Fresh",
                url="https://example.com/sitemap.xml",
                crawl_mode="sitemap",
                crawl_config={"max_pages": 10},
            )
        assert source.status == SourceStatus.READY
        stale.refresh_from_db()
        assert stale.status == SourceStatus.ERROR


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
            patch.object(logic, "CRAWL_WRITE_BATCH_SIZE", 1),
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

    def test_vanished_page_chunks_do_not_count_against_the_cap(self) -> None:
        source = self._seed(["https://example.com/a", "https://example.com/b"])
        doc_b = KnowledgeDocument.objects.unscoped().get(source=source, stable_id="https://example.com/b")
        at_cap = KnowledgeChunk.objects.unscoped().filter(team_id=self.team.id).count()

        sitemap = _sitemap_xml(["https://example.com/a", "https://example.com/c"])
        behaviours = {
            url: _ok(url, f"<html><body>body of {url}</body></html>".encode())
            for url in ["https://example.com/a", "https://example.com/c"]
        }
        with (
            patch.object(discover, "_http_get_text", return_value=sitemap),
            patch.object(crawl.url_fetch, "fetch_url", side_effect=_FakeFetch(behaviours)),
            patch.object(logic, "MAX_CHUNKS_PER_TEAM", at_cap),
        ):
            refresh_source(source_id=source.id, team_id=self.team.id)

        source.refresh_from_db()
        doc_b.refresh_from_db()
        assert source.status == SourceStatus.READY
        assert source.last_refresh_error == ""
        assert doc_b.tombstoned_at is not None
        assert KnowledgeDocument.objects.unscoped().filter(source=source, stable_id="https://example.com/c").exists()

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
        with patch(
            "products.business_knowledge.backend.discover.fetch_text",
            side_effect=url_fetch.UrlFetchError("127.0.0.1 is not reachable (SSRF blocked)"),
        ):
            with self.assertRaises(discover.DiscoverError):
                discover._http_get_text("https://example.com/sitemap.xml")
