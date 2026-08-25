"""Cross-cutting accumulator for data warehouse sync warnings emitted during query execution.

Every HogQL execution that resolves a warehouse table writes warnings into the active accumulator
via ``record_warnings``. The query runner installs a fresh accumulator at the top of
``_execute_and_cache_blocking`` and attaches its contents to the response at the end — so a
TrendsQueryRunner backed by warehouse tables ends up with the same ``warnings`` field as a raw
HogQL query, without each runner having to copy them through by hand.

Composite runners (one runner calling another internally) don't re-install: the inner runner sees
the parent's accumulator and contributes to it. The outermost runner is the one that owns the
install/reset and the final response attachment.

Pattern mirrors ``posthog.clickhouse.query_tagging.tags_context`` — same ContextVar lifecycle, same
asgiref-compatible propagation across ``database_sync_to_async`` boundaries.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterable, Iterator
from contextvars import ContextVar, Token
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from posthog.schema import DataWarehouseSyncWarning


WarningKey = tuple[str, str]

_accumulator: ContextVar[dict[WarningKey, DataWarehouseSyncWarning] | None] = ContextVar(
    "data_warehouse_warnings_accumulator",
    default=None,
)

# Rides the same lifecycle as the warnings accumulator: a composite runner's inner HogQL executions
# each report whether the printer floored an events scan, and the outermost runner attaches the
# union to its response.
_events_retention_applied: ContextVar[list[bool] | None] = ContextVar(
    "events_retention_applied_accumulator",
    default=None,
)


def install_accumulator() -> tuple[dict[WarningKey, DataWarehouseSyncWarning], Token | None]:
    """Install a fresh accumulator if none is currently active.

    Returns ``(accumulator, token)``. ``token`` is ``None`` when an outer scope already installed
    one — in that case the caller should NOT reset on exit. The outer scope owns the lifecycle.
    """
    current = _accumulator.get()
    if current is not None:
        return current, None
    fresh: dict[WarningKey, DataWarehouseSyncWarning] = {}
    token = _accumulator.set(fresh)
    _events_retention_applied.set([])
    return fresh, token


def reset_accumulator(token: Token | None) -> None:
    if token is not None:
        _accumulator.reset(token)
        _events_retention_applied.set(None)


def record_events_retention_applied() -> None:
    """Note that the current execution floored an events scan. No-op if no scope is installed."""
    applied = _events_retention_applied.get()
    if applied is not None:
        applied.append(True)


def events_retention_applied_in_scope() -> bool:
    return bool(_events_retention_applied.get())


def record_warnings(warnings: Iterable[DataWarehouseSyncWarning]) -> None:
    """Merge `warnings` into the active accumulator. No-op if none is installed."""
    accumulator = _accumulator.get()
    if accumulator is None:
        return
    for warning in warnings:
        accumulator[(warning.table_name, warning.schema_name)] = warning


@contextlib.contextmanager
def accumulator_scope() -> Iterator[dict[WarningKey, DataWarehouseSyncWarning]]:
    """Context manager: install an accumulator on entry, reset on exit.

    If a parent scope already installed one, this yields the same dict and does not reset on exit —
    the outer scope owns the lifecycle. Always safe to nest.
    """
    accumulator, token = install_accumulator()
    try:
        yield accumulator
    finally:
        reset_accumulator(token)
