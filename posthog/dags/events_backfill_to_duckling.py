"""
Dagster job to backfill ClickHouse events to customer-specific ducklings.

This job exports events from ClickHouse's `posthog.events` table to customer S3 buckets
as Parquet files, then registers those files with their DuckLake catalog.

This job targets individual customer "ducklings" - isolated DuckLake instances with their
own RDS catalog and S3 bucket.

Architecture:
    DuckgresServer (duckgres connection + DuckLake catalog connection + S3 bucket name)
        │ team_id → organization_id → connection; bucket from the control plane / stored DuckgresServer row
        ▼
    ClickHouse (events table)
        │ export via s3() - bucket policy allows ClickHouse EC2 role
        ▼
    Duckling S3 Bucket (parquet files)
        │ register via ducklake_add_data_files (duckgres auto-attaches the catalog)
        ▼
    Duckling RDS Catalog (PostgreSQL)

IAM Access:
    - ClickHouse EC2 role is allowed in duckling bucket policy (direct S3 access)
    - Dagster IRSA role can assume duckling cross-account roles (for DuckDB registration)

Partition Strategy:
    DynamicPartitionsDefinition with composite keys: {team_id}_{date}
    - team_id maps to a duckling via DuckgresServerTeam (membership + enablement) + DuckgresServer (connection)
    - date is the partition date (YYYY-MM-DD)
"""

import os
import re
import math
import time
import random
import calendar
import dataclasses
from collections.abc import Callable
from contextlib import closing
from datetime import date, datetime, timedelta
from typing import Any, Literal

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
from posthog.ducklake.common import DUCKGRES_BUCKET_REGION, _get_org_id_for_team, get_duckgres_server_for_organization
from posthog.ducklake.models import DuckgresServerTeam

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


@dataclasses.dataclass(frozen=True)
class DucklingTarget:
    """Resolved per-org duckling backfill target: connection identity + S3 storage.

    Built once per run from the team's organization id. The duckgres connection is driven by
    make_duckgres_conninfo (duckgres owns catalog attachment on the connection); the S3 bucket
    is resolved by _resolve_duckling_target (control plane → stored DuckgresServer fallback).
    The control plane is the authoritative owner of the bucket name.
    """

    team_id: int
    organization_id: str
    bucket: str
    bucket_region: str
    # Default to the shared tables; _resolve_duckling_target sets these per-team from table_suffix.
    events_table: str = "events"
    persons_table: str = "persons"


def _resolve_table_names(team_id: int) -> tuple[str, str]:
    """Resolve this team's per-environment events/persons table names.

    A team's `DuckgresServerTeam.table_suffix` (when set) isolates its data into
    dedicated `events_<suffix>` / `persons_<suffix>` tables so multiple teams sharing one
    org-scoped duckling don't merge into the shared `posthog.events` / `posthog.persons`.
    An unset suffix (legacy single-team ducklings) keeps the shared table names.
    """
    suffix = DuckgresServerTeam.objects.filter(team_id=team_id).values_list("table_suffix", flat=True).first()
    if not suffix:
        return "events", "persons"
    _validate_identifier(suffix)
    return f"events_{suffix}", f"persons_{suffix}"


def _resolve_duckling_target(team_id: int) -> DucklingTarget:
    """Resolve the per-org duckling target for a backfill partition.

    The organization id (team → org) drives both the connection (make_duckgres_conninfo
    resolves the duckgres server itself) and the S3 bucket. The table names carry the team's
    per-environment suffix (or the shared defaults).

    Bucket resolution order:
      1. The control plane — the single owner of the duckling bucket name. It is consulted
         BEFORE the stored DuckgresServer row on purpose: a row provisioned before the
         naming fix carries a stale, locally-derived bucket that names an object store
         that doesn't exist, and that stale value must not win. cp_bucket_for() also
         reconciles the row so it converges for next time.
      2. The stored DuckgresServer.bucket, only as a fallback when the control plane is
         unreachable/unconfigured — so a transient CP outage doesn't fail a run whose
         bucket is already known-good.

    The bucket name is never re-derived locally — that derivation drifted from the
    Crossplane composition and produced buckets that don't exist. Fail loudly if nothing
    can name it rather than export to a guessed bucket.
    """
    from products.data_warehouse.backend.presentation.views import managed_warehouse  # noqa: PLC0415

    org_id = _get_org_id_for_team(team_id)
    events_table, persons_table = _resolve_table_names(team_id)

    # Control plane first — authoritative, and rejects an org_id-mismatched status body.
    cp_bucket = managed_warehouse.cp_bucket_for(org_id)
    if cp_bucket:
        logger.info(
            "duckling_bucket_resolved_from_control_plane",
            team_id=team_id,
            organization_id=org_id,
            bucket=cp_bucket,
        )
        return DucklingTarget(
            team_id=team_id,
            organization_id=org_id,
            bucket=cp_bucket,
            bucket_region=DUCKGRES_BUCKET_REGION,
            events_table=events_table,
            persons_table=persons_table,
        )

    # CP couldn't answer — fall back to the stored row if it knows a bucket.
    server = get_duckgres_server_for_organization(org_id)
    if server is not None and server.bucket:
        bucket, bucket_region = server.bucket, server.bucket_region or DUCKGRES_BUCKET_REGION
        logger.warning(
            "duckling_bucket_from_stored_server_control_plane_unavailable",
            team_id=team_id,
            organization_id=org_id,
            bucket=bucket,
        )
        return DucklingTarget(
            team_id=team_id,
            organization_id=org_id,
            bucket=bucket,
            bucket_region=bucket_region,
            events_table=events_table,
            persons_table=persons_table,
        )

    raise ValueError(
        f"No S3 bucket resolvable for org {org_id}: the control plane warehouse status named "
        f"none, and no stored DuckgresServer bucket to fall back to."
    )


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
def _connect_duckgres(target: DucklingTarget) -> psycopg.Connection[Any]:
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
    conninfo = make_duckgres_conninfo(
        target.team_id,
        organization_id=target.organization_id,
    )
    conn = psycopg.connect(
        conninfo,
        autocommit=True,
        connect_timeout=DUCKGRES_CONNECT_TIMEOUT,
        options=_duckgres_backfill_options(),
    )
    # Pin the session to UTC. The ranged partition DELETEs compare the TIMESTAMPTZ catalog
    # columns against bare 'YYYY-MM-DD' strings, a cast that uses the session TimeZone; with
    # ICU loaded that defaults to system-local, which would shift the half-open [day,
    # next_day) window off the UTC day the ClickHouse export wrote and strand/over-delete
    # rows at day boundaries. Best-effort: never fail a connection over this — a server that
    # doesn't expose the setting just keeps its prior (UTC-on-our-containers) behavior.
    try:
        conn.execute("SET TimeZone='UTC'")
    except Exception as exc:
        logger.warning("duckling_set_timezone_failed", error=str(exc), error_type=type(exc).__name__)
    return conn


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


# Transient S3 responses (5xx and throttling) that DuckLake surfaces back through the PG
# wire while touching object storage: glob() listing the run's files, ducklake_add_data_files
# reading Parquet footers, and the ranged DELETE's data-file rewrites. S3 occasionally returns
# 503 SlowDown/Service Unavailable or 500 InternalError under load (e.g. right after an export
# writes a fan-out of files and registration immediately lists them).
_TRANSIENT_S3_MARKERS = (
    "http 503",
    "service unavailable",
    "http 500",
    "internalerror",
    "http 429",
    "too many requests",
    "slowdown",
    "slow down",
    "reduce your request rate",
)


