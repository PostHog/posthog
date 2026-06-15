"""
URL discovery for Stage 2b crawl modes.

Three strategies, all returning a deduped, glob-filtered, capped list of
absolute URLs:

- `sitemap`: parse sitemap.xml (+ sitemap indexes) anchored at the entry URL.
- `same_origin`: BFS from the entry URL, staying on the same scheme/host/port,
  honoring robots.txt.
- `github_repo`: Reserved — raises NotImplementedError so we fail cleanly if
  someone sets the enum without having built the discovery path.

Only `logic.py` is allowed to import this module. Errors bubble as
`DiscoverError` with user-safe messages.
"""

from __future__ import annotations

import fnmatch
import urllib.parse as urlparse
import urllib.robotparser
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass

import structlog
import defusedxml.ElementTree as ET
from bs4 import BeautifulSoup
from defusedxml.ElementTree import ParseError as DefusedParseError

from .constants import (
    CRAWL_HARD_MAX_DEPTH,
    DEFAULT_CRAWL_MAX_DEPTH,
    HARD_DISCOVER_CAP,
    PREFETCH_CACHE_MAX_BYTES,
    URL_BOT_NAME,
    URL_MAX_BYTES,
)
from .url_fetch import FetchResult, UrlFetchError, fetch_text, fetch_url, prefetch_key

logger = structlog.get_logger(__name__)


class DiscoverError(Exception):
    """User-safe discover failure. No server detail in the message."""


@dataclass(frozen=True)
class DiscoverResult:
    """
    Discovery output: the deduped/filtered/capped URL list, plus the pages we
    already fetched while traversing (same-origin BFS fetches every
    intermediate page to extract links). `prefetched` is keyed by normalized
    URL so the crawl fetch phase can reuse those bodies instead of hitting
    the origin a second time.
    """

    urls: list[str]
    prefetched: dict[str, FetchResult]


@dataclass(frozen=True)
class CrawlConfig:
    """
    Validated crawl knobs. The serializer is the single layer responsible
    for constructing one of these — logic/discover never accepts a raw dict.
    """

    include_globs: tuple[str, ...] = ()
    exclude_globs: tuple[str, ...] = ()
    max_depth: int = DEFAULT_CRAWL_MAX_DEPTH
    max_pages: int = 50


# --- Sitemap discovery -------------------------------------------------------


_SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def _http_get_text(url: str, *, max_bytes: int = URL_MAX_BYTES) -> str:
    """
    Thin wrapper around `url_fetch.fetch_text` that translates
    `UrlFetchError` into `DiscoverError` for callers in this module.
    """

    try:
        return fetch_text(url, max_bytes=max_bytes)
    except UrlFetchError as exc:
        raise DiscoverError(str(exc)) from exc


def _parse_sitemap_xml(xml_text: str) -> tuple[list[str], list[str]]:
    """
    Parse one sitemap document. Returns (urls, sub_sitemaps).

    Supports both `<urlset>` (URLs) and `<sitemapindex>` (indexes) per the
    sitemaps.org schema. Malformed XML is a user-safe error — we never
    reveal parser internals.
    """

    try:
        root = ET.fromstring(xml_text)
    except DefusedParseError as exc:
        # defusedxml rejects billion-laughs / external-entity attacks here —
        # treat everything the parser refuses as "not a sitemap".
        raise DiscoverError("Sitemap is not valid XML.") from exc

    # Strip namespace so we don't care about prefix variations.
    tag = root.tag.split("}", 1)[-1] if "}" in root.tag else root.tag

    urls: list[str] = []
    subs: list[str] = []
    if tag == "urlset":
        for loc in root.iterfind(".//sm:url/sm:loc", _SITEMAP_NS) or []:
            if loc.text:
                urls.append(loc.text.strip())
    elif tag == "sitemapindex":
        for loc in root.iterfind(".//sm:sitemap/sm:loc", _SITEMAP_NS) or []:
            if loc.text:
                subs.append(loc.text.strip())
    else:
        # Some sites serve sitemap.xml without xmlns. Fall back to a tag scan.
        for loc in root.iter():
            local = loc.tag.split("}", 1)[-1] if "}" in loc.tag else loc.tag
            if local == "loc" and loc.text:
                urls.append(loc.text.strip())
    return urls, subs


