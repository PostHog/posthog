"""Thread-local connection cache for direct MotherDuck queries.

Opening a MotherDuck connection loads the `motherduck` DuckDB extension and completes a
WebSocket handshake — routinely seconds — which dominates latency for the interactive SQL
editor where a user issues many small queries in sequence. This caches one open connection
per (token + database) per worker thread, reusing it across queries and reopening lazily
when it expires, dies, or is evicted.

Same scope choices as the Snowflake cache: direct-query path only (the data-import
pipeline opens its own short-lived connections per sync), and thread-local because a
DuckDB connection must not be shared across threads mid-query.
"""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from time import monotonic
from typing import TYPE_CHECKING

from posthog.hogql.direct_query_metrics import DIRECT_CONNECTION_CACHE_TOTAL

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    import duckdb

    from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.motherduck import (
        MotherduckSourceConfig,
    )
    from products.warehouse_sources.backend.temporal.data_imports.sources.motherduck.source import MotherduckSource


MOTHERDUCK_CONNECTION_CACHE_TTL_SECONDS = 1800
# Bound per-thread connection count so a worker that touches many distinct sources
# can't accumulate open sessions without limit.
MOTHERDUCK_CONNECTION_CACHE_MAX_PER_THREAD = 4
# On a warm connection the probe is a single round trip, so a couple of seconds means the
# session is gone; anything slower should read as dead rather than block the request thread.
MOTHERDUCK_LIVENESS_PROBE_TIMEOUT_SECONDS = 5


@frozen
class _Entry:
    cm: AbstractContextManager[duckdb.DuckDBPyConnection]
    connection: duckdb.DuckDBPyConnection
    opened_at: float


_thread_local = threading.local()


def _cache() -> OrderedDict[str, _Entry]:
    cache = getattr(_thread_local, "cache", None)
    if cache is None:
        cache = OrderedDict()
        _thread_local.cache = cache
    return cache


def _config_key(token: str, database: str | None) -> str:
    # Hash the token rather than carry it in the key. Keying on the credential means a
    # rotation routes to a fresh connection automatically (the old entry just expires).
    token_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return hashlib.sha256(f"{token_digest}\x00{database or ''}".encode()).hexdigest()


def _close_entry(entry: _Entry) -> None:
    try:
        entry.cm.__exit__(None, None, None)
    except Exception:
        pass


def _evict(key: str) -> None:
    entry = _cache().pop(key, None)
    if entry is not None:
        _close_entry(entry)


def _interrupt_quietly(connection: duckdb.DuckDBPyConnection) -> None:
    try:
        connection.interrupt()
    except Exception:
        pass


def _is_reusable(entry: _Entry, now: float) -> bool:
    if now - entry.opened_at >= MOTHERDUCK_CONNECTION_CACHE_TTL_SECONDS:
        return False
    # Cheap liveness probe. A cleanly-closed socket raises immediately, but a half-open one
    # (remote gone without FIN/RST) can block the read until an OS-level timeout, so a timer
    # interrupts the probe after a short deadline and the connection reads as dead.
    timer = threading.Timer(MOTHERDUCK_LIVENESS_PROBE_TIMEOUT_SECONDS, _interrupt_quietly, args=(entry.connection,))
    timer.daemon = True
    timer.start()
    try:
        entry.connection.execute("SELECT 1")
        return True
    except Exception:
        return False
    finally:
        timer.cancel()


@contextmanager
def cached_motherduck_connection(
    source: MotherduckSource,
    config: MotherduckSourceConfig,
) -> Iterator[duckdb.DuckDBPyConnection]:
    """Yield a cached open read-only MotherDuck connection for this thread.

    The connection is kept open after the block exits so the next query on the same thread
    can reuse it. It is dropped (and reopened next time) on expiry, when found dead, on LRU
    eviction, or when the block raises a connection-level error.
    """
    # Function-local: keeps the duckdb driver off the django.setup() path.
    import duckdb  # noqa: PLC0415

    key = _config_key(config.access_token, source.normalized_database(config))
    cache = _cache()
    now = monotonic()

    entry = cache.get(key)
    if entry is not None and _is_reusable(entry, now):
        cache.move_to_end(key)
        connection = entry.connection
        DIRECT_CONNECTION_CACHE_TOTAL.labels(engine="motherduck", result="reused").inc()
    else:
        if entry is not None:
            _evict(key)
        # Drive the source's own connection contextmanager but keep it entered, so the
        # read-only/SaaS-mode connection settings stay owned by the source.
        cm = source.direct_query_connection(config)
        connection = cm.__enter__()
        cache[key] = _Entry(cm=cm, connection=connection, opened_at=now)
        DIRECT_CONNECTION_CACHE_TOTAL.labels(engine="motherduck", result="opened").inc()
        while len(cache) > MOTHERDUCK_CONNECTION_CACHE_MAX_PER_THREAD:
            _old_key, old_entry = cache.popitem(last=False)
            _close_entry(old_entry)

    try:
        yield connection
    except duckdb.Error as error:
        # SQL-level errors (Binder, Catalog, Parser) leave the connection healthy; anything
        # transport-shaped means the cached session is suspect.
        if isinstance(error, duckdb.IOException | duckdb.ConnectionException | duckdb.FatalException):
            _evict(key)
        raise


def clear_thread_local_motherduck_connections() -> None:
    """Close and drop every cached connection for the current thread (tests, shutdown)."""
    cache = _cache()
    for entry in list(cache.values()):
        _close_entry(entry)
    cache.clear()
