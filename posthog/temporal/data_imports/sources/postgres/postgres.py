from __future__ import annotations

import re
import math
import time
import collections
from collections.abc import Callable, Iterator
from contextlib import _GeneratorContextManager, contextmanager
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any, Literal, LiteralString, Optional, cast

if TYPE_CHECKING:
    from products.data_warehouse.backend.models import ExternalDataSource

from django.conf import settings

import psycopg
import pyarrow as pa
import structlog
from psycopg import sql
from psycopg.adapt import Loader
from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception
from posthog.temporal.data_imports.naming_convention import NamingConvention
from posthog.temporal.data_imports.pipelines.helpers import incremental_type_to_initial_value
from posthog.temporal.data_imports.pipelines.pipeline.consts import DEFAULT_CHUNK_SIZE, DEFAULT_TABLE_SIZE_BYTES
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
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
from posthog.temporal.data_imports.sources.common.sql import Column, Table

from products.data_warehouse.backend.types import IncrementalFieldType, PartitionSettings

# Sources created after this date must use SSL/TLS connections
SSL_REQUIRED_AFTER_DATE = datetime(2026, 2, 18, tzinfo=UTC)
IDENTIFIER_FUNCTION_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Max rows per FETCH when reading a partitioned parent table. A partitioned
# parent scan dispatches across every child partition; a large chunk size can
# blow past the source's statement_timeout even when per-row payload is small.
PARTITIONED_TABLE_MAX_CHUNK_SIZE = 10_000

