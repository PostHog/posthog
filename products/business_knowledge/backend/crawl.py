"""
Multi-URL fetch orchestration for Stage 2b.

Wraps `url_fetch.fetch_url` with:

- A bounded ThreadPoolExecutor so a large crawl saturates network IO.
- A per-hostname `threading.Semaphore` so we never hit an origin with more
  than `PER_HOST_CONCURRENCY` concurrent requests even if the thread pool
  is bigger.
- HTML parse hand-off (same `html_parse` used by Stage 2a).
- Per-URL outcome records so the caller can upsert / tombstone cleanly.

Errors per URL are *isolated*: one broken page doesn't tank the batch.
"""

from __future__ import annotations

import hashlib
import threading
import urllib.parse as urlparse
from collections.abc import Callable
from concurrent.futures import ALL_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass

import structlog

from . import html_parse, url_fetch
from .facade.enums import MAX_TEXT_SIZE_BYTES, PER_HOST_CONCURRENCY

CRAWL_TOTAL_TIMEOUT_SECONDS = 120

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class CrawlOutcome:
    """
    Result for a single URL in the crawl batch.

    `status`:
      - "ok": we got usable HTML/text. `title`, `text`, `etag`, `content_hash`
        are populated.
      - "not_modified": conditional GET returned 304. No body re-parsed.
      - "error": fetch or parse failed. `error` is a user-safe message.
    """

    url: str
    final_url: str
    status: str
    title: str = ""
    text: str = ""
    etag: str = ""
    content_hash: str = ""
    error: str = ""


def _host_of(url: str) -> str:
    parsed = urlparse.urlparse(url)
    return (parsed.hostname or "").lower()


class _PerHostSemaphoreRegistry:
    """
    Lazily-created `threading.Semaphore` per hostname. Cheap enough to keep
    in a dict since a single crawl rarely spans >5 hostnames.
    """

    def __init__(self, per_host: int) -> None:
        self._per_host = per_host
        self._lock = threading.Lock()
        self._map: dict[str, threading.Semaphore] = {}

    def get(self, host: str) -> threading.Semaphore:
        with self._lock:
            sem = self._map.get(host)
            if sem is None:
                sem = threading.Semaphore(self._per_host)
                self._map[host] = sem
            return sem


def _sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fetch_one(url: str, *, etag: str | None, registry: _PerHostSemaphoreRegistry) -> CrawlOutcome:
    """
    Fetch + parse a single URL. Never raises — all failures return a
    CrawlOutcome(status="error", error=...). Matches the `url_fetch.fetch_url`
    contract for SSRF re-validation per-hop.
    """

    sem = registry.get(_host_of(url))
    sem.acquire()
    try:
        try:
            result = url_fetch.fetch_url(url, etag=etag)
        except url_fetch.UrlFetchError as exc:
            return CrawlOutcome(url=url, final_url=url, status="error", error=str(exc))

        if result.status == 304:
            return CrawlOutcome(
                url=url,
                final_url=result.final_url,
                status="not_modified",
                etag=result.etag or (etag or ""),
            )

        if not result.body:
            return CrawlOutcome(url=url, final_url=result.final_url, status="error", error="Remote response was empty.")

        if not url_fetch.is_html_content_type(result.content_type):
            return CrawlOutcome(url=url, final_url=result.final_url, status="error", error="Unsupported content type.")

        title, text = html_parse.parse_html(result.body, result.final_url)
        if not text.strip():
            return CrawlOutcome(
                url=url, final_url=result.final_url, status="error", error="Could not extract any text."
            )
        # Per-page byte cap — trimming beats rejecting a huge wiki page.
        if len(text.encode("utf-8")) > MAX_TEXT_SIZE_BYTES:
            return CrawlOutcome(
                url=url,
                final_url=result.final_url,
                status="error",
                error="Page content exceeds the maximum allowed size.",
            )
        return CrawlOutcome(
            url=url,
            final_url=result.final_url,
            status="ok",
            title=title,
            text=text,
            etag=result.etag or "",
            content_hash=_sha256_of(text),
        )
    finally:
        sem.release()


def fetch_many(
    urls: list[str],
    *,
    etag_for: Callable[[str], str | None] | None = None,
    per_host: int = PER_HOST_CONCURRENCY,
    max_workers: int | None = None,
) -> list[CrawlOutcome]:
    """
    Fetch all `urls` in parallel, capped per-host by a threading semaphore.

    `etag_for(url)` — optional; called once per URL to pull a stored ETag
    for conditional GET. Returns None when we don't have one yet.

    `max_workers` — defaults to `max(PER_HOST_CONCURRENCY * 4, 8)`. We want
    enough threads to saturate the per-host semaphore without going wild;
    the semaphore is the real throttle.
    """

    if not urls:
        return []

    registry = _PerHostSemaphoreRegistry(per_host)
    workers = max_workers if max_workers is not None else max(per_host * 4, 8)

    results: list[CrawlOutcome] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_fetch_one, url, etag=(etag_for(url) if etag_for else None), registry=registry): url
            for url in urls
        }
        done, not_done = wait(futures, timeout=CRAWL_TOTAL_TIMEOUT_SECONDS, return_when=ALL_COMPLETED)
        for future in done:
            try:
                outcome = future.result()
            except Exception as exc:  # defense in depth — _fetch_one shouldn't raise
                url = futures[future]
                logger.exception("business_knowledge.crawl.unexpected_error", url=url)
                outcome = CrawlOutcome(url=url, final_url=url, status="error", error=str(exc))
            results.append(outcome)
        for future in not_done:
            future.cancel()
            url = futures[future]
            logger.warning("business_knowledge.crawl.timeout", url=url)
            results.append(CrawlOutcome(url=url, final_url=url, status="error", error="Crawl total timeout exceeded"))
    return results
