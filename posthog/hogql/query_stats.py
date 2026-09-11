"""Add up the rows and time ClickHouse spent on one query request.

One request can run several ClickHouse queries (a trends insight runs one per series). The runner
opens ``query_stats_scope()`` around the run, ``sync_execute`` calls ``record()`` after each query,
and the runner reads the totals at the end. With no scope open, ``record()`` does nothing.

A new thread does not see the scope its parent opened, so a runner that runs its queries in threads
reads the totals with ``get_active()`` and installs them in each thread with ``use()``.
"""

from __future__ import annotations

import threading
import contextlib
from collections.abc import Iterator
from contextvars import ContextVar
from dataclasses import field
from typing import TYPE_CHECKING

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from posthog.hogql import ast
    from posthog.hogql.context import HogQLContext


@frozen
class RecordedExecution:
    """One ClickHouse execution inside a scope, held by reference for the job to explain later."""

    tree: ast.Expr
    context: HogQLContext
    rows_read: int


@frozen(frozen=False)
class QueryStats:
    """The totals for one request."""

    rows_read: int = 0
    duration_ms: float = 0.0
    # Runners that record from several threads share one QueryStats.
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)
    # References only, filled by the executor, so the job can explain each execution without rerunning it.
    executions: list[RecordedExecution] = field(default_factory=list, repr=False, compare=False)

    def add(self, *, rows_read: int, duration_ms: float) -> None:
        with self.lock:
            self.rows_read += rows_read
            self.duration_ms += duration_ms

    def record_execution(self, *, tree: ast.Expr, context: HogQLContext, rows_read: int) -> None:
        with self.lock:
            self.executions.append(RecordedExecution(tree=tree, context=context, rows_read=rows_read))


_accumulator: ContextVar[QueryStats | None] = ContextVar("query_stats_accumulator", default=None)


@contextlib.contextmanager
def query_stats_scope() -> Iterator[QueryStats]:
    """Add up every ClickHouse query run inside this block. Nested in another scope, it adds to that one."""
    outer = _accumulator.get()
    if outer is not None:
        yield outer
        return
    stats = QueryStats()
    token = _accumulator.set(stats)
    try:
        yield stats
    finally:
        _accumulator.reset(token)


def get_active() -> QueryStats | None:
    """The totals of the open scope, or None when none is open."""
    return _accumulator.get()


@contextlib.contextmanager
def use(stats: QueryStats | None) -> Iterator[None]:
    """Record into ``stats`` inside this block, for a thread that does not see its parent's scope.
    Does nothing for None."""
    if stats is None:
        yield
        return
    token = _accumulator.set(stats)
    try:
        yield
    finally:
        _accumulator.reset(token)


def record(*, rows_read: int, duration_ms: float) -> None:
    """Add one ClickHouse query to the open scope. Does nothing without one."""
    stats = _accumulator.get()
    if stats is None:
        return
    stats.add(rows_read=rows_read, duration_ms=duration_ms)
