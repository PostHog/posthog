from __future__ import annotations

import re
import math
import time
import collections
import dataclasses
from collections.abc import Callable, Iterator
from contextlib import _GeneratorContextManager, contextmanager
from datetime import (
    UTC,
    date,
    datetime,
    time as datetime_time,
    timezone,
)
from typing import TYPE_CHECKING, Any, Literal, LiteralString, Optional, cast

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

from django.conf import settings

import psycopg
import pyarrow as pa
import structlog
from psycopg import sql
from psycopg.adapt import Loader
from psycopg.types.datetime import TimeLoader, TimestampLoader, TimestamptzLoader, TimetzLoader
from structlog.types import FilteringBoundLogger

from posthog.hogql.database.schema.duckdb_table_functions import is_dangerous_table_function

from posthog.exceptions_capture import capture_exception
from posthog.temporal.data_imports.naming_convention import NamingConvention
from posthog.temporal.data_imports.pipelines.helpers import (
    incremental_type_to_initial_value,
    incremental_type_to_operator,
)
from posthog.temporal.data_imports.pipelines.pipeline.consts import DEFAULT_CHUNK_SIZE, DEFAULT_TABLE_SIZE_BYTES
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.pipelines.pipeline.utils import (
    DEFAULT_NUMERIC_PRECISION,
    DEFAULT_NUMERIC_SCALE,
    DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES,
    MAX_NUMERIC_SCALE,
    QueryTimeoutException,
    TemporaryFileSizeExceedsLimitException,
    build_pyarrow_decimal_type,
    table_from_iterator,
)
from posthog.temporal.data_imports.sources.common.mixins import open_ssh_tunnel
from posthog.temporal.data_imports.sources.common.sql import Column, Table, compute_projected_columns
from posthog.temporal.data_imports.sources.common.sql.implementation import SQLSourceImplementation
from posthog.temporal.data_imports.sources.common.sql.incremental import IncrementalFieldFilter
from posthog.temporal.data_imports.sources.generated_configs import PostgresSourceConfig
from posthog.temporal.data_imports.sources.postgres.partitioned_tables import (
    build_partition_query,
    get_estimated_row_count_for_partitioned_table as _get_estimated_row_count_for_partitioned_table,
    get_partition_settings_for_partitioned_table as _get_partition_settings_for_partitioned_table,
    get_partition_strategy,
    is_partitioned_table as _is_partitioned_table,
    is_supported_incremental_type_for_window,
    iterate_date_windows,
    iterate_partitions,
    list_child_partitions,
)

from products.data_warehouse.backend.types import IncrementalFieldType, PartitionSettings

# Sources created after this date must use SSL/TLS connections
SSL_REQUIRED_AFTER_DATE = datetime(2026, 2, 18, tzinfo=UTC)
IDENTIFIER_FUNCTION_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SYSTEM_POSTGRES_SCHEMAS = ["information_schema", "pg_catalog", "pg_toast"]

# Statement timeout applied to the row-streaming connection so a slow FETCH
# (large partitioned scan, cold cache, etc.) does not get killed by a short
# default statement_timeout on the source role.
SYNC_STATEMENT_TIMEOUT_MS = 1000 * 60 * 10  # 10 mins

# How many times the metadata-gathering phase reconnects and retries when a hot-standby
# recovery conflict terminates the setup connection. Past this the conflict is treated as
# sustained and surfaced as the non-retryable "successive SerializationFailure errors" abort.
_MAX_SETUP_RECOVERY_CONFLICT_RETRIES = 10

# Bounded in-process retries for a transient connection drop hit *during* the setup metadata
# probes (not just the initial connect). Mirrors `_connect_with_dropped_retry`'s default; past
# this the drop is treated as sustained and re-raised for Temporal to retry the whole activity.
_MAX_SETUP_CONNECTION_DROPPED_RETRIES = 5


def source_requires_ssl(source: ExternalDataSource, source_config: Any = None) -> bool:
    """Return whether this source must connect over SSL/TLS.

    SSL is required for sources created after the cutoff date, unless the
    user has explicitly opted out via the ``require_tls`` toggle on an active
    SSH tunnel.
    """
    if source.created_at < SSL_REQUIRED_AFTER_DATE:
        return False

    if source_config is not None:
        ssh_tunnel = source_config.ssh_tunnel
        if ssh_tunnel is not None and ssh_tunnel.enabled and not ssh_tunnel.require_tls.enabled:
            return False

    return True


class SSLRequiredError(Exception):
    """Raised when SSL/TLS is required but the database does not support it."""

    pass


# libpq connection option that pins the client encoding to UTF8. Some Postgres-wire-compatible
# engines (notably Amazon Redshift) report their `client_encoding` as the legacy alias `UNICODE`,
# which psycopg3's encoding map doesn't recognise — decoding the first query result then raises
# `NotSupportedError: codec not available in Python: 'UNICODE'`. Forcing the encoding sidesteps it.
FORCE_UTF8_CLIENT_ENCODING = "-c client_encoding=UTF8"


# Substrings PgBouncer / libpq use when the upstream backend connection died
# mid-stream. We hit these when a long-running sync holds a server-side cursor
# (and thus an open transaction) idle across the slow delta-merge phase and the
# source's idle_in_transaction_session_timeout / PgBouncer server_idle_timeout
# culls the backend. They're transient — recover by reconnecting and resuming.
_CONNECTION_DROPPED_ERROR_SUBSTRINGS = (
    "server conn crashed",
    "server closed the connection unexpectedly",
    # Narrow "connection to server …" variants only — a bare "connection to server"
    # would also match initial-connect failures like "connection to server at
    # \"host\" failed: FATAL: password authentication failed", which are permanent
    # and must not be retried.
    "connection to server was lost",
    "connection to server was closed",
    "consuming input failed",
    "no connection to the server",
    "terminating connection due to",
)

# Supavisor (Supabase's connection pooler) doesn't surface a dropped upstream connection with a
# libpq/PgBouncer signature — it raises its own pooler-internal error as a generic psycopg
# InternalError_ (SQLSTATE XX000) with the message "(EDBHANDLEREXITED) DbHandler exited. Check
# logs for more information". The pooler's per-session DbHandler process exits when its backend
# connection dies (idle cull, backend restart, failover), so it's the same transient class as the
# libpq drops above and recovers on reconnect. Matched narrowly by the stable "DbHandler exited"
# text — the surrounding "(EDBHANDLEREXITED)" code and trailing "Check logs..." vary and are
# excluded — so genuine XX000 internal errors (data corruption, etc.) stay non-recoverable.
_POOLER_CONNECTION_DROPPED_ERROR_SUBSTRINGS = ("dbhandler exited",)

# Exception types that can carry a connection-dropped error. ProtocolViolation is
# PgBouncer's synthetic error packet; OperationalError is libpq detecting the dead
# socket. IdleInTransactionSessionTimeout (SQLSTATE 25P03) is what Postgres raises
# when the source's idle_in_transaction_session_timeout culls our backend while a
# server-side cursor holds a transaction open across the slow delta-merge between
# yields — psycopg maps it to InternalError, not OperationalError, so it must be
# named explicitly or the type-based catch below would miss it. InternalError_ is the
# generic XX000 class Supavisor's "DbHandler exited" pooler drop arrives as; it's only
# treated as a drop when its message matches the narrow pooler signature above.
_CONNECTION_DROPPED_ERROR_TYPES = (
    psycopg.errors.ProtocolViolation,
    psycopg.OperationalError,
    psycopg.errors.IdleInTransactionSessionTimeout,
    psycopg.errors.InternalError_,
)


def _safe_close_connection(connection: psycopg.Connection) -> None:
    """Close a connection without raising.

    Prefer this over Connection.__exit__ for teardown in exception handlers:
    __exit__ attempts a commit/rollback first, which can itself raise on a
    broken connection and mask the original error. close() just releases the
    socket.
    """
    if connection.closed:
        return
    try:
        connection.close()
    except Exception:
        pass


def _is_connection_dropped_error(error: BaseException) -> bool:
    """True if the error indicates the upstream connection was dropped mid-stream.

    psycopg surfaces these as ProtocolViolation (PgBouncer's synthetic error
    packet) or OperationalError (libpq detecting the dead socket), so we match on
    type and message rather than a single SQLSTATE.

    IdleInTransactionSessionTimeout is the exception: it carries SQLSTATE 25P03 and
    unambiguously means the source terminated our backend for holding a transaction
    open too long, so the type alone is enough — no message match required.
    """
    if isinstance(error, psycopg.errors.IdleInTransactionSessionTimeout):
        return True
    if isinstance(error, psycopg.errors.ProtocolViolation | psycopg.OperationalError):
        message = " ".join(str(arg) for arg in error.args).lower()
        return any(substring in message for substring in _CONNECTION_DROPPED_ERROR_SUBSTRINGS)
    # Supavisor's pooler drop arrives as a generic XX000 InternalError_, not the libpq/PgBouncer
    # types above, so match it on its own narrow signature (see _POOLER_CONNECTION_DROPPED_*).
    if isinstance(error, psycopg.errors.InternalError_):
        message = " ".join(str(arg) for arg in error.args).lower()
        return any(substring in message for substring in _POOLER_CONNECTION_DROPPED_ERROR_SUBSTRINGS)
    return False


def _connect_with_dropped_retry(
    connect: Callable[[], psycopg.Connection],
    logger: FilteringBoundLogger,
    *,
    max_attempts: int = 5,
) -> psycopg.Connection:
    """Open a connection via `connect`, retrying transient connection-dropped errors.

    The streaming recovery path (offset chunking) is reached precisely because the
    source just dropped our connection (idle cull, failover, mid-stream SSL EOF), so
    the very reconnect that bootstraps the recovery can itself hit a still-recovering
    source and fail with another connection-dropped error. Without this, that
    transient failure escapes the recovery loop and fails the whole sync. Retry with
    bounded backoff; permanent errors (auth failures, SSL-required) are re-raised
    immediately because `_is_connection_dropped_error` only matches transient drops.
    """
    attempt = 0
    while True:
        try:
            return connect()
        except _CONNECTION_DROPPED_ERROR_TYPES as e:
            if not _is_connection_dropped_error(e):
                raise
            attempt += 1
            if attempt >= max_attempts:
                raise
            logger.debug(f"Connection attempt failed ({e}). Retrying (attempt {attempt}/{max_attempts})")
            time.sleep(min(2 * attempt, 30))


def _statement_timeout_as_non_retryable(
    error: BaseException,
    *,
    should_use_incremental_field: bool,
    incremental_field: str | None,
) -> QueryTimeoutException | None:
    """Classify a statement_timeout (QueryCanceled) hit while streaming rows.

    A chunk/fetch that exhausts the 10-min statement_timeout cannot complete in
    time — usually a missing index on the incremental field or a deep OFFSET scan —
    so retrying is futile. On incremental syncs, map it to the same non-retryable
    QueryTimeoutException the server-cursor and windowed read paths already raise,
    with an actionable message. Returns None when the error is not a statement
    timeout, or the sync is non-incremental (the caller should re-raise the original
    error so a full re-sync can reorder rows safely).
    """
    if not isinstance(error, psycopg.errors.QueryCanceled) or not should_use_incremental_field:
        return None
    return QueryTimeoutException(
        f"10 min timeout statement reached. Please ensure your incremental field "
        f"({incremental_field}) has an appropriate index created"
    )


@dataclasses.dataclass(frozen=True)
class PostgresDiscoveredSchema:
    source_catalog: str | None
    source_schema: str
    source_table_name: str
    columns: list[tuple[str, str, bool]]


def _is_duckdb_connection(cursor: psycopg.Cursor) -> bool:
    cursor.execute("SELECT version()")
    row = cursor.fetchone()
    version = str(row[0]) if row and row[0] is not None else ""
    return "duckdb" in version.lower() or "duckgres" in version.lower()


def _get_sslmode(require_ssl: bool) -> str:
    """Return the appropriate sslmode based on whether SSL is required.

    Args:
        require_ssl: If True, returns "require" which forces SSL and fails if
            the server doesn't support it. If False, returns "prefer" which
            tries SSL but falls back to unencrypted if not available.
    """

    if settings.TEST or settings.DEBUG or settings.E2E_TESTING:
        return "prefer"

    return "require" if require_ssl else "prefer"


# Transaction-mode connection poolers reject the libpq `options` startup parameter outright:
# Supabase's Supavisor (port 6543) and PgBouncer in transaction mode report "unsupported startup
# parameter: options", and AWS RDS Proxy reports "RDS Proxy currently doesn't support command-line
# options". We only send `options` to pin client_encoding=UTF8 for Redshift's legacy UNICODE alias
# (see FORCE_UTF8_CLIENT_ENCODING), and Redshift never sits behind these poolers — so when a server
# rejects `options`, dropping it and retrying is safe (UTF8 is the default client encoding for real
# Postgres). The RDS Proxy text uses a typographic apostrophe, so match the apostrophe-free tail.
_OPTIONS_STARTUP_PARAM_UNSUPPORTED_SUBSTRINGS = (
    "unsupported startup parameter: options",
    "support command-line options",
)