# Statement timeout applied to the row-streaming connection so a slow FETCH
# (large partitioned scan, cold cache, etc.) does not get killed by a short
# default statement_timeout on the source role.
SYNC_STATEMENT_TIMEOUT_MS = 1000 * 60 * 10  # 10 mins


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
    try:
        return psycopg.connect(
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


def get_postgres_row_count(
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    schema: str,
    require_ssl: bool = False,
    names: list[str] | None = None,
) -> dict[str, int]:
    try:
        with pg_connection(
            host=host, port=port, database=database, user=user, password=password, require_ssl=require_ssl
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("SET LOCAL statement_timeout = {timeout}").format(
                        timeout=sql.Literal(1000 * 30)  # 30 secs
                    )
                )

                params: dict = {"schema": schema}
                names_filter_tables = ""
                names_filter_matviews = ""
                if names:
                    params["names"] = names
                    names_filter_tables = "AND tablename = ANY(%(names)s)"
                    names_filter_matviews = "AND matviewname = ANY(%(names)s)"

                cursor.execute(
                    f"""
                    SELECT tablename as table_name FROM pg_tables WHERE schemaname = %(schema)s {names_filter_tables}
                    UNION ALL
                    SELECT matviewname as table_name FROM pg_matviews WHERE schemaname = %(schema)s {names_filter_matviews}
                    """,
                    params,
                )
                tables = cursor.fetchall()

                if not tables:
                    return {}

                counts = [
                    sql.SQL("SELECT {table_name} AS table_name, COUNT(*) AS row_count FROM {schema}.{table}").format(
                        table_name=sql.Literal(table[0]), schema=sql.Identifier(schema), table=sql.Identifier(table[0])
                    )
                    for table in tables
                ]

                union_counts = sql.SQL(" UNION ALL ").join(counts)
                cursor.execute(union_counts)
                row_count_result = cursor.fetchall()
                return {row[0]: row[1] for row in row_count_result}
    except:
        return {}


def get_schemas(
    host: str,
    database: str,
    user: str,
    password: str,
    schema: str,
    port: int,
    require_ssl: bool = False,
    names: list[str] | None = None,
) -> dict[str, list[tuple[str, str, bool]]]:
    """Get all tables from PostgreSQL source schemas to sync."""

    with pg_connection(
        host=host, port=port, database=database, user=user, password=password, require_ssl=require_ssl
    ) as connection:
        with connection.cursor() as cursor:
            params: dict = {"schema": schema}
            names_filter = ""
            names_filter_pg = ""
            if names:
                params["names"] = names
                names_filter = "AND table_name = ANY(%(names)s)"
                names_filter_pg = "AND c.relname = ANY(%(names)s)"

            cursor.execute(
                f"""
                SELECT * FROM (
                    SELECT table_name, column_name, data_type, is_nullable FROM information_schema.columns
                    WHERE table_schema = %(schema)s {names_filter}
                    UNION ALL
                    SELECT
                        c.relname AS table_name,
                        a.attname AS column_name,
                        pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type,
                        CASE WHEN a.attnotnull THEN 'NO' ELSE 'YES' END AS is_nullable
                    FROM pg_class c
                    JOIN pg_namespace n ON c.relnamespace = n.oid
                    JOIN pg_attribute a ON a.attrelid = c.oid
                    WHERE c.relkind = 'm'  -- materialized view
                    AND n.nspname = %(schema)s
                    AND a.attnum > 0
                    AND NOT a.attisdropped
                    {names_filter_pg}
                ) t
                ORDER BY table_name ASC""",
                params,
            )
            result = cursor.fetchall()

        schema_list: dict[str, list[tuple[str, str, bool]]] = collections.defaultdict(list)
        for row in result:
            schema_list[row[0]].append((row[1], row[2], row[3] == "YES"))

    return schema_list


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


def get_foreign_keys(
    host: str,
    database: str,
    user: str,
    password: str,
    schema: str,
    port: int,
    require_ssl: bool = False,
    names: list[str] | None = None,
) -> dict[str, list[tuple[str, str, str]]]:
    """Get foreign keys for tables in the selected PostgreSQL schema."""

    with pg_connection(
        host=host, port=port, database=database, user=user, password=password, require_ssl=require_ssl
    ) as connection:
        with connection.cursor() as cursor:
            params: dict = {"schema": schema}
            names_filter = ""
            if names:
                params["names"] = names
                names_filter = "AND tc.table_name = ANY(%(names)s)"

            cursor.execute(
                f"""
                SELECT
                    tc.table_name AS table_name,
                    kcu.column_name AS column_name,
                    ccu.table_name AS target_table_name,
                    ccu.column_name AS target_column_name
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage AS ccu
                    ON ccu.constraint_name = tc.constraint_name
                    AND ccu.table_schema = tc.table_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND tc.table_schema = %(schema)s
                  AND ccu.table_schema = %(schema)s
                  {names_filter}
                ORDER BY tc.table_name, kcu.ordinal_position
                """,
                params,
            )
            result = cursor.fetchall()

        foreign_keys_by_table: dict[str, list[tuple[str, str, str]]] = collections.defaultdict(list)
        for table_name, column_name, target_table_name, target_column_name in result:
            foreign_keys_by_table[table_name].append((column_name, target_table_name, target_column_name))

    return foreign_keys_by_table


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

            try:
                if is_duckdb:
                    cursor.execute("SELECT DISTINCT function_name FROM duckdb_functions()")
                else:
                    cursor.execute("SELECT DISTINCT proname FROM pg_proc WHERE pg_function_is_visible(oid)")
                available_functions = _normalize_function_names([row[0] for row in cursor.fetchall()])
            except Exception as error:
                capture_exception(error)

            return {
                "database": current_database,
                "version": version,
                "engine": "duckdb" if is_duckdb else "postgres",
                "function_source": function_source,
                "available_functions": available_functions,
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


def _build_query(
    schema: str,
    table_name: str,
    should_use_incremental_field: bool,
    table_type: Literal["table", "view", "materialized_view"] | None,
    incremental_field: Optional[str],
    incremental_field_type: Optional[IncrementalFieldType],
    db_incremental_field_last_value: Optional[Any],
    add_sampling: Optional[bool] = False,
) -> sql.Composed:
    if not should_use_incremental_field:
        if add_sampling:
            if table_type == "view":
                query = sql.SQL("SELECT * FROM {} WHERE random() < 0.01").format(sql.Identifier(schema, table_name))
            else:
                query = sql.SQL("SELECT * FROM {} TABLESAMPLE SYSTEM (1)").format(sql.Identifier(schema, table_name))
        else:
            query = sql.SQL("SELECT * FROM {}").format(sql.Identifier(schema, table_name))

        if add_sampling:
            query_with_limit = cast(LiteralString, f"{query.as_string()} LIMIT 1000")
            return sql.SQL(query_with_limit).format()

        return query

    if incremental_field is None or incremental_field_type is None:
        raise ValueError("incremental_field and incremental_field_type can't be None")

    if db_incremental_field_last_value is None:
        db_incremental_field_last_value = incremental_type_to_initial_value(incremental_field_type)

    if add_sampling:
        if table_type == "view":
            query = sql.SQL(
                "SELECT * FROM {schema}.{table} WHERE {incremental_field} > {last_value} AND random() < 0.01"
            ).format(
                schema=sql.Identifier(schema),
                table=sql.Identifier(table_name),
                incremental_field=sql.Identifier(incremental_field),
                last_value=sql.Literal(db_incremental_field_last_value),
            )
        else:
            query = sql.SQL(
                "SELECT * FROM {schema}.{table} TABLESAMPLE SYSTEM (1) WHERE {incremental_field} > {last_value}"
            ).format(
                schema=sql.Identifier(schema),
                table=sql.Identifier(table_name),
                incremental_field=sql.Identifier(incremental_field),
                last_value=sql.Literal(db_incremental_field_last_value),
            )
    else:
        query = sql.SQL("SELECT * FROM {schema}.{table} WHERE {incremental_field} > {last_value}").format(
            schema=sql.Identifier(schema),
            table=sql.Identifier(table_name),
            incremental_field=sql.Identifier(incremental_field),
            last_value=sql.Literal(db_incremental_field_last_value),
        )

    if add_sampling:
        query_with_limit = cast(LiteralString, f"{query.as_string()} LIMIT 1000")
        return sql.SQL(query_with_limit).format()
    else:
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

    return sql.SQL("SELECT COUNT(*) FROM {schema}.{table} WHERE {incremental_field} > {last_value}").format(
        schema=sql.Identifier(schema),
        table=sql.Identifier(table_name),
        incremental_field=sql.Identifier(incremental_field),
        last_value=sql.Literal(db_incremental_field_last_value),
    )


def _is_partitioned_table(cursor: psycopg.Cursor, schema: str, table_name: str) -> bool:
    """Check if a table is a partitioned (parent) table via pg_partitioned_table."""
    cursor.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM pg_partitioned_table pt
            JOIN pg_class c ON c.oid = pt.partrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = %(schema)s AND c.relname = %(table)s
        )
        """,
        {"schema": schema, "table": table_name},
    )
    row = cursor.fetchone()
    return bool(row and row[0])


def _get_estimated_row_count_for_partitioned_table(
    cursor: psycopg.Cursor, schema: str, table_name: str, logger: FilteringBoundLogger
) -> int | None:
    """Get approximate row count for a partitioned table by summing stats across child partitions.

    Tries two sources in order:
    1. pg_class.reltuples — accurate after ANALYZE, but 0 if ANALYZE never ran.
    2. pg_stat_user_tables.n_live_tup — maintained incrementally by the stats
       collector (tracks inserts/deletes in near-real-time), works even without ANALYZE.

    Returns None if neither source has data (no child partitions found), so the
    caller can fall back to an exact COUNT(*).
    """
    # pg_class.reltuples = -1 means the partition has never been ANALYZEd.
    # Summing a mix of analyzed (>=0) and unanalyzed (-1) partitions produces
    # an under-count, so we track unanalyzed partitions separately and only
    # trust reltuples_sum when every partition has been analyzed.
    cursor.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN c.reltuples >= 0 THEN c.reltuples ELSE 0 END), 0)::bigint,
            COALESCE(SUM(CASE WHEN c.reltuples < 0 THEN 1 ELSE 0 END), 0)::bigint,
            COALESCE(SUM(s.n_live_tup), 0)::bigint,
            COUNT(*)::bigint
        FROM pg_inherits i
        JOIN pg_class c ON c.oid = i.inhrelid
        LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
        WHERE i.inhparent = (
            SELECT c2.oid
            FROM pg_class c2
            JOIN pg_namespace n ON n.oid = c2.relnamespace
            WHERE n.nspname = %(schema)s AND c2.relname = %(table)s
        )
        """,
        {"schema": schema, "table": table_name},
    )
    row = cursor.fetchone()

    if row is None:
        logger.debug("_get_estimated_row_count_for_partitioned_table: no result, returning None")
        return None

    reltuples_sum, unanalyzed_count, n_live_tup_sum, partition_count = (
        int(row[0]),
        int(row[1]),
        int(row[2]),
        int(row[3]),
    )

    if partition_count == 0:
        logger.debug("_get_estimated_row_count_for_partitioned_table: no child partitions, returning None")
        return None

    # reltuples is most accurate (set by ANALYZE), but only trustworthy when
    # every partition has been analyzed — otherwise the sum under-counts.
    if unanalyzed_count == 0 and reltuples_sum > 0:
        logger.debug(f"_get_estimated_row_count_for_partitioned_table: reltuples estimate = {reltuples_sum}")
        return reltuples_sum

    # reltuples unreliable (unanalyzed partitions present) — fall back to
    # stats collector count, which is maintained incrementally.
    if n_live_tup_sum > 0:
        logger.debug(
            f"_get_estimated_row_count_for_partitioned_table: reltuples unreliable "
            f"(unanalyzed_partitions={unanalyzed_count}/{partition_count}), "
            f"n_live_tup estimate = {n_live_tup_sum}"
        )
        return n_live_tup_sum

    # Both sources unreliable — caller will fall back to exact COUNT(*).
    logger.debug(
        f"_get_estimated_row_count_for_partitioned_table: no reliable estimate "
        f"(reltuples={reltuples_sum}, unanalyzed={unanalyzed_count}/{partition_count}, "
        f"n_live_tup={n_live_tup_sum}), returning None"
    )
    return None