def _discover_sitemap(entry_url: str, *, config: CrawlConfig) -> list[str]:
    """
    Fetch the sitemap at `entry_url` (or `<origin>/sitemap.xml` if the user
    gave us an HTML page), follow one level of sitemap-index children, and
    return the flat URL list (unfiltered, uncapped — filter/cap happens in
    `discover()`).
    """

    # If the user gave us a page URL, try sitemap.xml at the origin root.
    parsed = urlparse.urlparse(entry_url)
    if not parsed.path.lower().endswith((".xml", ".xml.gz")):
        origin = f"{parsed.scheme}://{parsed.netloc}"
        candidate = urlparse.urljoin(origin + "/", "sitemap.xml")
    else:
        candidate = entry_url

    xml_text = _http_get_text(candidate)
    urls, subs = _parse_sitemap_xml(xml_text)

    # One level of sitemap-index unfurling. A huge site usually has nested
    # indexes (products, docs, blog). Deeper nesting is rare; we cap at 1 to
    # keep the total network IO bounded on discover.
    for sub in subs[: min(config.max_pages, HARD_DISCOVER_CAP)]:
        if len(urls) >= HARD_DISCOVER_CAP:
            break
        try:
            child = _http_get_text(sub)
            child_urls, _ = _parse_sitemap_xml(child)
            urls.extend(child_urls)
        except DiscoverError:
            # A broken child sitemap shouldn't tank the whole discover.
            # Log and move on.
            logger.info("business_knowledge.discover.sitemap_child_failed", sub=sub)
            continue
    return urls


# --- Same-origin BFS ---------------------------------------------------------


def _origin_of(url: str) -> tuple[str, str, int | None]:
    parsed = urlparse.urlparse(url)
    return (parsed.scheme.lower(), (parsed.hostname or "").lower(), parsed.port)


def _extract_links(html: str, base_url: str, same_origin: tuple[str, str, int | None]) -> list[str]:
    """
    Pull all `<a href>` links from `html`, resolve relative hrefs against
    `base_url`, drop anything not on the same origin. Fragments are stripped
    so `/foo` and `/foo#bar` collapse to one URL.
    """

    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return []

    out: list[str] = []
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if not href or href.startswith(("mailto:", "javascript:", "tel:")):
            continue
        joined = urlparse.urljoin(base_url, href)
        # Strip fragment.
        joined = joined.split("#", 1)[0]
        if _origin_of(joined) != same_origin:
            continue
        if urlparse.urlparse(joined).scheme not in ("http", "https"):
            continue
        out.append(joined)
    return out


def _glob_literal_prefix(glob: str) -> str:
    """
    The leading literal portion of a glob, up to the first wildcard metachar.

    ``/handbook/*`` → ``/handbook/``; ``/docs/**`` → ``/docs/``; ``/a?b`` → ``/a``.
    Used to focus a same-origin crawl on the subtree the user actually wants.
    """
    out: list[str] = []
    for ch in glob:
        if ch in "*?[":
            break
        out.append(ch)
    return "".join(out)


def _should_traverse(path: str, include_prefixes: list[str]) -> bool:
    """
    Whether a discovered link is worth following given the include globs.

    With no include globs we crawl the whole origin (unchanged behaviour).
    Otherwise we follow a link only when it's inside an include subtree
    (``path`` starts with a prefix) OR an ancestor on the way to one (a prefix
    starts with ``path``) — so we reach ``/handbook/x`` via ``/handbook``
    without fetching ``/pricing``, ``/docs``, etc.
    """
    if not include_prefixes:
        return True
    return any(path.startswith(prefix) or prefix.startswith(path) for prefix in include_prefixes)


def _load_robots(origin: str) -> urllib.robotparser.RobotFileParser | None:
    """
    Best-effort robots.txt load. Missing / broken robots.txt is treated as
    allow-all (RFC-consistent for malformed robots). We keep the parser
    cached per-origin in the caller.
    """

    parser = urllib.robotparser.RobotFileParser()
    try:
        text = _http_get_text(f"{origin}/robots.txt", max_bytes=256 * 1024)
    except DiscoverError:
        return None
    parser.parse(text.splitlines())
    return parser