def _is_transient_s3_error(exc: BaseException) -> bool:
    """True when `exc` is a transient S3 5xx/throttle surfaced by duckgres while reading or
    listing object storage. Unlike _connection_dropped the worker is healthy — S3 just
    hiccuped — so it is retryable on the SAME connection (no reconnect) after a backoff.

    Gated on the message actually referencing object storage / an HTTP transport error so a
    genuine SQL error that merely contains a number like "500" can't be misclassified.
    """
    msg = str(exc).lower()
    if not any(token in msg for token in ("s3://", "http error", "http get", "http put", "http head")):
        return False
    return any(marker in msg for marker in _TRANSIENT_S3_MARKERS)


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

    def __init__(self, context: AssetExecutionContext, target: DucklingTarget) -> None:
        self._context = context
        self._target = target
        self._conn = _connect_duckgres(target)

    @property
    def conn(self) -> psycopg.Connection[Any]:
        return self._conn

    def run(self, what: str, op: Callable[[psycopg.Connection[Any]], Any]) -> Any:
        """Run `op(conn)`, retrying on two recoverable failure classes:

          * worker/connection drop mid-statement → reconnect to a fresh worker and replay;
          * transient S3 5xx/throttle while touching object storage → replay on the SAME
            connection (the worker is healthy) after a backoff.

        Any other (genuine SQL/logic) error propagates immediately. The last recoverable
        error is re-raised once the attempt budget is exhausted. `op` MUST be idempotent —
        a replay can re-run an already-applied op (see the class docstring).
        """
        last_exc: Exception | None = None
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            try:
                return op(self._conn)
            except Exception as exc:
                dropped = _connection_dropped(exc)
                transient_s3 = _is_transient_s3_error(exc)
                if not (dropped or transient_s3):
                    raise
                last_exc = exc
                if attempt == self.MAX_ATTEMPTS:
                    break
                if dropped:
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
                else:
                    # Transient S3 hiccup — the worker is fine, just back off and replay.
                    self._context.log.warning(
                        f"transient S3 error during {what} "
                        f"(attempt {attempt}/{self.MAX_ATTEMPTS}); retrying after backoff: {exc}"
                    )
                    logger.warning(
                        "duckling_duckgres_transient_s3_retry",
                        what=what,
                        attempt=attempt,
                        error=str(exc),
                        error_type=type(exc).__name__,
                    )
                time.sleep(min(2**attempt, 30))
        assert last_exc is not None  # only reached after a recoverable-error break
        raise last_exc

    def _reconnect(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
        self._conn = _connect_duckgres(self._target)

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
EXPECTED_DUCKLAKE_EVENTS_COLUMNS = {
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

# Fan a single export out across many right-sized Parquet files instead of one
# monster object. ClickHouse PARTITION BY with a {_partition_id} placeholder in the
# S3 path emits one file per bucket, so an export becomes ~fanout files. The
# year/month/day Hive layout (and DuckLake's matching SET PARTITIONED BY) is
# unchanged — only the number of files inside each day= directory grows, which is
# what gives reads parallelism and keeps per-file scans cheap. Bucketing on a hash
# of distinct_id spreads rows evenly and keeps each file independently scannable.
#
# The fan-out is computed PER EXPORT from a cheap row-count estimate, not fixed:
# team-day volumes span many orders of magnitude (a top team's day is tens of
# millions of rows; a small team's is a handful), so one constant would either
# leave huge days as monster files or shatter tiny days into a swarm of near-empty
# objects. We target ~TARGET_ROWS_PER_FILE rows per file and clamp to
# [1, MAX_S3_FILE_FANOUT]. Row count (not bytes) is the signal because it's the
# dominant driver of file size and the only one ClickHouse estimates cheaply from
# the primary key without scanning the wide columns; wide-row teams can be tuned via
# the per-run config. At ~4KB/event-row, 5M rows lands a file near ~20GB.
#
# Larger files also mean fewer per-file DuckLake catalog commits: each Parquet
# file registered via `ducklake_add_data_files` is its own autocommit'd
# transaction, so the fan-out target directly sets the write-side commit rate
# a downstream reader (e.g. viaduck) has to contend with under DuckLake's
# per-table OCC.
#
# MAX_S3_FILE_FANOUT is bounded by WRITER MEMORY, not file count: ClickHouse's
# PartitionedSink keeps one Parquet writer open per active bucket for the whole
# INSERT (a footer is written only at stream close), and a uniform hash key activates
# all N buckets at once. Each writer buffers at most one in-progress row group, so
# peak ≈ N × output_format_parquet_row_group_size_bytes (× parallel-encoding
# overhead). With that byte cap pinned to 128 MiB (see PARQUET_WRITER_SETTINGS),
# 256 × 128 MiB ≈ 32 GiB stays comfortably under the 100 GiB max_memory_usage ceiling.
# N may exceed ClickHouse's max_partitions_per_insert_block (default 100) safely —
# that limit gates MergeTree part creation, not the s3() PartitionedSink.
TARGET_ROWS_PER_FILE = 5_000_000
MAX_S3_FILE_FANOUT = 256

# Parquet writer settings shared by every export. The byte cap is the load-bearing one:
# it bounds each open partition writer's in-progress row group, so aggregate writer
# memory scales as fan-out × this value (see MAX_S3_FILE_FANOUT). For wide event rows it
# is also the binding row-group flush trigger (the row pin below only binds for the
# narrower persons rows, which flush on rows first). 128 MiB row groups stay large enough
# for efficient DuckLake/DuckDB reads while keeping high-fan-out writes within budget.
PARQUET_WRITER_SETTINGS: dict[str, Any] = {
    "output_format_parquet_row_group_size_bytes": 128 * 1024 * 1024,  # 128 MiB — bounds per-partition writer memory
    "output_format_parquet_row_group_size": 250_000,  # secondary cap; binds for narrow persons rows
}

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
CREATE TABLE IF NOT EXISTS {catalog}.posthog.{table} (
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
CREATE TABLE IF NOT EXISTS {catalog}.posthog.{table} (
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
    # Dynamic S3 fan-out: each export is split into ~ceil(row_count / target_rows_per_file)
    # Parquet files, clamped to [1, max_s3_file_fanout]. Huge team-days produce many
    # right-sized files; tiny ones stay a single file. The fan-out also drives writer
    # memory (peak ≈ fan-out × per-partition row-group buffer; see PARQUET_WRITER_SETTINGS),
    # so for teams with unusually wide rows, lowering target_rows_per_file both keeps files
    # in range AND raises fan-out — pair it with a lower max_s3_file_fanout if memory is tight.
    target_rows_per_file: int = TARGET_ROWS_PER_FILE
    max_s3_file_fanout: int = MAX_S3_FILE_FANOUT


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
    target: DucklingTarget,
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
    table = target.events_table

    if table_exists(conn, alias, "posthog", table):
        context.log.info("Events table already exists in duckling catalog")
        # Ensure partitioning is set even on existing tables (idempotent)
        _set_table_partitioning(
            conn,
            alias,
            table,
            "year(timestamp), month(timestamp), day(timestamp)",
            context,
            target.team_id,
        )
        return False

    context.log.info("Creating posthog schema if it doesn't exist...")
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {alias}.posthog")

    context.log.info("Creating events table in duckling catalog...")
    conn.execute(EVENTS_TABLE_DDL.format(catalog=alias, table=table))
    context.log.info("Successfully created events table")

    # Set partitioning by year/month/day for efficient querying
    _set_table_partitioning(
        conn,
        alias,
        table,
        "year(timestamp), month(timestamp), day(timestamp)",
        context,
        target.team_id,
    )

    logger.info(
        "duckling_events_table_created",
        team_id=target.team_id,
        bucket=target.bucket,
    )
    return True


def ensure_persons_table_exists(
    context: AssetExecutionContext,
    target: DucklingTarget,
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
    table = target.persons_table

    if table_exists(conn, alias, "posthog", table):
        context.log.info("Persons table already exists in duckling catalog")
        # Ensure partitioning is set even on existing tables (idempotent)
        _set_table_partitioning(
            conn,
            alias,
            table,
            "year(_timestamp), month(_timestamp)",
            context,
            target.team_id,
        )
        return False

    context.log.info("Creating posthog schema if it doesn't exist...")
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {alias}.posthog")

    context.log.info("Creating persons table in duckling catalog...")
    conn.execute(PERSONS_TABLE_DDL.format(catalog=alias, table=table))
    context.log.info("Successfully created persons table")

    # Set partitioning by year/month of _timestamp for efficient querying
    _set_table_partitioning(
        conn,
        alias,
        table,
        "year(_timestamp), month(_timestamp)",
        context,
        target.team_id,
    )

    logger.info(
        "duckling_persons_table_created",
        team_id=target.team_id,
        bucket=target.bucket,
    )
    return True


def validate_duckling_schema(
    context: AssetExecutionContext,
    target: DucklingTarget,
    conn: psycopg.Connection[Any],
) -> None:
    """Validate that the duckling's events table schema matches our export columns.

    This pre-flight check ensures we don't waste time exporting data that can't
    be registered with DuckLake due to schema mismatches.
    """
    alias = DUCKLAKE_ALIAS

    with conn.cursor() as cur:
        cur.execute(f"DESCRIBE {alias}.posthog.{target.events_table}")
        ducklake_columns = {row[0] for row in cur.fetchall()}

    missing_in_ducklake = EXPECTED_DUCKLAKE_EVENTS_COLUMNS - ducklake_columns
    if missing_in_ducklake:
        context.log.warning(
            f"Duckling events table is missing columns that we export: {missing_in_ducklake}. "
            "These columns will be added automatically by ducklake_add_data_files if the table "
            "supports schema evolution."
        )
        logger.warning(
            "duckling_schema_mismatch",
            team_id=target.team_id,
            missing_columns=list(missing_in_ducklake),
        )

    extra_in_ducklake = ducklake_columns - EXPECTED_DUCKLAKE_EVENTS_COLUMNS
    if extra_in_ducklake:
        context.log.info(f"Duckling has additional columns not in our export: {extra_in_ducklake}")

    context.log.info(
        f"Schema validation passed. Duckling has {len(ducklake_columns)} columns, "
        f"we export {len(EXPECTED_DUCKLAKE_EVENTS_COLUMNS)} columns."
    )
    logger.info(
        "duckling_schema_validation_passed",
        team_id=target.team_id,
        ducklake_columns=len(ducklake_columns),
        export_columns=len(EXPECTED_DUCKLAKE_EVENTS_COLUMNS),
    )


def validate_duckling_persons_schema(
    context: AssetExecutionContext,
    target: DucklingTarget,
    conn: psycopg.Connection[Any],
) -> None:
    """Validate that the duckling's persons table schema matches our export columns."""
    alias = DUCKLAKE_ALIAS

    with conn.cursor() as cur:
        cur.execute(f"DESCRIBE {alias}.posthog.{target.persons_table}")
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
            team_id=target.team_id,
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
        team_id=target.team_id,
        ducklake_columns=len(ducklake_columns),
        export_columns=len(EXPECTED_DUCKLAKE_PERSONS_COLUMNS),
    )


def _compute_fanout(row_count: int, target_rows_per_file: int, max_fanout: int) -> int:
    """Pick how many Parquet files to split an export into.

    Sizes the fan-out to the export's actual volume: one file per ~target_rows_per_file
    rows, clamped to [1, max_fanout]. A near-empty export collapses to a single file; a
    tens-of-millions-of-rows day spreads across many right-sized files.

    Pure arithmetic — no ClickHouse I/O, so no retry decorator (the count that feeds it
    is retried in _estimate_export_row_count).

    Fails closed to a single file on an empty export or a non-positive config (these are
    user-tunable, so a 0 target must not divide-by-zero the backfill).
    """
    if row_count <= 0 or target_rows_per_file <= 0 or max_fanout <= 0:
        return 1
    return max(1, min(math.ceil(row_count / target_rows_per_file), max_fanout))


@retry(
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    retry=retry_if_exception_type((ClickHouseError, OSError, TimeoutError)),
    reraise=True,
)
def _estimate_export_row_count(client: Client, count_sql: str, settings: dict[str, Any]) -> int:
    """Cheap row-count estimate used to size the export fan-out.

    `count()` over a team-day reads only the primary-key marks (team_id is the leading
    key), so it does not scan the wide event/person columns the export itself streams.
    Retried like the export itself — it's the only other ClickHouse call on the path, and
    a transient failure here shouldn't fail the whole partition before the INSERT runs.
    """
    result = client.execute(count_sql, settings=settings)
    return int(result[0][0]) if result and result[0] else 0


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
    target: DucklingTarget,
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
    DELETE FROM {alias}.posthog.{target.events_table}
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
    target: DucklingTarget,
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
        DELETE FROM {alias}.posthog.{target.persons_table}
        WHERE team_id = %s
        """
        delete_params = (team_id,)
    else:
        date_str = partition_date.strftime("%Y-%m-%d")
        next_date_str = (partition_date + timedelta(days=1)).strftime("%Y-%m-%d")
        delete_sql = f"""
        DELETE FROM {alias}.posthog.{target.persons_table}
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
    target: DucklingTarget,
    team_id: int,
    date: datetime,
    run_id: str,
    settings: dict[str, Any],
) -> str | None:
    """Export events for a team/date to the duckling's S3 bucket.

    The day is fanned out across a volume-sized number of Parquet files via ClickHouse
    PARTITION BY rather than one giant per-day object (see _compute_fanout).

    ClickHouse uses its EC2 instance role for S3 access. The duckling bucket policy
    explicitly allows the ClickHouse EC2 role, so no explicit credentials are needed.

    Returns:
        S3 glob matching every file this run produced for the day, or None if dry_run.
    """
    year = date.strftime("%Y")
    month = date.strftime("%m")
    day = date.strftime("%d")
    date_str = date.strftime("%Y-%m-%d")

    day_dir = f"{BACKFILL_EVENTS_S3_PREFIX}/{team_id}/year={year}/month={month}/day={day}"

    # {_partition_id} is substituted by ClickHouse per PARTITION BY bucket, so one
    # INSERT emits {run_id}_0.parquet … {run_id}_{N-1}.parquet. The run_id prefix
    # keeps each run's files isolated: a re-run writes a fresh set, and registration
    # globs only this run's files (see register_files_with_duckling), so a replay can
    # never re-register a prior run's objects. Prior runs' physical files are left in
    # place — they're orphaned from the catalog by the DELETE-before-register step and
    # are harmless; deleting registered S3 files would corrupt the catalog.
    partition_path = f"{day_dir}/{run_id}_{{_partition_id}}.parquet"
    file_glob = f"{day_dir}/{run_id}_*.parquet"

    # ClickHouse needs HTTPS URL format for cross-account S3 access
    s3_url = get_s3_url_for_clickhouse(target.bucket, target.bucket_region, partition_path)

    # S3 glob with scheme that registration enumerates to find every produced file
    s3_glob = f"s3://{target.bucket}/{file_glob}"

    where_clause = f"team_id = {team_id} AND toDate(timestamp) = '{date_str}'"

    # Event rows are wide (large properties/person_properties JSON). With PARTITION BY,
    # writer memory is dominated by the per-partition row-group buffers (one open writer
    # per active bucket), so we cap the row group by bytes via PARQUET_WRITER_SETTINGS;
    # the 100 GiB ceiling is headroom on top. See the PARQUET_WRITER_SETTINGS /
    # MAX_S3_FILE_FANOUT comments for the fan-out × buffer memory model.
    export_settings = settings.copy()
    export_settings.update(PARQUET_WRITER_SETTINGS)
    export_settings["max_memory_usage"] = 100 * 1024 * 1024 * 1024  # 100GB, matching the full-persons export

    info = f"team_id={team_id}, date={date_str}"

    if config.dry_run:
        context.log.info(
            f"[DRY RUN] Would estimate row count for {info} and fan the export across up to "
            f"{config.max_s3_file_fanout} files (~{config.target_rows_per_file} rows/file) to {s3_glob}"
        )
        return None

    # Size the fan-out to this team-day's actual volume.
    row_count = _estimate_export_row_count(client, f"SELECT count() FROM events WHERE {where_clause}", settings)
    fanout = _compute_fanout(row_count, config.target_rows_per_file, config.max_s3_file_fanout)

    # ClickHouse uses its EC2 instance role - no credentials needed
    # The duckling bucket policy allows the ClickHouse EC2 role
    export_sql = f"""
    INSERT INTO FUNCTION s3(
        '{s3_url}',
        'Parquet'
    )
    PARTITION BY toString(cityHash64(distinct_id) % {fanout})
    SELECT
        {EVENTS_COLUMNS}
    FROM events
    WHERE {where_clause}
    SETTINGS s3_truncate_on_insert=1, use_hive_partitioning=0
    """

    context.log.info(f"Exporting events for {info} ({row_count} rows → {fanout} file(s)) to {s3_glob}")
    logger.info(
        "duckling_export_start",
        team_id=team_id,
        date=date_str,
        s3_glob=s3_glob,
        row_count=row_count,
        fanout=fanout,
    )

    try:
        _execute_export_with_retry(client, export_sql, export_settings, info)
        context.log.info(f"Successfully exported events for {info}")
        logger.info("duckling_export_success", team_id=team_id, date=date_str)
        return s3_glob
    except Exception:
        context.log.exception(f"Failed to export events for {info} after {MAX_RETRY_ATTEMPTS} attempts")
        logger.exception("duckling_export_failed", team_id=team_id, date=date_str)
        raise


def _glob_run_files(conn: psycopg.Connection[Any], s3_glob: str) -> list[str]:
    """Enumerate the Parquet files a fanned-out export produced for one run.

    The export writes a variable (and possibly empty) number of files — one per
    non-empty PARTITION BY bucket — so registration discovers them by globbing the
    run's output rather than predicting names. The glob is run-scoped, so it never
    returns a prior run's objects.

    A zero-event team-day is normal in a historical backfill: ClickHouse writes no
    Parquet for an empty partition, so the glob matches nothing. duckgres returns
    that empty glob as a command-complete with no result set (rather than an empty
    row set), which psycopg surfaces as "the last operation didn't produce a result"
    when the rows are fetched — catch that and treat it as "no files".
    """
    with conn.cursor() as cur:
        cur.execute("SELECT file FROM glob(%s) ORDER BY file", (s3_glob,))
        try:
            rows = cur.fetchall()
        except psycopg.ProgrammingError as exc:
            if "didn't produce a result" in str(exc):
                return []
            raise
        return [row[0] for row in rows]


# ---------------------------------------------------------------------------
# DuckLake ducklake_file_partition_value post-write fix-up
# ---------------------------------------------------------------------------
# Workaround for a DuckLake bug in ducklake_add_data_files(): when a partition
# spec applies multiple transforms to one source column (events: year/month/day
# on `timestamp`; persons: year/month on `_timestamp`), every ducklake_file_partition_value row lands at
# the HIGHEST partition_key_index instead of being spread across the spec's
# columns. Tier-3 compaction then fails with "Files have different hive
# partition path", and partition pruning silently misses files.
#
# Bug writeup: see PR #67168 (the workaround landing this fix-up).
# Buggy code:  ducklake src/functions/ducklake_add_data_files.cpp — see the
#              `field_partition_key_map` map keyed bare `field_id.index` and
#              the loop in `MapPartitionColumns` (line numbers will rot).
#
# Failure semantics: this fix-up raises RuntimeError on any inconsistency
# (catalog unreachable, spec drift, post-condition fail). _DuckgresSession.run
# only retries _connection_dropped exceptions, so a ducklake_file_partition_value failure is terminal
# for the partition — Dagster asset-level retry recovers, not the duckgres
# replay loop. Failures are convergent if retried because DELETE-then-INSERT
# of the same paths produces the same end state.

_DUCKLAKE_FILE_PARTITION_VALUE_FIXUP_ENV_VAR = "DUCKLAKE_FILE_PARTITION_VALUE_FIXUP_ENABLED"

# Catalog Postgres connect timeout. NOT shared with DUCKGRES_CONNECT_TIMEOUT —
# duckgres needs minutes for a cold-start worker; plain Postgres connects in
# under a second.
_DUCKLAKE_FILE_PARTITION_VALUE_CATALOG_CONNECT_TIMEOUT = 10

# Bound for the per-batch fix-up: DML + post-condition (the advisory lock
# acquisition is OUTSIDE the txn — see _acquire_*_session_advisory_lock).
_DUCKLAKE_FILE_PARTITION_VALUE_STATEMENT_TIMEOUT = "60s"
# Bound for any single row-lock wait inside the txn (defense in depth — the
# session advisory lock already serializes us against other maintenance ops).
_DUCKLAKE_FILE_PARTITION_VALUE_LOCK_TIMEOUT = "5s"

# pg_try_advisory_lock retry (session-scoped): bounded so a hung maintainer
# can't block a backfill step forever. Sleeps happen OUTSIDE any open txn.
_DUCKLAKE_FILE_PARTITION_VALUE_LOCK_RETRY_ATTEMPTS = 6
_DUCKLAKE_FILE_PARTITION_VALUE_LOCK_RETRY_BASE_SECONDS = 1.0
_DUCKLAKE_FILE_PARTITION_VALUE_LOCK_RETRY_MAX_SECONDS = 8.0

# Per-table partition spec: (partition_key_index, transform name). Transform
# names mirror the hive segment names in the S3 paths produced by the dagster
# exports AND the live catalog (ducklake_partition_column.transform). Asserted
# at runtime against the live catalog before any DML — drift fails loud.
_DUCKLAKE_FILE_PARTITION_VALUE_SPEC: dict[str, tuple[tuple[int, str], ...]] = {
    "events": ((0, "year"), (1, "month"), (2, "day")),
    "persons": ((0, "year"), (1, "month")),
}

# Pre-flight: every registered path must carry the spec's hive segments. Fail
# loud before any catalog DML — a NULL partition_value insert would produce a
# third class of catalog rot worse than the bug itself.
_DUCKLAKE_FILE_PARTITION_VALUE_PATH_REGEXES: dict[str, re.Pattern[str]] = {
    # Persons "full" export writes year=0/month=0 (export_persons_full_to_duckling_s3),
    # so accept any digit width on both tables.
    "events": re.compile(r"/year=\d+/month=\d+/day=\d+/[^/]+\.parquet$"),
    "persons": re.compile(r"/year=\d+/month=\d+/[^/]+\.parquet$"),
}


def _ducklake_file_partition_value_fixup_enabled() -> bool:
    return os.environ.get(_DUCKLAKE_FILE_PARTITION_VALUE_FIXUP_ENV_VAR, "true").lower() in ("1", "true", "yes", "on")


def _open_catalog_conn(target: DucklingTarget) -> psycopg.Connection[Any]:
    server = get_duckgres_server_for_organization(target.organization_id)
    if server is None or not server.catalog_host:
        raise RuntimeError(
            f"DuckgresServer with catalog_* fields not found for organization_id={target.organization_id}; "
            f"set {_DUCKLAKE_FILE_PARTITION_VALUE_FIXUP_ENV_VAR}=false to skip the "
            f"ducklake_file_partition_value fix-up (loses bug coverage)."
        )
    return psycopg.connect(
        host=server.catalog_host,
        port=server.catalog_port,
        dbname=server.catalog_database,
        user=server.catalog_username,
        password=server.catalog_password,
        autocommit=False,
        connect_timeout=_DUCKLAKE_FILE_PARTITION_VALUE_CATALOG_CONNECT_TIMEOUT,
    )


def _acquire_ducklake_file_partition_value_session_advisory_lock(conn: Any) -> None:
    # Bounded retry on the session-scoped pg_try_advisory_lock so a stuck
    # maintainer can't hang a backfill step indefinitely (pg_advisory_lock would
    # block forever). Session-scoped — not xact-scoped — so the retry backoffs
    # happen OUTSIDE any open Postgres transaction; sleeping inside an open txn
    # would leave the connection idle-in-transaction, which blocks vacuum and
    # accumulates xid age. Caller must release via the matching `_release_*`
    # helper, and must have set conn.autocommit=True before calling.
    for attempt in range(_DUCKLAKE_FILE_PARTITION_VALUE_LOCK_RETRY_ATTEMPTS):
        with conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(hashtext('millpond-ducklake-maintenance')::bigint)")
            row = cur.fetchone()
        if row is None:
            raise RuntimeError("pg_try_advisory_lock returned no row — Postgres protocol invariant violated")
        if row[0]:
            return
        backoff = min(
            _DUCKLAKE_FILE_PARTITION_VALUE_LOCK_RETRY_MAX_SECONDS,
            _DUCKLAKE_FILE_PARTITION_VALUE_LOCK_RETRY_BASE_SECONDS * (2**attempt),
        )
        time.sleep(backoff * (0.5 + random.random()))
    raise RuntimeError(
        f"ducklake_file_partition_value fix-up: could not acquire millpond-ducklake-maintenance advisory lock "
        f"after {_DUCKLAKE_FILE_PARTITION_VALUE_LOCK_RETRY_ATTEMPTS} attempts"
    )


def _release_ducklake_file_partition_value_session_advisory_lock(conn: Any) -> None:
    # Best-effort: if the connection is already gone, Postgres releases the
    # session-scoped lock on disconnect anyway. Caller must have set
    # conn.autocommit=True before calling so the unlock SELECT doesn't
    # implicitly start a transaction. We deliberately don't read the unlock
    # return value — `false` (didn't hold the lock) would mean the connection
    # is about to drop it anyway via `closing(...)`, so the extra roundtrip
    # is noise.
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(hashtext('millpond-ducklake-maintenance')::bigint)")
    except (psycopg.Error, OSError) as exc:
        # Narrowed to the catalog/transport error classes that the unlock SELECT
        # can actually raise. Anything else (programming bug, etc.) propagates.
        logger.warning(
            "duckling_ducklake_file_partition_value_fixup_release_failed",
            error=str(exc),
            error_type=type(exc).__name__,
        )


def _assert_live_spec_matches(
    cur: Any,
    table_kind: Literal["events", "persons"],
    table_name: str,
    table_id: int,
    partition_id: int,
) -> None:
    # The fix-up bakes _DUCKLAKE_FILE_PARTITION_VALUE_SPEC into the SQL it emits. If the live catalog spec
    # drifts (someone runs ALTER ... SET PARTITIONED BY, or a future writer
    # version reshapes things), we'd silently mis-index rows. Cheap one-SELECT
    # defense against that whole class. table_kind ("events"/"persons") keys
    # the spec; table_name is the actual catalog name and may carry a per-team
    # suffix (events_<suffix> / persons_<suffix>) — the spec is the same for
    # every suffix variant since the partition layout doesn't change.
    cur.execute(
        """
        SELECT partition_key_index, transform
        FROM public.ducklake_partition_column
        WHERE partition_id = %s AND table_id = %s
        ORDER BY partition_key_index
        """,
        (partition_id, table_id),
    )
    actual = tuple((int(idx), str(transform)) for idx, transform in cur.fetchall())
    expected = _DUCKLAKE_FILE_PARTITION_VALUE_SPEC[table_kind]
    if actual != expected:
        raise RuntimeError(
            f"ducklake_file_partition_value fix-up: live catalog spec for posthog.{table_name} "
            f"(kind={table_kind}, partition_id={partition_id}) is {actual}; expected {expected}. "
            f"Update _DUCKLAKE_FILE_PARTITION_VALUE_SPEC and redeploy before re-enabling the fix-up."
        )


def _fixup_partition_values_for_added_files(
    context: AssetExecutionContext,
    target: DucklingTarget,
    table_kind: Literal["events", "persons"],
    table_name: str,
    file_paths: list[str],
) -> None:
    # Repair ducklake_file_partition_value rows for files just registered via ducklake_add_data_files().
    # table_kind is the logical kind ("events" or "persons") used to look up the
    # spec + path regex; table_name is the actual catalog table the files were
    # registered into and may carry a per-team suffix (events_<suffix> /
    # persons_<suffix>) per DuckgresServerTeam.table_suffix. The dagster
    # registration path writes files for the suffixed table while keeping the
    # S3 prefix (backfill/events/.../) tied to the kind, not the suffix.
    # Raises RuntimeError on any inconsistency; see module-level block for the
    # failure-semantics contract. Convergent and idempotent.
    if not file_paths:
        return

    spec = _DUCKLAKE_FILE_PARTITION_VALUE_SPEC.get(table_kind)
    path_regex = _DUCKLAKE_FILE_PARTITION_VALUE_PATH_REGEXES.get(table_kind)
    if spec is None or path_regex is None:
        raise ValueError(f"_DUCKLAKE_FILE_PARTITION_VALUE_SPEC has no entry for table_kind={table_kind!r}")

    unparseable = [p for p in file_paths if not path_regex.search(p)]
    if unparseable:
        sample = ", ".join(unparseable[:3])
        raise ValueError(
            f"ducklake_file_partition_value fix-up: {len(unparseable)} of {len(file_paths)} "
            f"{table_kind} (in {table_name}) path(s) do not match the expected hive layout (sample: {sample})"
        )

    expected_index_set = [idx for idx, _ in spec]

    # closing(...) actually closes the connection on exit; psycopg3's Connection
    # context manager only commits/rolls back the open txn. We acquire the
    # session advisory lock OUTSIDE the main txn (autocommit=True during
    # acquisition) so retry backoffs don't sit idle-in-transaction; switch to
    # autocommit=False to drive the BEGIN→COMMIT (clean) or BEGIN→ROLLBACK
    # (exception) via the inner `with conn:`; finally, switch back to
    # autocommit=True to release the session lock (best-effort — PG releases
    # it on disconnect anyway, so the `closing(...)` exit is the backstop).
    with closing(_open_catalog_conn(target)) as catalog_conn:
        catalog_conn.autocommit = True
        _acquire_ducklake_file_partition_value_session_advisory_lock(catalog_conn)
        try:
            catalog_conn.autocommit = False
            with catalog_conn, catalog_conn.cursor() as cur:
                # Bound any single statement so a misbehaving server can't hang
                # the step. SET LOCAL is scoped to this txn — no global side effect.
                cur.execute(
                    psql.SQL("SET LOCAL statement_timeout = {}").format(
                        psql.Literal(_DUCKLAKE_FILE_PARTITION_VALUE_STATEMENT_TIMEOUT)
                    )
                )
                cur.execute(
                    psql.SQL("SET LOCAL lock_timeout = {}").format(
                        psql.Literal(_DUCKLAKE_FILE_PARTITION_VALUE_LOCK_TIMEOUT)
                    )
                )

                cur.execute(
                    """
                    SELECT t.table_id, pi.partition_id
                    FROM public.ducklake_table t
                    JOIN public.ducklake_schema s
                      ON s.schema_id = t.schema_id AND s.end_snapshot IS NULL
                    JOIN public.ducklake_partition_info pi
                      ON pi.table_id = t.table_id AND pi.end_snapshot IS NULL
                    WHERE s.schema_name = 'posthog'
                      AND t.table_name = %s
                      AND t.end_snapshot IS NULL
                    """,
                    (table_name,),
                )
                rows = cur.fetchall()
                if len(rows) != 1:
                    raise RuntimeError(
                        f"ducklake_file_partition_value fix-up: expected exactly one live partition_info "
                        f"for posthog.{table_name}, got {len(rows)}"
                    )
                table_id, partition_id = rows[0]

                _assert_live_spec_matches(cur, table_kind, table_name, table_id, partition_id)

                # Single-statement DELETE + INSERT so no reader sees zero ducklake_file_partition_value rows.
                # DELETE is scoped by table_id AND data_file_id (defense in depth).
                # The INSERT runs unconditionally over `to_repair`. Do NOT add a
                # defensive `WHERE EXISTS (... deleted)` or scalar-subquery
                # reference — that filters out target files whose DELETE returned
                # 0 rows (e.g., a file that arrived with no fpv rows at all),
                # leaving them stuck. `deleted` is intentionally unreferenced:
                # per PG docs §7.8.2, data-modifying CTEs in WITH execute exactly
                # once "always to completion, independently of whether the
                # primary query reads all (or indeed any) of their output."
                insert_branches = psql.SQL(" UNION ALL ").join(
                    psql.SQL(
                        "SELECT t.data_file_id, {tid}, {idx}, "
                        "(substring(t.path from {hive_re}))::INT::TEXT "
                        "FROM targets t"
                    ).format(
                        tid=psql.Literal(table_id),
                        idx=psql.Literal(key_index),
                        hive_re=psql.Literal(f"{col_name}=([0-9]+)"),
                    )
                    for key_index, col_name in spec
                )
                stmt = psql.SQL(
                    """
                    WITH targets AS (
                        SELECT data_file_id, path
                        FROM public.ducklake_data_file
                        WHERE table_id = {tid}
                          AND end_snapshot IS NULL
                          AND partition_id = {pid}
                          AND path = ANY(%s)
                    ),
                    deleted AS (
                        DELETE FROM public.ducklake_file_partition_value
                        WHERE table_id = {tid}
                          AND data_file_id IN (SELECT data_file_id FROM targets)
                        RETURNING data_file_id
                    )
                    INSERT INTO public.ducklake_file_partition_value
                        (data_file_id, table_id, partition_key_index, partition_value)
                    {inserts}
                    """
                ).format(
                    tid=psql.Literal(table_id),
                    pid=psql.Literal(partition_id),
                    inserts=insert_branches,
                )
                # file_paths bound via %s (not psql.Literal of a list) so the
                # statement text stays small and statement-cache-friendly even for
                # large batches. Keep file_paths a list — psycopg3 maps list[str]
                # to PG text[]; a tuple would map to a record instead.
                cur.execute(stmt, (list(file_paths),))

                # Post-condition: every file's actual partition_key_index set equals
                # the expected set, and no NULL partition_value rows landed. The
                # set-equality catches the bug pattern (multiple rows at the
                # highest index) that a naive count check would miss.
                cur.execute(
                    psql.SQL(
                        """
                        WITH file_partition_value_state AS (
                            SELECT df.data_file_id,
                                   COALESCE(
                                       array_agg(file_partition_value.partition_key_index
                                                 ORDER BY file_partition_value.partition_key_index)
                                       FILTER (WHERE file_partition_value.partition_key_index IS NOT NULL),
                                       '{{}}'::bigint[]
                                   ) AS indexes,
                                   COUNT(*) FILTER (WHERE file_partition_value.partition_value IS NULL) AS nulls
                            FROM public.ducklake_data_file df
                            LEFT JOIN public.ducklake_file_partition_value file_partition_value
                              ON file_partition_value.data_file_id = df.data_file_id
                             AND file_partition_value.table_id = {tid}
                            WHERE df.table_id = {tid}
                              AND df.end_snapshot IS NULL
                              AND df.path = ANY(%s)
                            GROUP BY df.data_file_id
                        )
                        SELECT
                            COUNT(*) FILTER (WHERE indexes IS DISTINCT FROM %s::bigint[]) AS wrong_indexes,
                            COUNT(*) FILTER (WHERE nulls > 0)                          AS null_values,
                            COUNT(*) AS total
                        FROM file_partition_value_state
                        """
                    ).format(tid=psql.Literal(table_id)),
                    (list(file_paths), expected_index_set),
                )
                post_condition_row = cur.fetchone()
                if post_condition_row is None:
                    raise RuntimeError(
                        "post-condition aggregate returned no row — Postgres protocol invariant violated"
                    )
                wrong_indexes, null_values, total = post_condition_row

                if wrong_indexes != 0 or null_values != 0 or total != len(file_paths):
                    # Raise inside the `with catalog_conn` block so the context
                    # manager rolls back; no explicit rollback needed. logger.error
                    # (not .exception) since we're not inside an except block — no
                    # live exception to capture a traceback from.
                    logger.error(
                        "duckling_ducklake_file_partition_value_fixup_post_condition_failed",
                        table_kind=table_kind,
                        table_name=table_name,
                        organization_id=target.organization_id,
                        team_id=target.team_id,
                        wrong_indexes=wrong_indexes,
                        null_values=null_values,
                        actual_total=total,
                        expected_total=len(file_paths),
                    )
                    raise RuntimeError(
                        f"ducklake_file_partition_value fix-up post-condition failed for {table_name}: "
                        f"wrong_indexes={wrong_indexes}, null_values={null_values}, "
                        f"total={total}, expected_total={len(file_paths)}"
                    )
        finally:
            # Release the session-scoped lock. Skip if the conn has been closed
            # mid-flight (e.g., transport drop during DML) — toggling autocommit
            # on a closed conn raises InterfaceError, which would mask the
            # original exception. PG releases session locks on disconnect
            # anyway, so there's nothing to do.
            if not catalog_conn.closed:
                catalog_conn.autocommit = True
                _release_ducklake_file_partition_value_session_advisory_lock(catalog_conn)

    context.log.info(
        f"ducklake_file_partition_value fix-up: rebuilt partition values for {len(file_paths)} {table_name} file(s)"
    )
    logger.info(
        "duckling_ducklake_file_partition_value_fixup_succeeded",
        table_kind=table_kind,
        table_name=table_name,
        organization_id=target.organization_id,
        team_id=target.team_id,
        files_rewritten=len(file_paths),
    )


def register_files_with_duckling(
    context: AssetExecutionContext,
    target: DucklingTarget,
    s3_glob: str,
    config: DucklingBackfillConfig,
    conn: psycopg.Connection[Any],
) -> int:
    """Register every Parquet file a fanned-out events export produced.

    A team-day export now emits many files, so this globs the run's output and
    registers each one exactly once. Cross-account S3 access is configured
    server-side on the duckling's duckgres via IRSA, so the DAG only needs a pgwire
    connection.

    DuckLake transaction conflicts are retried server-side by duckgres. Connection
    retries live in the caller — this helper operates on a connection it doesn't own.
    Because ducklake_add_data_files APPENDS with no dedup-by-path, the caller must
    have cleared the day's existing rows (DELETE) before calling, so a replay can't
    double-register.

    Args:
        context: Dagster asset execution context.
        target: The resolved duckling target (duckgres connection identity + S3 bucket).
        s3_glob: S3 glob matching every file this run produced for the day.
        config: Job configuration.
        conn: psycopg connection to the org's duckgres server.

    Returns:
        Number of files registered (0 if skipped, dry_run, or the day was empty).
    """
    if config.skip_ducklake_registration:
        context.log.info("Skipping DuckLake registration (skip_ducklake_registration=True)")
        return 0

    if config.dry_run:
        context.log.info(
            f"[DRY RUN] Would register files matching {s3_glob} with DuckLake (org {target.organization_id})"
        )
        return 0

    alias = DUCKLAKE_ALIAS

    try:
        files = _glob_run_files(conn, s3_glob)
        if not files:
            context.log.info(f"No files produced for {s3_glob}, nothing to register")
            return 0

        context.log.info(f"Registering {len(files)} file(s) with DuckLake from {s3_glob}")
        for s3_path in files:
            # allow_missing tolerates columns the live ingestion path added to the
            # duckling table via schema evolution but the backfill export doesn't carry.
            # Safe because the export SELECT is a fixed column set — a missing critical
            # column (team_id/uuid/timestamp) would only arise from an export bug, not
            # normal operation, and would surface as NULL-filled rows in downstream reads.
            conn.execute(
                psql.SQL("CALL ducklake_add_data_files({}, {}, {}, schema => 'posthog', allow_missing => true)").format(
                    psql.Literal(alias),
                    psql.Literal(target.events_table),
                    psql.Literal(s3_path),
                )
            )

        if _ducklake_file_partition_value_fixup_enabled():
            _fixup_partition_values_for_added_files(context, target, "events", target.events_table, files)
    except Exception as exc:
        # Connection drops are retried by the caller (_DuckgresSession.run); only
        # log loudly for genuine failures so a recovered drop doesn't false-alert.
        if not _connection_dropped(exc):
            context.log.exception(f"Failed to register files matching {s3_glob}")
            logger.exception(
                "duckling_file_registration_failed",
                s3_glob=s3_glob,
                team_id=target.team_id,
            )
        raise

    context.log.info(f"Successfully registered {len(files)} file(s) from {s3_glob}")
    logger.info(
        "duckling_files_registered",
        s3_glob=s3_glob,
        file_count=len(files),
        team_id=target.team_id,
    )
    return len(files)


def export_persons_to_duckling_s3(
    context: AssetExecutionContext,
    client: Client,
    config: DucklingBackfillConfig,
    target: DucklingTarget,
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
        S3 glob matching every file this run produced, or None if dry_run.
    """
    year = date.strftime("%Y")
    month = date.strftime("%m")
    date_str = date.strftime("%Y-%m-%d")

    period_dir = f"{BACKFILL_PERSONS_S3_PREFIX}/{team_id}/year={year}/month={month}"
    # Fanned out by PARTITION BY into {run_id}_*.parquet — see export_events_to_duckling_s3
    # for why the run_id prefix keeps replays from re-registering prior files.
    partition_path = f"{period_dir}/{run_id}_{{_partition_id}}.parquet"
    file_glob = f"{period_dir}/{run_id}_*.parquet"
    s3_url = get_s3_url_for_clickhouse(target.bucket, target.bucket_region, partition_path)
    s3_glob = f"s3://{target.bucket}/{file_glob}"

    info = f"team_id={team_id}, date={date_str}"

    if config.dry_run:
        context.log.info(
            f"[DRY RUN] Would estimate row count for persons {info} and fan the export across up to "
            f"{config.max_s3_file_fanout} files (~{config.target_rows_per_file} rows/file) to {s3_glob}"
        )
        return None

    # Size the fan-out from a cheap proxy: persons modified that day (team_id is the
    # leading primary key). Output rows are these persons' distinct_ids, so this under-counts
    # by the distinct-ids-per-person ratio (~1-2). We can't use the accurate
    # person_distinct_id2 count the full export uses: the daily filter is on person._timestamp
    # (which day a person changed), and person_distinct_id2 has no equivalent per-day column —
    # counting the actual output would mean running the FINAL'd JOIN, i.e. the export itself.
    # The under-count only nudges files slightly above target; persons days are small and the
    # max_s3_file_fanout clamp binds first.
    row_count = _estimate_export_row_count(
        client,
        f"SELECT count() FROM person WHERE team_id = {team_id} AND toDate(_timestamp) = '{date_str}' AND is_deleted = 0",
        settings,
    )
    fanout = _compute_fanout(row_count, config.target_rows_per_file, config.max_s3_file_fanout)

    # Join person with person_distinct_id2 to get distinct_ids
    # Use FINAL to handle ReplacingMergeTree deduplication
    # Filter by _timestamp to get persons modified on this date
    export_sql = f"""
    INSERT INTO FUNCTION s3(
        '{s3_url}',
        'Parquet'
    )
    PARTITION BY toString(cityHash64(distinct_id) % {fanout})
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

    # Bound per-partition writer memory like the events export (see PARQUET_WRITER_SETTINGS).
    export_settings = settings.copy()
    export_settings.update(PARQUET_WRITER_SETTINGS)

    context.log.info(f"Exporting persons for {info} ({row_count} persons → {fanout} file(s)) to {s3_glob}")
    logger.info(
        "duckling_persons_export_start",
        team_id=team_id,
        date=date_str,
        s3_glob=s3_glob,
        row_count=row_count,
        fanout=fanout,
    )

    try:
        _execute_export_with_retry(client, export_sql, export_settings, info)
        context.log.info(f"Successfully exported persons for {info}")
        logger.info("duckling_persons_export_success", team_id=team_id, date=date_str)
        return s3_glob
    except Exception:
        context.log.exception(f"Failed to export persons for {info} after {MAX_RETRY_ATTEMPTS} attempts")
        logger.exception("duckling_persons_export_failed", team_id=team_id, date=date_str)
        raise


def export_persons_full_to_duckling_s3(
    context: AssetExecutionContext,
    client: Client,
    config: DucklingBackfillConfig,
    target: DucklingTarget,
    team_id: int,
    run_id: str,
    settings: dict[str, Any],
) -> str | None:
    """Export ALL persons for a team to the duckling's S3 bucket.

    Single FINAL query with no date filtering - much more efficient than
    per-day exports for full backfills. Exports persons joined with
    person_distinct_id2 to include distinct_ids.

    Returns:
        S3 glob matching every file this run produced, or None if dry_run.
    """
    period_dir = f"{BACKFILL_PERSONS_S3_PREFIX}/{team_id}/year=0/month=0"
    # Fanned out by PARTITION BY into {run_id}_*.parquet — see export_events_to_duckling_s3
    # for why the run_id prefix keeps replays from re-registering prior files.
    partition_path = f"{period_dir}/{run_id}_{{_partition_id}}.parquet"
    file_glob = f"{period_dir}/{run_id}_*.parquet"
    s3_url = get_s3_url_for_clickhouse(target.bucket, target.bucket_region, partition_path)
    s3_glob = f"s3://{target.bucket}/{file_glob}"

    # Join person with person_distinct_id2 to get distinct_ids
    # Use FINAL to handle ReplacingMergeTree deduplication
    # No date filtering - export all persons for the team
    # Full exports need more memory due to FINAL + JOIN on large datasets
    # Also enable external sorting to spill to disk if memory is still exceeded
    full_export_settings = settings.copy()
    full_export_settings.update(PARQUET_WRITER_SETTINGS)  # bound per-partition writer memory
    full_export_settings.update(
        {
            "max_memory_usage": 100 * 1024 * 1024 * 1024,  # 100GB for full exports
            "max_bytes_before_external_sort": 50 * 1024 * 1024 * 1024,  # Spill to disk after 50GB
        }
    )

    info = f"team_id={team_id}, full_export"

    if config.dry_run:
        context.log.info(
            f"[DRY RUN] Would estimate row count for persons {info} and fan the export across up to "
            f"{config.max_s3_file_fanout} files (~{config.target_rows_per_file} rows/file) to {s3_glob}"
        )
        return None

    # Size the fan-out from the team's distinct-id rows (≈ output rows; team_id is the
    # leading primary key). No FINAL — a slight overcount only nudges the file count up.
    row_count = _estimate_export_row_count(
        client,
        f"SELECT count() FROM person_distinct_id2 WHERE team_id = {team_id} AND is_deleted = 0",
        settings,
    )
    fanout = _compute_fanout(row_count, config.target_rows_per_file, config.max_s3_file_fanout)

    export_sql = f"""
    INSERT INTO FUNCTION s3(
        '{s3_url}',
        'Parquet'
    )
    PARTITION BY toString(cityHash64(distinct_id) % {fanout})
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

    context.log.info(f"Exporting all persons for {info} ({row_count} distinct-ids → {fanout} file(s)) to {s3_glob}")
    logger.info(
        "duckling_persons_full_export_start",
        team_id=team_id,
        s3_glob=s3_glob,
        row_count=row_count,
        fanout=fanout,
    )

    try:
        _execute_export_with_retry(client, export_sql, full_export_settings, info)
        context.log.info(f"Successfully exported all persons for {info}")
        logger.info("duckling_persons_full_export_success", team_id=team_id)
        return s3_glob
    except Exception:
        context.log.exception(f"Failed to export persons (full) for {info} after {MAX_RETRY_ATTEMPTS} attempts")
        logger.exception("duckling_persons_full_export_failed", team_id=team_id)
        raise


def register_persons_files_with_duckling(
    context: AssetExecutionContext,
    target: DucklingTarget,
    s3_glob: str,
    config: DucklingBackfillConfig,
    conn: psycopg.Connection[Any],
) -> int:
    """Register every Parquet file a fanned-out persons export produced.

    Globs the run's output and registers each file exactly once. The caller must
    have cleared the existing rows (DELETE) first so a replay can't double-register.

    DuckLake transaction conflicts are retried server-side by duckgres. Connection
    retries live in the caller — this helper operates on a connection it doesn't own.

    Returns:
        Number of files registered (0 if skipped, dry_run, or the export was empty).
    """
    if config.skip_ducklake_registration:
        context.log.info("Skipping DuckLake registration (skip_ducklake_registration=True)")
        return 0

    if config.dry_run:
        context.log.info(
            f"[DRY RUN] Would register files matching {s3_glob} with DuckLake (org {target.organization_id})"
        )
        return 0

    alias = DUCKLAKE_ALIAS

    try:
        files = _glob_run_files(conn, s3_glob)
        if not files:
            context.log.info(f"No persons files produced for {s3_glob}, nothing to register")
            return 0

        context.log.info(f"Registering {len(files)} persons file(s) with DuckLake from {s3_glob}")
        for s3_path in files:
            # See the events registration site for the allow_missing rationale.
            conn.execute(
                psql.SQL("CALL ducklake_add_data_files({}, {}, {}, schema => 'posthog', allow_missing => true)").format(
                    psql.Literal(alias),
                    psql.Literal(target.persons_table),
                    psql.Literal(s3_path),
                )
            )

        if _ducklake_file_partition_value_fixup_enabled():
            _fixup_partition_values_for_added_files(context, target, "persons", target.persons_table, files)
    except Exception as exc:
        # Connection drops are retried by the caller (_DuckgresSession.run); only
        # log loudly for genuine failures so a recovered drop doesn't false-alert.
        if not _connection_dropped(exc):
            context.log.exception(f"Failed to register persons files matching {s3_glob}")
            logger.exception(
                "duckling_persons_file_registration_failed",
                s3_glob=s3_glob,
                team_id=target.team_id,
            )
        raise

    context.log.info(f"Successfully registered {len(files)} persons file(s) from {s3_glob}")
    logger.info(
        "duckling_persons_files_registered",
        s3_glob=s3_glob,
        file_count=len(files),
        team_id=target.team_id,
    )
    return len(files)


@asset(
    partitions_def=duckling_events_partitions_def,
    name="duckling_events_backfill",
    tags={"owner": JobOwners.TEAM_MANAGED_WAREHOUSE.value, **EVENTS_CONCURRENCY_TAG},
)
def duckling_events_backfill(context: AssetExecutionContext, config: DucklingBackfillConfig) -> None:
    """Backfill events from ClickHouse to a customer's duckling.

    Supports both daily (YYYY-MM-DD) and monthly (YYYY-MM) partition keys.
    For monthly partitions, processes all days in the month.

    This asset:
    1. Parses the partition key to get team_id and date(s)
    2. Resolves the duckling target — DuckgresServer connection + derived S3 bucket
    3. Creates the events table if it doesn't exist (optional, enabled by default)
    4. Validates the duckling's schema compatibility (optional)
    5. For each date in the partition:
       a. Deletes existing DuckLake data for this partition (idempotent re-processing)
       b. Exports events to the duckling's S3 bucket (ClickHouse EC2 role has bucket access)
       c. Registers the Parquet file with the duckling's DuckLake catalog (via cross-account role)
    """
    team_id, dates = parse_partition_key_dates(context.partition_key)
    # 16 hex chars (64 bits): the file prefix that scopes each run's glob. The exactly-once
    # guarantee is the ranged DELETE, not prefix uniqueness, but a wider prefix makes a
    # same-day re-run sharing a prefix (→ globbing a prior run's orphans) effectively impossible.
    run_id = context.run.run_id[:16]

    context.log.info(f"Starting duckling backfill for team_id={team_id}, dates={len(dates)} day(s)")
    logger.info(
        "duckling_backfill_start",
        team_id=team_id,
        date_count=len(dates),
        run_id=run_id,
    )

    # Resolve the duckling target: org id (team → org) drives both the connection and the
    # S3 bucket (the control plane is the authoritative source of the bucket name).
    target = _resolve_duckling_target(team_id)

    context.log.info(f"Backfill ready for team_id={team_id}: org={target.organization_id}, bucket={target.bucket}")

    # Open one duckgres connection for all metadata operations, but skip it
    # entirely when no duckgres-backed work will run (dry_run / skip_ducklake_registration).
    should_use_duckgres = not (config.dry_run or config.skip_ducklake_registration)
    session = _DuckgresSession(context, target) if should_use_duckgres else None
    try:
        if session is not None:
            # Delete events table if requested (dangerous - loses all data)
            if config.delete_tables:
                context.log.warning("delete_tables=True: Deleting events table...")
                try:
                    session.run(
                        "drop events table",
                        lambda c: c.execute(f"DROP TABLE IF EXISTS {DUCKLAKE_ALIAS}.posthog.{target.events_table}"),
                    )
                except Exception:
                    context.log.exception(f"Failed to drop events table for team_id={team_id}")
                    logger.exception(
                        "duckling_events_table_drop_failed",
                        team_id=team_id,
                        bucket=target.bucket,
                    )
                    raise

            # Create events table if it doesn't exist
            if config.create_tables_if_missing:
                context.log.info("Ensuring events table exists in duckling catalog...")
                session.run("ensure events table", lambda c: ensure_events_table_exists(context, target, c))

            # Validate schema before starting export
            if not config.skip_schema_validation:
                context.log.info("Validating duckling schema compatibility...")
                session.run("validate events schema", lambda c: validate_duckling_schema(context, target, c))

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
        days_exported = 0
        total_registered = 0

        for partition_date in dates:
            date_str = partition_date.strftime("%Y-%m-%d")
            context.log.info(f"Processing date {date_str}...")

            # Delete existing DuckLake data for this partition before re-processing
            if session is not None and config.cleanup_existing_partition_data:

                def delete_events_partition(conn: psycopg.Connection[Any], date: datetime = partition_date) -> None:
                    delete_events_partition_data(context, target, team_id, date, conn=conn)

                session.run(f"delete events partition {date_str}", delete_events_partition)

            def do_export(client: Client, date: datetime = partition_date) -> str | None:
                with tags_context(kind="dagster", dagster=tags):
                    return export_events_to_duckling_s3(
                        context=context,
                        client=client,
                        config=config,
                        target=target,
                        team_id=team_id,
                        date=date,
                        run_id=run_id,
                        settings=merged_settings,
                    )

            s3_glob = cluster.any_host_by_role(
                fn=do_export,
                workload=workload,
                node_role=NodeRole.DATA,
            ).result()

            # Register every file the day's fanned-out export produced
            if s3_glob:
                days_exported += 1
                if session is not None:

                    def register_events_files(
                        conn: psycopg.Connection[Any],
                        glob: str = s3_glob,
                        date: datetime = partition_date,
                    ) -> int:
                        # Idempotent replay unit: ducklake_add_data_files APPENDS with no
                        # dedup-by-path, so if a prior attempt committed some registrations
                        # but the worker died before the client saw the ack, re-clear the
                        # day's range first (idempotent DELETE) then re-add all of this run's
                        # files — the net state is exactly this run's file set for the day,
                        # wherever the prior attempt died.
                        if config.cleanup_existing_partition_data:
                            delete_events_partition_data(context, target, team_id, date, conn=conn)
                        return register_files_with_duckling(context, target, glob, config, conn)

                    total_registered += session.run(f"register events files {date_str}", register_events_files)

        context.add_output_metadata(
            {
                "team_id": team_id,
                "partition_key": context.partition_key,
                "dates_processed": len(dates),
                "days_exported": days_exported,
                "files_registered": total_registered,
                "bucket": target.bucket,
            }
        )

        context.log.info(
            f"Completed duckling backfill for team_id={team_id}: "
            f"{days_exported}/{len(dates)} days exported, {total_registered} files registered"
        )
        logger.info(
            "duckling_backfill_complete",
            team_id=team_id,
            dates_processed=len(dates),
            days_exported=days_exported,
            files_registered=total_registered,
        )

    finally:
        if session is not None:
            session.close()


@asset(
    partitions_def=duckling_persons_partitions_def,
    name="duckling_persons_backfill",
    tags={"owner": JobOwners.TEAM_MANAGED_WAREHOUSE.value, **PERSONS_CONCURRENCY_TAG},
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
    2. Resolves the duckling target — DuckgresServer connection + derived S3 bucket
    3. Creates the persons table if it doesn't exist (optional, enabled by default)
    4. Validates the duckling's persons schema compatibility (optional)
    5. Exports persons to S3 and registers with DuckLake
    """
    partition_key = context.partition_key
    is_full = is_full_export_partition(partition_key)
    # 16 hex chars (64 bits): the file prefix that scopes each run's glob. The exactly-once
    # guarantee is the ranged DELETE, not prefix uniqueness, but a wider prefix makes a
    # same-day re-run sharing a prefix (→ globbing a prior run's orphans) effectively impossible.
    run_id = context.run.run_id[:16]

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

    # Resolve the duckling target: org id (team → org) drives both the connection and the
    # S3 bucket (the control plane is the authoritative source of the bucket name).
    target = _resolve_duckling_target(team_id)

    context.log.info(f"Backfill ready for team_id={team_id}: org={target.organization_id}, bucket={target.bucket}")

    # Open one duckgres connection for all metadata operations, but skip it
    # entirely when no duckgres-backed work will run (dry_run / skip_ducklake_registration).
    should_use_duckgres = not (config.dry_run or config.skip_ducklake_registration)
    session = _DuckgresSession(context, target) if should_use_duckgres else None
    try:
        if session is not None:
            # Delete persons table if requested (dangerous - loses all data)
            if config.delete_tables:
                context.log.warning("delete_tables=True: Deleting persons table...")
                try:
                    session.run(
                        "drop persons table",
                        lambda c: c.execute(f"DROP TABLE IF EXISTS {DUCKLAKE_ALIAS}.posthog.{target.persons_table}"),
                    )
                except Exception:
                    context.log.exception(f"Failed to drop persons table for team_id={team_id}")
                    logger.exception(
                        "duckling_persons_table_drop_failed",
                        team_id=team_id,
                        bucket=target.bucket,
                    )
                    raise

            # Create persons table if it doesn't exist
            if config.create_tables_if_missing:
                context.log.info("Ensuring persons table exists in duckling catalog...")
                session.run("ensure persons table", lambda c: ensure_persons_table_exists(context, target, c))

            if not config.skip_schema_validation:
                context.log.info("Validating duckling persons schema compatibility...")
                session.run("validate persons schema", lambda c: validate_duckling_persons_schema(context, target, c))

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
                    lambda c: delete_persons_partition_data(context, target, team_id, partition_date=None, conn=c),
                )

            def do_full_export(client: Client) -> str | None:
                with tags_context(kind="dagster", dagster=tags):
                    return export_persons_full_to_duckling_s3(
                        context=context,
                        client=client,
                        config=config,
                        target=target,
                        team_id=team_id,
                        run_id=run_id,
                        settings=merged_settings,
                    )

            s3_glob = cluster.any_host_by_role(
                fn=do_full_export,
                workload=workload,
                node_role=NodeRole.DATA,
            ).result()

            files_registered = 0
            if s3_glob and session is not None:

                def register_full_persons_files(conn: psycopg.Connection[Any], glob: str = s3_glob) -> int:
                    # Idempotent replay unit (see _DuckgresSession): re-clear all of the
                    # team's persons (idempotent DELETE) then re-add all of this run's files,
                    # so a replay after a committed-but-unacked registration can't double-register.
                    if config.cleanup_existing_partition_data:
                        delete_persons_partition_data(context, target, team_id, partition_date=None, conn=conn)
                    return register_persons_files_with_duckling(context, target, glob, config, conn)

                files_registered = session.run("register persons files (full)", register_full_persons_files)

            context.add_output_metadata(
                {
                    "team_id": team_id,
                    "partition_key": partition_key,
                    "export_mode": "full",
                    "files_registered": files_registered,
                    "bucket": target.bucket,
                }
            )

            context.log.info(
                f"Completed duckling persons full backfill for team_id={team_id}: {files_registered} files registered"
            )
            logger.info(
                "duckling_persons_backfill_complete",
                team_id=team_id,
                export_mode="full",
                files_registered=files_registered,
            )
        else:
            # DAILY EXPORT MODE - process each date in the partition
            days_exported = 0
            total_registered = 0

            for partition_date in dates:
                date_str = partition_date.strftime("%Y-%m-%d")
                context.log.info(f"Processing persons for date {date_str}...")

                # Delete existing DuckLake data for this partition before re-processing
                if session is not None and config.cleanup_existing_partition_data:

                    def delete_persons_partition(
                        conn: psycopg.Connection[Any], date: datetime = partition_date
                    ) -> None:
                        delete_persons_partition_data(context, target, team_id, date, conn=conn)

                    session.run(f"delete persons partition {date_str}", delete_persons_partition)

                def do_export(client: Client, date: datetime = partition_date) -> str | None:
                    with tags_context(kind="dagster", dagster=tags):
                        return export_persons_to_duckling_s3(
                            context=context,
                            client=client,
                            config=config,
                            target=target,
                            team_id=team_id,
                            date=date,
                            run_id=run_id,
                            settings=merged_settings,
                        )

                s3_glob = cluster.any_host_by_role(
                    fn=do_export,
                    workload=workload,
                    node_role=NodeRole.DATA,
                ).result()

                if s3_glob:
                    days_exported += 1
                    if session is not None:

                        def register_persons_files(
                            conn: psycopg.Connection[Any],
                            glob: str = s3_glob,
                            date: datetime = partition_date,
                        ) -> int:
                            # Idempotent replay unit (see _DuckgresSession): re-clear the
                            # day's range (idempotent DELETE) then re-add all of this run's
                            # files, so a replay after a committed-but-unacked registration
                            # can't double-register.
                            if config.cleanup_existing_partition_data:
                                delete_persons_partition_data(context, target, team_id, date, conn=conn)
                            return register_persons_files_with_duckling(context, target, glob, config, conn)

                        total_registered += session.run(f"register persons files {date_str}", register_persons_files)

            context.add_output_metadata(
                {
                    "team_id": team_id,
                    "partition_key": partition_key,
                    "export_mode": "daily",
                    "dates_processed": len(dates),
                    "days_exported": days_exported,
                    "files_registered": total_registered,
                    "bucket": target.bucket,
                }
            )

            context.log.info(
                f"Completed duckling persons daily backfill for team_id={team_id}: "
                f"{days_exported}/{len(dates)} days exported, {total_registered} files registered"
            )
            logger.info(
                "duckling_persons_backfill_complete",
                team_id=team_id,
                export_mode="daily",
                dates_processed=len(dates),
                days_exported=days_exported,
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
    """Discover teams with backfills enabled (DuckgresServerTeam) and create daily backfill partitions.

    This sensor runs periodically to:
    1. Find all teams with backfills enabled (DuckgresServerTeam)
    2. Create partitions for yesterday's data (if not already exists)
    3. Trigger backfill runs for new partitions
    4. Retry failed partitions that already exist
    """
    yesterday = (timezone.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    # Get existing partitions
    existing = set(context.instance.get_dynamic_partitions("duckling_events_backfill"))

    new_partitions: list[str] = []
    run_requests: list[RunRequest] = []

    for backfill in DuckgresServerTeam.objects.filter(backfill_enabled=True):
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


# Number of monthly partitions to create per sensor tick (to avoid timeout).
# Still used by the persons full-backfill sensor below.
BACKFILL_MONTHS_PER_TICK = 3

# Ignore events before this date — pre-2015 data is typically junk timestamps
EARLIEST_BACKFILL_DATE = datetime(2015, 1, 1)

# Full EVENTS-backfill sensor (round-robin, bounded top-up). Execution is throttled
# separately by the duckling_events_v1 managed concurrency limit (charts) — kept small so
# ClickHouse only ever sees a few concurrent exports. These knobs govern how the sensor
# ENQUEUES into that limit; they never widen ClickHouse load.
#
# Standing depth of the run queue the sensor keeps topped up. Bounded so Dagster never
# holds thousands of QUEUED runs: with the concurrency limit draining a few at a time, a
# shallow queue keeps every slot busy while staying small. Fairness across orgs comes from
# round-robin selection, not from depth.
EVENTS_BACKFILL_TARGET_QUEUE_DEPTH = 100
# Hard cap on RunRequests emitted in one tick, bounding the tick's work (and its 60s eval
# budget) even when filling the queue from empty.
EVENTS_BACKFILL_MAX_PARTITIONS_PER_TICK = 100
# Cap on per-team earliest-event ClickHouse lookups per tick. This is the only expensive
# sensor op; it runs once per team ever, then the result is cached on the model row.
EVENTS_BACKFILL_MAX_EARLIEST_LOOKUPS_PER_TICK = 5
# Stored in DuckgresServerTeam.earliest_event_date for a team with no events, so the sensor
# caches "nothing to backfill" instead of re-querying every tick. Far enough in the future
# that the generated months range is always empty.
_NO_HISTORY_SENTINEL = date(9999, 12, 31)
# Run tag stamped on full-backfill runs only. The full and daily events sensors share one
# job (duckling_events_backfill_job), so the top-up's in-flight count filters on this tag to
# count its OWN queued runs — otherwise a burst of daily runs could zero out its slots.
_FULL_BACKFILL_RUN_TAG = {"duckling_backfill_type": "full"}


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
    minimum_interval_seconds=60,  # Cheap now (no per-month ClickHouse query) — tick often to keep the queue fed
    job_name="duckling_events_backfill_job",
    default_status=DefaultSensorStatus.RUNNING,
)
def duckling_events_full_backfill_sensor(
    context: SensorEvaluationContext,
) -> SensorResult:
    """Full historical events backfill — monthly partitions, enqueued round-robin under a bounded queue.

    Monthly partitions (``{team_id}_{YYYY-MM}``) keep the partition count down; each one
    backfills all days in its month. Only COMPLETE historical months are enqueued — the
    current, in-progress month is left to the daily backfill sensor, so a team whose earliest
    event is only in the current month gets no full-backfill partition at all.

    Enqueue strategy, decoupled from execution (which the duckling_events_v1 concurrency
    limit throttles to a handful of concurrent runs to protect ClickHouse):

      * ``earliest_event_date`` is resolved from ClickHouse ONCE per team and cached on the
        ``DuckgresServerTeam`` row (bounded to EVENTS_BACKFILL_MAX_EARLIEST_LOOKUPS_PER_TICK
        lookups per tick), so the hot path issues no ClickHouse queries and an org's whole
        history can be enqueued in a few quick ticks instead of dripping 3 months / 10 min.
      * Candidate months are interleaved ROUND-ROBIN across all enabled teams (each team
        advances one month per round), so the FIFO run queue drains fairly — no org waits
        for another's entire history to finish first.
      * The sensor tops the queue up to EVENTS_BACKFILL_TARGET_QUEUE_DEPTH (counting
        in-flight runs) rather than dumping the whole backlog, so Dagster holds a small
        bounded queue while the concurrency limit does the actual throttling.

    Idempotent and cursor-free: already-registered partitions are skipped and ``run_key`` is
    the partition key, so re-ticks and restarts never double-enqueue. Any cursor written by
    the previous serial implementation is simply ignored (safe rollback either way).
    """
    # Full backfill covers only COMPLETE historical months, up to the end of last month. The
    # current, in-progress month is owned by the daily backfill sensor (which fills it in
    # day-by-day), so emitting a whole-month partition for it is redundant — it re-DELETEs and
    # re-registers exactly the days the daily runs are handling, racing them under DuckLake's
    # per-table OCC (that conflict is why the current-month monthly partition goes red while the
    # daily partitions succeed).
    last_month_end = timezone.now().date().replace(day=1) - timedelta(days=1)

    backfills = list(DuckgresServerTeam.objects.filter(backfill_enabled=True).order_by("team_id"))
    if not backfills:
        context.log.info("No enabled DuckgresServerTeam entries found")
        return SensorResult(run_requests=[])

    # 1. Resolve + cache earliest_event_date for teams that don't have it yet. This is the
    #    only expensive op (one ClickHouse query/team), bounded per tick and cached forever.
    lookups = 0
    for bf in backfills:
        if bf.earliest_event_date is not None:
            continue
        if lookups >= EVENTS_BACKFILL_MAX_EARLIEST_LOOKUPS_PER_TICK:
            break
        lookups += 1
        earliest_dt = get_earliest_event_date_for_team(bf.team_id)
        if earliest_dt is None:
            bf.earliest_event_date = _NO_HISTORY_SENTINEL
            context.log.info(f"No events for team_id={bf.team_id}; caching no-history sentinel")
        else:
            bf.earliest_event_date = max(earliest_dt, EARLIEST_BACKFILL_DATE).date()
        bf.save(update_fields=["earliest_event_date"])

    # 2. Per-team remaining months (oldest first), skipping already-registered partitions.
    existing = set(context.instance.get_dynamic_partitions("duckling_events_backfill"))
    per_team_remaining: list[list[str]] = []
    for bf in backfills:
        earliest = bf.earliest_event_date
        if earliest is None or earliest > last_month_end:
            # Unresolved this tick, no-history sentinel, or a team whose earliest event is only
            # in the current month — no complete month to full-backfill (the daily sensor owns
            # the current month), so skip it.
            continue
        keys = [f"{bf.team_id}_{m}" for m in get_months_in_range(earliest, last_month_end)]
        remaining = [k for k in keys if k not in existing]
        if remaining:
            per_team_remaining.append(remaining)

    # 3. Round-robin interleave by month index: round r takes each team's r-th remaining
    #    month, so the queue order is team0-m0, team1-m0, ..., team0-m1, ... — fair under FIFO.
    candidates: list[str] = []
    round_idx = 0
    while True:
        added = False
        for team_keys in per_team_remaining:
            if round_idx < len(team_keys):
                candidates.append(team_keys[round_idx])
                added = True
        if not added:
            break
        round_idx += 1

    if not candidates:
        context.log.debug("Full events backfill: nothing left to enqueue")
        return SensorResult(run_requests=[])

    # 4. Bounded top-up: emit only enough to refill the queue to the target depth. The
    #    `limit` bounds the status query — we only need in-flight count vs. the target.
    inflight = context.instance.get_runs(
        filters=RunsFilter(
            job_name="duckling_events_backfill_job",
            tags=_FULL_BACKFILL_RUN_TAG,  # count only full-backfill runs, not the shared-job daily runs
            statuses=[
                DagsterRunStatus.QUEUED,
                DagsterRunStatus.NOT_STARTED,
                DagsterRunStatus.STARTING,
                DagsterRunStatus.STARTED,
            ],
        ),
        limit=EVENTS_BACKFILL_TARGET_QUEUE_DEPTH + 1,
    )
    slots = max(0, EVENTS_BACKFILL_TARGET_QUEUE_DEPTH - len(inflight))
    to_emit = candidates[: min(slots, EVENTS_BACKFILL_MAX_PARTITIONS_PER_TICK)]

    if not to_emit:
        context.log.debug(
            f"Full events backfill: queue at capacity ({len(inflight)}/{EVENTS_BACKFILL_TARGET_QUEUE_DEPTH}), "
            f"{len(candidates)} still pending"
        )
        return SensorResult(run_requests=[])

    # run_key = partition_key so a re-tick or restart can't double-launch the same month.
    # The tag lets the next tick's in-flight count see these as full-backfill runs.
    run_requests = [RunRequest(partition_key=k, run_key=k, tags=_FULL_BACKFILL_RUN_TAG) for k in to_emit]
    context.log.info(
        f"Enqueuing {len(to_emit)} monthly partition(s) across {len(per_team_remaining)} team(s); "
        f"{len(inflight)} in flight, {len(candidates) - len(to_emit)} still pending"
    )
    logger.info(
        "duckling_full_backfill_enqueue",
        emitted=len(to_emit),
        inflight=len(inflight),
        pending=len(candidates) - len(to_emit),
        teams_with_work=len(per_team_remaining),
    )
    return SensorResult(
        run_requests=run_requests,
        dynamic_partitions_requests=[duckling_events_partitions_def.build_add_request(to_emit)],
    )


duckling_events_backfill_job = define_asset_job(
    name="duckling_events_backfill_job",
    selection=["duckling_events_backfill"],
    tags={
        "owner": JobOwners.TEAM_MANAGED_WAREHOUSE.value,
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
    """Discover teams with backfills enabled (DuckgresServerTeam) and create daily persons partitions.

    Similar to duckling_events_daily_backfill_sensor but for persons data.
    Uses _timestamp (Kafka ingestion time) for date filtering.
    """
    yesterday = (timezone.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    existing = set(context.instance.get_dynamic_partitions("duckling_persons_backfill"))

    new_partitions: list[str] = []
    run_requests: list[RunRequest] = []

    for backfill in DuckgresServerTeam.objects.filter(backfill_enabled=True):
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
    backfills = list(DuckgresServerTeam.objects.filter(backfill_enabled=True).order_by("team_id"))
    if not backfills:
        context.log.info("No enabled DuckgresServerTeam entries found")
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
        "owner": JobOwners.TEAM_MANAGED_WAREHOUSE.value,
        **PERSONS_CONCURRENCY_TAG,
    },
)
