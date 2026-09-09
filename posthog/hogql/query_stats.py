"""Request-scoped accumulator for what ClickHouse read while serving one query response.

``sync_execute`` records the driver's progress for every execution inside the active scope, and the
query runner reads the totals to build the response's ``query_scan`` summary. One response can run
several ClickHouse queries (a trends runner runs one per series), so the totals are sums.

Nesting works the way ``posthog.hogql.warehouse_warnings`` does: an inner scope yields the outer
accumulator and does not reset it, so a runner that calls another runner contributes to the totals
the outermost scope reports.

The query runner installs the scope only for a team whose query scan flag is on. With no scope
``record`` does nothing, so a team with the flag off pays nothing.

A new thread starts with an empty context, so a runner that fans its series out over raw threads
takes the accumulator with ``get_active`` and installs it in the worker with ``use``. Without that
hand-off the worker records nothing and the response under-reports what ClickHouse read.
"""

from __future__ import annotations

import threading
import contextlib
from collections.abc import Iterator
from contextvars import ContextVar, Token
from dataclasses import field

from posthog.dataclasses import frozen


@frozen(frozen=False)
class QueryStats:
    """Totals for one scope. Mutable because every execution inside the scope adds to it."""

    rows_read: int = 0
    bytes_read: int = 0
    duration_ms: float = 0.0
    # Worker threads add into the one scope they were handed, and `+=` is not atomic.
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def add(self, *, rows_read: int, bytes_read: int, duration_ms: float) -> None:
        with self.lock:
            self.rows_read += rows_read
            self.bytes_read += bytes_read
            self.duration_ms += duration_ms


_accumulator: ContextVar[QueryStats | None] = ContextVar("query_stats_accumulator", default=None)


def _install() -> tuple[QueryStats, Token[QueryStats | None] | None]:
    """Return the accumulator to use and the token to reset, which is None inside an outer scope."""
    current = _accumulator.get()
    if current is not None:
        return current, None
    fresh = QueryStats()
    return fresh, _accumulator.set(fresh)


@contextlib.contextmanager
def query_stats_scope() -> Iterator[QueryStats]:
    """Collect what ClickHouse reads inside this block. Always safe to nest."""
    stats, token = _install()
    try:
        yield stats
    finally:
        if token is not None:
            _accumulator.reset(token)


def get_active() -> QueryStats | None:
    """The accumulator of the current context, to hand to a thread that does not inherit it."""
    return _accumulator.get()


@contextlib.contextmanager
def use(stats: QueryStats | None) -> Iterator[None]:
    """Install an accumulator taken from another thread. Does nothing when there is none."""
    if stats is None:
        yield
        return
    token = _accumulator.set(stats)
    try:
        yield
    finally:
        _accumulator.reset(token)


def record(*, rows_read: int, bytes_read: int, duration_ms: float) -> None:
    """Add one ClickHouse execution to the active accumulator. Does nothing without a scope."""
    stats = _accumulator.get()
    if stats is None:
        return
    stats.add(rows_read=rows_read, bytes_read=bytes_read, duration_ms=duration_ms)