def _explain_query(cursor: psycopg.Cursor, query: sql.Composed, logger: FilteringBoundLogger):
    logger.debug(f"Running EXPLAIN on {query.as_string()}")

    try:
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
        capture_exception(e)
        logger.debug(f"EXPLAIN raised an exception: {e}")


def _get_primary_keys(
    cursor: psycopg.Cursor, schema: str, table_name: str, logger: FilteringBoundLogger
) -> list[str] | None:
    info_schema_query = sql.SQL("""
        SELECT
            kcu.column_name
        FROM
            information_schema.table_constraints tc
        JOIN
            information_schema.key_column_usage kcu
            ON tc.constraint_name = kcu.constraint_name
            AND tc.table_schema = kcu.table_schema
        WHERE
            tc.table_schema = {schema}
            AND tc.table_name = {table}
            AND tc.constraint_type = 'PRIMARY KEY'""").format(schema=sql.Literal(schema), table=sql.Literal(table_name))

    _explain_query(cursor, info_schema_query, logger)
    logger.debug(f"Running query: {info_schema_query.as_string()}")
    cursor.execute(info_schema_query)
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
        f"No primary keys found for {table_name}. If the table is not a view, (a) does the table have a primary key set? (b) is the primary key returned from querying information_schema?"
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
    try:
        query = sql.SQL("""
            SELECT percentile_cont(0.95) within group (order by subquery.row_size) FROM (
                SELECT octet_length(t::text) as row_size FROM ({}) as t
            ) as subquery
        """).format(inner_query)

        _explain_query(cursor, query, logger)
        logger.debug(f"Running query: {query.as_string()}")
        cursor.execute(query)
        row = cursor.fetchone()

        if row is None:
            logger.debug(f"_get_table_chunk_size: No results returned. Using DEFAULT_CHUNK_SIZE={DEFAULT_CHUNK_SIZE}")
            return DEFAULT_CHUNK_SIZE

        row_size_bytes = row[0] or 1
        chunk_size = int(DEFAULT_TABLE_SIZE_BYTES / row_size_bytes)
        logger.debug(
            f"_get_table_chunk_size: row_size_bytes={row_size_bytes}. DEFAULT_TABLE_SIZE_BYTES={DEFAULT_TABLE_SIZE_BYTES}. Using CHUNK_SIZE={chunk_size}"
        )

        return chunk_size
    except psycopg.errors.QueryCanceled:
        raise
    except Exception as e:
        logger.debug(f"_get_table_chunk_size: Error: {e}. Using DEFAULT_CHUNK_SIZE={DEFAULT_CHUNK_SIZE}", exc_info=e)

        return DEFAULT_CHUNK_SIZE


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
        logger.debug(f"_get_rows_to_sync: Error: {e}. Using 0 as rows to sync", exc_info=e)
        capture_exception(e)

        if "temporary file size exceeds temp_file_limit" in str(e):
            raise TemporaryFileSizeExceedsLimitException(
                f"Error: {e}. Please ensure your incremental field has an appropriate index created"
            )

        return 0


