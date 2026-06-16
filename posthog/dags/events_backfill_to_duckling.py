"""
Dagster job to backfill ClickHouse events to customer-specific ducklings.

This job exports events from ClickHouse's `posthog.events` table to customer S3 buckets
as Parquet files, then registers those files with their DuckLake catalog.

This job targets individual customer "ducklings" - isolated DuckLake instances with their
own RDS catalog and S3 bucket.

Architecture:
    DuckLakeCatalog (Django model)
        │ lookup by team_id → organization_id
        ▼
    ClickHouse (events table)
        │ export via s3() - bucket policy allows ClickHouse EC2 role
        ▼
    Duckling S3 Bucket (parquet files)
        │ register via ducklake_add_data_files
        ▼
    Duckling RDS Catalog (PostgreSQL)

IAM Access:
    - ClickHouse EC2 role is allowed in duckling bucket policy (direct S3 access)
    - Dagster IRSA role can assume duckling cross-account roles (for DuckDB registration)

Partition Strategy:
    DynamicPartitionsDefinition with composite keys: {team_id}_{date}
    - team_id maps to duckling via DuckLakeCatalog
    - date is the partition date (YYYY-MM-DD)
"""

import os
import json
import time
import calendar
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

from django.utils import timezone

import psycopg
import structlog
from clickhouse_driver import Client
from clickhouse_driver.errors import Error as ClickHouseError
from dagster import (
    AssetExecutionContext,
    Config,
    DagsterRunStatus,
    DefaultSensorStatus,
    DynamicPartitionsDefinition,
    RunRequest,
    RunsFilter,
    SensorEvaluationContext,
    SensorResult,
    asset,
    define_asset_job,
    sensor,
)
from psycopg import sql as psql
from tenacity import retry, retry_if_exception_type, stop_after_attempt, stop_after_delay, wait_exponential, wait_fixed

from posthog.clickhouse.client.connection import NodeRole, Workload
from posthog.clickhouse.cluster import ClickhouseCluster, get_cluster
from posthog.clickhouse.query_tagging import tags_context
from posthog.cloud_utils import is_cloud
from posthog.dags.common import JobOwners, dagster_tags, settings_with_log_comment
from posthog.ducklake.client import make_duckgres_conninfo
from posthog.ducklake.common import get_duckgres_server_for_organization, get_ducklake_catalog_by_team_org
from posthog.ducklake.models import DuckLakeBackfill, DuckLakeCatalog

logger = structlog.get_logger(__name__)

# Catalog alias used by every duckgres connection. Duckgres auto-attaches the
# DuckLake catalog under this name on session start (see duckgres server.go),
# so the DAG can hardcode it everywhere instead of threading a config value.
DUCKLAKE_ALIAS = "ducklake"

MAX_RETRY_ATTEMPTS = 3

ONE_HOUR_IN_SECONDS = 60 * 60
ONE_GB_IN_BYTES = 1024 * 1024 * 1024

DEFAULT_CLICKHOUSE_SETTINGS = {
    "max_execution_time": 4 * ONE_HOUR_IN_SECONDS,
    "max_memory_usage": 50 * ONE_GB_IN_BYTES,
    "distributed_aggregation_memory_efficient": "1",
}

# Duckgres connect timeout bounds the TCP+TLS handshake only. A backfill
# connection may have to wait for duckgres to spin up a fresh worker (a cold
# worker can require provisioning a new node, which takes minutes), so the
# handshake budget is generous and `_connect_duckgres` retries with backoff.
# Must exceed the binding duckgres server-side wait, which is the OUTER
# workerQueueTimeout (5m) — not warmAcquireTimeout (4m). On a warm-pool miss the
# CP blocks the connect server-side waiting for a colocated worker (which may need
# a cold node) instead of bouncing us with "no warm worker available"; that whole
# block is bounded by workerQueueTimeout. 360s gives margin over the 300s server
# block + TLS/handshake. Ladder: warmAcquire 4m < workerQueueTimeout 5m < 360s.
#
# We deliberately set NO statement_timeout. Duckling backfills are long-running
# OLAP statements (a partition DELETE / file registration over an event-day) —
# running long is the whole point of an OLAP engine, so capping them at 5 minutes
# (or any value) is wrong. A worker that disappears mid-statement is handled by
# reconnect-and-retry (`_DuckgresSession`), not by pre-emptively killing the query.
DUCKGRES_CONNECT_TIMEOUT = 360  # seconds

# Worker-profile control. When enabled, a backfill connection asks duckgres for a
# small COLOCATED (bin-packed) worker via libpq startup options, so it bursts into
# a right-sized pod instead of contending for the big exclusive shared workers
# (270GB / 46-thread). A metadata-only DuckLake register/DELETE has no use for
# that much worker, and grabbing one made the backfill both wasteful and fragile —
# a single shared worker dying mid-statement took out the partition. The server
# gate (DUCKGRES_K8S_ALLOW_CLIENT_WORKER_PROFILE) is on in prod, so this defaults
# ON; set DUCKGRES_WORKER_PROFILE_ENABLED=0 to put a deployment back on the big
# exclusive workers.
#
# Evaluated once at process startup, not per connection/partition — toggling it
# (including rollback) requires redeploying the Dagster code location so the
# process restarts and re-reads the env, not just unsetting the variable.
DUCKGRES_WORKER_PROFILE_ENABLED = os.environ.get("DUCKGRES_WORKER_PROFILE_ENABLED", "true").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
# Colocated worker size for the metadata-only DuckLake register/DELETE path.
DUCKGRES_BACKFILL_COLOCATE_CPU = "4"
DUCKGRES_BACKFILL_COLOCATE_MEMORY = "16Gi"


def _duckgres_backfill_options() -> str:
    """libpq startup `options` for a backfill connection.

    When the worker-profile feature is enabled (the default), requests a small
    colocated worker shape. Returns a single space-joined `-c key=value` string —
    psycopg forwards it as the startup `options` parameter, which duckgres parses
    to size/schedule the worker. No statement_timeout is set (see
    DUCKGRES_CONNECT_TIMEOUT note above). Returns "" when the profile is disabled,
    so the connection falls back to the default exclusive worker with no extra
    startup options.
    """
    if not DUCKGRES_WORKER_PROFILE_ENABLED:
        return ""
    return " ".join(
        [
            "-c duckgres.colocate=true",
            f"-c duckgres.worker_cpu={DUCKGRES_BACKFILL_COLOCATE_CPU}",
            f"-c duckgres.worker_memory={DUCKGRES_BACKFILL_COLOCATE_MEMORY}",
        ]
    )


@retry(
    stop=stop_after_attempt(3),
    wait=wait_fixed(5),
    retry=retry_if_exception_type((TimeoutError, OSError)),
    reraise=True,
)
def _get_cluster() -> ClickhouseCluster:
    """get_cluster() with retry for transient bootstrap timeouts.

    Retries the cluster discovery query only — does not affect subsequent
    per-host query execution, avoiding stacked retries with Tenacity
    export retry decorators.
    """
    return get_cluster()


@retry(
    # The duckgres CP absorbs a warm-pool miss by blocking the connect itself for
    # up to the outer workerQueueTimeout (5m) waiting for a colocated worker — so a
    # single attempt can run the full connect_timeout (360s). The retry budget here
    # is the BACKSTOP for fast failures (network blip, CP pod rolled mid-handshake,
    # or the CP giving up after its block): the delay cap must exceed one full
    # attempt so a second one can actually run, hence 780s (~2 attempts) rather
    # than 360s (which a single 360s attempt would exhaust, making retries a no-op).
    # This guards only the initial connect; a worker that drops mid-statement is
    # handled separately by _DuckgresSession's reconnect-and-retry.
    stop=stop_after_delay(780) | stop_after_attempt(12),
    wait=wait_exponential(multiplier=1, min=5, max=60),
    retry=retry_if_exception_type((psycopg.OperationalError, OSError)),
    reraise=True,
)
def _connect_duckgres(catalog: DuckLakeCatalog) -> psycopg.Connection[Any]:
    """Open a psycopg connection to the org's duckgres server.

    Each org runs its own duckgres process on the duckling side; it auto-attaches
    the DuckLake catalog as `ducklake` on connection. The Dagster image is no
    longer responsible for choosing a duckdb/ducklake version — duckgres is.

    Cross-account S3 credentials are configured server-side via IRSA on the
    duckling, so the DAG no longer calls `configure_cross_account_connection`.

    Retries with backoff: a cold duckgres worker can take longer than a single
    connect_timeout to become ready (worker pod may need a fresh node), so we
    retry the connect rather than failing the partition on the first timeout.
    `psycopg.errors.ConnectionTimeout` is an `OperationalError` subclass.
    """
    if catalog.team_id is None:
        raise ValueError(
            f"DuckLakeCatalog team_id is None for org={catalog.organization_id} — "
            "cannot route to a duckgres instance without a team identifier."
        )

    conninfo = make_duckgres_conninfo(
        catalog.team_id,
        organization_id=str(catalog.organization_id),
    )
    return psycopg.connect(
        conninfo,
        autocommit=True,
        connect_timeout=DUCKGRES_CONNECT_TIMEOUT,
        options=_duckgres_backfill_options(),
    )


_CONNECTION_DROPPED_SQLSTATES = {
    "57P01",  # admin_shutdown
    "57P02",  # crash_shutdown
    "57P03",  # cannot_connect_now
}

# Transport/connection-loss phrases ONLY. Deliberately NOT "flight execute":
# duckgres prefixes essentially every worker-side SQL error with "flight execute"
# (server/flightclient/flight_executor.go), so matching it would treat genuine,
# non-retryable engine errors as recoverable — most dangerously a worker OOM
# ("Out of Memory Error", mapped to XX000 → psycopg.InternalError), which is more
# likely now that backfills run on small 16Gi colocated workers, and must NOT be
# retried 4x. A real transport drop still carries one of these gRPC/libpq phrases
# (e.g. the observed "flight execute update: rpc error: code = Unavailable desc =
# error reading from server: EOF" matches on "code = unavailable" +
# "error reading from server"), so dropping the prefix marker loses no coverage.
_CONNECTION_DROPPED_MARKERS = (
    "broken pipe",
    "code = unavailable",
    "code=unavailable",
    "connection refused",
    "connection reset",
    "connection to server was closed",
    "connection to server was lost",
    "consuming input failed",
    "eof detected",
    "error reading from server",
    "server closed the connection",
    "terminating connection due to administrator command",
    "transport:",
)


