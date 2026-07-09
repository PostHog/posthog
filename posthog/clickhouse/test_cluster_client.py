"""Client for the autoresearch test ClickHouse cluster.

Deliberately separate from the main-cluster pooled clients: this connects with the
restricted ``autoresearch`` user, whose server-side grants (read-only, query-log
tables only) are the enforcement layer. Fails closed when unconfigured.
"""

import uuid
import dataclasses

from django.conf import settings

from clickhouse_driver import Client as SyncClient

QUERY_SETTINGS: dict[str, int] = {
    # Defense in depth on top of the restricted user's server-side grants.
    "readonly": 1,
    "max_execution_time": 60,
    "max_result_rows": 10_000,
    "result_overflow_mode": 1,  # break: truncate instead of erroring at the cap
}


class TestClusterNotConfigured(Exception):
    pass


class TestClusterQueryError(Exception):
    pass


@dataclasses.dataclass
class TestClusterResult:
    result: list[list[object]]
    query_id: str | None
    elapsed_ms: float | None
    rows_read: int | None
    bytes_read: int | None


def _canonicalize(value: object) -> object:
    """JSON-safe positional values: UUIDs/datetimes/etc. become strings."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def execute_on_test_cluster(sql: str) -> TestClusterResult:
    if not settings.CLICKHOUSE_TEST_CLUSTER_HOST:
        raise TestClusterNotConfigured("CLICKHOUSE_TEST_CLUSTER_HOST is not set")
    query_id = f"pulse-autoresearch-{uuid.uuid4()}"
    client = SyncClient(
        host=settings.CLICKHOUSE_TEST_CLUSTER_HOST,
        database=settings.CLICKHOUSE_TEST_CLUSTER_DATABASE or "default",
        user=settings.CLICKHOUSE_TEST_CLUSTER_USER,
        password=settings.CLICKHOUSE_TEST_CLUSTER_PASSWORD,
        secure=settings.CLICKHOUSE_TEST_CLUSTER_SECURE,
        ca_certs=settings.CLICKHOUSE_TEST_CLUSTER_CA,
        verify=settings.CLICKHOUSE_TEST_CLUSTER_VERIFY,
        settings=dict(QUERY_SETTINGS),
    )
    try:
        rows = client.execute(sql, query_id=query_id)
    except Exception as err:  # clickhouse_driver raises driver-specific ServerException etc.
        raise TestClusterQueryError(str(err)) from err
    finally:
        last_query = getattr(client, "last_query", None)
        client.disconnect()
    elapsed_ms: float | None = None
    rows_read: int | None = None
    bytes_read: int | None = None
    if last_query is not None:
        elapsed = getattr(last_query, "elapsed", None)
        elapsed_ms = elapsed * 1000 if elapsed is not None else None
        progress = getattr(last_query, "progress", None)
        if progress is not None:
            rows_read = getattr(progress, "rows", None)
            bytes_read = getattr(progress, "bytes", None)
    return TestClusterResult(
        result=[[_canonicalize(v) for v in row] for row in rows],
        query_id=query_id,
        elapsed_ms=elapsed_ms,
        rows_read=rows_read,
        bytes_read=bytes_read,
    )