def _discover_same_origin(entry_url: str, *, config: CrawlConfig) -> tuple[list[str], dict[str, FetchResult]]:
    """
    BFS crawler scoped to the entry URL's (scheme, host, port). Respects
    robots.txt when available. Stops at `config.max_depth`, once `max_pages`
    matching URLs are collected, or at `HARD_DISCOVER_CAP` fetches.

    Returns (urls, prefetched). Every traversed page's `FetchResult` is kept
    in `prefetched` so the content fetch phase doesn't re-download it.

    Glob filtering happens *here*, not after, so `max_pages` counts pages that
    actually match the include globs — otherwise the budget gets spent on
    non-matching pages (e.g. crawling `/` for `/handbook/*` would collect 50
    homepage links and then filter down to the 1-2 that are handbook pages).
    Traversal is also focused on the include subtree (see `_should_traverse`)
    so we don't fetch the whole site to find a handful of matching pages.
    """

    origin_tuple = _origin_of(entry_url)
    origin = f"{origin_tuple[0]}://{urlparse.urlparse(entry_url).netloc}"
    robots = _load_robots(origin)

    max_depth = max(0, min(config.max_depth, CRAWL_HARD_MAX_DEPTH))
    include_prefixes = [_glob_literal_prefix(g) for g in config.include_globs]
    page_cap = min(config.max_pages, HARD_DISCOVER_CAP)

    seen: set[str] = {entry_url}
    out: list[str] = []
    prefetched: dict[str, FetchResult] = {}
    prefetched_bytes = 0
    visited = 0
    queue: deque[tuple[str, int]] = deque([(entry_url, 0)])
    while queue and len(out) < page_cap and visited < HARD_DISCOVER_CAP:
        url, depth = queue.popleft()
        # Use the short bot token (not the full UA string) — urllib.robotparser
        # prefix-matches this against `User-agent:` lines in robots.txt.
        if robots is not None and not robots.can_fetch(URL_BOT_NAME, url):
            continue
        path = urlparse.urlparse(url).path or "/"
        excluded = bool(config.exclude_globs) and _matches_any(path, config.exclude_globs)
        included = not config.include_globs or _matches_any(path, config.include_globs)
        # Collect only matching pages; the entry URL and other intermediates are
        # still traversed (below) so we can reach matching pages through them.
        if included and not excluded:
            out.append(url)
        # Don't descend past max depth or into explicitly-excluded subtrees.
        if depth >= max_depth or excluded:
            continue
        try:
            visited += 1
            # fetch_url (not fetch_text): content Accept headers, and the full
            # FetchResult (body/etag/content-type) is reusable downstream.
            result = fetch_url(url)
        except UrlFetchError:
            # One bad page shouldn't tank the crawl.
            continue
        if result.body is None:
            continue
        # Cache only pages the fetch phase will actually request (collected
        # ones), within a total byte budget — beyond it the fetch phase just
        # re-downloads, trading a request for bounded memory.
        # `excluded` pages never reach here — the depth/exclusion guard above
        # already skipped them before the fetch.
        if included and prefetched_bytes + len(result.body) <= PREFETCH_CACHE_MAX_BYTES:
            prefetched[prefetch_key(url)] = result
            prefetched_bytes += len(result.body)
        # Decode for link extraction only — hrefs are effectively ASCII, so
        # utf-8/replace is good enough here.
        html = result.body.decode("utf-8", errors="replace")
        for link in _extract_links(html, url, origin_tuple):
            if link in seen:
                continue
            seen.add(link)
            link_path = urlparse.urlparse(link).path or "/"
            if not _should_traverse(link_path, include_prefixes):
                continue
            queue.append((link, depth + 1))
    return out, prefetched


# --- Glob filter + public entry point ---------------------------------------


def _matches_any(path: str, globs: Iterable[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, g) for g in globs)


def _apply_globs(urls: list[str], config: CrawlConfig) -> list[str]:
    """
    Include/exclude globs run against the URL *path* (not the full URL), so
    users don't have to care about protocol/host when filtering.

    - `include_globs=()` means "include everything".
    - `exclude_globs=()` means "exclude nothing".
    - Exclude wins over include when both match.
    """

    if not config.include_globs and not config.exclude_globs:
        return urls

    filtered: list[str] = []
    for url in urls:
        path = urlparse.urlparse(url).path or "/"
        if config.include_globs and not _matches_any(path, config.include_globs):
            continue
        if config.exclude_globs and _matches_any(path, config.exclude_globs):
            continue
        filtered.append(url)
    return filtered


def _dedupe_preserving_order(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def discover(mode: str, entry_url: str, config: CrawlConfig) -> DiscoverResult:
    """
    Entry point for `logic.py`. Dispatches on `mode`, dedupes, applies
    include/exclude globs, truncates to `max_pages`, and returns the URLs
    ready for the fetch loop plus any page bodies already fetched during
    traversal (same-origin mode only).

    Never returns more than `min(max_pages, MAX_URLS_PER_SOURCE)` URLs.
    """

    prefetched: dict[str, FetchResult] = {}
    if mode == "sitemap":
        raw = _discover_sitemap(entry_url, config=config)
    elif mode == "same_origin":
        raw, prefetched = _discover_same_origin(entry_url, config=config)
    elif mode == "github_repo":
        raise NotImplementedError("github_repo crawl mode is not yet supported")
    else:
        raise DiscoverError(f"Unsupported crawl mode: {mode}")

    deduped = _dedupe_preserving_order(raw)
    filtered = _apply_globs(deduped, config)
    return DiscoverResult(urls=filtered[: config.max_pages], prefetched=prefetched)
