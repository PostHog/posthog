"""Prometheus metrics of the integrations SDK. See "Metrics" in README.md.

The accessor operations use the `instrumented` decorator, so one place counts every operation. The sync
and async forms count the same operation, because each async form calls its sync form. No label holds a
team id, an integration id, an external id or a config value.

Metrics must never break an SDK call. Every step that reads a label or writes a sample catches its
errors and logs them.
"""

import time
import functools
from collections.abc import Callable
from typing import TYPE_CHECKING, Literal, ParamSpec, TypeVar

import structlog
from prometheus_client import Counter, Histogram

from posthog.dataclasses import frozen
from posthog.integrations.contracts import (
    IntegrationConflict,
    IntegrationInUse,
    IntegrationNotFound,
    UnsupportedAuthType,
    UnsupportedIntegrationFilter,
)
from posthog.integrations.enums import AuthType

if TYPE_CHECKING:
    from posthog.integrations.accessors import IntegrationReader

logger = structlog.get_logger(__name__)

P = ParamSpec("P")
R = TypeVar("R")

RowsMeasure = Literal["none", "returned", "written"]
TokenRefreshResult = Literal["fresh", "refreshed", "stale_token", "error"]

MULTI_KIND = "multi"
ANY_AUTH_TYPE = "any"

_OPERATIONS = Counter(
    "integrations_sdk_operations_total",
    "Number of integrations SDK operations, by accessor, kind, auth type and outcome.",
    labelnames=["operation", "accessor", "kind", "auth_type", "outcome"],
)
_DURATION = Histogram(
    "integrations_sdk_operation_duration_seconds",
    "Time of one integrations SDK operation.",
    labelnames=["operation", "accessor", "outcome"],
    buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)
_ROWS_RETURNED = Histogram(
    "integrations_sdk_rows_returned",
    "Number of rows that a list-shaped integrations SDK read returned.",
    labelnames=["operation", "accessor"],
    buckets=(0, 1, 2, 5, 10, 50, 100, 500, 1000),
)
_ROWS_WRITTEN = Counter(
    "integrations_sdk_rows_written_total",
    "Number of rows that a cross-team integrations SDK write changed or deleted.",
    labelnames=["operation", "kind"],
)
_TOKEN_REFRESH = Counter(
    "integrations_sdk_token_refresh_total",
    "Number of integrations SDK access token refresh calls, by result.",
    labelnames=["kind", "result"],
)

_OUTCOMES: tuple[tuple[type[Exception], str], ...] = (
    (IntegrationNotFound, "not_found"),
    (IntegrationConflict, "conflict"),
    (IntegrationInUse, "in_use"),
    (UnsupportedIntegrationFilter, "unsupported_filter"),
    (UnsupportedAuthType, "unsupported_auth_type"),
)


def outcome_of(error: Exception) -> str:
    for error_type, outcome in _OUTCOMES:
        if isinstance(error, error_type):
            return outcome
    return "error"


@frozen
class AccessorLabels:
    accessor: str
    kind: str
    auth_type: str


def accessor_labels(reader: "IntegrationReader") -> AccessorLabels:
    """The `accessor`, `kind` and `auth_type` labels of a reader, from its scope."""
    kinds = reader._kinds
    if reader._source_rows.value == "only":
        accessor = "source"
    elif kinds is None:
        accessor = "any"
    elif len(kinds) == 1:
        accessor = "named"
    else:
        accessor = "kinds"
    kind = next(iter(kinds)) if kinds is not None and len(kinds) == 1 else MULTI_KIND
    auth_type = reader._auth_type.value if isinstance(reader._auth_type, AuthType) else ANY_AUTH_TYPE
    return AccessorLabels(accessor=accessor, kind=kind, auth_type=auth_type)


def _row_count(result: object) -> int | None:
    if isinstance(result, bool):
        return None
    if isinstance(result, int):
        return result
    try:
        return len(result)  # type: ignore[arg-type]
    except TypeError:
        return None


def _record(
    reader: "IntegrationReader",
    operation: str,
    started: float,
    outcome: str,
    rows: RowsMeasure,
    result: object,
) -> None:
    try:
        labels = accessor_labels(reader)
        accessor, kind, auth_type = labels.accessor, labels.kind, labels.auth_type
        _OPERATIONS.labels(operation, accessor, kind, auth_type, outcome).inc()
        _DURATION.labels(operation, accessor, outcome).observe(time.perf_counter() - started)
        if outcome != "ok" or rows == "none":
            return
        count = _row_count(result)
        if count is None:
            return
        if rows == "returned":
            _ROWS_RETURNED.labels(operation, accessor).observe(count)
        else:
            _ROWS_WRITTEN.labels(operation, kind).inc(count)
    except Exception:
        logger.warning("integrations_sdk_metrics_failed", operation=operation, exc_info=True)


def instrumented(operation: str, *, rows: RowsMeasure = "none") -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Count and time an accessor method. `rows` also records the size of the result: how many rows a
    read returned, or how many rows a cross-team write changed."""

    def decorator(method: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(method)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            started = time.perf_counter()
            reader = args[0]
            try:
                result = method(*args, **kwargs)
            except Exception as error:
                _record(reader, operation, started, outcome_of(error), rows, None)  # type: ignore[arg-type]
                raise
            _record(reader, operation, started, "ok", rows, result)  # type: ignore[arg-type]
            return result

        return wrapper

    return decorator


def record_token_refresh(kind: str, result: TokenRefreshResult) -> None:
    try:
        _TOKEN_REFRESH.labels(kind, result).inc()
    except Exception:
        logger.warning("integrations_sdk_metrics_failed", operation="refresh_access_token", exc_info=True)