def _connection_dropped(exc: BaseException) -> bool:
    """True when `exc` means the duckgres worker/connection went away mid-statement
    (worker pod died, control plane lost the Flight stream), as opposed to a
    SQL/logic error. Recoverable by reconnecting to a fresh worker and replaying
    the (idempotent, transactional) duckgres metadata op.
    """
    msg = str(exc).lower()
    if isinstance(exc, psycopg.errors.ConnectionException):
        return True

    sqlstate = getattr(exc, "sqlstate", None)
    if isinstance(sqlstate, str) and (sqlstate.startswith("08") or sqlstate in _CONNECTION_DROPPED_SQLSTATES):
        return True

    # psycopg.OperationalError also covers permanent operational failures (for
    # example SQLSTATE class 53 resource exhaustion), so only retry the message
    # shapes that are clearly connection/transport loss.
    if isinstance(exc, psycopg.OperationalError):
        return any(marker in msg for marker in _CONNECTION_DROPPED_MARKERS)

    # The control plane surfaces a worker-side Flight RPC failure — e.g. the
    # worker pod dying mid-DELETE — back through the PG wire as InternalError
    # wrapping transport-specific gRPC text ("code = Unavailable", "connection
    # reset by peer", "transport: ...", "error reading from server").
    if isinstance(exc, psycopg.InternalError):
        return any(marker in msg for marker in _CONNECTION_DROPPED_MARKERS)
    return False


