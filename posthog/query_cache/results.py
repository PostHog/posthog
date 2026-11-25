import threading
from collections import Counter
from collections.abc import Iterator, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Optional

import structlog
import zstandard

from posthog.dataclasses import frozen
from posthog.query_cache.serialization import CachedEntry, split_cached_response_bytes
from posthog.query_cache.storage import (
    ZSTD_FRAME_MAGIC,
    decode_pointer,
    decode_stored_value,
    delete_entry,
    is_s3_pointer,
    load_entry_value,
    load_entry_values,
)

logger = structlog.get_logger(__name__)


@frozen
class EntryFreshness:
    """What a freshness probe learns from Redis alone: the entry exists, and when it was
    last refreshed (None when the stored response carries no last_refresh)."""

    last_refresh: Optional[str]


# Values read by `prefetched_entries`, by cache key, one per lookup still to come. A key's value is dropped after its
# last lookup, so a board's decompressed blobs don't stay in memory next to the results copied out of them. None
# outside the block, so every entry is read on its own.
_prefetched_values: ContextVar[dict[str, list[Optional[bytes]]] | None] = ContextVar(
    "query_cache_prefetched_values", default=None
)
# The decoded size of each entry a lookup inside the block read, prefetched or read on its own after a failed batch.
_decoded_sizes: ContextVar[dict[str, int] | None] = ContextVar("query_cache_decoded_sizes", default=None)

# Blob fetches run in parallel, so a board of S3-backed entries waits about as long as its slowest blob. The pool is
# shared by every request in the process, so concurrent board loads queue for these threads instead of each starting
# their own.
_PREFETCH_S3_CONCURRENCY = 8

_prefetch_executor: Optional[ThreadPoolExecutor] = None
_prefetch_executor_lock = threading.Lock()


def _get_prefetch_executor() -> ThreadPoolExecutor:
    # Created on first use so the threads start in the serving process, not in a pre-fork parent.
    global _prefetch_executor
    if _prefetch_executor is None:
        with _prefetch_executor_lock:
            if _prefetch_executor is None:
                _prefetch_executor = ThreadPoolExecutor(
                    max_workers=_PREFETCH_S3_CONCURRENCY, thread_name_prefix="query-cache-prefetch"
                )
    return _prefetch_executor


@contextmanager
def prefetched_entries(cache_keys: Sequence[str], *, team_id: int) -> Iterator[None]:
    """Read the entries of `cache_keys` in one round trip, so the lookups of those keys inside the block don't read
    them one by one. The S3 blobs behind pointer entries are fetched at the same time.

    Lookups see the values as they were when the block started. Each occurrence of a key in `cache_keys` serves one
    lookup. A key not in `cache_keys` is read as usual, and so is a lookup past those occurrences and every key when
    the batched read fails.
    """
    token = _prefetched_values.set(_read_values(cache_keys, team_id=team_id))
    sizes_token = _decoded_sizes.set({})
    try:
        yield
    finally:
        _decoded_sizes.reset(sizes_token)
        _prefetched_values.reset(token)


def _read_values(cache_keys: Sequence[str], *, team_id: int) -> dict[str, list[Optional[bytes]]]:
    lookups = Counter(cache_keys)
    unique_keys = list(lookups)
    if not unique_keys:
        return {}
    try:
        values = dict(zip(unique_keys, load_entry_values(unique_keys)))
    except Exception:
        logger.warning("query_cache_batched_read_error", team_id=team_id, keys=len(unique_keys), exc_info=True)
        return {}
    pointers = [(key, value) for key, value in values.items() if value is not None and is_s3_pointer(value)]
    if pointers:
        # A resolved blob is the decompressed payload, which decode_stored_value returns as it is on lookup.
        values.update(_read_blobs(pointers, team_id=team_id))
    return {key: [value] * lookups[key] for key, value in values.items()}


def _read_blobs(pointers: Sequence[tuple[str, bytes]], *, team_id: int) -> dict[str, Optional[bytes]]:
    # A request keeps at most one pool's worth of reads queued, so a board with many blobs takes turns with the
    # requests that arrive after it instead of making them wait for every one of its reads.
    executor = _get_prefetch_executor()
    waiting = iter(pointers)
    in_flight: dict[Future[Optional[bytes]], str] = {}
    resolved: dict[str, Optional[bytes]] = {}

    def submit_next() -> None:
        pointer = next(waiting, None)
        if pointer is not None:
            key, value = pointer
            in_flight[executor.submit(decode_stored_value, value, team_id=team_id, cache_key=key)] = key

    try:
        for _ in range(_PREFETCH_S3_CONCURRENCY):
            submit_next()
        while in_flight:
            done, _ = wait(in_flight, return_when=FIRST_COMPLETED)
            for future in done:
                resolved[in_flight.pop(future)] = future.result()
                submit_next()
    finally:
        for future in in_flight:
            future.cancel()
    return resolved