def _is_options_startup_param_unsupported(error: BaseException) -> bool:
    if not isinstance(error, psycopg.OperationalError):
        return False
    message = " ".join(str(arg) for arg in error.args).lower()
    return any(substring in message for substring in _OPTIONS_STARTUP_PARAM_UNSUPPORTED_SUBSTRINGS)


def _connect_with_options_fallback(**connect_kwargs: Any) -> psycopg.Connection:
    """`psycopg.connect` that retries without the libpq `options` startup parameter when the
    server rejects it.

    See `_OPTIONS_STARTUP_PARAM_UNSUPPORTED_SUBSTRINGS` for why transaction-mode poolers reject
    `options` and why dropping it is safe.
    """
    try:
        return psycopg.connect(**connect_kwargs)
    except psycopg.OperationalError as e:
        if connect_kwargs.get("options") and _is_options_startup_param_unsupported(e):
            return psycopg.connect(**{k: v for k, v in connect_kwargs.items() if k != "options"})
        raise


def _connect_to_postgres(
    *,
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    require_ssl: bool = False,
    connect_timeout: int = 15,
    **kwargs: Any,
) -> psycopg.Connection:
    sslmode = _get_sslmode(require_ssl)
    # Redshift (and other Postgres-wire-compatible engines) report `client_encoding` as the legacy
    # alias `UNICODE`, which psycopg3's encoding map doesn't recognise — it raises
    # `NotSupportedError: codec not available in Python: 'UNICODE'` the first time it decodes a query
    # result. Pinning the client encoding makes the server report `UTF8` instead, which psycopg maps
    # cleanly. We always force UTF8 and append any caller-supplied `options` after it.
    caller_options = kwargs.pop("options", None)
    options = f"{FORCE_UTF8_CLIENT_ENCODING} {caller_options}" if caller_options else FORCE_UTF8_CLIENT_ENCODING
    try:
        return _connect_with_options_fallback(
            host=host,
            port=port,
            dbname=database,
            user=user,
            password=password,
            sslmode=sslmode,
            connect_timeout=connect_timeout,
            sslrootcert="/tmp/no.txt",
            sslcert="/tmp/no.txt",
            sslkey="/tmp/no.txt",
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=10,
            keepalives_count=5,
            options=options,
            **kwargs,
        )
    except psycopg.OperationalError as e:
        if require_ssl and "SSL" in str(e):
            raise SSLRequiredError(
                "SSL/TLS connection is required but your database does not support it. "
                "Please enable SSL/TLS on your PostgreSQL server or contact your database administrator."
            ) from e
        raise


@contextmanager
def pg_connection(
    *,
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    require_ssl: bool = False,
) -> Iterator[psycopg.Connection]:
    """Context manager that opens a postgres connection and ensures it is closed on exit."""
    conn = _connect_to_postgres(
        host=host, port=port, database=database, user=user, password=password, require_ssl=require_ssl
    )
    try:
        yield conn
    finally:
        conn.close()


def get_primary_key_columns(conn: psycopg.Connection, schema: str, table_names: list[str]) -> dict[str, list[str]]:
    """Return ordered PK columns per table: {table_name: [col, ...]}.

    Uses pg_catalog rather than information_schema because information_schema views
    are ACL-filtered — a user with only SELECT grants may not see PK constraint rows
    depending on PostgreSQL version, which would silently hide `supports_cdc=True`
    for their tables and make CDC look unavailable in the source wizard.
    """
    if not table_names:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.relname AS table_name,
                   a.attname AS column_name,
                   array_position(i.indkey, a.attnum) AS ord
            FROM pg_index i
            JOIN pg_class c ON c.oid = i.indrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY(i.indkey)
            WHERE i.indisprimary
              AND n.nspname = %s
              AND c.relname = ANY(%s)
            ORDER BY c.relname, array_position(i.indkey, a.attnum)
            """,
            (schema, table_names),
        )
        result: dict[str, list[str]] = {}
        for row in cur:
            result.setdefault(row[0], []).append(row[1])
    return result


def get_leading_index_columns(
    conn: psycopg.Connection, schema: str, table_names: list[str]
) -> dict[str, set[str]] | None:
    """Return the set of columns that are the leading column of any index per table.

    Used to surface a UI warning when a user picks an incremental field that isn't
    indexed — those would force a full scan on every sync. Includes the primary key
    (since PKs back an implicit index in Postgres). Excludes:

    - `indkey[0] = 0`: the leading index entry is an expression (e.g. a functional
      index on `lower(email)`), not a plain column — we can't tell whether it
      accelerates `WHERE col >= …` so don't claim it does.
    - `indisvalid = false`: the index isn't usable by the planner (failed
      `CREATE INDEX CONCURRENTLY`, in-progress build) and won't accelerate any
      query.
    - `indpred IS NOT NULL`: partial indexes only accelerate queries whose
      predicate the planner can prove implies the index predicate. Most partial
      indexes in practice (`WHERE deleted_at IS NULL` and similar) don't apply
      to the incremental sync's `WHERE col >= last_max`, so flagging the
      leading column as indexed would suppress a warning the user genuinely
      needs.

    Returns None when discovery fails (e.g. permission issues on system catalogs)
    so the caller can default to no warning rather than blowing away other
    discovery results.
    """
    if not table_names:
        return {}
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.relname AS table_name,
                       a.attname AS column_name
                FROM pg_index i
                JOIN pg_class c ON c.oid = i.indrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = i.indkey[0]
                WHERE i.indkey[0] <> 0
                  AND i.indisvalid
                  AND i.indpred IS NULL
                  AND n.nspname = %s
                  AND c.relname = ANY(%s)
                """,
                (schema, table_names),
            )
            result: dict[str, set[str]] = {}
            for row in cur:
                result.setdefault(row[0], set()).add(row[1])
        return result
    except Exception as e:
        structlog.get_logger().warning("Failed to detect leading index columns for Postgres schemas", exc_info=e)
        return None


def _normalize_function_names(function_names: list[Any]) -> list[str]:
    return sorted(
        {
            function_name.lower()
            for function_name in function_names
            if isinstance(function_name, str) and IDENTIFIER_FUNCTION_NAME_RE.fullmatch(function_name)
        }
    )


def filter_postgres_incremental_fields(
    columns: list[tuple[str, str, bool]],
) -> list[tuple[str, IncrementalFieldType, bool]]:
    results: list[tuple[str, IncrementalFieldType, bool]] = []
    for column_name, type, nullable in columns:
        type = type.lower()
        if type.startswith("timestamp"):
            results.append((column_name, IncrementalFieldType.Timestamp, nullable))
        elif type == "date":
            results.append((column_name, IncrementalFieldType.Date, nullable))
        elif type == "integer" or type == "smallint" or type == "bigint":
            results.append((column_name, IncrementalFieldType.Integer, nullable))

    return results


def _normalize_selected_schema(schema: str | None) -> str | None:
    if not isinstance(schema, str):
        return None

    normalized = schema.strip()
    return normalized or None


def _get_display_table_name(schema_name: str, table_name: str, *, qualify_with_schema: bool) -> str:
    return f"{schema_name}.{table_name}" if qualify_with_schema else table_name


def _build_named_value_placeholders(prefix: str, values: list[str]) -> tuple[str, dict[str, str]]:
    placeholders: list[str] = []
    params: dict[str, str] = {}

    for index, value in enumerate(values):
        key = f"{prefix}_{index}"
        placeholders.append(f"%({key})s")
        params[key] = value

    return ", ".join(placeholders), params


def _get_discovered_tables(
    cursor: psycopg.Cursor, schema: str | None, names: list[str] | None = None
) -> tuple[dict[str, tuple[str | None, str, str]], bool]:
    selected_schema = _normalize_selected_schema(schema)
    qualify_with_schema = selected_schema is None
    is_duckdb = _is_duckdb_connection(cursor)

    if is_duckdb:
        cursor.execute("SELECT current_database()")
        row = cursor.fetchone()
        current_database = str(row[0]) if row and row[0] is not None else None

        if selected_schema is not None:
            cursor.execute(
                """
                SELECT table_catalog, table_schema, table_name
                FROM information_schema.tables
                WHERE table_catalog = %(current_database)s
                  AND table_schema = %(schema)s
                ORDER BY table_schema, table_name
                """,
                {"current_database": current_database, "schema": selected_schema},
            )
        else:
            system_schema_placeholders, system_schema_params = _build_named_value_placeholders(
                "system_schema", SYSTEM_POSTGRES_SCHEMAS
            )
            cursor.execute(
                f"""
                SELECT table_catalog, table_schema, table_name
                FROM information_schema.tables
                WHERE table_catalog = %(current_database)s
                  AND table_schema NOT IN ({system_schema_placeholders})
                ORDER BY table_schema, table_name
                """,
                {"current_database": current_database, **system_schema_params},
            )

        discovered_rows = cursor.fetchall()
        all_tables = {
            _get_display_table_name(schema_name, table_name, qualify_with_schema=qualify_with_schema): (
                table_catalog,
                schema_name,
                table_name,
            )
            for table_catalog, schema_name, table_name in discovered_rows
        }
    else:
        # pg_class covers all syncable relkinds: r/p (tables), v/m (views), f (foreign).
        if selected_schema is not None:
            cursor.execute(
                """
                SELECT n.nspname AS schema_name, c.relname AS table_name
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f')
                  AND n.nspname = %(schema)s
                ORDER BY n.nspname, c.relname
                """,
                {"schema": selected_schema},
            )
        else:
            system_schema_placeholders, system_schema_params = _build_named_value_placeholders(
                "system_schema", SYSTEM_POSTGRES_SCHEMAS
            )
            cursor.execute(
                f"""
                SELECT n.nspname AS schema_name, c.relname AS table_name
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f')
                  AND n.nspname NOT IN ({system_schema_placeholders})
                  AND n.nspname NOT LIKE 'pg_temp_%%'
                  AND n.nspname NOT LIKE 'pg_toast_temp_%%'
                ORDER BY n.nspname, c.relname
                """,
                system_schema_params,
            )

        discovered_rows = cursor.fetchall()
        all_tables = {
            _get_display_table_name(schema_name, table_name, qualify_with_schema=qualify_with_schema): (
                None,
                schema_name,
                table_name,
            )
            for schema_name, table_name in discovered_rows
        }

    if names is None:
        return all_tables, qualify_with_schema

    # Match qualified (`schema.table`) and bare `table` names — keys may differ after multi-schema migration.
    filtered: dict[str, tuple[str | None, str, str]] = {}
    for name in names:
        if name in all_tables:
            filtered[name] = all_tables[name]
        elif "." in name:
            _, _, unqualified = name.partition(".")
            if unqualified in all_tables:
                filtered[name] = all_tables[unqualified]
    return filtered, qualify_with_schema


def _row_counts_from_conn(
    connection: psycopg.Connection,
    schema: str | None,
    names: list[str] | None,
) -> dict[str, int]:
    if _normalize_selected_schema(schema) is None and not names:
        return {}
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("SET LOCAL statement_timeout = {timeout}").format(
                    timeout=sql.Literal(1000 * 30)  # 30 secs
                )
            )
            discovered_tables, _qualify_with_schema = _get_discovered_tables(cursor, schema, names)
            if not discovered_tables:
                return {}

            counts = [
                sql.SQL("SELECT {table_name} AS table_name, COUNT(*) AS row_count FROM {schema}.{table}").format(
                    table_name=sql.Literal(display_name),
                    schema=sql.Identifier(schema_name),
                    table=sql.Identifier(table_name),
                )
                for display_name, (_source_catalog, schema_name, table_name) in discovered_tables.items()
            ]

            union_counts = sql.SQL(" UNION ALL ").join(counts)
            cursor.execute(union_counts)
            row_count_result = cursor.fetchall()
            return {row[0]: row[1] for row in row_count_result}
    except:
        return {}


def _is_unsupported_function_error(error: Exception, function_name: str) -> bool:
    """True when `error` says the database doesn't implement `function_name`.

    Real Postgres raises `UndefinedFunction` (SQLSTATE 42883), but Postgres-wire-compatible engines
    (DuckDB/Flight-SQL-backed proxies, etc.) accept the connection yet lack Postgres-only catalog
    functions like `row_security_active`, surfacing the failure as a generic error whose SQLSTATE we
    can't rely on. Match the function name plus a "missing function" signal in the message so callers
    can degrade quietly instead of alerting on an expected, already-handled shape.
    """
    if isinstance(error, psycopg.errors.UndefinedFunction):
        return True
    message = str(error).lower()
    if function_name.lower() not in message:
        return False
    return any(marker in message for marker in ("does not exist", "unknown function", "not found", "no function"))


