"""Thread-local connection cache for direct Snowflake queries.

Opening a Snowflake connection runs a full auth handshake (often hundreds of ms or
more), which dominates latency for the interactive SQL editor where a user issues
many small queries in sequence. This caches one open connection per
(credentials + target) per worker thread, reusing it across queries and reopening
lazily when it expires, dies, or is evicted.

Two deliberate scope choices:

- Direct-query path only. The data-import pipeline opens its own short-lived
  connections per sync and must not share these.
- Thread-local. A ``SnowflakeConnection`` is not safe to use from multiple threads
  concurrently, and the web app runs blocking DB work in a threadpool — so each
  thread keeps its own connection and never shares it, no locking required.
"""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from time import monotonic
from typing import TYPE_CHECKING

from posthog.hogql.direct_query_metrics import SNOWFLAKE_CONNECTION_CACHE_TOTAL

if TYPE_CHECKING:
    import snowflake.connector

    from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SnowflakeSourceConfig
    from products.warehouse_sources.backend.temporal.data_imports.sources.snowflake.snowflake import (
        SnowflakeImplementation,
    )

# Refresh well before Snowflake's session/token expiry so a cached connection is
# replaced proactively rather than failing mid-query.
SNOWFLAKE_CONNECTION_CACHE_TTL_SECONDS = 1800
# Bound per-thread connection count so a worker that touches many distinct sources
# can't accumulate open sessions without limit.
SNOWFLAKE_CONNECTION_CACHE_MAX_PER_THREAD = 8


def _connection_level_error_types() -> tuple[type[BaseException], ...]:
    # Transport/connection-level failures mean the cached session is suspect; SQL-level
    # errors (ProgrammingError, IntegrityError) leave the connection healthy. Imported here
    # rather than at module scope so snowflake.connector stays off the hogql query import path.
    import snowflake.connector  # noqa: PLC0415 — keeps snowflake.connector off the hogql query import path

    return (
        snowflake.connector.errors.OperationalError,
        snowflake.connector.errors.InterfaceError,
    )


@dataclass
class _Entry:
    cm: AbstractContextManager[snowflake.connector.SnowflakeConnection]
    connection: snowflake.connector.SnowflakeConnection
    opened_at: float


_thread_local = threading.local()


def _cache() -> OrderedDict[str, _Entry]:
    cache = getattr(_thread_local, "cache", None)
    if cache is None:
        cache = OrderedDict()
        _thread_local.cache = cache
    return cache


def _config_key(config: SnowflakeSourceConfig) -> str:
    auth = config.auth_type
    selection = auth.selection
    secret = auth.private_key if selection == "keypair" else auth.password

    def text(value: object) -> str:
        return str(value) if value else ""

    def digest(value: object) -> str:
        return hashlib.sha256(text(value).encode("utf-8")).hexdigest()

    # Hash the secret rather than carry it in the key. Keying on the credentials means
    # a rotation routes to a fresh connection automatically (old entry just expires).
    secret_digest = digest(secret)
    passphrase_digest = digest(getattr(auth, "passphrase", None))
    parts = [
        text(config.account_id),
        text(auth.user),
        text(config.warehouse),
        text(config.database),
        text(config.role),
        text(config.schema),
        text(selection),
        secret_digest,
        passphrase_digest,
    ]
    return hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()


def _close_entry(entry: _Entry) -> None:
    try:
        entry.cm.__exit__(None, None, None)
    except Exception:
        pass


def _evict(key: str) -> None:
    entry = _cache().pop(key, None)
    if entry is not None:
        _close_entry(entry)


def _is_reusable(entry: _Entry, now: float) -> bool:
    if now - entry.opened_at >= SNOWFLAKE_CONNECTION_CACHE_TTL_SECONDS:
        return False
    try:
        return not entry.connection.is_closed()
    except Exception:
        return False


@contextmanager
def cached_snowflake_connection(
    implementation: SnowflakeImplementation,
    config: SnowflakeSourceConfig,
) -> Iterator[snowflake.connector.SnowflakeConnection]:
    """Yield a cached open Snowflake connection for this thread, opening one if needed.

    The connection is kept open after the block exits so the next query on the same
    thread can reuse it. It is dropped (and reopened next time) on expiry, when found
    closed, on LRU eviction, or when the block raises a connection-level error.
    """
    key = _config_key(config)
    cache = _cache()
    now = monotonic()

    entry = cache.get(key)
    if entry is not None and _is_reusable(entry, now):
        cache.move_to_end(key)
        connection = entry.connection
        SNOWFLAKE_CONNECTION_CACHE_TOTAL.labels(result="reused").inc()
    else:
        if entry is not None:
            _evict(key)
        # Drive the implementation's own connect() contextmanager but keep it entered, so
        # we reuse its auth/keypair logic without closing the connection on block exit.
        cm = implementation.connect(config)
        connection = cm.__enter__()
        # A fresh key lands at the tail (LRU-newest) already, so no move_to_end needed here.
        cache[key] = _Entry(cm=cm, connection=connection, opened_at=now)
        SNOWFLAKE_CONNECTION_CACHE_TOTAL.labels(result="opened").inc()
        while len(cache) > SNOWFLAKE_CONNECTION_CACHE_MAX_PER_THREAD:
            _old_key, old_entry = cache.popitem(last=False)
            _close_entry(old_entry)

    try:
        yield connection
    except _connection_level_error_types():
        _evict(key)
        raise


def clear_thread_local_snowflake_connections() -> None:
    """Close and drop every cached connection for the current thread (tests, shutdown)."""
    cache = _cache()
    for entry in list(cache.values()):
        _close_entry(entry)
    cache.clear()