def _get_partition_settings(
    cursor: psycopg.Cursor, schema: str, table_name: str, logger: FilteringBoundLogger
) -> PartitionSettings | None:
    # For partitioned tables, a plain COUNT(*) and pg_table_size on the
    # parent would scan every child partition / return 0. Use catalog
    # estimates instead.
    try:
        if _is_partitioned_table(cursor, schema, table_name):
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
    except Exception as e:
        capture_exception(e)
        logger.debug(f"_get_partition_settings: returning None due to error: {e}")
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


def _get_partition_settings_for_partitioned_table(
    cursor: psycopg.Cursor, schema: str, table_name: str, logger: FilteringBoundLogger
) -> PartitionSettings | None:
    """Compute PartitionSettings for a partitioned table via catalog stats.

    Summing pg_table_size and reltuples across child partitions avoids the
    full-table scan that COUNT(*) + pg_table_size on the parent would incur.
    Returns None if catalog stats are unreliable (any partition unanalyzed),
    letting the caller skip partitioning rather than use bad numbers.
    """
    cursor.execute(
        """
        SELECT
            COALESCE(SUM(pg_table_size(c.oid)), 0)::bigint,
            COALESCE(SUM(CASE WHEN c.reltuples >= 0 THEN c.reltuples ELSE 0 END), 0)::bigint,
            COALESCE(SUM(CASE WHEN c.reltuples < 0 THEN 1 ELSE 0 END), 0)::bigint,
            COUNT(*)::bigint
        FROM pg_inherits i
        JOIN pg_class c ON c.oid = i.inhrelid
        WHERE i.inhparent = (
            SELECT c2.oid
            FROM pg_class c2
            JOIN pg_namespace n ON n.oid = c2.relnamespace
            WHERE n.nspname = %(schema)s AND c2.relname = %(table)s
        )
        """,
        {"schema": schema, "table": table_name},
    )
    row = cursor.fetchone()
    if row is None:
        return None

    total_size, total_rows, unanalyzed_count, partition_count_children = (
        int(row[0]),
        int(row[1]),
        int(row[2]),
        int(row[3]),
    )

    if partition_count_children == 0 or total_size == 0 or total_rows == 0 or unanalyzed_count > 0:
        logger.debug(
            f"_get_partition_settings_for_partitioned_table: no reliable estimate "
            f"(children={partition_count_children}, size={total_size}, rows={total_rows}, "
            f"unanalyzed={unanalyzed_count}), returning None"
        )
        return None

    avg_row_size = total_size / total_rows
    partition_size = round(DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES / avg_row_size)
    partition_count = max(1, math.floor(total_rows / partition_size))
    logger.debug(
        f"_get_partition_settings_for_partitioned_table: partition_count={partition_count}, "
        f"partition_size={partition_size} (total_rows={total_rows}, total_size={total_size})"
    )
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
            # Isolate the probe in a savepoint so that any failure (permission denied, bad
            # type, statement_timeout, network blip) rolls back cleanly without poisoning the
            # enclosing metadata transaction. Without this, a probe error leaves the
            # transaction in `INERROR` state and every subsequent query in `postgres_source`
            # (SET LOCAL statement_timeout, _is_read_replica, _get_primary_keys, _get_rows_to_sync,
            # ...) fails with `InFailedSqlTransaction: current transaction is aborted`.
            with cursor.connection.transaction(savepoint_name="probe_numeric_scale"):
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
) -> SourceResponse:
    table_name = table_names[0]
    if not table_name:
        raise ValueError("Table name is missing")

    effective_sslmode = _get_sslmode(require_ssl)

    with tunnel() as (host, port):
        try:
            connection = psycopg.connect(
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
                options=f"-c statement_timeout={SYNC_STATEMENT_TIMEOUT_MS}",
            )
        except psycopg.OperationalError as e:
            if require_ssl and "SSL" in str(e):
                raise SSLRequiredError(
                    "SSL/TLS connection is required but your database does not support it. "
                    "Please enable SSL/TLS on your PostgreSQL server or contact your database administrator."
                ) from e
            raise

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
                table = _get_table(
                    cursor,
                    schema,
                    table_name,
                    logger,
                    probe_unconstrained_numeric_scale=fresh_schema_being_created,
                )
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
                )

                count_query = _build_count_query(
                    schema,
                    table_name,
                    should_use_incremental_field,
                    incremental_field,
                    incremental_field_type,
                    db_incremental_field_last_value,
                )
                cursor.execute(
                    sql.SQL("SET LOCAL statement_timeout = {timeout}").format(
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
                    logger.debug("Checking if table is partitioned...")
                    is_partitioned = False
                    try:
                        is_partitioned = _is_partitioned_table(cursor, schema, table_name)
                    except Exception as e:
                        logger.debug(f"Partition detection failed: {e}")
                    logger.debug("Getting table chunk size...")
                    if chunk_size_override is not None:
                        chunk_size = chunk_size_override
                        logger.debug(f"Using chunk_size_override: {chunk_size_override}")
                    else:
                        chunk_size = _get_table_chunk_size(cursor, inner_query_with_limit, logger)
                        # Cap chunk size for partitioned tables. Server-cursor FETCH
                        # on a partitioned parent scans across all child partitions,
                        # so a large chunk can exceed statement_timeout even when
                        # per-row size is small.
                        if is_partitioned and chunk_size > PARTITIONED_TABLE_MAX_CHUNK_SIZE:
                            logger.debug(
                                f"Capping chunk_size from {chunk_size} to {PARTITIONED_TABLE_MAX_CHUNK_SIZE} for partitioned table"
                            )
                            chunk_size = PARTITIONED_TABLE_MAX_CHUNK_SIZE
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
                    logger.debug("Getting partition settings...")
                    partition_settings = (
                        _get_partition_settings(cursor, schema, table_name, logger)
                        if should_use_incremental_field
                        else None
                    )
                    has_duplicate_primary_keys = False

                    # Fallback on checking for an `id` field on the table
                    if primary_keys is None and "id" in table:
                        logger.debug("Falling back to ['id'] for primary keys...")
                        primary_keys = ["id"]
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

    def get_rows(chunk_size: int) -> Iterator[Any]:
        arrow_schema = table.to_arrow_schema()
        with tunnel() as (host, port):
            cursor_factory = psycopg.ServerCursor if not using_read_replica else None

            def get_connection():
                try:
                    connection = psycopg.connect(
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
                        options=f"-c statement_timeout={SYNC_STATEMENT_TIMEOUT_MS}",
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
                # Use psycopg.Cursor directly to bypass cursor_factory (which may be ServerCursor
                # and requires a `name` arg).
                with psycopg.Cursor(connection) as check_cursor:
                    check_cursor.execute("SHOW statement_timeout")
                    row = check_cursor.fetchone()
                    timeout_val = str(row[0]) if row else "unknown"  # type: ignore[index]
                    logger.info(f"Effective statement_timeout on sync connection: {timeout_val}")
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
                )

                successive_errors = 0
                connection = get_connection()
                while True:
                    try:
                        if connection.closed:
                            logger.debug("Postgres connection was closed, reopening...")
                            connection = get_connection()

                        with connection.cursor() as cursor:
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
                    except psycopg.errors.SerializationFailure as e:
                        if "due to conflict with recovery" not in "".join(e.args):
                            raise

                        # This error happens when the read replica is out of sync with the primary
                        logger.debug(f"SerializationFailure error: {e}. Retrying chunk at offset {offset}")

                        successive_errors += 1
                        if successive_errors >= 30:
                            # The connection should be closed here, but want to double check to make sure
                            if connection.closed is False:
                                connection.__exit__(type(e), e, None)

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
                    except Exception as e:
                        if connection.closed is False:
                            connection.__exit__(type(e), e, None)
                        raise

                if connection.closed is False:
                    connection.__exit__(None, None, None)

            offset = 0
            try:
                with get_connection() as connection:
                    with connection.cursor(name=f"posthog_{team_id}_{schema}.{table_name}") as cursor:
                        query = _build_query(
                            schema,
                            table_name,
                            should_use_incremental_field,
                            table.type,
                            incremental_field,
                            incremental_field_type,
                            db_incremental_field_last_value,
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