def _rls_active_from_conn(
    connection: psycopg.Connection,
    schema: str | None,
    names: list[str] | None,
) -> dict[str, bool]:
    """Per-table map of whether row-level security is active for the connecting role.

    Runs even with no schema/names selected: `row_security_active` is a cheap catalog lookup, so
    there's no cost reason to skip it on the full-table-list view — and that view (the source setup
    picker) is exactly where the warning needs to show.

    One set-based catalog query rather than a per-table function call, so an odd relation (a view, a
    foreign table, one dropped mid-discovery) is simply absent from the result instead of erroring
    the whole batch and dropping every table's warning. Returns only the tables it could resolve;
    callers treat a missing key as "no warning".
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("SET LOCAL statement_timeout = {timeout}").format(
                    timeout=sql.Literal(1000 * 30)  # 30 secs
                )
            )
            discovered_tables, _qualify_with_schema = _get_discovered_tables(cursor, schema, names)
            if not discovered_tables:
                return {}

            # (source schema, source table) -> the display name used as the schema key elsewhere.
            display_by_source = {
                (schema_name, table_name): display_name
                for display_name, (_source_catalog, schema_name, table_name) in discovered_tables.items()
            }
            wanted = sql.SQL(", ").join(
                sql.SQL("({}, {})").format(sql.Literal(schema_name), sql.Literal(table_name))
                for schema_name, table_name in display_by_source
            )
            # relkind r/p only: RLS is meaningless on views/foreign tables, and row_security_active
            # is never called on them so a discovered view can't error the query.
            query = sql.SQL("""
                SELECT n.nspname, c.relname, row_security_active(c.oid)
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                JOIN (VALUES {wanted}) AS want(schema_name, table_name)
                    ON n.nspname::text = want.schema_name AND c.relname::text = want.table_name
                WHERE c.relkind IN ('r', 'p')
            """).format(wanted=wanted)

            cursor.execute(query)
            result: dict[str, bool] = {}
            for nspname, relname, rls_active in cursor.fetchall():
                display_name = display_by_source.get((nspname, relname))
                if display_name is not None:
                    result[display_name] = bool(rls_active)
            return result
    except Exception as e:
        # This runs on a connection shared with earlier best-effort metadata lookups (PK + index
        # discovery). When one of those fails on a non-Postgres engine — e.g. a Redshift-incompatible
        # `pg_catalog` query — its exception is caught upstream but the connection's transaction is
        # left in `INERROR`, so our first statement here fails with `InFailedSqlTransaction` purely as
        # a downstream symptom. That's an already-handled condition, not a bug in this lookup, so
        # don't re-capture it (mirrors `_get_partition_settings`).
        #
        # Postgres-wire-compatible engines (DuckDB/Flight-SQL proxies, etc.) accept our connection
        # but don't implement `row_security_active`. RLS is a Postgres-only concept there, so a
        # missing-function error is an expected "no RLS" answer, not a bug — degrade quietly rather
        # than flooding error tracking. Still capture genuinely unexpected failures.
        if not isinstance(e, psycopg.errors.InFailedSqlTransaction) and not _is_unsupported_function_error(
            e, "row_security_active"
        ):
            capture_exception(e)
        return {}


def get_postgres_row_count(
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    schema: str | None,
    require_ssl: bool = False,
    names: list[str] | None = None,
) -> dict[str, int]:
    if _normalize_selected_schema(schema) is None and not names:
        return {}
    try:
        with pg_connection(
            host=host, port=port, database=database, user=user, password=password, require_ssl=require_ssl
        ) as connection:
            return _row_counts_from_conn(connection, schema, names)
    except:
        return {}


def _schemas_from_conn(
    connection: psycopg.Connection,
    schema: str | None,
    names: list[str] | None,
) -> dict[str, PostgresDiscoveredSchema]:
    """Discover columns for tables on the given pre-opened connection."""
    with connection.cursor() as cursor:
        discovered_tables, _qualify_with_schema = _get_discovered_tables(cursor, schema, names)
        if not discovered_tables:
            return {}

        source_schemas = sorted(
            {schema_name for _table_catalog, schema_name, _table_name in discovered_tables.values()}
        )
        schema_placeholders, schema_params = _build_named_value_placeholders("schema", source_schemas)

        cursor.execute(
            f"""
            SELECT * FROM (
                SELECT
                    table_schema,
                    table_name,
                    column_name,
                    data_type,
                    is_nullable,
                    ordinal_position
                FROM information_schema.columns
                WHERE table_schema IN ({schema_placeholders})
                UNION ALL
                SELECT
                    n.nspname AS table_schema,
                    c.relname AS table_name,
                    a.attname AS column_name,
                    pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type,
                    CASE WHEN a.attnotnull THEN 'NO' ELSE 'YES' END AS is_nullable,
                    a.attnum AS ordinal_position
                FROM pg_class c
                JOIN pg_namespace n ON c.relnamespace = n.oid
                JOIN pg_attribute a ON a.attrelid = c.oid
                WHERE c.relkind = 'm'
                  AND n.nspname IN ({schema_placeholders})
                  AND a.attnum > 0
                  AND NOT a.attisdropped
            ) t
            ORDER BY table_schema ASC, table_name ASC, ordinal_position ASC
            """,
            schema_params,
        )
        result = cursor.fetchall()

        columns_by_table: dict[str, list[tuple[str, str, bool]]] = collections.defaultdict(list)
        discovered_pairs_by_schema_and_table = {
            (schema_name, table_name): display_name
            for display_name, (_source_catalog, schema_name, table_name) in discovered_tables.items()
        }
        for table_schema, table_name, column_name, data_type, is_nullable, _ordinal_position in result:
            display_name = discovered_pairs_by_schema_and_table.get((table_schema, table_name))
            if display_name is None:
                continue

            columns_by_table[display_name].append((column_name, data_type, is_nullable == "YES"))

        return {
            display_name: PostgresDiscoveredSchema(
                source_catalog=source_catalog,
                source_schema=schema_name,
                source_table_name=table_name,
                columns=columns_by_table.get(display_name, []),
            )
            for display_name, (source_catalog, schema_name, table_name) in discovered_tables.items()
        }


def get_schemas(
    host: str,
    database: str,
    user: str,
    password: str,
    schema: str | None,
    port: int,
    require_ssl: bool = False,
    names: list[str] | None = None,
) -> dict[str, PostgresDiscoveredSchema]:
    """Get all tables from PostgreSQL source schemas to sync."""
    with pg_connection(
        host=host, port=port, database=database, user=user, password=password, require_ssl=require_ssl
    ) as connection:
        return _schemas_from_conn(connection, schema, names)


def get_primary_keys_for_schemas(
    host: str,
    database: str,
    user: str,
    password: str,
    schema: str,
    port: int,
    table_names: list[str],
    require_ssl: bool = False,
) -> dict[str, list[str] | None]:
    """Detect primary keys for all tables in a single query."""
    result: dict[str, list[str] | None] = dict.fromkeys(table_names)

    try:
        with pg_connection(
            host=host, port=port, database=database, user=user, password=password, require_ssl=require_ssl
        ) as connection:
            pks = get_primary_key_columns(connection, schema, table_names)
            for table_name, pk_cols in pks.items():
                result[table_name] = pk_cols
    except Exception as e:
        structlog.get_logger().warning("Failed to detect primary keys for Postgres schemas", exc_info=e)

    return result


def _foreign_keys_from_conn(
    connection: psycopg.Connection,
    schema: str | None,
    names: list[str] | None,
) -> dict[str, list[tuple[str, str, str]]]:
    """Discover foreign keys on a pre-opened connection."""
    with connection.cursor() as cursor:
        discovered_tables, qualify_with_schema = _get_discovered_tables(cursor, schema, names)
        if not discovered_tables:
            return {}

        source_schemas = sorted(
            {schema_name for _table_catalog, schema_name, _table_name in discovered_tables.values()}
        )
        schema_placeholders, schema_params = _build_named_value_placeholders("schema", source_schemas)

        cursor.execute(
            f"""
            SELECT
                tc.table_schema AS source_schema_name,
                tc.table_name AS table_name,
                kcu.column_name AS column_name,
                ccu.table_schema AS target_schema_name,
                ccu.table_name AS target_table_name,
                ccu.column_name AS target_column_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.constraint_schema = kcu.constraint_schema
                AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage AS ccu
                ON ccu.constraint_name = tc.constraint_name
                AND ccu.constraint_schema = tc.constraint_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema IN ({schema_placeholders})
            ORDER BY tc.table_schema, tc.table_name, kcu.ordinal_position
            """,
            schema_params,
        )
        result = cursor.fetchall()

        foreign_keys_by_table: dict[str, list[tuple[str, str, str]]] = collections.defaultdict(list)
        discovered_pairs_by_schema_and_table = {
            (schema_name, table_name): display_name
            for display_name, (_source_catalog, schema_name, table_name) in discovered_tables.items()
        }
        for (
            source_schema_name,
            table_name,
            column_name,
            target_schema_name,
            target_table_name,
            target_column_name,
        ) in result:
            display_name = discovered_pairs_by_schema_and_table.get((source_schema_name, table_name))
            if display_name is None:
                continue

            target_display_name = _get_display_table_name(
                target_schema_name,
                target_table_name,
                qualify_with_schema=qualify_with_schema or target_schema_name != source_schema_name,
            )
            foreign_keys_by_table[display_name].append((column_name, target_display_name, target_column_name))

        return foreign_keys_by_table


def get_foreign_keys(
    host: str,
    database: str,
    user: str,
    password: str,
    schema: str | None,
    port: int,
    require_ssl: bool = False,
    names: list[str] | None = None,
) -> dict[str, list[tuple[str, str, str]]]:
    """Get foreign keys for tables in the selected PostgreSQL schema."""
    with pg_connection(
        host=host, port=port, database=database, user=user, password=password, require_ssl=require_ssl
    ) as connection:
        return _foreign_keys_from_conn(connection, schema, names)


def get_connection_metadata(
    host: str,
    database: str,
    user: str,
    password: str,
    port: int,
    require_ssl: bool = False,
) -> dict[str, Any]:
    with pg_connection(
        host=host, port=port, database=database, user=user, password=password, require_ssl=require_ssl
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), version()")
            row = cursor.fetchone()
            current_database = str(row[0]) if row and row[0] is not None else database
            version = str(row[1]) if row and row[1] is not None else ""
            is_duckdb = "duckdb" in version.lower() or "duckgres" in version.lower()

            function_source = "duckdb_functions" if is_duckdb else "pg_proc"
            available_functions: list[str] = []
            available_table_functions: list[str] = []

            try:
                if is_duckdb:
                    cursor.execute("SELECT DISTINCT function_name FROM duckdb_functions()")
                else:
                    cursor.execute("SELECT DISTINCT proname FROM pg_proc WHERE pg_function_is_visible(oid)")
                available_functions = _normalize_function_names([row[0] for row in cursor.fetchall()])
            except Exception as error:
                capture_exception(error)

            try:
                if is_duckdb:
                    cursor.execute(
                        "SELECT DISTINCT function_name FROM duckdb_functions() WHERE function_type = 'table'"
                    )
                else:
                    # prokind='f' excludes aggregates/windows/procedures; proretset=true selects set-returning fns,
                    # which is how Postgres exposes table functions in pg_proc.
                    cursor.execute(
                        "SELECT DISTINCT proname FROM pg_proc "
                        "WHERE pg_function_is_visible(oid) AND proretset = true AND prokind = 'f'"
                    )
                available_table_functions = _normalize_function_names([row[0] for row in cursor.fetchall()])
            except Exception as error:
                capture_exception(error)

            available_functions = [fn for fn in available_functions if not is_dangerous_table_function(fn)]
            available_table_functions = [fn for fn in available_table_functions if not is_dangerous_table_function(fn)]

            return {
                "database": current_database,
                "version": version,
                "engine": "duckdb" if is_duckdb else "postgres",
                "function_source": function_source,
                "available_functions": available_functions,
                "available_table_functions": available_table_functions,
            }


class JsonAsStringLoader(Loader):
    def load(self, data):
        if data is None:
            return None
        return bytes(data).decode("utf-8")


class RangeAsStringLoader(Loader):
    """Load PostgreSQL range types as their string representation.

    We currently do not support range types. So, for now, the best we can do is
    convert them to `str`. For example, instead of loading a
    `psycopg.types.range.Range(4, 5, '[)')`, we will load `str` "[4,5)".

    Keep in mind that a single range can have multiple possible string
    representations. For example, `psycopg.types.range.Range(4, 5, '[]')` could
    be represented as "[4,5]" or "[4,6)". We let `psycopg` figure which string
    representation to use (from testing, it seems that the latter is preferred).
    """

    def load(self, data):
        if data is None:
            return None
        return bytes(data).decode("utf-8")


class SafeDateLoader(Loader):
    """Load PostgreSQL dates, handling edge cases beyond Python's date range.

    PostgreSQL can store dates beyond Python's datetime.date limits (year 1 to
    year 9999). This includes 'infinity', '-infinity', and dates in years > 9999.
    When encountering such dates, we clamp to Python's date limits rather than
    raising an error.
    """

    def load(self, data) -> date | None:
        if data is None:
            return None

        s = bytes(data).decode("utf-8")

        if s in ("infinity", "-infinity"):
            return date.max if s == "infinity" else date.min

        # Handle negative years (BC dates)
        if s.startswith("-") or "bc" in s.lower():
            return date.min

        try:
            parts = s.split("-")
            if len(parts) == 3:
                year = int(parts[0])
                month = int(parts[1])
                day = int(parts[2])

                if year > 9999:
                    return date.max
                if year < 1:
                    return date.min

                return date(year, month, day)
        except (ValueError, IndexError):
            pass

        # Fallback: clamp to max for unparseable dates
        return date.max


def _clamp_out_of_range_timestamp(data, *, tzinfo: timezone | None) -> datetime:
    """Map a Postgres timestamp value outside Python's datetime range onto datetime.min/max.

    PostgreSQL timestamps span years 4713 BC to 294276 AD and include 'infinity'/'-infinity',
    far wider than Python's datetime (year 1 to 9999). We pick the boundary by sign so values
    'before year 1' (BC dates, '-infinity', negative years) clamp low and everything else
    clamps high. `tzinfo` keeps the result aware/naive to match the column's Arrow type.
    """
    s = bytes(data).decode("utf-8", "replace").strip().lower()
    if s == "-infinity" or s.startswith("-") or "bc" in s:
        return datetime.min.replace(tzinfo=tzinfo)
    return datetime.max.replace(tzinfo=tzinfo)


class SafeTimestampLoader(TimestampLoader):
    """Load PostgreSQL timestamps, handling values beyond Python's datetime range.

    psycopg's default loader raises `DataError` on timestamps outside Python's datetime
    range (years > 9999, 'infinity'/'-infinity'), which aborts the whole table sync. We
    defer to the default loader for in-range values and clamp the rest, mirroring
    `SafeDateLoader`. `timestamp` columns map to a naive Arrow type, so the clamp stays naive.
    """

    # psycopg short-circuits SQL NULL before the loader, so `data` is never None in practice;
    # the guard mirrors SafeDateLoader's defensive parity, hence the widened return + override ignore.
    def load(self, data) -> datetime | None:  # type: ignore[override]
        if data is None:
            return None
        try:
            return super().load(data)
        except psycopg.DataError:
            return _clamp_out_of_range_timestamp(data, tzinfo=None)


class SafeTimestamptzLoader(TimestamptzLoader):
    """`timestamptz` counterpart of `SafeTimestampLoader` (see its docstring).

    `timestamptz` columns map to a UTC-aware Arrow type, so the clamp is made tz-aware to
    avoid mixing naive and aware datetimes in the same Arrow column.
    """

    # See SafeTimestampLoader.load for why the override is widened/ignored.
    def load(self, data) -> datetime | None:  # type: ignore[override]
        if data is None:
            return None
        try:
            return super().load(data)
        except psycopg.DataError:
            return _clamp_out_of_range_timestamp(data, tzinfo=UTC)


def _clamp_pg_hour_24(data) -> bytes | None:
    """Clamp a Postgres '24:00:00' time/timetz value to the max Python time.

    PostgreSQL accepts '24:00:00' as the maximum value for the `time` and
    `timetz` types (end-of-day midnight), but Python's datetime.time caps the
    hour at 23. The time portion of an hour-24 value is always exactly
    '24:00:00', so we return an equivalent buffer with the time clamped to the
    maximum representable value, preserving any timezone suffix. Returns None
    for any value that is not an hour-24 time, so callers re-raise as usual.
    """
    s = bytes(data).decode("utf-8")
    if not s.startswith("24:"):
        return None
    rest = s[len("24:00:00") :]
    tz_suffix = ""
    for i, ch in enumerate(rest):
        if ch in "+-":
            tz_suffix = rest[i:]
            break
    return ("23:59:59.999999" + tz_suffix).encode("utf-8")


def _load_time_clamping_hour_24(super_load: Callable[[Any], datetime_time], data) -> datetime_time:
    """Run psycopg's default time loader, clamping the '24:00:00' edge case.

    Mirrors SafeDateLoader's clamp-to-max behaviour: a Postgres end-of-day
    '24:00:00' (which Python's datetime.time cannot represent) is clamped to
    time.max, while every other value — and any genuine parse error — is
    delegated to psycopg's default loader.
    """
    try:
        return super_load(data)
    except psycopg.DataError:
        clamped = _clamp_pg_hour_24(data)
        if clamped is None:
            raise
        return super_load(clamped)


class SafeTimeLoader(TimeLoader):
    """Load PostgreSQL `time` values, clamping the '24:00:00' edge case."""

    def load(self, data) -> datetime_time:
        return _load_time_clamping_hour_24(super().load, data)


class SafeTimetzLoader(TimetzLoader):
    """Load PostgreSQL `timetz` values, clamping '24:00:00' while preserving the timezone offset."""

    def load(self, data) -> datetime_time:
        return _load_time_clamping_hour_24(super().load, data)


def _build_query(
    schema: str,
    table_name: str,
    should_use_incremental_field: bool,
    table_type: Literal["table", "view", "materialized_view"] | None,
    incremental_field: Optional[str],
    incremental_field_type: Optional[IncrementalFieldType],
    db_incremental_field_last_value: Optional[Any],
    add_sampling: Optional[bool] = False,
    *,
    upper_bound_inclusive: Optional[Any] = None,
    enabled_columns: Optional[list[str]] = None,
    primary_keys: Optional[list[str]] = None,
) -> sql.Composed:
    projected = compute_projected_columns(enabled_columns, primary_keys, incremental_field)
    select_clause: sql.Composable = (
        sql.SQL("*") if projected is None else sql.SQL(", ").join(sql.Identifier(c) for c in projected)
    )

    if not should_use_incremental_field:
        if add_sampling:
            if table_type == "view":
                query = sql.SQL("SELECT {cols} FROM {table} WHERE random() < 0.01").format(
                    cols=select_clause, table=sql.Identifier(schema, table_name)
                )
            else:
                query = sql.SQL("SELECT {cols} FROM {table} TABLESAMPLE SYSTEM (1)").format(
                    cols=select_clause, table=sql.Identifier(schema, table_name)
                )
        else:
            query = sql.SQL("SELECT {cols} FROM {table}").format(
                cols=select_clause, table=sql.Identifier(schema, table_name)
            )

        if add_sampling:
            query_with_limit = cast(LiteralString, f"{query.as_string()} LIMIT 1000")
            return sql.SQL(query_with_limit).format()

        return query

    if incremental_field is None or incremental_field_type is None:
        raise ValueError("incremental_field and incremental_field_type can't be None")

    if db_incremental_field_last_value is None:
        db_incremental_field_last_value = incremental_type_to_initial_value(incremental_field_type)

    # Use the type-aware operator (`>=` for Date) only for single-shot scans. Windowed
    # scans (upper_bound_inclusive set) must keep `>` because consecutive windows use the
    # previous window's hi as the next window's lo — `>=` would re-fetch every row at the
    # boundary value, duplicating each window's hi inside a single run.
    operator = (
        sql.SQL(incremental_type_to_operator(incremental_field_type)) if upper_bound_inclusive is None else sql.SQL(">")
    )

    if add_sampling:
        if table_type == "view":
            query = sql.SQL(
                "SELECT {cols} FROM {schema}.{table} WHERE {incremental_field} {op} {last_value} AND random() < 0.01"
            ).format(
                cols=select_clause,
                schema=sql.Identifier(schema),
                table=sql.Identifier(table_name),
                incremental_field=sql.Identifier(incremental_field),
                op=operator,
                last_value=sql.Literal(db_incremental_field_last_value),
            )
        else:
            query = sql.SQL(
                "SELECT {cols} FROM {schema}.{table} TABLESAMPLE SYSTEM (1) WHERE {incremental_field} {op} {last_value}"
            ).format(
                cols=select_clause,
                schema=sql.Identifier(schema),
                table=sql.Identifier(table_name),
                incremental_field=sql.Identifier(incremental_field),
                op=operator,
                last_value=sql.Literal(db_incremental_field_last_value),
            )
    else:
        query = sql.SQL("SELECT {cols} FROM {schema}.{table} WHERE {incremental_field} {op} {last_value}").format(
            cols=select_clause,
            schema=sql.Identifier(schema),
            table=sql.Identifier(table_name),
            incremental_field=sql.Identifier(incremental_field),
            op=operator,
            last_value=sql.Literal(db_incremental_field_last_value),
        )

    if add_sampling:
        query_with_limit = cast(LiteralString, f"{query.as_string()} LIMIT 1000")
        return sql.SQL(query_with_limit).format()

    if upper_bound_inclusive is not None:
        query = sql.SQL("{inner} AND {field} <= {upper}").format(
            inner=query,
            field=sql.Identifier(incremental_field),
            upper=sql.Literal(upper_bound_inclusive),
        )

    query_str = cast(LiteralString, f"{query.as_string()} ORDER BY {{incremental_field}} ASC")
    return sql.SQL(query_str).format(incremental_field=sql.Identifier(incremental_field))


def _build_count_query(
    schema: str,
    table_name: str,
    should_use_incremental_field: bool,
    incremental_field: Optional[str],
    incremental_field_type: Optional[IncrementalFieldType],
    db_incremental_field_last_value: Optional[Any],
) -> sql.Composed:
    if not should_use_incremental_field:
        return sql.SQL("SELECT COUNT(*) FROM {schema}.{table}").format(
            schema=sql.Identifier(schema),
            table=sql.Identifier(table_name),
        )

    if incremental_field is None or incremental_field_type is None:
        raise ValueError("incremental_field and incremental_field_type can't be None")

    if db_incremental_field_last_value is None:
        db_incremental_field_last_value = incremental_type_to_initial_value(incremental_field_type)

    operator = sql.SQL(incremental_type_to_operator(incremental_field_type))
    return sql.SQL("SELECT COUNT(*) FROM {schema}.{table} WHERE {incremental_field} {op} {last_value}").format(
        schema=sql.Identifier(schema),
        table=sql.Identifier(table_name),
        incremental_field=sql.Identifier(incremental_field),
        op=operator,
        last_value=sql.Literal(db_incremental_field_last_value),
    )


def _explain_query(cursor: psycopg.Cursor, query: sql.Composed, logger: FilteringBoundLogger):
    logger.debug(f"Running EXPLAIN on {query.as_string()}")

    try:
        # Debug-only, best-effort: EXPLAIN may use syntax the source rejects (e.g. TABLESAMPLE
        # on CockroachDB), so swallow failures.
        query_with_explain = sql.SQL("EXPLAIN {}").format(query)
        cursor.execute(query_with_explain)
        rows = cursor.fetchall()
        explain_result: str = ""
        # Build up a single string of the EXPLAIN output
        for row in rows:
            for col in row:
                explain_result += f"\n{col}"
        logger.debug(f"EXPLAIN result: {explain_result}")
    except Exception as e:
        logger.debug(f"EXPLAIN raised an exception: {e}")


def _get_primary_keys(
    cursor: psycopg.Cursor, schema: str, table_name: str, logger: FilteringBoundLogger
) -> list[str] | None:
    # Uses pg_catalog rather than information_schema because information_schema views
    # are ACL-filtered — a user with only SELECT grants may not see PK constraint rows
    # depending on PostgreSQL version, which silently returned no primary key at sync
    # time even though discovery (which already uses pg_catalog) found one.
    pg_catalog_query = sql.SQL("""
        SELECT a.attname AS column_name
        FROM pg_index i
        JOIN pg_class c ON c.oid = i.indrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY(i.indkey)
        WHERE i.indisprimary
          AND n.nspname = {schema}
          AND c.relname = {table}
        ORDER BY array_position(i.indkey, a.attnum)
    """).format(schema=sql.Literal(schema), table=sql.Literal(table_name))

    _explain_query(cursor, pg_catalog_query, logger)
    logger.debug(f"Running query: {pg_catalog_query.as_string()}")
    cursor.execute(pg_catalog_query)
    rows = cursor.fetchall()
    if len(rows) > 0:
        return [row[0] for row in rows]

    # Some partitioned setups define PKs on child partitions only.
    # In that case, infer PK columns from children if they are consistent.
    child_partition_pk_query = sql.SQL("""
        SELECT
            child_cls.relname AS child_table_name,
            att.attname AS pk_column_name,
            conkey.ordinality AS pk_ordinality
        FROM
            pg_catalog.pg_class parent_cls
        JOIN
            pg_catalog.pg_namespace parent_nsp
            ON parent_nsp.oid = parent_cls.relnamespace
        JOIN
            pg_catalog.pg_inherits inh
            ON inh.inhparent = parent_cls.oid
        JOIN
            pg_catalog.pg_class child_cls
            ON child_cls.oid = inh.inhrelid
        JOIN
            pg_catalog.pg_constraint con
            ON con.conrelid = child_cls.oid
            AND con.contype = 'p'
        JOIN LATERAL
            unnest(con.conkey) WITH ORDINALITY AS conkey(attnum, ordinality)
            ON TRUE
        JOIN
            pg_catalog.pg_attribute att
            ON att.attrelid = child_cls.oid
            AND att.attnum = conkey.attnum
        WHERE
            parent_nsp.nspname = {schema}
            AND parent_cls.relname = {table}
        ORDER BY
            child_cls.relname,
            conkey.ordinality
    """).format(schema=sql.Literal(schema), table=sql.Literal(table_name))
    child_pk_rows: list[tuple[str, str, int]] = []
    try:
        _explain_query(cursor, child_partition_pk_query, logger)
        logger.debug(f"Running child-partition fallback query: {child_partition_pk_query.as_string()}")
        cursor.execute(child_partition_pk_query)
        child_pk_rows = cursor.fetchall()
    except Exception as e:
        capture_exception(e)
        logger.warning(f"Child-partition fallback query failed for {table_name}: {e}")
    if len(child_pk_rows) > 0:
        child_pks: dict[str, list[str]] = {}
        for child_table_name, pk_column_name, _ in child_pk_rows:
            child_pks.setdefault(child_table_name, []).append(pk_column_name)

        unique_pk_sets = {tuple(pk_cols) for pk_cols in child_pks.values()}
        if len(unique_pk_sets) == 1:
            inferred_primary_keys = list(next(iter(unique_pk_sets)))
            logger.debug(f"Found primary keys for {table_name} via child partitions fallback: {inferred_primary_keys}")
            return inferred_primary_keys

        logger.warning(
            f"Found inconsistent child partition primary keys for {table_name}: {child_pks}. Could not infer a stable key for parent."
        )
        return None

    logger.warning(
        f"No primary keys found for {table_name}. If the table is not a view, does the table have a primary key set?"
    )

    return None


def _has_duplicate_primary_keys(
    cursor: psycopg.Cursor, schema: str, table_name: str, primary_keys: list[str] | None, logger: FilteringBoundLogger
) -> bool:
    if not primary_keys or len(primary_keys) == 0:
        return False

    try:
        sql_query = cast(
            LiteralString,
            f"""
            SELECT {", ".join(["{}" for _ in primary_keys])}
            FROM {{}}.{{}}
            GROUP BY {", ".join([str(i + 1) for i, _ in enumerate(primary_keys)])}
            HAVING COUNT(*) > 1
            LIMIT 1
        """,
        )
        query = sql.SQL(sql_query).format(
            *[sql.Identifier(key) for key in primary_keys], sql.Identifier(schema), sql.Identifier(table_name)
        )
        _explain_query(cursor, query, logger)
        logger.debug(f"Running query: {query.as_string()}")
        cursor.execute(query)
        row = cursor.fetchone()

        return row is not None
    except psycopg.errors.QueryCanceled:
        raise
    except Exception as e:
        capture_exception(e)
        return False


def _get_table_chunk_size(cursor: psycopg.Cursor, inner_query: sql.Composed, logger: FilteringBoundLogger) -> int:
    # Under autocommit each statement is its own transaction — a failure can't poison
    # subsequent commands, so no SAVEPOINT is needed. When called inside a shared
    # transaction (e.g. tests or future callers), wrap in a SAVEPOINT so that a
    # QueryCanceled doesn't abort the surrounding transaction.
    use_savepoint = not cursor.connection.autocommit
    try:
        if use_savepoint:
            cursor.execute("SAVEPOINT _chunk_size_probe")

        query = sql.SQL("""
            SELECT percentile_cont(0.95) within group (order by subquery.row_size) FROM (
                SELECT octet_length(t::text) as row_size FROM ({}) as t
            ) as subquery
        """).format(inner_query)

        # Best-effort: the sampled query can fail (e.g. TABLESAMPLE on CockroachDB); fall back.
        _explain_query(cursor, query, logger)
        logger.debug(f"Running query: {query.as_string()}")
        cursor.execute(query)
        row = cursor.fetchone()

        if use_savepoint:
            cursor.execute("RELEASE SAVEPOINT _chunk_size_probe")

        if row is None:
            logger.debug(f"_get_table_chunk_size: No results returned. Using DEFAULT_CHUNK_SIZE={DEFAULT_CHUNK_SIZE}")
            return DEFAULT_CHUNK_SIZE

        row_size_bytes = row[0] or 1
        chunk_size = int(DEFAULT_TABLE_SIZE_BYTES / row_size_bytes)
        logger.debug(
            f"_get_table_chunk_size: row_size_bytes={row_size_bytes}. DEFAULT_TABLE_SIZE_BYTES={DEFAULT_TABLE_SIZE_BYTES}. Using CHUNK_SIZE={chunk_size}"
        )

        return chunk_size
    except Exception as e:
        # Best-effort: any failure (including a statement_timeout / QueryCanceled) falls back to
        # DEFAULT_CHUNK_SIZE. The estimation query wraps the sample in `octet_length(t::text)`,
        # which serializes every column to text and so evaluates generated columns and check/domain
        # validator functions — making it strictly more expensive than the real chunked `SELECT *`
        # extraction. A timeout here therefore says nothing about whether extraction will succeed,
        # and the savepoint (when present) keeps the connection usable. The streaming read loop has
        # its own dedicated QueryCanceled handling (`_statement_timeout_as_non_retryable`), so
        # re-raising the cancellation here would only bypass that path and leak a raw, retryable
        # QueryCanceled that Temporal re-attempts forever on tables this query can never complete on.
        if use_savepoint:
            try:
                cursor.execute("ROLLBACK TO SAVEPOINT _chunk_size_probe")
            except Exception:
                pass
        logger.debug(f"_get_table_chunk_size: Error: {e}. Using DEFAULT_CHUNK_SIZE={DEFAULT_CHUNK_SIZE}", exc_info=e)

        return DEFAULT_CHUNK_SIZE


def _role_subject_to_rls(cursor: psycopg.Cursor, schema: str, table_name: str, logger: FilteringBoundLogger) -> bool:
    """Whether row-level security is active for the connecting role on this table."""
    try:
        query = sql.SQL("""
            SELECT row_security_active(c.oid)
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = {schema} AND c.relname = {table}
        """).format(schema=sql.Literal(schema), table=sql.Literal(table_name))
        cursor.execute(query)
        row = cursor.fetchone()
        return bool(row and row[0])
    except psycopg.errors.QueryCanceled:
        raise
    except Exception as e:
        logger.debug(f"_role_subject_to_rls: Error: {e}", exc_info=e)
        return False


def _get_rows_to_sync(cursor: psycopg.Cursor, count_query: sql.Composed, logger: FilteringBoundLogger) -> int:
    try:
        _explain_query(cursor, count_query, logger)
        logger.debug(f"Running query: {count_query.as_string()}")
        cursor.execute(count_query)
        row = cursor.fetchone()

        if row is None:
            logger.debug(f"_get_rows_to_sync: No results returned. Using 0 as rows to sync")
            return 0

        rows_to_sync = row[0] or 0
        rows_to_sync_int = int(rows_to_sync)

        logger.debug(f"_get_rows_to_sync: rows_to_sync_int={rows_to_sync_int}")

        return int(rows_to_sync)
    except psycopg.errors.QueryCanceled:
        raise
    except Exception as e:
        # This COUNT(*) is a best-effort estimate for progress reporting and partition sizing.
        # It shares its FROM/WHERE with the real extraction query, so any genuine problem
        # (missing column, unpopulated materialized view, permissions, bad incremental field)
        # resurfaces there and is classified through the normal retryable/non-retryable path.
        # Capturing it here too would only flood error tracking with handled duplicates of
        # user/upstream conditions we already tolerate, so we log at debug and fall back to 0.
        logger.debug(f"_get_rows_to_sync: Error: {e}. Using 0 as rows to sync", exc_info=e)

        if "temporary file size exceeds temp_file_limit" in str(e):
            raise TemporaryFileSizeExceedsLimitException(
                f"Error: {e}. Please ensure your incremental field has an appropriate index created"
            )

        return 0


def _get_partition_settings(
    cursor: psycopg.Cursor,
    schema: str,
    table_name: str,
    logger: FilteringBoundLogger,
    *,
    is_partitioned: bool | None = None,
) -> PartitionSettings | None:
    # For partitioned tables, a plain COUNT(*) and pg_table_size on the
    # parent would scan every child partition / return 0. Use catalog
    # estimates instead.
    try:
        # Reuse the caller's partition flag when given; saves a redundant catalog round trip.
        if is_partitioned is None:
            is_partitioned = _is_partitioned_table(cursor, schema, table_name)
        if is_partitioned:
            return _get_partition_settings_for_partitioned_table(cursor, schema, table_name, logger)
    except Exception as e:
        logger.debug(f"_get_partition_settings: partition detection failed, falling back: {e}")

    query = sql.SQL("""
        SELECT
            CASE WHEN count(*) = 0 OR pg_table_size({schema_table_name_literal}) = 0 THEN NULL
            ELSE round({bytes_per_partition} / (pg_table_size({schema_table_name_literal}) / count(*))) END,
            COUNT(*)
        FROM {schema}.{table}""").format(
        bytes_per_partition=sql.Literal(DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES),
        schema_table_name_literal=sql.Literal(f'{schema}."{table_name}"'),
        schema=sql.Identifier(schema),
        table=sql.Identifier(table_name),
    )

    try:
        _explain_query(cursor, query, logger)
        logger.debug(f"Running query: {query.as_string()}")
        cursor.execute(query)
    except psycopg.errors.QueryCanceled:
        raise
    except psycopg.errors.UndefinedTable as e:
        # The selected table was dropped or renamed in the source between schema discovery and
        # this best-effort partition-sizing probe. That's a user/upstream condition we already
        # tolerate here (return None -> no partitioning), and the real extraction query — which
        # shares this FROM clause — hits the same missing relation and surfaces it through the
        # normal non-retryable path ("does not exist"). Capturing it here too would only flood
        # error tracking with handled duplicates, so mirror `_get_rows_to_sync` and log at debug.
        logger.debug(f"_get_partition_settings: table does not exist, returning None: {e}")
        return None
    except Exception as e:
        # Partition sizing is a best-effort optimization: returning None just falls back to
        # default partition settings and the sync proceeds. This query shares its FROM with the
        # real extraction query, so any genuine problem (missing table, permissions, upstream
        # extension state, read-replica recovery conflict, or an earlier best-effort query in this
        # same transaction having left it `InFailedSqlTransaction`) resurfaces there and is
        # classified through the normal retryable/non-retryable path. Capturing it here too only
        # floods error tracking with handled duplicates of user/upstream conditions we already
        # tolerate, so log at debug and fall back — mirroring `_get_rows_to_sync`.
        logger.debug(f"_get_partition_settings: returning None due to error: {e}", exc_info=e)

        if "temporary file size exceeds temp_file_limit" in str(e):
            raise TemporaryFileSizeExceedsLimitException(
                f"Error: {e}. Please ensure your incremental field has an appropriate index created"
            )

        return None

    result = cursor.fetchone()

    if result is None or len(result) == 0 or result[0] is None:
        logger.debug(f"_get_partition_settings: query result is None, returning None")
        return None

    partition_size = int(result[0])
    total_rows = int(result[1])
    partition_count = math.floor(total_rows / partition_size)

    if partition_count == 0:
        logger.debug(f"_get_partition_settings: partition_count=1, partition_size={partition_size}")
        return PartitionSettings(partition_count=1, partition_size=partition_size)

    logger.debug(f"_get_partition_settings: partition_count={partition_count}, partition_size={partition_size}")
    return PartitionSettings(partition_count=partition_count, partition_size=partition_size)


class PostgreSQLColumn(Column):
    """Implementation of the `Column` protocol for a PostgreSQL source.

    Attributes:
        name: The column's name.
        data_type: The name of the column's data type as described in
            https://www.postgresql.org/docs/current/datatype.html.
        nullable: Whether the column is nullable or not.
        numeric_precision: The number of significant digits. Only used with
            numeric `data_type`s, otherwise `None`.
        numeric_scale: The number of significant digits to the right of
            decimal point. Only used with numeric `data_type`s, otherwise
            `None`.
    """

    def __init__(
        self,
        name: str,
        data_type: str,
        nullable: bool,
        numeric_precision: int | None = None,
        numeric_scale: int | None = None,
    ) -> None:
        self.name = name
        self.data_type = data_type
        self.nullable = nullable
        self.numeric_precision = numeric_precision
        self.numeric_scale = numeric_scale

    def to_arrow_field(self) -> pa.Field[pa.DataType]:
        """Return a `pyarrow.Field` that closely matches this column."""
        arrow_type: pa.DataType

        match self.data_type.lower():
            case "bigint":
                arrow_type = pa.int64()
            case "integer":
                arrow_type = pa.int32()
            case "smallint":
                arrow_type = pa.int16()
            case "numeric" | "decimal":
                # Use `is None` for the scale half of the guard so that legitimate `NUMERIC(X, 0)`
                # columns (integer-valued numerics, scale == 0) are not mistakenly treated as
                # "missing scale". Precision still uses a truthiness check — precision == 0 is a
                # real pathology (zero-digit budget) and should keep raising from our layer.
                if not self.numeric_precision or self.numeric_scale is None:
                    raise TypeError("expected `numeric_precision` and `numeric_scale` to be `int`, got `NoneType`")

                arrow_type = build_pyarrow_decimal_type(self.numeric_precision, self.numeric_scale)
            case "real":
                arrow_type = pa.float32()
            case "double precision":
                arrow_type = pa.float64()
            case "text" | "varchar" | "character varying":
                arrow_type = pa.string()
            case "date":
                arrow_type = pa.date32()
            case "time" | "time without time zone":
                arrow_type = pa.time64("us")
            case "timestamp" | "timestamp without time zone":
                arrow_type = pa.timestamp("us")
            case "timestamptz" | "timestamp with time zone":
                arrow_type = pa.timestamp("us", tz="UTC")
            case "interval":
                arrow_type = pa.duration("us")
            case "boolean":
                arrow_type = pa.bool_()
            case "bytea":
                arrow_type = pa.binary()
            case "uuid":
                arrow_type = pa.string()
            case "json" | "jsonb":
                arrow_type = pa.string()
            case _ if self.data_type.endswith("[]"):  # Array types
                arrow_type = pa.string()
            case _:
                arrow_type = pa.string()

        return pa.field(self.name, arrow_type, nullable=self.nullable)


def _is_read_replica(cursor: psycopg.Cursor) -> bool:
    cursor.execute("SELECT pg_is_in_recovery()")
    row = cursor.fetchone()
    if row is None:
        return False

    return row[0] is True


def _get_table(
    cursor: psycopg.Cursor,
    schema: str,
    table_name: str,
    logger: FilteringBoundLogger,
    probe_unconstrained_numeric_scale: bool = False,
) -> Table[PostgreSQLColumn]:
    """Read column metadata for `schema.table_name`.

    If `probe_unconstrained_numeric_scale` is True, additionally run a `MAX(scale(col))`
    aggregation on unconstrained `numeric` columns (those declared as `numeric` with no
    precision/scale) to pick a source arrow decimal scale that matches the real data.

    The probe is only useful when a fresh delta column is about to be created — either a
    first-ever sync or a post-reset sync with a cleared incremental watermark — because delta
    decimal column types are immutable after creation. On normal incremental syncs the delta
    column already exists and the probed value is discarded, so the caller should gate
    probing on "is a fresh schema being created" (see the equivalent gating on
    `_get_estimated_row_count_for_partitioned_table` in `postgres_source`)."""
    is_mat_view_query = sql.SQL(
        "select {table} in (select matviewname from pg_matviews where schemaname = {schema}) as res"
    ).format(schema=sql.Literal(schema), table=sql.Literal(table_name))
    is_mat_view_res = cursor.execute(is_mat_view_query).fetchone()
    is_mat_view = is_mat_view_res is not None and is_mat_view_res[0] is True
    is_view = False
    if not is_mat_view:
        is_view_query = sql.SQL(
            "select {table} in (select viewname from pg_views where schemaname = {schema}) as res"
        ).format(schema=sql.Literal(schema), table=sql.Literal(table_name))
        is_view_res = cursor.execute(is_view_query).fetchone()
        is_view = is_view_res is not None and is_view_res[0] is True

    if is_mat_view:
        # Table is a materialised view, column info doesn't exist in information_schema.columns
        query = sql.SQL("""
            SELECT
                a.attname AS column_name,
                pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type,
                NOT a.attnotnull AS is_nullable,
                CASE
                    WHEN t.typcategory = 'N' THEN
                        CASE
                            WHEN a.atttypmod = -1 THEN NULL
                            ELSE ((a.atttypmod - 4) >> 16) & 65535
                        END
                    ELSE NULL
                END AS numeric_precision,
                CASE
                    WHEN t.typcategory = 'N' THEN
                        CASE
                            WHEN a.atttypmod = -1 THEN NULL
                            ELSE (a.atttypmod - 4) & 65535
                        END
                    ELSE NULL
                END AS numeric_scale
            FROM pg_attribute a
            JOIN pg_class c ON a.attrelid = c.oid
            JOIN pg_namespace n ON c.relnamespace = n.oid
            JOIN pg_type t ON a.atttypid = t.oid
            WHERE c.relname = {table}
            AND n.nspname = {schema}
            AND a.attnum > 0
            AND NOT a.attisdropped""").format(schema=sql.Literal(schema), table=sql.Literal(table_name))
    else:
        query = sql.SQL("""
            SELECT
                column_name,
                data_type,
                is_nullable,
                numeric_precision,
                numeric_scale
            FROM
                information_schema.columns
            WHERE
                table_schema = {schema}
                AND table_name = {table}""").format(schema=sql.Literal(schema), table=sql.Literal(table_name))

    _explain_query(cursor, query, logger)
    logger.debug(f"Running query: {query.as_string()}")
    cursor.execute(query)

    numeric_data_types = {"numeric", "decimal"}
    metadata_rows = cursor.fetchall()

    # For unconstrained numeric columns (declared as `numeric` with no precision/scale),
    # postgres returns NULL for numeric_precision/numeric_scale in information_schema. Falling
    # back to a static default scale (18) causes the delta column to be created with less scale
    # than the actual data requires, which later breaks merges when a chunk contains values with
    # trailing non-zero digits past that default scale. Probe the actual data for its max used
    # scale so the delta column is sized correctly from the start.
    unconstrained_numeric_columns = [
        name
        for name, data_type, _nullable, _np, numeric_scale_candidate in metadata_rows
        if data_type in numeric_data_types and numeric_scale_candidate is None
    ]
    probed_scales: dict[str, int | None] = {}
    # Alongside scale, we also probe the max integer digits per column so we can size precision
    # to cover BOTH dimensions. Freezing the delta column at `decimal128(38, probed_scale)` when
    # the observed data has `int_digits + scale > 38` would cause later arrow casts to fail — the
    # probe alone cannot protect the integer side because precision is hard-capped at 38 for
    # decimal128.
    probed_int_digits: dict[str, int | None] = {}
    # Only probe when a fresh delta column is about to be created. On incremental syncs the
    # delta column type is already set and probing wastes a full-table aggregation per sync.
    # Skip regular views: `MAX(scale(col))` on a view forces the view definition to execute,
    # which can be arbitrarily expensive for join/aggregate views. Materialized views are
    # already materialized on disk and behave like tables here.
    if unconstrained_numeric_columns and probe_unconstrained_numeric_scale and not is_view:
        try:
            # Own transaction so the 30s `SET LOCAL statement_timeout` below scopes to this
            # aggregation and auto-resets (a self-contained BEGIN/COMMIT under autocommit).
            with cursor.connection.transaction():
                # Scope a short statement_timeout to the probe so a pathologically large table
                # or slow aggregation can't hang schema discovery. The outer 10-minute
                # statement_timeout isn't set until `postgres_source` continues after
                # `_get_table` returns, so without this the probe inherits whatever role-level
                # default postgres has — which might be "no limit" on some hosted instances.
                cursor.execute(
                    sql.SQL("SET LOCAL statement_timeout = {timeout}").format(
                        timeout=sql.Literal(30 * 1000)  # 30 seconds
                    )
                )
                # `abs(col)` strips the minus sign before `::text` so negative values don't
                # inflate the measured integer-digit count. `trunc` drops the fractional part;
                # the result is always numeric (never scientific notation), so `length(::text)`
                # is the integer-digit count. Pairs: (MAX(scale), MAX(int_digits)) per column,
                # emitted in the same order as `unconstrained_numeric_columns`.
                select_parts = sql.SQL(", ").join(
                    sql.SQL("MAX(scale({col})), MAX(length(trunc(abs({col}))::text))").format(
                        col=sql.Identifier(col_name)
                    )
                    for col_name in unconstrained_numeric_columns
                )
                probe_query = sql.SQL("SELECT {parts} FROM {table}").format(
                    parts=select_parts,
                    table=sql.Identifier(schema, table_name),
                )
                logger.debug(f"Probing numeric dimensions: {probe_query.as_string()}")
                cursor.execute(probe_query)
                row = cursor.fetchone()
                if row is not None:
                    for i, col_name in enumerate(unconstrained_numeric_columns):
                        probed_scales[col_name] = row[2 * i]
                        probed_int_digits[col_name] = row[2 * i + 1]
        except Exception as e:
            # Probe is best-effort. Fall back to DEFAULT_NUMERIC_SCALE and let the downstream
            # `_process_batch` fallback chain infer the right type at row-fetching time.
            logger.warning(
                "Failed to probe numeric dimensions",
                schema=schema,
                table=table_name,
                error=str(e),
            )

    columns = []
    for name, data_type, nullable, numeric_precision_candidate, numeric_scale_candidate in metadata_rows:
        if data_type in numeric_data_types:
            if numeric_scale_candidate is not None:
                # Constrained `NUMERIC(p, s)`: trust the declared precision and scale directly.
                numeric_precision = numeric_precision_candidate or DEFAULT_NUMERIC_PRECISION
                numeric_scale = numeric_scale_candidate
            else:
                probed_scale = probed_scales.get(name)
                probed_int = probed_int_digits.get(name)
                # Intentionally fall back to DEFAULT_NUMERIC_SCALE when probed_scale is 0 or
                # missing. A scale of 0 means every row we saw today happens to be integer-valued,
                # but the source column is declared as unconstrained `numeric` — meaning the schema
                # makes no scale promise. Freezing the delta column at scale=0 based on a transient
                # all-integer snapshot would reintroduce this PR's original bug the moment a future
                # sync sees a fractional value. DEFAULT_NUMERIC_SCALE leaves room for that future.
                if probed_scale is not None and probed_scale > 0:
                    # MAX_NUMERIC_SCALE bounds the scale we're willing to write into delta.
                    effective_scale = min(probed_scale, MAX_NUMERIC_SCALE)
                    # Precision must cover BOTH integer digits and scale — if `int_digits +
                    # effective_scale` fits within the decimal128 budget (38), keep precision at
                    # 38 to leave maximum integer headroom for future rows. Otherwise escalate
                    # precision past 38 so `build_pyarrow_decimal_type` promotes the column to
                    # decimal256. That column will then be collapsed to `string` at delta write
                    # time (see `ensure_delta_compatible_arrow_schema` in dlt's deltalake libs) —
                    # a known fidelity loss that's preferable to silently truncating either
                    # integer digits (undersized precision) or fractional digits (undersized
                    # scale).
                    total_needed = (probed_int or 0) + effective_scale
                    if total_needed <= DEFAULT_NUMERIC_PRECISION:
                        numeric_precision = DEFAULT_NUMERIC_PRECISION
                    else:
                        numeric_precision = total_needed
                        logger.warning(
                            "Unconstrained numeric column exceeds decimal128 budget; "
                            "will be stored as string in delta to preserve fidelity",
                            schema=schema,
                            table=table_name,
                            column=name,
                            total_digits_needed=total_needed,
                            integer_digits=probed_int,
                            scale=effective_scale,
                            decimal128_budget=DEFAULT_NUMERIC_PRECISION,
                        )
                    numeric_scale = effective_scale
                else:
                    numeric_precision = DEFAULT_NUMERIC_PRECISION
                    numeric_scale = DEFAULT_NUMERIC_SCALE
        else:
            numeric_precision = None
            numeric_scale = None

        columns.append(
            PostgreSQLColumn(
                name=name,
                data_type=data_type,
                nullable=nullable,
                numeric_precision=numeric_precision,
                numeric_scale=numeric_scale,
            )
        )

    table_type: Literal["materialized_view", "view", "table"] = "table"
    if is_mat_view:
        table_type = "materialized_view"
    elif is_view:
        table_type = "view"

    return Table(name=table_name, parents=(schema,), columns=columns, type=table_type)


def _project_table_columns(
    table: Table[PostgreSQLColumn],
    retained: list[str] | None,
) -> Table[PostgreSQLColumn]:
    """Return a new `Table` whose columns are filtered to `retained` (in source order).

    `None` retained returns the table unchanged. Columns missing from `retained` are dropped from
    the Arrow schema so projected SELECT output zips correctly into the schema."""
    if retained is None:
        return table

    retained_set = set(retained)
    filtered = [column for column in table.columns if column.name in retained_set]
    return Table(name=table.name, parents=table.parents, columns=filtered, type=table.type, alias=table.alias)


def postgres_source(
    tunnel: Callable[[], _GeneratorContextManager[tuple[str, int]]],
    user: str,
    password: str,
    database: str,
    sslmode: str,
    schema: str,
    table_names: list[str],
    should_use_incremental_field: bool,
    logger: FilteringBoundLogger,
    db_incremental_field_last_value: Optional[Any],
    chunk_size_override: Optional[int] = None,
    team_id: Optional[int] = None,
    incremental_field: Optional[str] = None,
    incremental_field_type: Optional[IncrementalFieldType] = None,
    require_ssl: bool = False,
    is_initial_sync: bool = False,
    enabled_columns: Optional[list[str]] = None,
) -> SourceResponse:
    table_name = table_names[0]
    if not table_name:
        raise ValueError("Table name is missing")

    effective_sslmode = _get_sslmode(require_ssl)

    with tunnel() as (host, port):

        def _open_setup_connection() -> psycopg.Connection:
            try:
                conn = _connect_with_options_fallback(
                    host=host,
                    port=port,
                    dbname=database,
                    user=user,
                    password=password,
                    sslmode=effective_sslmode,
                    connect_timeout=15,
                    sslrootcert="/tmp/no.txt",
                    sslcert="/tmp/no.txt",
                    sslkey="/tmp/no.txt",
                    keepalives=1,
                    keepalives_idle=30,
                    keepalives_interval=10,
                    keepalives_count=5,
                    options=FORCE_UTF8_CLIENT_ENCODING,
                )
            except psycopg.OperationalError as e:
                if require_ssl and "SSL" in str(e):
                    raise SSLRequiredError(
                        "SSL/TLS connection is required but your database does not support it. "
                        "Please enable SSL/TLS on your PostgreSQL server or contact your database administrator."
                    ) from e
                raise

            # Autocommit so each best-effort probe is its own transaction: one that fails — a
            # read-replica recovery conflict on a slow COUNT(*), or syntax the source rejects like
            # TABLESAMPLE on CockroachDB — can't poison the rest. Replaces the per-probe savepoints.
            conn.autocommit = True
            return conn

        # A hot-standby recovery conflict ("terminating connection due to conflict with recovery")
        # terminates the whole connection mid-probe, so autocommit alone can't isolate it — every
        # subsequent probe on the dead connection fails too. Reconnect and retry the metadata
        # probes a bounded number of times with backoff, mirroring how the read loop recovers from
        # the same conflict. Only once the conflicts are sustained do we raise the non-retryable
        # "successive SerializationFailure errors" abort the read path already uses, rather than
        # letting Temporal re-run setup straight back into the same wall.
        setup_recovery_conflicts = 0
        setup_connection_dropped_errors = 0
        while True:
            # Opening the setup connection can itself hit a transient drop ("server closed the
            # connection unexpectedly", idle cull, failover) — the same class of error the read
            # path already recovers from. Retry the connect in-process with bounded backoff,
            # mirroring `offset_chunking`, so a momentary blip during setup doesn't fail the whole
            # activity. Permanent errors (auth failures, SSL-required) re-raise immediately.
            connection = _connect_with_dropped_retry(_open_setup_connection, logger)
            try:
                with connection:
                    with connection.cursor() as cursor:
                        logger.debug("Getting table types...")
                        # Only probe the actual data for numeric scale when a fresh delta column is
                        # about to be created — either a first-ever sync or a post-reset full scan
                        # (watermark cleared). On normal incremental syncs the delta column already
                        # exists, so probing would be a wasted full-table aggregation. Mirrors the
                        # `is_initial_sync or full_table_scan` gating used a few lines below for
                        # partitioned-table row estimation.
                        fresh_schema_being_created = is_initial_sync or db_incremental_field_last_value is None
                        full_table = _get_table(
                            cursor,
                            schema,
                            table_name,
                            logger,
                            probe_unconstrained_numeric_scale=fresh_schema_being_created,
                        )

                        # Session, not LOCAL: under autocommit a LOCAL timeout has no transaction to bind to.
                        cursor.execute(
                            sql.SQL("SET statement_timeout = {timeout}").format(
                                timeout=sql.Literal(1000 * 60 * 10)  # 10 mins
                            )
                        )

                        try:
                            logger.debug("Checking if source is a read replica...")
                            using_read_replica = _is_read_replica(cursor)
                            logger.debug(f"using_read_replica = {using_read_replica}")
                            logger.debug("Getting primary keys...")
                            primary_keys = _get_primary_keys(cursor, schema, table_name, logger)
                            if primary_keys:
                                logger.debug(f"Found primary keys: {primary_keys}")

                            # Fallback on checking for an `id` field on the table. Resolve the PKs
                            # before building queries so chunk-size sampling and the actual reader
                            # project the same columns.
                            used_id_pk_fallback = False
                            if primary_keys is None and "id" in full_table:
                                logger.debug("Falling back to ['id'] for primary keys...")
                                primary_keys = ["id"]
                                used_id_pk_fallback = True

                            # Project both the Arrow schema and the SELECT clause so the cursor's row shape
                            # matches what downstream consumers expect.
                            retained_columns: list[str] | None = None
                            if enabled_columns is not None:
                                retained_set: set[str] = set(enabled_columns)
                                for pk in primary_keys or []:
                                    retained_set.add(pk)
                                if incremental_field:
                                    retained_set.add(incremental_field)
                                retained_columns = [
                                    column.name for column in full_table.columns if column.name in retained_set
                                ]
                                # Mirror `compute_projected_columns` fallback to `SELECT *` so Arrow stays full-table.
                                if not retained_columns:
                                    retained_columns = None

                            table = _project_table_columns(full_table, retained_columns)
                            logger.debug(f"Source schema: {table.to_arrow_schema()}")

                            inner_query_with_limit = _build_query(
                                schema,
                                table_name,
                                should_use_incremental_field,
                                table.type,
                                incremental_field,
                                incremental_field_type,
                                db_incremental_field_last_value,
                                add_sampling=True,
                                enabled_columns=enabled_columns,
                                primary_keys=primary_keys,
                            )

                            count_query = _build_count_query(
                                schema,
                                table_name,
                                should_use_incremental_field,
                                incremental_field,
                                incremental_field_type,
                                db_incremental_field_last_value,
                            )

                            logger.debug("Checking if table is partitioned...")
                            is_partitioned = False
                            child_partitions: list = []
                            try:
                                is_partitioned = _is_partitioned_table(cursor, schema, table_name)
                                if is_partitioned:
                                    child_partitions = list_child_partitions(cursor, schema, table_name)
                            except Exception as e:
                                logger.debug(f"Partition detection failed: {e}")
                            logger.debug("Getting table chunk size...")
                            if chunk_size_override is not None:
                                chunk_size = chunk_size_override
                                logger.debug(f"Using chunk_size_override: {chunk_size_override}")
                            else:
                                chunk_size = _get_table_chunk_size(cursor, inner_query_with_limit, logger)

                            logger.debug("Getting rows to sync...")
                            # For partitioned tables without an incremental cursor (initial
                            # sync, re-sync, or non-incremental), use pg_class.reltuples
                            # estimate to avoid scanning all partitions with a COUNT(*).
                            # `is_initial_sync` only reflects the first-ever sync; a forced
                            # re-sync keeps initial_sync_complete=True but still scans the
                            # whole table, so we gate on the filter actually being a full
                            # scan (no incremental cursor value).
                            rows_to_sync: int | None = None
                            full_table_scan = db_incremental_field_last_value is None
                            if is_partitioned and (is_initial_sync or full_table_scan):
                                try:
                                    logger.debug(
                                        f"Partitioned table detected (is_initial_sync={is_initial_sync}, "
                                        f"full_table_scan={full_table_scan}), using estimated row count"
                                    )
                                    rows_to_sync = _get_estimated_row_count_for_partitioned_table(
                                        cursor, schema, table_name, logger
                                    )
                                except Exception as e:
                                    logger.debug(f"Estimated row count failed, falling back to exact count: {e}")
                            if rows_to_sync is None:
                                rows_to_sync = _get_rows_to_sync(cursor, count_query, logger)

                            if _role_subject_to_rls(cursor, schema, table_name, logger):
                                logger.warning(
                                    f"Row-level security is active for the sync role on {schema}.{table_name} "
                                    f"(rows visible to this sync: {rows_to_sync}). Grant the role BYPASSRLS "
                                    f"or a permissive policy if it should see all rows."
                                )

                            logger.debug("Getting partition settings...")
                            partition_settings = (
                                _get_partition_settings(
                                    cursor, schema, table_name, logger, is_partitioned=is_partitioned
                                )
                                if should_use_incremental_field
                                else None
                            )

                            # Bounded date/numeric window chunking for partitioned parents keeps
                            # each query small so statement_timeout stays comfortable and partition
                            # pruning can drop empty partitions server-side. Non-partitioned tables
                            # continue through the legacy single-cursor path below.
                            use_window_chunking = (
                                is_partitioned
                                and should_use_incremental_field
                                and is_supported_incremental_type_for_window(incremental_field_type)
                            )
                            # When the parent is range-partitioned on the incremental field, we can
                            # query each child relation directly instead of routing through the parent
                            # and forcing the planner to Append + sort across all children. One cursor
                            # per child = no cross-partition merge sort, trivial pruning, and child-sized
                            # query plans that fit comfortably under statement_timeout.
                            use_per_partition_chunking = False
                            if use_window_chunking and child_partitions:
                                try:
                                    partition_strategy = get_partition_strategy(cursor, schema, table_name)
                                except Exception as e:
                                    partition_strategy = None
                                    logger.debug(f"Partition strategy detection failed: {e}")
                                use_per_partition_chunking = (
                                    partition_strategy is not None
                                    and partition_strategy.strategy == "r"
                                    and incremental_field is not None
                                    and incremental_field in partition_strategy.key_columns
                                )
                            logger.debug(
                                f"Postgres read strategy: use_window_chunking={use_window_chunking}, "
                                f"use_per_partition_chunking={use_per_partition_chunking}, "
                                f"child_partitions={len(child_partitions)}"
                            )

                            has_duplicate_primary_keys = False
                            if used_id_pk_fallback:
                                logger.debug("Checking duplicate primary keys...")
                                has_duplicate_primary_keys = _has_duplicate_primary_keys(
                                    cursor, schema, table_name, primary_keys, logger
                                )
                        except psycopg.errors.QueryCanceled:
                            if should_use_incremental_field:
                                raise QueryTimeoutException(
                                    f"10 min timeout statement reached. Please ensure your incremental field ({incremental_field}) has an appropriate index created"
                                )
                            raise
                        except Exception:
                            raise
                break
            except psycopg.errors.SerializationFailure as e:
                if "conflict with recovery" not in "".join(e.args):
                    raise
                # Connection is dead; close defensively before reconnecting.
                _safe_close_connection(connection)
                setup_recovery_conflicts += 1
                if setup_recovery_conflicts >= _MAX_SETUP_RECOVERY_CONFLICT_RETRIES:
                    raise Exception(
                        f"Hit {setup_recovery_conflicts} successive SerializationFailure errors. Aborting."
                    ) from e
                logger.debug(
                    f"SerializationFailure during table setup ({e}). Reconnecting and retrying "
                    f"(attempt {setup_recovery_conflicts}/{_MAX_SETUP_RECOVERY_CONFLICT_RETRIES})"
                )
                time.sleep(min(2 * setup_recovery_conflicts, 30))
            except _CONNECTION_DROPPED_ERROR_TYPES as e:
                # A transient drop *during* the metadata probes (e.g. a Supavisor pooler "DbHandler
                # exited" or a libpq "server closed the connection unexpectedly" while running
                # `_get_table`) leaves the connection dead. `_connect_with_dropped_retry` only guards
                # the initial connect, so without this the probe-time drop escapes and fails the
                # whole activity. Reconnect and retry the probes in-process with bounded backoff,
                # mirroring the recovery-conflict handler above and the read path's offset-chunking
                # recovery. Permanent errors (auth failures, SSL-required, genuine XX000 internal
                # errors) aren't connection drops, so they re-raise immediately.
                if not _is_connection_dropped_error(e):
                    raise
                _safe_close_connection(connection)
                setup_connection_dropped_errors += 1
                if setup_connection_dropped_errors >= _MAX_SETUP_CONNECTION_DROPPED_RETRIES:
                    raise
                logger.debug(
                    f"Connection dropped during table setup ({e}). Reconnecting and retrying "
                    f"(attempt {setup_connection_dropped_errors}/{_MAX_SETUP_CONNECTION_DROPPED_RETRIES})"
                )
                time.sleep(min(2 * setup_connection_dropped_errors, 30))

    def get_rows(chunk_size: int) -> Iterator[Any]:
        arrow_schema = table.to_arrow_schema()
        with tunnel() as (host, port):
            cursor_factory = psycopg.ServerCursor if not using_read_replica else None

            def get_connection():
                try:
                    connection = _connect_with_options_fallback(
                        host=host,
                        port=port,
                        dbname=database,
                        user=user,
                        password=password,
                        sslmode=effective_sslmode,
                        connect_timeout=15,
                        sslrootcert="/tmp/no.txt",
                        sslcert="/tmp/no.txt",
                        sslkey="/tmp/no.txt",
                        cursor_factory=cursor_factory,
                        keepalives=1,
                        keepalives_idle=30,
                        keepalives_interval=10,
                        keepalives_count=5,
                        options=FORCE_UTF8_CLIENT_ENCODING,
                    )
                except psycopg.OperationalError as e:
                    if require_ssl and "SSL" in str(e):
                        raise SSLRequiredError(
                            "SSL/TLS connection is required but your database does not support it. "
                            "Please enable SSL/TLS on your PostgreSQL server or contact your database administrator."
                        ) from e
                    raise
                connection.adapters.register_loader("json", JsonAsStringLoader)
                connection.adapters.register_loader("jsonb", JsonAsStringLoader)
                connection.adapters.register_loader("int4range", RangeAsStringLoader)
                connection.adapters.register_loader("int8range", RangeAsStringLoader)
                connection.adapters.register_loader("numrange", RangeAsStringLoader)
                connection.adapters.register_loader("tsrange", RangeAsStringLoader)
                connection.adapters.register_loader("tstzrange", RangeAsStringLoader)
                connection.adapters.register_loader("daterange", RangeAsStringLoader)
                connection.adapters.register_loader("date", SafeDateLoader)
                connection.adapters.register_loader("timestamp", SafeTimestampLoader)
                connection.adapters.register_loader("timestamptz", SafeTimestamptzLoader)
                connection.adapters.register_loader("time", SafeTimeLoader)
                connection.adapters.register_loader("timetz", SafeTimetzLoader)
                # Bump statement_timeout for the streaming connection. A server
                # cursor FETCH inherits the session statement_timeout, and on
                # wide/partitioned scans the source's default (often 30-60s)
                # kills the fetch before rows come back.
                try:
                    # Use psycopg.Cursor directly to bypass cursor_factory (which may be
                    # ServerCursor and requires a `name` arg, breaking an unnamed cursor()).
                    with psycopg.Cursor(connection) as setup_cursor:
                        setup_cursor.execute(
                            sql.SQL("SET statement_timeout = {timeout}").format(
                                timeout=sql.Literal(SYNC_STATEMENT_TIMEOUT_MS)
                            )
                        )
                except Exception as e:
                    logger.debug(f"Failed to set statement_timeout on sync connection: {e}")
                # The SET above opens an implicit transaction in psycopg's default
                # non-autocommit mode, leaving the connection INTRANS. Commit so the
                # connection is returned IDLE: callers that flip on autocommit (offset
                # chunking) would otherwise hit "can't change autocommit state:
                # connection in transaction". SET statement_timeout has session scope,
                # so committing preserves it.
                connection.commit()
                return connection

            def offset_chunking(offset: int, chunk_size: int):
                # If the db is a read replica and we're running into `conflict with recovery errors,
                # we create a new query for each chunk. This is due to how the primary replicates
                # over, we often run into errors when vacuums are happening
                logger.debug(
                    f"Using offset chunking to read from read replica. offset = {offset}, chunk_size = {chunk_size}"
                )

                query = _build_query(
                    schema,
                    table_name,
                    should_use_incremental_field,
                    table.type,
                    incremental_field,
                    incremental_field_type,
                    db_incremental_field_last_value,
                    enabled_columns=enabled_columns,
                    primary_keys=primary_keys,
                )

                successive_errors = 0
                successive_conn_errors = 0
                connection = _connect_with_dropped_retry(get_connection, logger)
                # Autocommit so each LIMIT/OFFSET query runs as its own statement
                # and no transaction stays open across the slow delta-merge that
                # happens between yields. A held transaction is what gets the
                # backend culled by idle_in_transaction_session_timeout, producing
                # the "server conn crashed?" ProtocolViolation on the next fetch.
                connection.autocommit = True
                while True:
                    try:
                        if connection.closed:
                            logger.debug("Postgres connection was closed, reopening...")
                            connection = get_connection()
                            connection.autocommit = True

                        # Use psycopg.Cursor directly to bypass cursor_factory: on a
                        # non-read-replica source it is ServerCursor (set in get_rows),
                        # which requires a `name` and makes an unnamed connection.cursor()
                        # raise "ServerCursor.__init__() missing 1 required positional
                        # argument: 'name'". This LIMIT/OFFSET fetchall path wants an
                        # unnamed client cursor.
                        with psycopg.Cursor(connection) as cursor:
                            query_with_limit = cast(
                                LiteralString, f"{query.as_string()} LIMIT {chunk_size} OFFSET {offset}"
                            )
                            query_with_limit_sql = sql.SQL(query_with_limit).format()

                            logger.debug(f"Postgres query: {query_with_limit}")
                            cursor.execute(query_with_limit_sql)

                            column_names = [column.name for column in cursor.description or []]
                            rows = cursor.fetchall()

                            if not rows or len(rows) == 0:
                                break

                            offset += len(rows)

                            yield table_from_iterator((dict(zip(column_names, row)) for row in rows), arrow_schema)

                            successive_errors = 0
                            successive_conn_errors = 0
                    except psycopg.errors.SerializationFailure as e:
                        if "due to conflict with recovery" not in "".join(e.args):
                            raise

                        # This error happens when the read replica is out of sync with the primary
                        logger.debug(f"SerializationFailure error: {e}. Retrying chunk at offset {offset}")

                        successive_errors += 1
                        if successive_errors >= 30:
                            # The connection should be closed here, but want to double check to make sure
                            _safe_close_connection(connection)

                            raise Exception(
                                f"Hit {successive_errors} successive SerializationFailure errors. Aborting."
                            ) from e
                        elif successive_errors >= 5:
                            chunk_size = max(int(chunk_size / 1.5), 100)
                            logger.debug(f"Reducing chunk size to {chunk_size} to reduce load on read replica")
                            time.sleep(2 * successive_errors)
                        else:
                            # Linear backoff on successive errors to make sure we give the read replica time to catch up
                            time.sleep(2 * successive_errors)
                    except psycopg.errors.QueryCanceled as e:
                        # A chunk hit the 10-min statement_timeout. QueryCanceled
                        # subclasses OperationalError, so this clause must precede the
                        # connection-dropped handler below. Retrying won't help, so map
                        # it to the same non-retryable QueryTimeoutException the
                        # server-cursor and windowed paths raise instead of leaking a
                        # raw, retryable QueryCanceled that Temporal keeps re-attempting.
                        _safe_close_connection(connection)
                        timeout_error = _statement_timeout_as_non_retryable(
                            e,
                            should_use_incremental_field=should_use_incremental_field,
                            incremental_field=incremental_field,
                        )
                        if timeout_error is not None:
                            raise timeout_error from e
                        raise
                    except _CONNECTION_DROPPED_ERROR_TYPES as e:
                        if not _is_connection_dropped_error(e):
                            _safe_close_connection(connection)
                            raise

                        # The upstream connection died (idle cull, failover, etc.).
                        # offset only advances after a fully fetched+yielded chunk,
                        # so reopening and retrying the same offset resumes cleanly.
                        successive_conn_errors += 1
                        _safe_close_connection(connection)
                        if successive_conn_errors >= 10:
                            raise Exception(
                                f"Hit {successive_conn_errors} successive connection-dropped errors. Aborting."
                            ) from e
                        logger.debug(
                            f"Connection dropped ({e}). Reconnecting and retrying chunk at offset {offset} "
                            f"(attempt {successive_conn_errors})"
                        )
                        time.sleep(min(2 * successive_conn_errors, 30))
                        connection = _connect_with_dropped_retry(get_connection, logger)
                        connection.autocommit = True
                    except Exception:
                        _safe_close_connection(connection)
                        raise

                _safe_close_connection(connection)

            if use_per_partition_chunking and incremental_field is not None and incremental_field_type is not None:

                def _build_per_partition_query(child_schema: str, child_name: str) -> sql.Composed:
                    return build_partition_query(
                        child_schema,
                        child_name,
                        should_use_incremental_field,
                        incremental_field,
                        incremental_field_type,
                        db_incremental_field_last_value,
                        enabled_columns=enabled_columns,
                        primary_keys=primary_keys,
                    )

                yield from iterate_partitions(
                    get_connection=get_connection,
                    build_partition_query=_build_per_partition_query,
                    schema=schema,
                    table_name=table_name,
                    child_partitions=child_partitions,
                    chunk_size=chunk_size,
                    arrow_schema=arrow_schema,
                    logger=logger,
                    incremental_field=incremental_field,
                    incremental_field_type=incremental_field_type,
                    db_incremental_field_last_value=db_incremental_field_last_value,
                )
                return

            if use_window_chunking and incremental_field is not None and incremental_field_type is not None:

                def _build_windowed_query(lo: Any, hi: Any) -> sql.Composed:
                    return _build_query(
                        schema,
                        table_name,
                        should_use_incremental_field,
                        table.type,
                        incremental_field,
                        incremental_field_type,
                        lo,
                        upper_bound_inclusive=hi,
                        enabled_columns=enabled_columns,
                        primary_keys=primary_keys,
                    )

                yield from iterate_date_windows(
                    get_connection=get_connection,
                    build_windowed_query=_build_windowed_query,
                    schema=schema,
                    table_name=table_name,
                    incremental_field=incremental_field,
                    incremental_field_type=incremental_field_type,
                    db_incremental_field_last_value=db_incremental_field_last_value,
                    child_partitions=child_partitions,
                    chunk_size=chunk_size,
                    arrow_schema=arrow_schema,
                    logger=logger,
                    using_read_replica=using_read_replica,
                )
                return

            offset = 0
            try:
                # Retry transient connection-dropped errors (e.g. "server closed the
                # connection unexpectedly") on the initial connect, matching the
                # offset-chunking bootstrap above. Retrying here is always safe: offset
                # is still 0 and no rows have been yielded, so the unsafe-resume concern
                # in the except clause below doesn't apply. Permanent errors (auth,
                # SSL-required) still surface immediately — _is_connection_dropped_error
                # only matches transient drops.
                with _connect_with_dropped_retry(get_connection, logger) as connection:
                    with connection.cursor(name=f"posthog_{team_id}_{schema}.{table_name}") as cursor:
                        query = _build_query(
                            schema,
                            table_name,
                            should_use_incremental_field,
                            table.type,
                            incremental_field,
                            incremental_field_type,
                            db_incremental_field_last_value,
                            enabled_columns=enabled_columns,
                            primary_keys=primary_keys,
                        )
                        logger.debug(f"Postgres query: {query.as_string()}")

                        cursor.execute(query)

                        column_names = [column.name for column in cursor.description or []]

                        while True:
                            rows = cursor.fetchmany(chunk_size)
                            if not rows:
                                break

                            dicts = [dict(zip(column_names, row)) for row in rows]
                            del rows
                            yield table_from_iterator(iter(dicts), arrow_schema)
                            offset += len(dicts)
            except psycopg.errors.SerializationFailure as e:
                # If we hit a SerializationFailure and we're reading from a read replica, we fallback to offset chunking
                if using_read_replica and "conflict with recovery" in "".join(e.args):
                    logger.debug(f"Falling back to offset chunking for table due to SerializationFailure error: {e}.")
                    yield from offset_chunking(offset, chunk_size)
                    return

                raise
            except _CONNECTION_DROPPED_ERROR_TYPES as e:
                # The server cursor holds a transaction open across the slow
                # delta-merge between yields; the source can cull the backend
                # (idle_in_transaction_session_timeout / PgBouncer) and the next
                # fetch fails with "server conn crashed?". Resume from the current
                # offset via offset_chunking, which runs in autocommit so it never
                # holds a transaction open across the merge.
                if not _is_connection_dropped_error(e):
                    raise
                # Offset-based resume is only safe when the query has a stable
                # ORDER BY (added by _build_query for incremental syncs). A
                # full-table scan has no ORDER BY, so Postgres may return rows in
                # a different order on the resumed query and OFFSET would skip or
                # duplicate rows. In that case re-raise and let the sync restart.
                if not should_use_incremental_field:
                    raise
                logger.debug(f"Connection dropped ({e}). Falling back to offset chunking at offset {offset}.")
                yield from offset_chunking(offset, chunk_size)
                return

    name = NamingConvention.normalize_identifier(table_name)

    return SourceResponse(
        name=name,
        items=lambda: get_rows(chunk_size),
        primary_keys=primary_keys,
        partition_count=partition_settings.partition_count if partition_settings else None,
        partition_size=partition_settings.partition_size if partition_settings else None,
        rows_to_sync=rows_to_sync,
        has_duplicate_primary_keys=has_duplicate_primary_keys,
    )


# psycopg's `Cursor.execute` accepts `sql.Composable`/`bytes` in addition to `str`, so it
# does not satisfy the narrow `_CursorLike(execute(query: str, ...))` protocol on the base.
# Use `Any` for the cursor type variable.
class PostgresImplementation(SQLSourceImplementation[PostgresSourceConfig, psycopg.Connection, Any]):
    """Minimal `SQLSourceImplementation` stub paired with `PostgresSource`.

    `PostgresSource` overrides `get_schemas` and `source_for_pipeline` end to
    end — multi-schema discovery, `enabled_columns` column selection, CDC
    dispatch, SSL cutoff, and storage-key naming all live there because none of
    them fit `SourceInputs` or the base template. This impl only exists to
    satisfy the `SQLSource` type contract; only the four abstract methods are
    implemented. A deeper migration that pushes Postgres onto the base template
    would extend `SourceInputs` and is tracked as future work.
    """

    @contextmanager
    def connect(
        self,
        config: PostgresSourceConfig,
        *,
        require_ssl: bool = False,
    ) -> Iterator[psycopg.Connection]:
        """Open a single psycopg connection (through the SSH tunnel if configured)."""
        with open_ssh_tunnel(config) as (host, port):
            with pg_connection(
                host=host,
                port=port,
                database=config.database,
                user=config.user,
                password=config.password,
                require_ssl=require_ssl,
            ) as conn:
                yield conn

    def get_columns(
        self,
        conn: psycopg.Connection,
        config: PostgresSourceConfig,
        names: list[str] | None,
    ) -> dict[str, list[tuple[str, str, bool]]]:
        discovered = _schemas_from_conn(conn, config.schema, names)
        return {display_name: discovered_schema.columns for display_name, discovered_schema in discovered.items()}

    def get_incremental_filter(self) -> IncrementalFieldFilter:
        return filter_postgres_incremental_fields

    def build_pipeline(self, config: PostgresSourceConfig, inputs: SourceInputs) -> SourceResponse:
        """Postgres syncs go through `PostgresSource.source_for_pipeline`, not this method.

        The production path needs the `ExternalDataSchema` lookup to thread
        `enabled_columns`, `require_ssl` (derived from `source_requires_ssl`),
        `is_initial_sync`, `chunk_size_override`, and the multi-schema /
        CDC-streaming reconciliation into `postgres_source(...)`. None of that is
        available from `SourceInputs` alone, and silently defaulting `require_ssl`
        to `False` here would let new (post-cutoff) sources bypass SSL on the base
        template path. Raise loudly so a refactor that drops the source-level
        override surfaces immediately rather than going to prod unencrypted.
        """
        raise NotImplementedError(
            "PostgresImplementation.build_pipeline is intentionally not implemented — "
            "use PostgresSource.source_for_pipeline which forwards require_ssl, "
            "enabled_columns, chunk_size_override, and CDC reconciliation."
        )
