"""
Multi-URL fetch orchestration for Stage 2b.

Wraps `url_fetch.fetch_url` with:

- A bounded ThreadPoolExecutor so a large crawl saturates network IO.
- A per-hostname `threading.Semaphore` so we never hit an origin with more
  than `PER_HOST_CONCURRENCY` concurrent requests even if the thread pool
  is bigger.
- HTML parse hand-off (same `html_parse` used by Stage 2a).
- Per-URL outcome records so the caller can upsert / tombstone cleanly.
- A bounded number of fetches in flight, with outcomes yielded as they finish,
  so the caller can write pages in batches instead of holding the whole crawl.

Errors per URL are *isolated*: one broken page doesn't tank the batch.
"""

from __future__ import annotations

import time
import threading
import urllib.parse as urlparse
from collections.abc import Callable, Iterator
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass

import structlog

from . import html_parse, url_fetch
from .constants import MAX_TEXT_SIZE_BYTES, PER_HOST_CONCURRENCY
from .url_fetch import sha256_of

# Wall clock for one source's page fetches, including the batch writes the caller
# does between them. A full source at PER_HOST_CONCURRENCY has to finish inside the
# crawl activity, which also discovers URLs and writes the last batch.
CRAWL_TOTAL_TIMEOUT_SECONDS = 40 * 60

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


def _fetch_one(
    url: str,
    *,
    etag: str | None,
    registry: _PerHostSemaphoreRegistry,
    prefetched: dict[str, url_fetch.FetchResult],
) -> CrawlOutcome:
    """
    Fetch + parse a single URL. Never raises — all failures return a
    CrawlOutcome(status="error", error=...). Matches the `url_fetch.fetch_url`
    contract for SSRF re-validation per-hop.

    Pages already downloaded during discovery (`prefetched`) skip the network
    round-trip entirely and go straight to parsing.
    """

    result = prefetched.get(url_fetch.prefetch_key(url))
    if result is not None:
        return _parse_outcome(url, result)

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

        return _parse_outcome(url, result)
    finally:
        sem.release()


def _parse_outcome(url: str, result: url_fetch.FetchResult) -> CrawlOutcome:
    """Parse a fetched body into a CrawlOutcome. Network-free."""

    if not result.body:
        return CrawlOutcome(url=url, final_url=result.final_url, status="error", error="Remote response was empty.")

    if not url_fetch.is_html_content_type(result.content_type):
        return CrawlOutcome(url=url, final_url=result.final_url, status="error", error="Unsupported content type.")

    title, text = html_parse.parse_html(result.body, result.final_url, content_type=result.content_type)
    if not text.strip():
        return CrawlOutcome(url=url, final_url=result.final_url, status="error", error="Could not extract any text.")
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
        content_hash=sha256_of(text),
    )


def _timeout_outcome(url: str) -> CrawlOutcome:
    logger.warning("business_knowledge.crawl.timeout", url=url)
    return CrawlOutcome(url=url, final_url=url, status="error", error="Crawl total timeout exceeded")


def iter_fetch(
    urls: list[str],
    *,
    etag_for: Callable[[str], str | None] | None = None,
    per_host: int = PER_HOST_CONCURRENCY,
    max_workers: int | None = None,
    max_in_flight: int | None = None,
    prefetched: dict[str, url_fetch.FetchResult] | None = None,
) -> Iterator[CrawlOutcome]:
    """
    Fetch `urls` in parallel, capped per-host by a threading semaphore, and yield
    one outcome per URL in completion order.

    At most `max_in_flight` URLs are submitted but not yet yielded, so memory
    holds that many parsed pages, not the whole crawl. Fetches keep running
    while the caller handles a yielded outcome.

    `etag_for(url)` — optional; called once per URL, when the URL is submitted,
    to pull a stored ETag for conditional GET. Returns None when we don't have one yet.

    `prefetched` — optional bodies already downloaded during discovery
    (keyed by normalized URL); matching URLs skip the network entirely.

    `max_workers` — defaults to `max(PER_HOST_CONCURRENCY * 4, 8)`. We want
    enough threads to saturate the per-host semaphore without going wild;
    the semaphore is the real throttle. `max_in_flight` defaults to twice that.
    """

    if not urls:
        return

    registry = _PerHostSemaphoreRegistry(per_host)
    workers = max_workers if max_workers is not None else max(per_host * 4, 8)
    in_flight_cap = max_in_flight if max_in_flight is not None else workers * 2
    cache = prefetched or {}
    deadline = time.monotonic() + CRAWL_TOTAL_TIMEOUT_SECONDS
    queued = iter(urls)
    in_flight: dict[Future[CrawlOutcome], str] = {}

    pool = ThreadPoolExecutor(max_workers=workers)
    try:

        def _submit_up_to_cap() -> None:
            while len(in_flight) < in_flight_cap:
                url = next(queued, None)
                if url is None:
                    return
                future = pool.submit(
                    _fetch_one,
                    url,
                    etag=(etag_for(url) if etag_for else None),
                    registry=registry,
                    prefetched=cache,
                )
                in_flight[future] = url

        _submit_up_to_cap()
        while in_flight:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            done, _not_done = wait(in_flight, timeout=remaining, return_when=FIRST_COMPLETED)
            if not done:
                break
            for future in done:
                url = in_flight.pop(future)
                try:
                    outcome = future.result()
                except Exception as exc:  # defense in depth — _fetch_one shouldn't raise
                    logger.exception("business_knowledge.crawl.unexpected_error", url=url)
                    outcome = CrawlOutcome(url=url, final_url=url, status="error", error=str(exc))
                yield outcome
            _submit_up_to_cap()

        for future, url in list(in_flight.items()):
            future.cancel()
            yield _timeout_outcome(url)
        for url in queued:
            yield _timeout_outcome(url)
    finally:
        # Don't block on still-running threads — let them drain in the
        # background. cancel_futures=True drops queued-but-not-started work.
        pool.shutdown(wait=False, cancel_futures=True)