def prefetched_size(cache_key: str) -> int:
    """The decoded size in bytes of the next prefetched value for `cache_key`, or 0 when none is waiting.

    A zstd frame is measured by the content size in its header, so nothing is decompressed to measure it.
    """
    prefetched = _prefetched_values.get()
    remaining = prefetched.get(cache_key) if prefetched is not None else None
    value = remaining[-1] if remaining else None
    if not isinstance(value, bytes):
        return 0
    if value.startswith(ZSTD_FRAME_MAGIC):
        try:
            size = zstandard.frame_content_size(value)
        except zstandard.ZstdError:
            size = -1
        if size >= 0:
            return size
    return len(value)


def decoded_size(cache_key: str) -> int:
    """The decoded size in bytes of the entry the last lookup of `cache_key` in a `prefetched_entries` block read, or
    0 when it read none."""
    sizes = _decoded_sizes.get()
    return sizes.get(cache_key, 0) if sizes is not None else 0


def _record_decoded_size(cache_key: str, payload: bytes) -> None:
    sizes = _decoded_sizes.get()
    if sizes is not None:
        sizes[cache_key] = len(payload)


def fetch_entry(cache_key: str, team_id: int) -> Optional[CachedEntry]:
    prefetched = _prefetched_values.get()
    if prefetched is not None and cache_key in prefetched:
        remaining = prefetched[cache_key]
        stored_value = remaining.pop()
        if not remaining:
            del prefetched[cache_key]
        return _entry_from_prefetched_value(stored_value, cache_key=cache_key, team_id=team_id)
    try:
        stored_value = load_entry_value(cache_key)
    except Exception:
        logger.warning("query_cache_read_error", cache_key=cache_key, team_id=team_id, exc_info=True)
        try:
            delete_entry(cache_key)
        except Exception:
            pass
        return None

    if not stored_value:
        return None

    payload = decode_stored_value(stored_value, team_id=team_id, cache_key=cache_key)
    if payload is None:
        return None
    _record_decoded_size(cache_key, payload)

    try:
        return split_cached_response_bytes(payload, cache_key=cache_key, team_id=team_id)
    except Exception:
        logger.exception("query_cache_deserialize_error", cache_key=cache_key, team_id=team_id, exc_info=True)
        return None


def _entry_from_prefetched_value(
    stored_value: Optional[bytes], *, cache_key: str, team_id: int
) -> Optional[CachedEntry]:
    # The steps fetch_entry takes after its own read.
    if not stored_value:
        return None

    payload = decode_stored_value(stored_value, team_id=team_id, cache_key=cache_key)
    if payload is None:
        return None
    _record_decoded_size(cache_key, payload)

    try:
        return split_cached_response_bytes(payload, cache_key=cache_key, team_id=team_id)
    except Exception:
        logger.exception("query_cache_deserialize_error", cache_key=cache_key, team_id=team_id, exc_info=True)
        return None


def fetch_entry_freshness(cache_key: str, team_id: int) -> Optional[EntryFreshness]:
    """Existence and last_refresh of an entry without resolving S3 pointers. Never raises.

    Pointer records carry last_refresh, so probing an S3-backed entry costs one Redis read;
    resolving the blob here would put an S3 round trip into every warming candidate check.
    The trade: a pointer whose blob has died still reads as a live entry until the recompute
    that follows a real read's miss overwrites it.
    """
    try:
        stored_value = load_entry_value(cache_key)
        if not stored_value:
            return None
        if is_s3_pointer(stored_value):
            pointer = decode_pointer(stored_value)
            if pointer is None:
                return None
            return EntryFreshness(last_refresh=pointer.last_refresh)
        payload = decode_stored_value(stored_value, team_id=team_id, cache_key=cache_key)
        if payload is None:
            return None
        entry = split_cached_response_bytes(payload, cache_key=cache_key, team_id=team_id)
        last_refresh = entry.header.get("last_refresh")
        return EntryFreshness(last_refresh=last_refresh if isinstance(last_refresh, str) else None)
    except Exception:
        logger.warning("query_cache_freshness_probe_failed", cache_key=cache_key, team_id=team_id, exc_info=True)
        return None