class _DuckgresSession:
    """A duckgres connection that transparently reconnects to a fresh worker when
    the current worker drops mid-statement.

    A worker pod can disappear under a long-running statement for many reasons
    (node consolidation, a control-plane rollout, an engine crash); the backfill
    should survive that by re-acquiring a worker, not fail the whole partition on
    the first blip. run() replays the op on a fresh connection when that happens.

    Replay safety is the caller's responsibility — an op handed to run() MUST be
    idempotent, because a worker can die in the at-least-once window (it COMMITTED
    the DuckLake transaction, then the connection dropped before the client saw
    the ack), in which case the replay re-runs an already-applied op. The backfill
    ops satisfy this:
      - the ranged partition DELETE is idempotent (re-deleting an emptied range
        is a 0-row no-op);
      - CREATE TABLE/SCHEMA IF NOT EXISTS, SET PARTITIONED BY, and the read-only
        schema validation are idempotent;
      - file registration via `ducklake_add_data_files` is NOT idempotent on its
        own (it APPENDS a data-file entry with no dedup-by-path, so a replay would
        double-register the file → duplicate rows). The register ops are therefore
        wrapped so the replay unit is "DELETE the day's range, then add the file":
        re-running that reproduces exactly the day's file regardless of where the
        prior attempt died. Never hand a bare `ducklake_add_data_files` to run().
    """

    MAX_ATTEMPTS = 4

    def __init__(self, context: AssetExecutionContext, catalog: DuckLakeCatalog) -> None:
        self._context = context
        self._catalog = catalog
        self._conn = _connect_duckgres(catalog)

    @property
    def conn(self) -> psycopg.Connection[Any]:
        return self._conn

    def run(self, what: str, op: Callable[[psycopg.Connection[Any]], Any]) -> Any:
        """Run `op(conn)`, reconnecting to a fresh worker and retrying if the
        worker/connection drops mid-statement. Non-connection errors propagate
        immediately (no retry); the last connection error is re-raised once the
        attempt budget is exhausted.
        """
        last_exc: Exception | None = None
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            try:
                return op(self._conn)
            except Exception as exc:
                if not _connection_dropped(exc):
                    raise
                last_exc = exc
                if attempt == self.MAX_ATTEMPTS:
                    break
                self._context.log.warning(
                    f"duckgres worker/connection dropped during {what} "
                    f"(attempt {attempt}/{self.MAX_ATTEMPTS}); reconnecting to a fresh worker: {exc}"
                )
                logger.warning(
                    "duckling_duckgres_reconnect",
                    what=what,
                    attempt=attempt,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                self._reconnect()
                time.sleep(min(2**attempt, 30))
        assert last_exc is not None  # only reached after a connection-drop break
        raise last_exc

    def _reconnect(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
        self._conn = _connect_duckgres(self._catalog)

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


# Columns to export from ClickHouse events table for duckling backfill.
# ClickHouse exports DateTime64 as TIMESTAMP WITH TIME ZONE in Parquet.
# DuckLake table uses TIMESTAMPTZ to match this format.
EVENTS_COLUMNS = """
    toString(uuid) as uuid,
    event,
    properties,
    timestamp,
    team_id,
    toInt64(team_id) as project_id,
    distinct_id,
    elements_chain,
    created_at,
    toString(person_id) as person_id,
    person_created_at,
    person_properties,
    group0_properties,
    group1_properties,
    group2_properties,
    group3_properties,
    group4_properties,
    group0_created_at,
    group1_created_at,
    group2_created_at,
    group3_created_at,
    group4_created_at,
    person_mode,
    historical_migration,
    now64(6) as _inserted_at
"""

# Expected columns in the duckling's events table for schema validation
EXPECTED_DUCKLAKE_COLUMNS = {
    "uuid",
    "event",
    "properties",
    "timestamp",
    "team_id",
    "project_id",
    "distinct_id",
    "elements_chain",
    "created_at",
    "person_id",
    "person_created_at",
    "person_properties",
    "group0_properties",
    "group1_properties",
    "group2_properties",
    "group3_properties",
    "group4_properties",
    "group0_created_at",
    "group1_created_at",
    "group2_created_at",
    "group3_created_at",
    "group4_created_at",
    "person_mode",
    "historical_migration",
    "_inserted_at",
}

BACKFILL_EVENTS_S3_PREFIX = "backfill/events"
BACKFILL_PERSONS_S3_PREFIX = "backfill/persons"

# Shared concurrency key across events + persons backfills. Each duckling
# connection spins up a duckgres worker, and the per-org worker pool is capped
# (maxWorkers in the duckgres chart) and shared with product queries — so the
# two backfills must draw from ONE combined limit, not two independent ones.
# The limit itself is a Dagster Cloud deployment setting (charts repo); this tag
# is just the key it targets. Per-product keys are kept for optional finer limits.
DUCKLING_BACKFILL_CONCURRENCY_TAG = {
    "duckling_backfill_concurrency": "duckling_v1",
}

EVENTS_CONCURRENCY_TAG = {
    "duckling_events_backfill_concurrency": "duckling_events_v1",
    **DUCKLING_BACKFILL_CONCURRENCY_TAG,
}

PERSONS_CONCURRENCY_TAG = {
    "duckling_persons_backfill_concurrency": "duckling_persons_v1",
    **DUCKLING_BACKFILL_CONCURRENCY_TAG,
}

# Persons columns for export - joined with person_distinct_id2 to include distinct_ids
# This creates one row per distinct_id, with the person's properties denormalized
# ClickHouse exports DateTime64 as TIMESTAMP WITH TIME ZONE in Parquet.
# DuckLake table uses TIMESTAMPTZ to match this format.
# Note: _timestamp is DateTime (not DateTime64), so we convert it to DateTime64 for consistency.
# Note: is_identified is Int8 in ClickHouse, cast to Bool for proper BOOLEAN type in Parquet.
PERSONS_COLUMNS = """
    pd.team_id AS team_id,
    pd.distinct_id AS distinct_id,
    toString(p.id) AS id,
    p.properties AS properties,
    p.created_at AS created_at,
    toBool(p.is_identified) AS is_identified,
    pd.version AS person_distinct_id_version,
    p.version AS person_version,
    toDateTime64(p._timestamp, 6) AS _timestamp,
    now64(6) AS _inserted_at
"""

# Expected columns in the duckling's persons table for schema validation
EXPECTED_DUCKLAKE_PERSONS_COLUMNS = {
    "team_id",
    "distinct_id",
    "id",
    "properties",
    "created_at",
    "is_identified",
    "person_distinct_id_version",
    "person_version",
    "_timestamp",
    "_inserted_at",
}

duckling_events_partitions_def = DynamicPartitionsDefinition(name="duckling_events_backfill")
duckling_persons_partitions_def = DynamicPartitionsDefinition(name="duckling_persons_backfill")

# SQL for creating the events table in DuckLake if it doesn't exist
# Uses TIMESTAMPTZ because ClickHouse exports DateTime64 as TIMESTAMP WITH TIME ZONE in Parquet.
EVENTS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS {catalog}.posthog.events (
    uuid VARCHAR,
    event VARCHAR,
    properties VARCHAR,
    timestamp TIMESTAMPTZ,
    team_id BIGINT,
    project_id BIGINT,
    distinct_id VARCHAR,
    elements_chain VARCHAR,
    created_at TIMESTAMPTZ,
    person_id VARCHAR,
    person_created_at TIMESTAMPTZ,
    person_properties VARCHAR,
    group0_properties VARCHAR,
    group1_properties VARCHAR,
    group2_properties VARCHAR,
    group3_properties VARCHAR,
    group4_properties VARCHAR,
    group0_created_at TIMESTAMPTZ,
    group1_created_at TIMESTAMPTZ,
    group2_created_at TIMESTAMPTZ,
    group3_created_at TIMESTAMPTZ,
    group4_created_at TIMESTAMPTZ,
    person_mode VARCHAR,
    historical_migration BOOLEAN,
    _inserted_at TIMESTAMPTZ
)
"""

# SQL for creating the persons table in DuckLake if it doesn't exist
# Uses TIMESTAMPTZ because ClickHouse exports DateTime64 as TIMESTAMP WITH TIME ZONE in Parquet.
# Note: person_version uses UBIGINT to match ClickHouse's UInt64 type.
PERSONS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS {catalog}.posthog.persons (
    team_id BIGINT,
    distinct_id VARCHAR,
    id VARCHAR,
    properties VARCHAR,
    created_at TIMESTAMPTZ,
    is_identified BOOLEAN,
    person_distinct_id_version BIGINT,
    person_version UBIGINT,
    _timestamp TIMESTAMPTZ,
    _inserted_at TIMESTAMPTZ
)
"""


class DucklingBackfillConfig(Config):
    """Config for duckling events backfill job."""

    clickhouse_settings: dict[str, Any] | None = None
    skip_ducklake_registration: bool = False
    skip_schema_validation: bool = False
    cleanup_existing_partition_data: bool = True  # Delete existing DuckLake data for partition before registering
    create_tables_if_missing: bool = True
    delete_tables: bool = False  # Danger: drops and recreates tables, losing all data
    dry_run: bool = False


def parse_partition_key(key: str) -> tuple[int, str]:
    """Parse a partition key into team_id and date.

    Args:
        key: Partition key in format "{team_id}_{date}" (e.g., "12345_2024-01-15")
             or "{team_id}_{month}" (e.g., "12345_2024-01")

    Returns:
        Tuple of (team_id, date_str)

    Raises:
        ValueError: If the partition key format is invalid.
    """
    parts = key.rsplit("_", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid partition key format: {key}. Expected 'team_id_YYYY-MM-DD' or 'team_id_YYYY-MM'")

    team_id_str, date_str = parts

    try:
        team_id = int(team_id_str)
    except ValueError as e:
        raise ValueError(f"Invalid team_id in partition key: {team_id_str}") from e

    # Try daily format first, then monthly
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        try:
            datetime.strptime(date_str, "%Y-%m")
        except ValueError as e:
            raise ValueError(f"Invalid date in partition key: {date_str}. Expected YYYY-MM-DD or YYYY-MM") from e

    return team_id, date_str


def parse_partition_key_dates(key: str) -> tuple[int, list[datetime]]:
    """Parse a partition key and return the list of dates to process.

    For daily partitions (YYYY-MM-DD): returns a single date (or empty if future)
    For monthly partitions (YYYY-MM): returns all dates in that month up to yesterday

    Args:
        key: Partition key in format "{team_id}_{date}" or "{team_id}_{month}"

    Returns:
        Tuple of (team_id, list of datetime objects to process)
    """
    team_id, date_str = parse_partition_key(key)
    yesterday = (timezone.now() - timedelta(days=1)).date()

    # Check if it's a monthly partition (YYYY-MM) or daily (YYYY-MM-DD)
    if len(date_str) == 7:  # YYYY-MM format
        year, month = int(date_str[:4]), int(date_str[5:7])
        _, last_day = calendar.monthrange(year, month)

        dates = []
        for day in range(1, last_day + 1):
            d = datetime(year, month, day)
            # Don't process future dates
            if d.date() <= yesterday:
                dates.append(d)
        return team_id, dates
    else:  # YYYY-MM-DD format
        d = datetime.strptime(date_str, "%Y-%m-%d")
        # Don't process future dates
        if d.date() > yesterday:
            return team_id, []
        return team_id, [d]


def is_full_export_partition(key: str) -> bool:
    """Detect if partition key is for full export mode.

    Full export: just team_id (e.g., "12345") - must be all digits
    Daily export: team_id with date (e.g., "12345_2024-12-04")
    """
    return key.isdigit()


def get_s3_url_for_clickhouse(bucket: str, region: str, path_without_scheme: str) -> str:
    """Build S3 URL in the format ClickHouse expects for cross-account access.

    ClickHouse uses the EC2 instance role for authentication. The duckling bucket
    policy explicitly allows the ClickHouse EC2 role, so no credentials needed.
    """
    return f"https://{bucket}.s3.{region}.amazonaws.com/{path_without_scheme}"


def get_earliest_event_date_for_team(team_id: int) -> datetime | None:
    """Query ClickHouse to find the earliest event date for a team.

    This is used by the full backfill sensor to determine the historical range
    of data to backfill.

    Returns:
        The date of the earliest event, or None if no events exist for this team.
    """
    cluster = _get_cluster()
    workload = Workload.OFFLINE if is_cloud() else Workload.DEFAULT

    def query_earliest(client: Client) -> datetime | None:
        # Filter timestamp >= '1970-01-01' to avoid toDate() overflow on pre-epoch timestamps.
        # ClickHouse's Date type is UInt16 (days since 1970-01-01), so negative timestamps
        # overflow to the max date (2149-06-06), breaking the backfill sensor logic.
        result = client.execute(
            """
            SELECT toDate(min(timestamp)) as earliest_date
            FROM events
            WHERE team_id = %(team_id)s
              AND timestamp >= '1970-01-01'
            """,
            {"team_id": team_id},
        )
        if result and result[0][0]:
            # ClickHouse returns a date object, convert to datetime
            date_val = result[0][0]
            if isinstance(date_val, datetime):
                return date_val
            return datetime.combine(date_val, datetime.min.time())
        return None

    return cluster.any_host_by_role(
        fn=query_earliest,
        workload=workload,
        node_role=NodeRole.DATA,
    ).result()


def get_earliest_person_date_for_team(team_id: int) -> datetime | None:
    """Query ClickHouse to find the earliest person modification date for a team.

    Uses _timestamp (Kafka ingestion time) since persons don't have a natural
    event timestamp like events do.

    Returns:
        The date of the earliest person modification, or None if no persons exist.
    """
    cluster = _get_cluster()
    workload = Workload.OFFLINE if is_cloud() else Workload.DEFAULT

    def query_earliest(client: Client) -> datetime | None:
        # Filter _timestamp >= '1970-01-01' to avoid toDate() overflow on pre-epoch timestamps.
        # ClickHouse's Date type is UInt16 (days since 1970-01-01), so negative timestamps
        # overflow to the max date (2149-06-06), breaking the backfill sensor logic.
        result = client.execute(
            """
            SELECT toDate(min(_timestamp)) as earliest_date
            FROM person
            WHERE team_id = %(team_id)s
              AND _timestamp >= '1970-01-01'
            """,
            {"team_id": team_id},
        )
        if result and result[0][0]:
            date_val = result[0][0]
            if isinstance(date_val, datetime):
                return date_val
            return datetime.combine(date_val, datetime.min.time())
        return None

    return cluster.any_host_by_role(
        fn=query_earliest,
        workload=workload,
        node_role=NodeRole.DATA,
    ).result()


def _validate_identifier(identifier: str) -> None:
    """Validate that an identifier is safe for SQL interpolation.

    Only allows alphanumeric characters and underscores to prevent SQL injection.
    """
    if not identifier.replace("_", "").isalnum():
        raise ValueError(f"Invalid SQL identifier: {identifier}")


def table_exists(
    conn: psycopg.Connection[Any],
    catalog_alias: str,
    schema: str,
    table: str,
) -> bool:
    """Check if a table exists in the DuckLake catalog.

    Args:
        conn: psycopg connection to the org's duckgres server.
        catalog_alias: Catalog alias (must be alphanumeric/underscore only).
        schema: Schema name (must be alphanumeric/underscore only).
        table: Table name (must be alphanumeric/underscore only).

    Returns:
        True if the table exists, False otherwise.

    Raises:
        ValueError: If any identifier contains invalid characters.
    """
    _validate_identifier(catalog_alias)
    _validate_identifier(schema)
    _validate_identifier(table)

    try:
        conn.execute(f"DESCRIBE {catalog_alias}.{schema}.{table}")
        return True
    except (psycopg.errors.UndefinedTable, psycopg.errors.InvalidSchemaName):
        return False


def _set_table_partitioning(
    conn: psycopg.Connection[Any],
    alias: str,
    table: str,
    partition_expr: str,
    context: AssetExecutionContext,
    team_id: int | None,
) -> bool:
    """Set partitioning on a DuckLake table.

    This operation is idempotent - calling it multiple times with the same
    partition expression is safe and will succeed.

    Args:
        conn: psycopg connection to the org's duckgres server.
        alias: Catalog alias.
        table: Table name (must be alphanumeric/underscore only).
        partition_expr: Partition expression (e.g., "year(timestamp), month(timestamp), day(timestamp)").
        context: Dagster asset execution context.
        team_id: Team ID for logging.

    Returns:
        True if partitioning was set successfully, False if it failed.
    """
    _validate_identifier(alias)
    _validate_identifier(table)

    context.log.info(f"Setting partitioning on {table} table...")
    try:
        conn.execute(f"ALTER TABLE {alias}.posthog.{table} SET PARTITIONED BY ({partition_expr})")
        context.log.info(f"Successfully set partitioning on {table} table")
        logger.info(
            "duckling_table_partitioning_set",
            team_id=team_id,
            table=table,
            partition_expr=partition_expr,
        )
        return True
    except Exception as exc:
        context.log.warning(f"Failed to set partitioning on {table} table: {exc}")
        logger.warning(
            "duckling_table_partitioning_failed",
            team_id=team_id,
            table=table,
            partition_expr=partition_expr,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return False


def ensure_events_table_exists(
    context: AssetExecutionContext,
    catalog: DuckLakeCatalog,
    conn: psycopg.Connection[Any],
) -> bool:
    """Create the events table in the duckling's DuckLake catalog if it doesn't exist.

    Also ensures partitioning is set on the table (idempotent operation).

    Returns True if the table was created, False if it already existed.

    Note: This function is safe to call concurrently - CREATE TABLE IF NOT EXISTS
    is idempotent and handles race conditions gracefully. Partitioning is also
    idempotent - calling SET PARTITIONED BY multiple times with the same keys succeeds.
    """
    alias = DUCKLAKE_ALIAS

    if table_exists(conn, alias, "posthog", "events"):
        context.log.info("Events table already exists in duckling catalog")
        # Ensure partitioning is set even on existing tables (idempotent)
        _set_table_partitioning(
            conn,
            alias,
            "events",
            "year(timestamp), month(timestamp), day(timestamp)",
            context,
            catalog.team_id,
        )
        return False

    context.log.info("Creating posthog schema if it doesn't exist...")
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {alias}.posthog")

    context.log.info("Creating events table in duckling catalog...")
    conn.execute(EVENTS_TABLE_DDL.format(catalog=alias))
    context.log.info("Successfully created events table")

    # Set partitioning by year/month/day for efficient querying
    _set_table_partitioning(
        conn,
        alias,
        "events",
        "year(timestamp), month(timestamp), day(timestamp)",
        context,
        catalog.team_id,
    )

    logger.info(
        "duckling_events_table_created",
        team_id=catalog.team_id,
        bucket=catalog.bucket,
    )
    return True


def ensure_persons_table_exists(
    context: AssetExecutionContext,
    catalog: DuckLakeCatalog,
    conn: psycopg.Connection[Any],
) -> bool:
    """Create the persons table in the duckling's DuckLake catalog if it doesn't exist.

    Also ensures partitioning is set on the table (idempotent operation).

    Returns True if the table was created, False if it already existed.

    Note: This function is safe to call concurrently - CREATE TABLE IF NOT EXISTS
    is idempotent and handles race conditions gracefully. Partitioning is also
    idempotent - calling SET PARTITIONED BY multiple times with the same keys succeeds.
    """
    alias = DUCKLAKE_ALIAS

    if table_exists(conn, alias, "posthog", "persons"):
        context.log.info("Persons table already exists in duckling catalog")
        # Ensure partitioning is set even on existing tables (idempotent)
        _set_table_partitioning(
            conn,
            alias,
            "persons",
            "year(_timestamp), month(_timestamp)",
            context,
            catalog.team_id,
        )
        return False

    context.log.info("Creating posthog schema if it doesn't exist...")
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {alias}.posthog")

    context.log.info("Creating persons table in duckling catalog...")
    conn.execute(PERSONS_TABLE_DDL.format(catalog=alias))
    context.log.info("Successfully created persons table")

    # Set partitioning by year/month of _timestamp for efficient querying
    _set_table_partitioning(
        conn,
        alias,
        "persons",
        "year(_timestamp), month(_timestamp)",
        context,
        catalog.team_id,
    )

    logger.info(
        "duckling_persons_table_created",
        team_id=catalog.team_id,
        bucket=catalog.bucket,
    )
    return True


def validate_duckling_schema(
    context: AssetExecutionContext,
    catalog: DuckLakeCatalog,
    conn: psycopg.Connection[Any],
) -> None:
    """Validate that the duckling's events table schema matches our export columns.

    This pre-flight check ensures we don't waste time exporting data that can't
    be registered with DuckLake due to schema mismatches.
    """
    alias = DUCKLAKE_ALIAS

    with conn.cursor() as cur:
        cur.execute(f"DESCRIBE {alias}.posthog.events")
        ducklake_columns = {row[0] for row in cur.fetchall()}

    missing_in_ducklake = EXPECTED_DUCKLAKE_COLUMNS - ducklake_columns
    if missing_in_ducklake:
        context.log.warning(
            f"Duckling events table is missing columns that we export: {missing_in_ducklake}. "
            "These columns will be added automatically by ducklake_add_data_files if the table "
            "supports schema evolution."
        )
        logger.warning(
            "duckling_schema_mismatch",
            team_id=catalog.team_id,
            missing_columns=list(missing_in_ducklake),
        )

    extra_in_ducklake = ducklake_columns - EXPECTED_DUCKLAKE_COLUMNS
    if extra_in_ducklake:
        context.log.info(f"Duckling has additional columns not in our export: {extra_in_ducklake}")

    context.log.info(
        f"Schema validation passed. Duckling has {len(ducklake_columns)} columns, "
        f"we export {len(EXPECTED_DUCKLAKE_COLUMNS)} columns."
    )
    logger.info(
        "duckling_schema_validation_passed",
        team_id=catalog.team_id,
        ducklake_columns=len(ducklake_columns),
        export_columns=len(EXPECTED_DUCKLAKE_COLUMNS),
    )


def validate_duckling_persons_schema(
    context: AssetExecutionContext,
    catalog: DuckLakeCatalog,
    conn: psycopg.Connection[Any],
) -> None:
    """Validate that the duckling's persons table schema matches our export columns."""
    alias = DUCKLAKE_ALIAS

    with conn.cursor() as cur:
        cur.execute(f"DESCRIBE {alias}.posthog.persons")
        ducklake_columns = {row[0] for row in cur.fetchall()}

    missing_in_ducklake = EXPECTED_DUCKLAKE_PERSONS_COLUMNS - ducklake_columns
    if missing_in_ducklake:
        context.log.warning(
            f"Duckling persons table is missing columns that we export: {missing_in_ducklake}. "
            "These columns will be added automatically by ducklake_add_data_files if the table "
            "supports schema evolution."
        )
        logger.warning(
            "duckling_persons_schema_mismatch",
            team_id=catalog.team_id,
            missing_columns=list(missing_in_ducklake),
        )

    extra_in_ducklake = ducklake_columns - EXPECTED_DUCKLAKE_PERSONS_COLUMNS
    if extra_in_ducklake:
        context.log.info(f"Duckling persons has additional columns not in our export: {extra_in_ducklake}")

    context.log.info(
        f"Persons schema validation passed. Duckling has {len(ducklake_columns)} columns, "
        f"we export {len(EXPECTED_DUCKLAKE_PERSONS_COLUMNS)} columns."
    )
    logger.info(
        "duckling_persons_schema_validation_passed",
        team_id=catalog.team_id,
        ducklake_columns=len(ducklake_columns),
        export_columns=len(EXPECTED_DUCKLAKE_PERSONS_COLUMNS),
    )


@retry(
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    retry=retry_if_exception_type((ClickHouseError, OSError, TimeoutError)),
    reraise=True,
)
def _execute_export_with_retry(
    client: Client,
    export_sql: str,
    settings: dict[str, Any],
    info: str,
) -> None:
    """Execute export SQL with retry logic for transient failures."""
    try:
        client.execute(export_sql, settings=settings)
    except Exception as e:
        logger.warning(
            "duckling_export_retry",
            info=info,
            error=str(e),
            error_type=type(e).__name__,
        )
        raise


def delete_events_partition_data(
    context: AssetExecutionContext,
    catalog: DuckLakeCatalog,
    team_id: int,
    partition_date: datetime,
    conn: psycopg.Connection[Any],
) -> int:
    """Delete existing events data for a specific team_id and date from DuckLake.

    Enables idempotent re-processing of partitions by removing existing data
    before registering new files.

    DuckLake transaction conflicts are retried server-side by duckgres
    (server/transient.go retryOnConflict, max 5 attempts with jitter). Connection
    retries live in the caller — this helper operates on a connection it doesn't own.

    Returns the number of rows deleted.
    """
    alias = DUCKLAKE_ALIAS
    date_str = partition_date.strftime("%Y-%m-%d")

    # Range predicate enables DuckLake partition pruning.
    # The table is partitioned by year(timestamp), month(timestamp), day(timestamp).
    # A half-open range [start_of_day, start_of_next_day) allows DuckDB to prune
    # to a single day's partition instead of scanning all data files.
    next_date_str = (partition_date + timedelta(days=1)).strftime("%Y-%m-%d")
    delete_sql = f"""
    DELETE FROM {alias}.posthog.events
    WHERE team_id = %s
      AND timestamp >= %s
      AND timestamp < %s
    """

    try:
        with conn.cursor() as cur:
            cur.execute(delete_sql, (team_id, date_str, next_date_str))
            deleted_count = cur.rowcount if cur.rowcount != -1 else 0

        if deleted_count > 0:
            context.log.info(f"Deleted {deleted_count} existing events for team_id={team_id}, date={date_str}")
            logger.info(
                "duckling_events_partition_deleted",
                team_id=team_id,
                date=date_str,
                deleted_count=deleted_count,
            )
        return deleted_count

    except (psycopg.errors.UndefinedTable, psycopg.errors.InvalidSchemaName):
        context.log.debug(f"Events table doesn't exist yet, nothing to delete for team_id={team_id}, date={date_str}")
        return 0
    except Exception as exc:
        # A worker/connection drop here is transparently retried by the caller
        # (_DuckgresSession.run reconnects + replays), so don't emit a loud
        # ERROR/_failed log + false alert for a failure that will recover — let it
        # propagate quietly. Only a genuine failure gets the loud log.
        if not _connection_dropped(exc):
            context.log.exception(f"Failed to delete events for team_id={team_id}, date={date_str}")
            logger.exception(
                "duckling_events_delete_failed",
                team_id=team_id,
                date=date_str,
            )
        raise


def delete_persons_partition_data(
    context: AssetExecutionContext,
    catalog: DuckLakeCatalog,
    team_id: int,
    partition_date: datetime | None,
    conn: psycopg.Connection[Any],
) -> int:
    """Delete existing persons data for a specific team_id (and optionally date) from DuckLake.

    For full exports (partition_date=None), deletes all persons for the team.
    For daily exports, deletes persons modified on that date.

    DuckLake transaction conflicts are retried server-side by duckgres. Connection
    retries live in the caller — this helper operates on a connection it doesn't own.

    Returns the number of rows deleted.
    """
    alias = DUCKLAKE_ALIAS
    date_label = partition_date.strftime("%Y-%m-%d") if partition_date else "full"

    delete_params: tuple[Any, ...]
    if partition_date is None:
        delete_sql = f"""
        DELETE FROM {alias}.posthog.persons
        WHERE team_id = %s
        """
        delete_params = (team_id,)
    else:
        date_str = partition_date.strftime("%Y-%m-%d")
        next_date_str = (partition_date + timedelta(days=1)).strftime("%Y-%m-%d")
        delete_sql = f"""
        DELETE FROM {alias}.posthog.persons
        WHERE team_id = %s
          AND _timestamp >= %s
          AND _timestamp < %s
        """
        delete_params = (team_id, date_str, next_date_str)

    try:
        if partition_date is None:
            context.log.info(f"Deleting all existing persons for team_id={team_id}")
        with conn.cursor() as cur:
            cur.execute(delete_sql, delete_params)
            deleted_count = cur.rowcount if cur.rowcount != -1 else 0

        if deleted_count > 0:
            context.log.info(f"Deleted {deleted_count} existing persons for team_id={team_id}, date={date_label}")
            logger.info(
                "duckling_persons_partition_deleted",
                team_id=team_id,
                date=date_label,
                deleted_count=deleted_count,
            )
        return deleted_count

    except (psycopg.errors.UndefinedTable, psycopg.errors.InvalidSchemaName):
        context.log.debug(f"Persons table doesn't exist yet, nothing to delete for team_id={team_id}")
        return 0
    except Exception as exc:
        # Connection drops are retried by the caller (_DuckgresSession.run); only
        # log loudly for genuine failures so a recovered drop doesn't false-alert.
        if not _connection_dropped(exc):
            context.log.exception(f"Failed to delete persons for team_id={team_id}, date={date_label}")
            logger.exception(
                "duckling_persons_delete_failed",
                team_id=team_id,
                date=date_label,
            )
        raise


def export_events_to_duckling_s3(
    context: AssetExecutionContext,
    client: Client,
    config: DucklingBackfillConfig,
    catalog: DuckLakeCatalog,
    team_id: int,
    date: datetime,
    run_id: str,
    settings: dict[str, Any],
) -> str | None:
    """Export events for a team/date to the duckling's S3 bucket.

    ClickHouse uses its EC2 instance role for S3 access. The duckling bucket policy
    explicitly allows the ClickHouse EC2 role, so no explicit credentials are needed.

    Returns:
        S3 path that was written, or None if dry_run.
    """
    year = date.strftime("%Y")
    month = date.strftime("%m")
    day = date.strftime("%d")
    date_str = date.strftime("%Y-%m-%d")

    # Path without s3:// scheme for the HTTPS URL
    path_without_scheme = f"{BACKFILL_EVENTS_S3_PREFIX}/{team_id}/year={year}/month={month}/day={day}/{run_id}.parquet"

    # ClickHouse needs HTTPS URL format for cross-account S3 access
    s3_url = get_s3_url_for_clickhouse(catalog.bucket, catalog.bucket_region, path_without_scheme)

    # S3 path with scheme for DuckLake registration
    s3_path = f"s3://{catalog.bucket}/{path_without_scheme}"

    where_clause = f"team_id = {team_id} AND toDate(timestamp) = '{date_str}'"

    # Event rows are wide (large properties/person_properties JSON), and the Parquet
    # writer buffers a full row group per encoding thread before flushing — this is where
    # the export OOMs (ParquetBlockOutputFormat in the stack trace), not the scan. Peak
    # memory is ~ row_group_size * bytes_per_row * threads, so the 1M-row default builds
    # multi-GB groups that blow the limit under parallel encoding. 250k rows lands each
    # group in Parquet's recommended byte range (~hundreds of MB) while keeping read
    # efficiency near the default; the raised ceiling is headroom on top.
    export_settings = settings.copy()
    export_settings.update(
        {
            "max_memory_usage": 100 * 1024 * 1024 * 1024,  # 100GB, matching the full-persons export
            "output_format_parquet_row_group_size": 250_000,  # down from the 1M default
        }
    )

    # ClickHouse uses its EC2 instance role - no credentials needed
    # The duckling bucket policy allows the ClickHouse EC2 role
    export_sql = f"""
    INSERT INTO FUNCTION s3(
        '{s3_url}',
        'Parquet'
    )
    SELECT
        {EVENTS_COLUMNS}
    FROM events
    WHERE {where_clause}
    SETTINGS s3_truncate_on_insert=1, use_hive_partitioning=0
    """

    info = f"team_id={team_id}, date={date_str}"

    if config.dry_run:
        context.log.info(f"[DRY RUN] Would export with SQL: {export_sql[:800]}...")
        return None

    context.log.info(f"Exporting events for {info} to {s3_path}")
    logger.info(
        "duckling_export_start",
        team_id=team_id,
        date=date_str,
        s3_path=s3_path,
    )

    try:
        _execute_export_with_retry(client, export_sql, export_settings, info)
        context.log.info(f"Successfully exported events for {info}")
        logger.info("duckling_export_success", team_id=team_id, date=date_str)
        return s3_path
    except Exception:
        context.log.exception(f"Failed to export events for {info} after {MAX_RETRY_ATTEMPTS} attempts")
        logger.exception("duckling_export_failed", team_id=team_id, date=date_str)
        raise


def register_file_with_duckling(
    context: AssetExecutionContext,
    catalog: DuckLakeCatalog,
    s3_path: str,
    config: DucklingBackfillConfig,
    conn: psycopg.Connection[Any],
) -> bool:
    """Register an exported Parquet file with the duckling's DuckLake catalog.

    Cross-account S3 access is configured server-side on the duckling's duckgres
    via IRSA, so the DAG only needs a pgwire connection.

    DuckLake transaction conflicts are retried server-side by duckgres. Connection
    retries live in the caller — this helper operates on a connection it doesn't own.

    Args:
        context: Dagster asset execution context.
        catalog: The DuckLakeCatalog for this duckling.
        s3_path: S3 path of the Parquet file to register.
        config: Job configuration.
        conn: psycopg connection to the org's duckgres server.

    Returns:
        True if registration succeeded, False otherwise.
    """
    if config.skip_ducklake_registration:
        context.log.info("Skipping DuckLake registration (skip_ducklake_registration=True)")
        return False

    if config.dry_run:
        context.log.info(f"[DRY RUN] Would register {s3_path} with DuckLake at {catalog.db_host}")
        return False

    alias = DUCKLAKE_ALIAS

    context.log.info(f"Registering file with DuckLake: {s3_path}")
    try:
        conn.execute(
            psql.SQL("CALL ducklake_add_data_files({}, 'events', {}, schema => 'posthog')").format(
                psql.Literal(alias),
                psql.Literal(s3_path),
            )
        )
    except Exception as exc:
        # Connection drops are retried by the caller (_DuckgresSession.run); only
        # log loudly for genuine failures so a recovered drop doesn't false-alert.
        if not _connection_dropped(exc):
            context.log.exception(f"Failed to register file {s3_path}")
            logger.exception(
                "duckling_file_registration_failed",
                s3_path=s3_path,
                team_id=catalog.team_id,
            )
        raise

    context.log.info(f"Successfully registered: {s3_path}")
    logger.info("duckling_file_registered", s3_path=s3_path, team_id=catalog.team_id)
    return True


def export_persons_to_duckling_s3(
    context: AssetExecutionContext,
    client: Client,
    config: DucklingBackfillConfig,
    catalog: DuckLakeCatalog,
    team_id: int,
    date: datetime,
    run_id: str,
    settings: dict[str, Any],
) -> str | None:
    """Export persons for a team/date to the duckling's S3 bucket.

    Exports persons joined with person_distinct_id2 to include distinct_ids.
    Uses _timestamp (Kafka ingestion time) for date filtering since persons
    don't have a natural event timestamp.

    The query uses ReplacingMergeTree deduplication with FINAL to get the
    latest version of each person and distinct_id mapping.

    Returns:
        S3 path that was written, or None if dry_run.
    """
    year = date.strftime("%Y")
    month = date.strftime("%m")
    date_str = date.strftime("%Y-%m-%d")

    path_without_scheme = f"{BACKFILL_PERSONS_S3_PREFIX}/{team_id}/year={year}/month={month}/{run_id}.parquet"
    s3_url = get_s3_url_for_clickhouse(catalog.bucket, catalog.bucket_region, path_without_scheme)
    s3_path = f"s3://{catalog.bucket}/{path_without_scheme}"

    # Join person with person_distinct_id2 to get distinct_ids
    # Use FINAL to handle ReplacingMergeTree deduplication
    # Filter by _timestamp to get persons modified on this date
    export_sql = f"""
    INSERT INTO FUNCTION s3(
        '{s3_url}',
        'Parquet'
    )
    SELECT
        {PERSONS_COLUMNS}
    FROM person AS p FINAL
    INNER JOIN person_distinct_id2 AS pd FINAL ON p.id = pd.person_id AND p.team_id = pd.team_id
    WHERE p.team_id = {team_id}
      AND pd.team_id = {team_id}
      AND toDate(p._timestamp) = '{date_str}'
      AND p.is_deleted = 0
      AND pd.is_deleted = 0
    SETTINGS s3_truncate_on_insert=1, use_hive_partitioning=0
    """

    info = f"team_id={team_id}, date={date_str}"

    if config.dry_run:
        context.log.info(f"[DRY RUN] Would export persons with SQL: {export_sql[:800]}...")
        return None

    context.log.info(f"Exporting persons for {info} to {s3_path}")
    logger.info(
        "duckling_persons_export_start",
        team_id=team_id,
        date=date_str,
        s3_path=s3_path,
    )

    try:
        _execute_export_with_retry(client, export_sql, settings, info)
        context.log.info(f"Successfully exported persons for {info}")
        logger.info("duckling_persons_export_success", team_id=team_id, date=date_str)
        return s3_path
    except Exception:
        context.log.exception(f"Failed to export persons for {info} after {MAX_RETRY_ATTEMPTS} attempts")
        logger.exception("duckling_persons_export_failed", team_id=team_id, date=date_str)
        raise


def export_persons_full_to_duckling_s3(
    context: AssetExecutionContext,
    client: Client,
    config: DucklingBackfillConfig,
    catalog: DuckLakeCatalog,
    team_id: int,
    run_id: str,
    settings: dict[str, Any],
) -> str | None:
    """Export ALL persons for a team to the duckling's S3 bucket.

    Single FINAL query with no date filtering - much more efficient than
    per-day exports for full backfills. Exports persons joined with
    person_distinct_id2 to include distinct_ids.

    Returns:
        S3 path that was written, or None if dry_run.
    """
    path_without_scheme = f"{BACKFILL_PERSONS_S3_PREFIX}/{team_id}/year=0/month=0/{run_id}.parquet"
    s3_url = get_s3_url_for_clickhouse(catalog.bucket, catalog.bucket_region, path_without_scheme)
    s3_path = f"s3://{catalog.bucket}/{path_without_scheme}"

    # Join person with person_distinct_id2 to get distinct_ids
    # Use FINAL to handle ReplacingMergeTree deduplication
    # No date filtering - export all persons for the team
    # Full exports need more memory due to FINAL + JOIN on large datasets
    # Also enable external sorting to spill to disk if memory is still exceeded
    full_export_settings = settings.copy()
    full_export_settings.update(
        {
            "max_memory_usage": 100 * 1024 * 1024 * 1024,  # 100GB for full exports
            "max_bytes_before_external_sort": 50 * 1024 * 1024 * 1024,  # Spill to disk after 50GB
        }
    )

    export_sql = f"""
    INSERT INTO FUNCTION s3(
        '{s3_url}',
        'Parquet'
    )
    SELECT
        {PERSONS_COLUMNS}
    FROM person AS p FINAL
    INNER JOIN person_distinct_id2 AS pd FINAL ON p.id = pd.person_id AND p.team_id = pd.team_id
    WHERE p.team_id = {team_id}
      AND pd.team_id = {team_id}
      AND p.is_deleted = 0
      AND pd.is_deleted = 0
    SETTINGS s3_truncate_on_insert=1, use_hive_partitioning=0
    """

    info = f"team_id={team_id}, full_export"

    if config.dry_run:
        context.log.info(f"[DRY RUN] Would export persons (full) with SQL: {export_sql[:800]}...")
        return None

    context.log.info(f"Exporting all persons for {info} to {s3_path}")
    logger.info(
        "duckling_persons_full_export_start",
        team_id=team_id,
        s3_path=s3_path,
    )

    try:
        _execute_export_with_retry(client, export_sql, full_export_settings, info)
        context.log.info(f"Successfully exported all persons for {info}")
        logger.info("duckling_persons_full_export_success", team_id=team_id)
        return s3_path
    except Exception:
        context.log.exception(f"Failed to export persons (full) for {info} after {MAX_RETRY_ATTEMPTS} attempts")
        logger.exception("duckling_persons_full_export_failed", team_id=team_id)
        raise


def register_persons_file_with_duckling(
    context: AssetExecutionContext,
    catalog: DuckLakeCatalog,
    s3_path: str,
    config: DucklingBackfillConfig,
    conn: psycopg.Connection[Any],
) -> bool:
    """Register an exported persons Parquet file with the duckling's DuckLake catalog.

    DuckLake transaction conflicts are retried server-side by duckgres. Connection
    retries live in the caller — this helper operates on a connection it doesn't own.
    """
    if config.skip_ducklake_registration:
        context.log.info("Skipping DuckLake registration (skip_ducklake_registration=True)")
        return False

    if config.dry_run:
        context.log.info(f"[DRY RUN] Would register {s3_path} with DuckLake at {catalog.db_host}")
        return False

    alias = DUCKLAKE_ALIAS

    context.log.info(f"Registering persons file with DuckLake: {s3_path}")
    try:
        conn.execute(
            psql.SQL("CALL ducklake_add_data_files({}, 'persons', {}, schema => 'posthog')").format(
                psql.Literal(alias),
                psql.Literal(s3_path),
            )
        )
    except Exception as exc:
        # Connection drops are retried by the caller (_DuckgresSession.run); only
        # log loudly for genuine failures so a recovered drop doesn't false-alert.
        if not _connection_dropped(exc):
            context.log.exception(f"Failed to register persons file {s3_path}")
            logger.exception(
                "duckling_persons_file_registration_failed",
                s3_path=s3_path,
                team_id=catalog.team_id,
            )
        raise

    context.log.info(f"Successfully registered persons: {s3_path}")
    logger.info(
        "duckling_persons_file_registered",
        s3_path=s3_path,
        team_id=catalog.team_id,
    )
    return True


@asset(
    partitions_def=duckling_events_partitions_def,
    name="duckling_events_backfill",
    tags={"owner": JobOwners.TEAM_DATA_STACK.value, **EVENTS_CONCURRENCY_TAG},
)
def duckling_events_backfill(context: AssetExecutionContext, config: DucklingBackfillConfig) -> None:
    """Backfill events from ClickHouse to a customer's duckling.

    Supports both daily (YYYY-MM-DD) and monthly (YYYY-MM) partition keys.
    For monthly partitions, processes all days in the month.

    This asset:
    1. Parses the partition key to get team_id and date(s)
    2. Looks up the DuckLakeCatalog for the team
    3. Creates the events table if it doesn't exist (optional, enabled by default)
    4. Validates the duckling's schema compatibility (optional)
    5. For each date in the partition:
       a. Deletes existing DuckLake data for this partition (idempotent re-processing)
       b. Exports events to the duckling's S3 bucket (ClickHouse EC2 role has bucket access)
       c. Registers the Parquet file with the duckling's DuckLake catalog (via cross-account role)
    """
    team_id, dates = parse_partition_key_dates(context.partition_key)
    run_id = context.run.run_id[:8]

    context.log.info(f"Starting duckling backfill for team_id={team_id}, dates={len(dates)} day(s)")
    logger.info(
        "duckling_backfill_start",
        team_id=team_id,
        date_count=len(dates),
        run_id=run_id,
    )

    # Look up the duckling configuration
    catalog = get_ducklake_catalog_by_team_org(team_id)
    if catalog is None:
        raise ValueError(f"No DuckLakeCatalog found for team_id={team_id}")

    server = get_duckgres_server_for_organization(str(catalog.organization_id))
    if server is None:
        raise ValueError(f"No DuckgresServer found for org={catalog.organization_id} — cannot proceed with backfill.")

    context.log.info(
        f"Backfill ready for team_id={team_id}: duckgres={server.host}:{server.port}, bucket={catalog.bucket}"
    )

    # Open one duckgres connection for all metadata operations, but skip it
    # entirely when no duckgres-backed work will run (dry_run / skip_ducklake_registration).
    should_use_duckgres = not (config.dry_run or config.skip_ducklake_registration)
    session = _DuckgresSession(context, catalog) if should_use_duckgres else None
    try:
        if session is not None:
            # Delete events table if requested (dangerous - loses all data)
            if config.delete_tables:
                context.log.warning("delete_tables=True: Deleting events table...")
                try:
                    session.run(
                        "drop events table",
                        lambda c: c.execute(f"DROP TABLE IF EXISTS {DUCKLAKE_ALIAS}.posthog.events"),
                    )
                except Exception:
                    context.log.exception(f"Failed to drop events table for team_id={team_id}")
                    logger.exception(
                        "duckling_events_table_drop_failed",
                        team_id=team_id,
                        bucket=catalog.bucket,
                    )
                    raise

            # Create events table if it doesn't exist
            if config.create_tables_if_missing:
                context.log.info("Ensuring events table exists in duckling catalog...")
                session.run("ensure events table", lambda c: ensure_events_table_exists(context, catalog, c))

            # Validate schema before starting export
            if not config.skip_schema_validation:
                context.log.info("Validating duckling schema compatibility...")
                session.run("validate events schema", lambda c: validate_duckling_schema(context, catalog, c))

        # Prepare ClickHouse settings
        merged_settings = DEFAULT_CLICKHOUSE_SETTINGS.copy()
        merged_settings.update(settings_with_log_comment(context))
        if config.clickhouse_settings:
            merged_settings.update(config.clickhouse_settings)
            context.log.info(f"Using custom ClickHouse settings: {config.clickhouse_settings}")

        cluster = _get_cluster()
        tags = dagster_tags(context)
        workload = Workload.OFFLINE if is_cloud() else Workload.DEFAULT

        # Process each date in the partition
        total_exported = 0
        total_registered = 0
        s3_paths: list[str] = []

        for partition_date in dates:
            date_str = partition_date.strftime("%Y-%m-%d")
            context.log.info(f"Processing date {date_str}...")

            # Delete existing DuckLake data for this partition before re-processing
            if session is not None and config.cleanup_existing_partition_data:

                def delete_events_partition(conn: psycopg.Connection[Any], date: datetime = partition_date) -> None:
                    delete_events_partition_data(context, catalog, team_id, date, conn=conn)

                session.run(f"delete events partition {date_str}", delete_events_partition)

            def do_export(client: Client, date: datetime = partition_date) -> str | None:
                with tags_context(kind="dagster", dagster=tags):
                    return export_events_to_duckling_s3(
                        context=context,
                        client=client,
                        config=config,
                        catalog=catalog,
                        team_id=team_id,
                        date=date,
                        run_id=run_id,
                        settings=merged_settings,
                    )

            s3_path = cluster.any_host_by_role(
                fn=do_export,
                workload=workload,
                node_role=NodeRole.DATA,
            ).result()

            # Register with DuckLake if we have a file
            if s3_path:
                total_exported += 1
                s3_paths.append(s3_path)
                if session is not None:

                    def register_events_file(
                        conn: psycopg.Connection[Any],
                        path: str = s3_path,
                        date: datetime = partition_date,
                    ) -> bool:
                        # Idempotent replay unit: ducklake_add_data_files APPENDS with no
                        # dedup-by-path, so if a prior attempt committed the registration
                        # but the worker died before the client saw the ack, re-clear the
                        # day's range first (idempotent DELETE) then re-add — the net state
                        # is exactly this file for the day, wherever the prior attempt died.
                        if config.cleanup_existing_partition_data:
                            delete_events_partition_data(context, catalog, team_id, date, conn=conn)
                        return register_file_with_duckling(context, catalog, path, config, conn)

                    if session.run(f"register events file {date_str}", register_events_file):
                        total_registered += 1

        context.add_output_metadata(
            {
                "team_id": team_id,
                "partition_key": context.partition_key,
                "dates_processed": len(dates),
                "files_exported": total_exported,
                "files_registered": total_registered,
                "bucket": catalog.bucket,
            }
        )

        context.log.info(
            f"Completed duckling backfill for team_id={team_id}: "
            f"{total_exported}/{len(dates)} days exported, {total_registered} registered"
        )
        logger.info(
            "duckling_backfill_complete",
            team_id=team_id,
            dates_processed=len(dates),
            files_exported=total_exported,
            files_registered=total_registered,
        )

    finally:
        if session is not None:
            session.close()


@asset(
    partitions_def=duckling_persons_partitions_def,
    name="duckling_persons_backfill",
    tags={"owner": JobOwners.TEAM_DATA_STACK.value, **PERSONS_CONCURRENCY_TAG},
)
def duckling_persons_backfill(context: AssetExecutionContext, config: DucklingBackfillConfig) -> None:
    """Backfill persons from ClickHouse to a customer's duckling.

    Supports two partition formats with different export strategies:
    - Full export: partition key is just team_id (e.g., "12345")
      Single FINAL query exports all persons for the team efficiently.
    - Daily export: partition key is team_id with date (e.g., "12345_2024-12-04")
      Date-filtered query for incremental daily top-up.

    This asset exports persons joined with person_distinct_id2 to include all
    distinct_ids associated with each person.

    Steps:
    1. Parses the partition key to determine export mode (full vs daily)
    2. Looks up the DuckLakeCatalog for the team
    3. Creates the persons table if it doesn't exist (optional, enabled by default)
    4. Validates the duckling's persons schema compatibility (optional)
    5. Exports persons to S3 and registers with DuckLake
    """
    partition_key = context.partition_key
    is_full = is_full_export_partition(partition_key)
    run_id = context.run.run_id[:8]

    if is_full:
        team_id = int(partition_key)
        export_mode = "full"
    else:
        team_id, dates = parse_partition_key_dates(partition_key)
        export_mode = "daily"

    context.log.info(f"Starting duckling persons backfill for team_id={team_id}, mode={export_mode}")
    logger.info(
        "duckling_persons_backfill_start",
        team_id=team_id,
        export_mode=export_mode,
        run_id=run_id,
    )

    catalog = get_ducklake_catalog_by_team_org(team_id)
    if catalog is None:
        raise ValueError(f"No DuckLakeCatalog found for team_id={team_id}")

    server = get_duckgres_server_for_organization(str(catalog.organization_id))
    if server is None:
        raise ValueError(f"No DuckgresServer found for org={catalog.organization_id} — cannot proceed with backfill.")

    context.log.info(
        f"Backfill ready for team_id={team_id}: duckgres={server.host}:{server.port}, bucket={catalog.bucket}"
    )

    # Open one duckgres connection for all metadata operations, but skip it
    # entirely when no duckgres-backed work will run (dry_run / skip_ducklake_registration).
    should_use_duckgres = not (config.dry_run or config.skip_ducklake_registration)
    session = _DuckgresSession(context, catalog) if should_use_duckgres else None
    try:
        if session is not None:
            # Delete persons table if requested (dangerous - loses all data)
            if config.delete_tables:
                context.log.warning("delete_tables=True: Deleting persons table...")
                try:
                    session.run(
                        "drop persons table",
                        lambda c: c.execute(f"DROP TABLE IF EXISTS {DUCKLAKE_ALIAS}.posthog.persons"),
                    )
                except Exception:
                    context.log.exception(f"Failed to drop persons table for team_id={team_id}")
                    logger.exception(
                        "duckling_persons_table_drop_failed",
                        team_id=team_id,
                        bucket=catalog.bucket,
                    )
                    raise

            # Create persons table if it doesn't exist
            if config.create_tables_if_missing:
                context.log.info("Ensuring persons table exists in duckling catalog...")
                session.run("ensure persons table", lambda c: ensure_persons_table_exists(context, catalog, c))

            if not config.skip_schema_validation:
                context.log.info("Validating duckling persons schema compatibility...")
                session.run("validate persons schema", lambda c: validate_duckling_persons_schema(context, catalog, c))

        merged_settings = DEFAULT_CLICKHOUSE_SETTINGS.copy()
        merged_settings.update(settings_with_log_comment(context))
        if config.clickhouse_settings:
            merged_settings.update(config.clickhouse_settings)
            context.log.info(f"Using custom ClickHouse settings: {config.clickhouse_settings}")

        cluster = _get_cluster()
        tags = dagster_tags(context)
        workload = Workload.OFFLINE if is_cloud() else Workload.DEFAULT

        if is_full:
            # FULL EXPORT MODE - single query for all persons
            context.log.info(f"Full export mode: exporting all persons for team_id={team_id}")

            # Delete all existing persons data for this team before full re-export
            if session is not None and config.cleanup_existing_partition_data:
                session.run(
                    "delete all persons",
                    lambda c: delete_persons_partition_data(context, catalog, team_id, partition_date=None, conn=c),
                )

            def do_full_export(client: Client) -> str | None:
                with tags_context(kind="dagster", dagster=tags):
                    return export_persons_full_to_duckling_s3(
                        context=context,
                        client=client,
                        config=config,
                        catalog=catalog,
                        team_id=team_id,
                        run_id=run_id,
                        settings=merged_settings,
                    )

            s3_path = cluster.any_host_by_role(
                fn=do_full_export,
                workload=workload,
                node_role=NodeRole.DATA,
            ).result()

            files_exported = 1 if s3_path else 0
            files_registered = 0
            if s3_path and session is not None:

                def register_full_persons_file(conn: psycopg.Connection[Any], path: str = s3_path) -> bool:
                    # Idempotent replay unit (see _DuckgresSession): re-clear all of the
                    # team's persons (idempotent DELETE) then re-add, so a replay after a
                    # committed-but-unacked registration can't double-register the file.
                    if config.cleanup_existing_partition_data:
                        delete_persons_partition_data(context, catalog, team_id, partition_date=None, conn=conn)
                    return register_persons_file_with_duckling(context, catalog, path, config, conn)

                if session.run("register persons file (full)", register_full_persons_file):
                    files_registered = 1

            context.add_output_metadata(
                {
                    "team_id": team_id,
                    "partition_key": partition_key,
                    "export_mode": "full",
                    "files_exported": files_exported,
                    "files_registered": files_registered,
                    "bucket": catalog.bucket,
                }
            )

            context.log.info(
                f"Completed duckling persons full backfill for team_id={team_id}: "
                f"{files_exported} file exported, {files_registered} registered"
            )
            logger.info(
                "duckling_persons_backfill_complete",
                team_id=team_id,
                export_mode="full",
                files_exported=files_exported,
                files_registered=files_registered,
            )
        else:
            # DAILY EXPORT MODE - process each date in the partition
            total_exported = 0
            total_registered = 0

            for partition_date in dates:
                date_str = partition_date.strftime("%Y-%m-%d")
                context.log.info(f"Processing persons for date {date_str}...")

                # Delete existing DuckLake data for this partition before re-processing
                if session is not None and config.cleanup_existing_partition_data:

                    def delete_persons_partition(
                        conn: psycopg.Connection[Any], date: datetime = partition_date
                    ) -> None:
                        delete_persons_partition_data(context, catalog, team_id, date, conn=conn)

                    session.run(f"delete persons partition {date_str}", delete_persons_partition)

                def do_export(client: Client, date: datetime = partition_date) -> str | None:
                    with tags_context(kind="dagster", dagster=tags):
                        return export_persons_to_duckling_s3(
                            context=context,
                            client=client,
                            config=config,
                            catalog=catalog,
                            team_id=team_id,
                            date=date,
                            run_id=run_id,
                            settings=merged_settings,
                        )

                s3_path = cluster.any_host_by_role(
                    fn=do_export,
                    workload=workload,
                    node_role=NodeRole.DATA,
                ).result()

                if s3_path:
                    total_exported += 1
                    if session is not None:

                        def register_persons_file(
                            conn: psycopg.Connection[Any],
                            path: str = s3_path,
                            date: datetime = partition_date,
                        ) -> bool:
                            # Idempotent replay unit (see _DuckgresSession): re-clear the
                            # day's range (idempotent DELETE) then re-add, so a replay after
                            # a committed-but-unacked registration can't double-register.
                            if config.cleanup_existing_partition_data:
                                delete_persons_partition_data(context, catalog, team_id, date, conn=conn)
                            return register_persons_file_with_duckling(context, catalog, path, config, conn)

                        if session.run(f"register persons file {date_str}", register_persons_file):
                            total_registered += 1

            context.add_output_metadata(
                {
                    "team_id": team_id,
                    "partition_key": partition_key,
                    "export_mode": "daily",
                    "dates_processed": len(dates),
                    "files_exported": total_exported,
                    "files_registered": total_registered,
                    "bucket": catalog.bucket,
                }
            )

            context.log.info(
                f"Completed duckling persons daily backfill for team_id={team_id}: "
                f"{total_exported}/{len(dates)} days exported, {total_registered} registered"
            )
            logger.info(
                "duckling_persons_backfill_complete",
                team_id=team_id,
                export_mode="daily",
                dates_processed=len(dates),
                files_exported=total_exported,
                files_registered=total_registered,
            )

    finally:
        if session is not None:
            session.close()


@sensor(
    name="duckling_events_daily_backfill_sensor",
    minimum_interval_seconds=3600,  # Run hourly
    job_name="duckling_events_backfill_job",
)
def duckling_events_daily_backfill_sensor(
    context: SensorEvaluationContext,
) -> SensorResult:
    """Discover teams with DuckLakeCatalog entries and create daily backfill partitions.

    This sensor runs periodically to:
    1. Find all teams with DuckLakeCatalog configurations
    2. Create partitions for yesterday's data (if not already exists)
    3. Trigger backfill runs for new partitions
    4. Retry failed partitions that already exist
    """
    yesterday = (timezone.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    # Get existing partitions
    existing = set(context.instance.get_dynamic_partitions("duckling_events_backfill"))

    new_partitions: list[str] = []
    run_requests: list[RunRequest] = []

    for backfill in DuckLakeBackfill.objects.filter(enabled=True):
        partition_key = f"{backfill.team_id}_{yesterday}"

        if partition_key not in existing:
            # New partition - create and trigger run
            new_partitions.append(partition_key)
            run_requests.append(
                RunRequest(
                    partition_key=partition_key,
                    run_key=f"{partition_key}_new",
                )
            )
            context.log.info(f"Creating partition for team_id={backfill.team_id}, date={yesterday}")
        else:
            # Existing partition - check if the last run failed and needs retry
            # Query for runs with this partition key (stored in dagster/partition tag)
            runs = context.instance.get_runs(
                filters=RunsFilter(
                    job_name="duckling_events_backfill_job",
                    tags={"dagster/partition": partition_key},
                ),
                limit=1,
            )
            if runs:
                latest_run = runs[0]
                # Only retry if failed - skip if in progress or succeeded
                if latest_run.status == DagsterRunStatus.FAILURE:
                    # Failed run - trigger retry with unique run_key
                    run_requests.append(
                        RunRequest(
                            partition_key=partition_key,
                            run_key=f"{partition_key}_retry_{latest_run.run_id[:8]}",
                        )
                    )
                    context.log.info(
                        f"Retrying failed partition team_id={backfill.team_id}, date={yesterday} "
                        f"(previous run: {latest_run.run_id[:8]})"
                    )
                    logger.info(
                        "duckling_sensor_retry_failed_partition",
                        team_id=backfill.team_id,
                        date=yesterday,
                        previous_run_id=latest_run.run_id,
                    )
                elif latest_run.status in (
                    DagsterRunStatus.STARTED,
                    DagsterRunStatus.QUEUED,
                ):
                    context.log.debug(
                        f"Skipping partition team_id={backfill.team_id}, date={yesterday} - run in progress"
                    )

    if new_partitions:
        context.log.info(f"Discovered {len(new_partitions)} new partitions to backfill")
        logger.info(
            "duckling_sensor_discovered_partitions",
            count=len(new_partitions),
            partitions=new_partitions,
        )

    if run_requests:
        logger.info(
            "duckling_sensor_run_requests",
            total_requests=len(run_requests),
            new_partitions=len(new_partitions),
            retries=len(run_requests) - len(new_partitions),
        )

    return SensorResult(
        run_requests=run_requests,
        dynamic_partitions_requests=[duckling_events_partitions_def.build_add_request(new_partitions)]
        if new_partitions
        else [],
    )


# Number of monthly partitions to create per sensor tick (to avoid timeout)
BACKFILL_MONTHS_PER_TICK = 3

# Ignore events before this date — pre-2015 data is typically junk timestamps
EARLIEST_BACKFILL_DATE = datetime(2015, 1, 1)


def get_months_in_range(start_date: date, end_date: date) -> list[str]:
    """Generate list of month strings (YYYY-MM) between start and end dates."""
    months = []
    current = date(start_date.year, start_date.month, 1)
    end_month = date(end_date.year, end_date.month, 1)

    while current <= end_month:
        months.append(current.strftime("%Y-%m"))
        # Move to next month
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)

    return months


@sensor(
    name="duckling_events_full_backfill_sensor",
    minimum_interval_seconds=600,  # Run every 10 minutes
    job_name="duckling_events_backfill_job",
    default_status=DefaultSensorStatus.RUNNING,
)
def duckling_events_full_backfill_sensor(
    context: SensorEvaluationContext,
) -> SensorResult:
    """Full historical backfill sensor - creates MONTHLY partitions for efficiency.

    Uses monthly partitions (YYYY-MM) instead of daily to reduce partition count.
    Each monthly partition processes all days in that month.

    Cursor format: {"team_id": X, "next_month": "YYYY-MM", "earliest": "YYYY-MM"}

    Each tick creates up to BACKFILL_MONTHS_PER_TICK partitions (default 3)
    to stay within the 60-second timeout limit.

    Manual trigger:
        To restart from scratch, reset the cursor in Dagster UI:
        Sensors -> duckling_events_full_backfill_sensor -> Reset cursor
    """
    yesterday = (timezone.now() - timedelta(days=1)).date()

    # Parse cursor - tracks where we left off
    cursor_data: dict = {}
    if context.cursor:
        try:
            cursor_data = json.loads(context.cursor)
        except json.JSONDecodeError:
            cursor_data = {}

    backfills = list(DuckLakeBackfill.objects.filter(enabled=True).order_by("team_id"))
    if not backfills:
        context.log.info("No enabled DuckLakeBackfill entries found")
        return SensorResult(run_requests=[])

    # Find where to resume from
    resume_team_id = cursor_data.get("team_id")
    resume_month = cursor_data.get("next_month")
    cached_earliest = cursor_data.get("earliest")

    # Find the backfill entry to resume from (or start from first)
    start_idx = 0
    if resume_team_id:
        for i, bf in enumerate(backfills):
            if bf.team_id == resume_team_id:
                start_idx = i
                break

    new_partitions: list[str] = []
    run_requests: list[RunRequest] = []
    existing_partitions = set(context.instance.get_dynamic_partitions("duckling_events_backfill"))

    # Process backfills starting from where we left off
    for bf_idx, bf in enumerate(backfills[start_idx:], start=start_idx):
        if len(new_partitions) >= BACKFILL_MONTHS_PER_TICK:
            context.log.info(f"Batch limit reached, will continue from team {bf.team_id}")
            break

        team_id = bf.team_id

        # Determine start month - use cached value if resuming same team
        if team_id == resume_team_id and cached_earliest:
            earliest_month = cached_earliest
            current_month = resume_month if resume_month else earliest_month
        else:
            # Query ClickHouse for earliest date (only once per team)
            earliest_dt = get_earliest_event_date_for_team(team_id)
            if earliest_dt is None:
                context.log.info(f"No events found for team_id={team_id}, skipping")
                continue
            earliest_dt = max(earliest_dt, EARLIEST_BACKFILL_DATE)
            earliest_month = earliest_dt.strftime("%Y-%m")
            current_month = earliest_month

        # Generate monthly partitions for this team
        end_month = yesterday.strftime("%Y-%m")
        all_months = get_months_in_range(datetime.strptime(current_month, "%Y-%m").date(), yesterday)

        for month in all_months:
            if len(new_partitions) >= BACKFILL_MONTHS_PER_TICK:
                break

            partition_key = f"{team_id}_{month}"
            current_month = month

            # Skip partitions that already exist — advance cursor past them
            if partition_key in existing_partitions:
                continue

            new_partitions.append(partition_key)
            run_requests.append(
                RunRequest(
                    partition_key=partition_key,
                )
            )

        # Update cursor for next tick
        # Move to next month after the last one we processed
        last_processed = datetime.strptime(current_month, "%Y-%m").date()
        if last_processed.month == 12:
            next_month_date = date(last_processed.year + 1, 1, 1)
        else:
            next_month_date = date(last_processed.year, last_processed.month + 1, 1)
        next_month = next_month_date.strftime("%Y-%m")

        if next_month <= end_month:
            # More months to process for this team
            cursor_data = {
                "team_id": team_id,
                "next_month": next_month,
                "earliest": earliest_month,
            }
        else:
            # Done with this team, move to next
            next_idx = bf_idx + 1
            if next_idx < len(backfills):
                cursor_data = {"team_id": backfills[next_idx].team_id}
            else:
                # All teams done - reset cursor to check again tomorrow
                cursor_data = {"completed": timezone.now().date().isoformat()}

    # Check if we're in "completed" state and should skip until new data
    if cursor_data.get("completed") == timezone.now().date().isoformat() and not new_partitions:
        context.log.debug("Full backfill complete for today")
        return SensorResult(run_requests=[], cursor=json.dumps(cursor_data))

    if new_partitions:
        context.log.info(f"Creating {len(new_partitions)} monthly partitions")
        logger.info(
            "duckling_full_backfill_batch",
            partition_count=len(new_partitions),
            cursor=cursor_data,
        )

    return SensorResult(
        run_requests=run_requests,
        dynamic_partitions_requests=[duckling_events_partitions_def.build_add_request(new_partitions)]
        if new_partitions
        else [],
        cursor=json.dumps(cursor_data),
    )


duckling_events_backfill_job = define_asset_job(
    name="duckling_events_backfill_job",
    selection=["duckling_events_backfill"],
    tags={
        "owner": JobOwners.TEAM_DATA_STACK.value,
        "disable_slack_notifications": True,
        **EVENTS_CONCURRENCY_TAG,
    },
)


@sensor(
    name="duckling_persons_daily_backfill_sensor",
    minimum_interval_seconds=3600,  # Run hourly
    job_name="duckling_persons_backfill_job",
)
def duckling_persons_daily_backfill_sensor(
    context: SensorEvaluationContext,
) -> SensorResult:
    """Discover teams with DuckLakeCatalog entries and create daily persons partitions.

    Similar to duckling_events_daily_backfill_sensor but for persons data.
    Uses _timestamp (Kafka ingestion time) for date filtering.
    """
    yesterday = (timezone.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    existing = set(context.instance.get_dynamic_partitions("duckling_persons_backfill"))

    new_partitions: list[str] = []
    run_requests: list[RunRequest] = []

    for backfill in DuckLakeBackfill.objects.filter(enabled=True):
        partition_key = f"{backfill.team_id}_{yesterday}"

        if partition_key not in existing:
            new_partitions.append(partition_key)
            run_requests.append(
                RunRequest(
                    partition_key=partition_key,
                    run_key=f"{partition_key}_persons_new",
                )
            )
            context.log.info(f"Creating persons partition for team_id={backfill.team_id}, date={yesterday}")
        else:
            runs = context.instance.get_runs(
                filters=RunsFilter(
                    job_name="duckling_persons_backfill_job",
                    tags={"dagster/partition": partition_key},
                ),
                limit=1,
            )
            if runs:
                latest_run = runs[0]
                # Only retry if failed - skip if in progress or succeeded
                if latest_run.status == DagsterRunStatus.FAILURE:
                    run_requests.append(
                        RunRequest(
                            partition_key=partition_key,
                            run_key=f"{partition_key}_persons_retry_{latest_run.run_id[:8]}",
                        )
                    )
                    context.log.info(f"Retrying failed persons partition team_id={backfill.team_id}, date={yesterday}")
                    logger.info(
                        "duckling_persons_sensor_retry_failed_partition",
                        team_id=backfill.team_id,
                        date=yesterday,
                        previous_run_id=latest_run.run_id,
                    )
                elif latest_run.status in (
                    DagsterRunStatus.STARTED,
                    DagsterRunStatus.QUEUED,
                ):
                    context.log.debug(
                        f"Skipping persons partition team_id={backfill.team_id}, date={yesterday} - run in progress"
                    )

    if new_partitions:
        context.log.info(f"Discovered {len(new_partitions)} new persons partitions to backfill")
        logger.info(
            "duckling_persons_sensor_discovered_partitions",
            count=len(new_partitions),
            partitions=new_partitions,
        )

    if run_requests:
        logger.info(
            "duckling_persons_sensor_run_requests",
            total_requests=len(run_requests),
            new_partitions=len(new_partitions),
            retries=len(run_requests) - len(new_partitions),
        )

    return SensorResult(
        run_requests=run_requests,
        dynamic_partitions_requests=[duckling_persons_partitions_def.build_add_request(new_partitions)]
        if new_partitions
        else [],
    )


@sensor(
    name="duckling_persons_full_backfill_sensor",
    minimum_interval_seconds=600,  # Run every 10 minutes
    job_name="duckling_persons_backfill_job",
    default_status=DefaultSensorStatus.RUNNING,
)
def duckling_persons_full_backfill_sensor(
    context: SensorEvaluationContext,
) -> SensorResult:
    """Full persons backfill sensor - one partition per team.

    Creates a single partition per team for efficient full export. Uses a single
    FINAL query to export all persons for the team in one go, rather than
    chunking by date which is expensive on ClickHouse.

    Partition format: "{team_id}" (e.g., "12345")

    Manual trigger:
        To restart from scratch, reset the cursor in Dagster UI:
        Sensors -> duckling_persons_full_backfill_sensor -> Reset cursor
    """
    backfills = list(DuckLakeBackfill.objects.filter(enabled=True).order_by("team_id"))
    if not backfills:
        context.log.info("No enabled DuckLakeBackfill entries found")
        return SensorResult(run_requests=[])

    # Check existing partitions
    existing_partitions = set(context.instance.get_dynamic_partitions("duckling_persons_backfill"))

    new_partitions: list[str] = []
    run_requests: list[RunRequest] = []

    for bf in backfills:
        team_id = bf.team_id
        partition_key = str(team_id)

        if partition_key not in existing_partitions:
            # New partition - create and trigger run
            # Batch limit to avoid timeout
            if len(new_partitions) >= BACKFILL_MONTHS_PER_TICK:
                context.log.info(f"Batch limit reached at team {team_id}")
                break

            new_partitions.append(partition_key)
            run_requests.append(
                RunRequest(
                    partition_key=partition_key,
                )
            )
            context.log.info(f"Creating full persons backfill partition for team_id={team_id}")
        else:
            # Partition exists - check if we need to retry a failed run
            runs = context.instance.get_runs(
                filters=RunsFilter(
                    job_name="duckling_persons_backfill_job",
                    tags={"dagster/partition": partition_key},
                ),
                limit=1,
            )
            if runs:
                latest_run = runs[0]
                # Only retry if failed - skip if in progress or succeeded
                if latest_run.status == DagsterRunStatus.FAILURE:
                    run_requests.append(
                        RunRequest(
                            partition_key=partition_key,
                            run_key=f"{partition_key}_persons_full_retry_{latest_run.run_id[:8]}",
                        )
                    )
                    context.log.info(f"Retrying failed full persons backfill for team_id={team_id}")
                    logger.info(
                        "duckling_persons_full_backfill_retry",
                        team_id=team_id,
                        previous_run_id=latest_run.run_id,
                    )
                elif latest_run.status in (
                    DagsterRunStatus.STARTED,
                    DagsterRunStatus.QUEUED,
                ):
                    context.log.debug(f"Skipping team_id={team_id} - run in progress")

    if new_partitions:
        context.log.info(f"Creating {len(new_partitions)} full persons backfill partitions")
        logger.info(
            "duckling_persons_full_backfill_batch",
            partition_count=len(new_partitions),
            partitions=new_partitions,
        )

    if run_requests:
        logger.info(
            "duckling_persons_full_backfill_run_requests",
            total_requests=len(run_requests),
            new_partitions=len(new_partitions),
            retries=len(run_requests) - len(new_partitions),
        )

    return SensorResult(
        run_requests=run_requests,
        dynamic_partitions_requests=[duckling_persons_partitions_def.build_add_request(new_partitions)]
        if new_partitions
        else [],
    )


duckling_persons_backfill_job = define_asset_job(
    name="duckling_persons_backfill_job",
    selection=["duckling_persons_backfill"],
    tags={
        "owner": JobOwners.TEAM_DATA_STACK.value,
        "disable_slack_notifications": True,
        **PERSONS_CONCURRENCY_TAG,
    },
)
