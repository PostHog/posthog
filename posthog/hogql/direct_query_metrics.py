"""Prometheus metrics for direct-query execution.

Direct queries run against a customer's own database over the network, so their
latency and failure modes are independent of ClickHouse. These low-cardinality
metrics make per-dialect error and timeout rates observable without leaking
team-specific labels. The instrumentation is dialect-agnostic (the dialect is a
label); the Snowflake adapter is the only caller today.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter
from typing import Literal

from prometheus_client import (
    Counter as PromCounter,
    Histogram,
)

DirectQueryDialect = Literal["postgres", "mysql", "snowflake"]
DirectQueryStatus = Literal["success", "error"]

DIRECT_QUERY_TOTAL = PromCounter(
    "hogql_direct_query_total",
    "Direct external-database query executions by dialect and result.",
    labelnames=["dialect", "status"],
)
DIRECT_QUERY_DURATION_SECONDS = Histogram(
    "hogql_direct_query_duration_seconds",
    "Wall-clock duration of a direct external-database query execution.",
    labelnames=["dialect"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0),
)
DIRECT_QUERY_ROW_CAP_EXCEEDED_TOTAL = PromCounter(
    "hogql_direct_query_row_cap_exceeded_total",
    "Direct queries rejected for exceeding the result-row cap, by dialect.",
    labelnames=["dialect"],
)
SNOWFLAKE_CONNECTION_CACHE_TOTAL = PromCounter(
    "hogql_snowflake_connection_cache_total",
    "Direct Snowflake connection-cache lookups by result (reused vs opened).",
    labelnames=["result"],
)


@contextmanager
def observe_direct_query(dialect: DirectQueryDialect) -> Iterator[None]:
    """Record duration and success/error outcome for one direct-query execution."""
    started = perf_counter()
    status: DirectQueryStatus = "success"
    try:
        yield
    except Exception:
        status = "error"
        raise
    finally:
        DIRECT_QUERY_DURATION_SECONDS.labels(dialect=dialect).observe(perf_counter() - started)
        DIRECT_QUERY_TOTAL.labels(dialect=dialect, status=status).inc()
