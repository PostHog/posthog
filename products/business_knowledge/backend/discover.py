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

from .constants import CRAWL_HARD_MAX_DEPTH, DEFAULT_CRAWL_MAX_DEPTH, HARD_DISCOVER_CAP, URL_BOT_NAME, URL_MAX_BYTES
from .url_fetch import UrlFetchError, fetch_text

logger = structlog.get_logger(__name__)


class DiscoverError(Exception):
    """User-safe discover failure. No server detail in the message."""


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
    for sub in subs[:HARD_DISCOVER_CAP]:
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


def _discover_same_origin(entry_url: str, *, config: CrawlConfig) -> list[str]:
    """
    BFS crawler scoped to the entry URL's (scheme, host, port). Respects
    robots.txt when available. Stops at `config.max_depth` or when we hit
    `HARD_DISCOVER_CAP` — whichever comes first.
    """

    origin_tuple = _origin_of(entry_url)
    origin = f"{origin_tuple[0]}://{urlparse.urlparse(entry_url).netloc}"
    robots = _load_robots(origin)

    max_depth = max(0, min(config.max_depth, CRAWL_HARD_MAX_DEPTH))

    seen: set[str] = set()
    out: list[str] = []
    queue: deque[tuple[str, int]] = deque([(entry_url, 0)])
    seen.add(entry_url)
    while queue and len(out) < HARD_DISCOVER_CAP:
        url, depth = queue.popleft()
        # Use the short bot token (not the full UA string) — urllib.robotparser
        # prefix-matches this against `User-agent:` lines in robots.txt.
        if robots is not None and not robots.can_fetch(URL_BOT_NAME, url):
            continue
        out.append(url)
        if depth >= max_depth:
            continue
        try:
            html = _http_get_text(url)
        except DiscoverError:
            # One bad page shouldn't tank the crawl.
            continue
        for link in _extract_links(html, url, origin_tuple):
            if link in seen:
                continue
            seen.add(link)
            queue.append((link, depth + 1))
    return out


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


def discover(mode: str, entry_url: str, config: CrawlConfig) -> list[str]:
    """
    Entry point for `logic.py`. Dispatches on `mode`, dedupes, applies
    include/exclude globs, truncates to `max_pages`, and returns a list of
    absolute URLs ready for the fetch loop.

    Never returns more than `min(max_pages, MAX_URLS_PER_SOURCE)` URLs.
    """

    if mode == "sitemap":
        raw = _discover_sitemap(entry_url, config=config)
    elif mode == "same_origin":
        raw = _discover_same_origin(entry_url, config=config)
    elif mode == "github_repo":
        raise NotImplementedError("github_repo crawl mode is not yet supported")
    else:
        raise DiscoverError(f"Unsupported crawl mode: {mode}")

    deduped = _dedupe_preserving_order(raw)
    filtered = _apply_globs(deduped, config)
    return filtered[: config.max_pages]
