from __future__ import annotations

import datetime
import collections
from collections.abc import Callable, Iterator
from contextlib import _GeneratorContextManager
from typing import Any

from django.conf import settings

import pymysql
import structlog
import pymysql.converters
from pymysql.constants import FIELD_TYPE
from pymysql.cursors import Cursor, SSCursor
from structlog.types import FilteringBoundLogger

from posthog.temporal.data_imports.naming_convention import NamingConvention
from posthog.temporal.data_imports.pipelines.pipeline.consts import DEFAULT_CHUNK_SIZE, DEFAULT_TABLE_SIZE_BYTES
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.pipelines.pipeline.utils import table_from_iterator
from posthog.temporal.data_imports.sources.common.sql import (
    BacktickIdentifierQuoter,
    InvalidIdentifierError,
    SelectQueryBuilder,
)
from posthog.temporal.data_imports.sources.mysql.schema_explorer import MySQLColumn, MySQLSchemaExplorer

from products.data_warehouse.backend.types import IncrementalFieldType, PartitionSettings

# Re-export `MySQLColumn` for back-compat — it used to live in this module.
__all__ = [
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_TABLE_SIZE_BYTES",
    "MySQLColumn",
    "STATEMENT_TIMEOUT_SECONDS",
    "filter_mysql_incremental_fields",
    "get_primary_keys_for_schemas",
    "get_schemas",
    "mysql_source",
]

_IDENTIFIER_QUOTER = BacktickIdentifierQuoter()
_QUERY_BUILDER = SelectQueryBuilder(quoter=_IDENTIFIER_QUOTER)
_SCHEMA_EXPLORER = MySQLSchemaExplorer(quoter=_IDENTIFIER_QUOTER)

# Applied to the row-streaming connection so large result preparation
# (e.g. filesort on a multi-GB table) doesn't hit MySQL's default 60s
# net_write_timeout before the first rows are ready. Used for both the
# client-side PyMySQL read_timeout and the server-side SET SESSION
# net_write_timeout / net_read_timeout — PyMySQL and MySQL both take seconds.
STATEMENT_TIMEOUT_SECONDS = 600  # 10 mins


def _safe_convert_date(obj: Any) -> datetime.date | None:
    """Convert MySQL date, returning None for invalid dates like '0000-00-00'."""
    if isinstance(obj, (bytes, bytearray)):
        obj = obj.decode("utf-8")
    try:
        parts = obj.split("-", 2)
        return datetime.date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError, AttributeError):
        return None


def _safe_convert_datetime(obj: Any) -> datetime.datetime | None:
    """Convert MySQL datetime/timestamp, returning None for invalid values like '0000-00-00 00:00:00'."""
    if isinstance(obj, (bytes, bytearray)):
        obj = obj.decode("utf-8")
    try:
        date_part, time_part = obj.split(" ", 1)
        date_values = [int(x) for x in date_part.split("-", 2)]
        time_parts = time_part.split(":", 2)
        hours = int(time_parts[0])
        minutes = int(time_parts[1])
        # Handle optional microseconds
        sec_parts = time_parts[2].split(".", 1)
        seconds = int(sec_parts[0])
        microseconds = int(sec_parts[1].ljust(6, "0")) if len(sec_parts) > 1 else 0
        return datetime.datetime(date_values[0], date_values[1], date_values[2], hours, minutes, seconds, microseconds)
    except (ValueError, IndexError, AttributeError):
        return None


# Custom conversions that return None for MySQL zero dates instead of raw strings
_MYSQL_SAFE_CONVERSIONS: dict[type[object] | int, Any] = {
    **pymysql.converters.conversions,
    FIELD_TYPE.DATE: _safe_convert_date,
    FIELD_TYPE.DATETIME: _safe_convert_datetime,
    FIELD_TYPE.TIMESTAMP: _safe_convert_datetime,
}


def filter_mysql_incremental_fields(
    columns: list[tuple[str, str, bool]],
) -> list[tuple[str, IncrementalFieldType, bool]]:
    results: list[tuple[str, IncrementalFieldType, bool]] = []
    for column_name, type, nullable in columns:
        type = type.lower()
        if type.startswith("timestamp"):
            results.append((column_name, IncrementalFieldType.Timestamp, nullable))
        elif type == "date":
            results.append((column_name, IncrementalFieldType.Date, nullable))
        elif type == "datetime":
            results.append((column_name, IncrementalFieldType.DateTime, nullable))
        elif type == "tinyint" or type == "smallint" or type == "mediumint" or type == "int" or type == "bigint":
            results.append((column_name, IncrementalFieldType.Integer, nullable))

    return results


def get_schemas(
    host: str,
    user: str,
    password: str,
    database: str,
    schema: str,
    port: int,
    using_ssl: bool = True,
    names: list[str] | None = None,
) -> dict[str, list[tuple[str, str, bool]]]:
    """Get all tables from MySQL source schemas to sync."""

    ssl_ca: str | None = None

    if using_ssl:
        ssl_ca = "/etc/ssl/cert.pem" if settings.DEBUG else "/etc/ssl/certs/ca-certificates.crt"

    connection = pymysql.connect(
        host=host,
        port=port,
        database=database,
        user=user,
        password=password,
        connect_timeout=10,
        ssl_ca=ssl_ca,
    )

    with connection.cursor() as cursor:
        params: dict = {"schema": schema}
        names_filter = ""
        if names:
            params["names"] = tuple(names)
            names_filter = "AND table_name IN %(names)s"

        cursor.execute(
            "SELECT table_name, column_name, data_type, is_nullable"
            " FROM information_schema.columns"
            f" WHERE table_schema = %(schema)s {names_filter}"
            " ORDER BY table_name ASC",
            params,
        )
        result = cursor.fetchall()

        schema_list: dict[str, list[tuple[str, str, bool]]] = collections.defaultdict(list)
        for row in result:
            schema_list[row[0]].append((row[1], row[2], row[3] == "YES"))

    connection.close()

    return schema_list


def _sanitize_identifier(identifier: str) -> str:
    """Back-compat shim for callers that still expect a plain `ValueError`.

    New code should use `BacktickIdentifierQuoter` directly — same allowlist,
    same quoting, exposed through the shared `IdentifierQuoter` interface.
    """
    try:
        return _IDENTIFIER_QUOTER.quote(identifier)
    except InvalidIdentifierError as e:
        # Preserve the old message shape so semgrep / log-matching rules that
        # key on the old text keep working.
        raise ValueError(f"Invalid SQL identifier: {identifier}") from e


def _build_query(
    schema: str,
    table_name: str,
    should_use_incremental_field: bool,
    incremental_field: str | None,
    incremental_field_type: IncrementalFieldType | None,
    db_incremental_field_last_value: Any | None,
    force_index_name: str | None = None,
) -> tuple[str, dict[str, Any]]:
    hint: str | None = None
    if force_index_name is not None:
        # Sanitize before building the hint — bad names must fail fast.
        hint = f"FORCE INDEX ({_IDENTIFIER_QUOTER.quote(force_index_name)})"

    if not should_use_incremental_field:
        result = _QUERY_BUILDER.select_all(
            schema=schema,
            table_name=table_name,
            extra_table_hint=hint,
        )
        params = result.params if isinstance(result.params, dict) else {}
        return result.sql, params

    if incremental_field is None or incremental_field_type is None:
        raise ValueError("incremental_field and incremental_field_type can't be None")

    result = _QUERY_BUILDER.select_all(
        schema=schema,
        table_name=table_name,
        incremental_field=incremental_field,
        incremental_field_type=incremental_field_type,
        incremental_last_value=db_incremental_field_last_value,
        extra_table_hint=hint,
    )
    params = result.params if isinstance(result.params, dict) else {}
    return result.sql, params


# pymysql error code for "Lost connection to MySQL server during query" — the
# symptom we see when the optimizer picks a bad plan (full scan + filesort) and
# the filesort preparation exceeds a middlebox / server-side query timeout
# before any rows stream back.
_LOST_CONNECTION_DURING_QUERY_CODE = 2013


def _is_bad_plan_timeout(e: pymysql.err.OperationalError) -> bool:
    """Return True if the error suggests we hit a bad-plan-induced query timeout.

    Narrowly matches `OperationalError(2013, ...)`. Other `OperationalError`s
    (access denied, table missing, etc.) should propagate untouched.
    """
    code = e.args[0] if e.args else None
    return code == _LOST_CONNECTION_DURING_QUERY_CODE


def _find_index_for_cursor(
    cursor: Cursor,
    schema: str,
    table_name: str,
    cursor_field: str,
    logger: FilteringBoundLogger,
) -> str | None:
    """Back-compat shim — delegates to `MySQLSchemaExplorer.find_index_for_cursor`."""
    return _SCHEMA_EXPLORER.find_index_for_cursor(cursor, schema, table_name, cursor_field, logger)


def _get_rows_to_sync(
    cursor: Cursor, inner_query: str, inner_query_args: dict[str, Any], logger: FilteringBoundLogger
) -> int:
    """Back-compat shim — delegates to `MySQLSchemaExplorer.get_rows_to_sync`."""
    return _SCHEMA_EXPLORER.get_rows_to_sync(cursor, inner_query, inner_query_args, logger)


def _get_partition_settings(
    cursor: Cursor,
    schema: str,
    table_name: str,
    logger: FilteringBoundLogger,
    partition_size_bytes: int | None = None,
) -> PartitionSettings | None:
    """Back-compat shim — delegates to `MySQLSchemaExplorer.get_partition_settings`.

    Integration tests still import this at module scope; new code should use
    the explorer directly.
    """
    if partition_size_bytes is None:
        return _SCHEMA_EXPLORER.get_partition_settings(cursor, schema, table_name, logger)
    return _SCHEMA_EXPLORER.get_partition_settings(
        cursor, schema, table_name, logger, partition_size_bytes=partition_size_bytes
    )


def get_primary_keys_for_schemas(
    host: str,
    user: str,
    password: str,
    database: str,
    schema: str,
    port: int,
    table_names: list[str],
    using_ssl: bool = True,
) -> dict[str, list[str] | None]:
    """Detect primary keys for all tables in a single query."""
    result: dict[str, list[str] | None] = dict.fromkeys(table_names)

    try:
        ssl_ca: str | None = None
        if using_ssl:
            ssl_ca = "/etc/ssl/cert.pem" if settings.DEBUG else "/etc/ssl/certs/ca-certificates.crt"

        with pymysql.connect(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password,
            connect_timeout=10,
            ssl_ca=ssl_ca,
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT tc.TABLE_NAME, kcu.COLUMN_NAME
                    FROM information_schema.TABLE_CONSTRAINTS tc
                    JOIN information_schema.KEY_COLUMN_USAGE kcu
                    ON tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
                    AND tc.TABLE_SCHEMA = kcu.TABLE_SCHEMA
                    AND tc.TABLE_NAME = kcu.TABLE_NAME
                    WHERE tc.TABLE_SCHEMA = %(schema)s
                    AND tc.TABLE_NAME IN %(names)s
                    AND tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
                    """,
                    {"schema": schema, "names": tuple(table_names)},
                )
                rows = cursor.fetchall()

                pks: dict[str, list[str]] = collections.defaultdict(list)
                for table_name, column_name in rows:
                    pks[table_name].append(column_name)

                for table_name, pk_cols in pks.items():
                    result[table_name] = pk_cols
    except Exception as e:
        structlog.get_logger().warning("Failed to detect primary keys for MySQL schemas", exc_info=e)

    return result


def _get_table_average_row_size(
    cursor: Cursor,
    schema: str,
    table_name: str,
    should_use_incremental_field: bool,
    incremental_field: str | None,
    incremental_field_type: IncrementalFieldType | None,
    db_incremental_field_last_value: Any | None,
    logger: FilteringBoundLogger,
) -> int | None:
    """Back-compat shim — builds the inner query then delegates to the explorer."""
    try:
        inner_query, inner_query_args = _build_query(
            schema,
            table_name,
            should_use_incremental_field,
            incremental_field,
            incremental_field_type,
            db_incremental_field_last_value,
        )
    except Exception as e:
        logger.debug(f"_get_table_average_row_size: Error: {e}.", exc_info=e)
        return None
    return _SCHEMA_EXPLORER.fetch_average_row_size(cursor, schema, table_name, inner_query, inner_query_args, logger)


def _get_table_chunk_size(
    cursor: Cursor,
    schema: str,
    table_name: str,
    should_use_incremental_field: bool,
    incremental_field: str | None,
    incremental_field_type: IncrementalFieldType | None,
    db_incremental_field_last_value: Any | None,
    logger: FilteringBoundLogger,
) -> int:
    """Back-compat shim — builds the inner query then delegates to the explorer."""
    try:
        inner_query, inner_query_args = _build_query(
            schema,
            table_name,
            should_use_incremental_field,
            incremental_field,
            incremental_field_type,
            db_incremental_field_last_value,
        )
    except Exception as e:
        logger.debug(f"_get_table_chunk_size: Error: {e}. Using DEFAULT_CHUNK_SIZE={DEFAULT_CHUNK_SIZE}", exc_info=e)
        return DEFAULT_CHUNK_SIZE
    return _SCHEMA_EXPLORER.get_chunk_size(cursor, schema, table_name, inner_query, inner_query_args, logger)


def mysql_source(
    tunnel: Callable[[], _GeneratorContextManager[tuple[str, int]]],
    user: str,
    password: str,
    database: str,
    using_ssl: bool,
    schema: str,
    table_names: list[str],
    should_use_incremental_field: bool,
    logger: FilteringBoundLogger,
    db_incremental_field_last_value: Any | None,
    incremental_field: str | None = None,
    incremental_field_type: IncrementalFieldType | None = None,
) -> SourceResponse:
    table_name = table_names[0]
    if not table_name:
        raise ValueError("Table name is missing")

    ssl_ca: str | None = None

    if using_ssl:
        ssl_ca = "/etc/ssl/cert.pem" if settings.DEBUG else "/etc/ssl/certs/ca-certificates.crt"

    explorer = _SCHEMA_EXPLORER

    with tunnel() as (host, port):
        with pymysql.connect(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password,
            connect_timeout=10,
            ssl_ca=ssl_ca,
            conv=_MYSQL_SAFE_CONVERSIONS,
        ) as connection:
            with connection.cursor() as cursor:
                inner_query, inner_query_args = _build_query(
                    schema,
                    table_name,
                    should_use_incremental_field,
                    incremental_field,
                    incremental_field_type,
                    db_incremental_field_last_value,
                )

                primary_keys = explorer.get_primary_keys(cursor, schema, table_name)
                table = explorer.get_table(cursor, schema, table_name)
                logger.debug(f"Source schema: {table.to_arrow_schema()}")
                rows_to_sync = explorer.get_rows_to_sync(cursor, inner_query, inner_query_args, logger)
                chunk_size = explorer.get_chunk_size(cursor, schema, table_name, inner_query, inner_query_args, logger)
                partition_settings = (
                    explorer.get_partition_settings(cursor, schema, table_name, logger)
                    if should_use_incremental_field
                    else None
                )

                # Fallback on checking for an `id` field on the table
                if primary_keys is None and "id" in table:
                    primary_keys = ["id"]

    arrow_schema = table.to_arrow_schema()

    def _stream_with_optional_force_index(force_index_name: str | None) -> Iterator[Any]:
        """Open a fresh connection and stream rows from `db_incremental_field_last_value`.

        The pipeline itself persists the per-batch cursor value (see
        `update_incremental_field_values`), so a retry that restarts from the
        original starting cursor is correct but occasionally replays a few
        already-processed rows; the delta merge dedupes by primary key.
        """
        with tunnel() as (host, port):
            # PlanetScale needs this to be set
            init_command = "SET workload = 'OLAP';" if host.endswith("psdb.cloud") else None

            with pymysql.connect(
                host=host,
                port=port,
                database=database,
                user=user,
                password=password,
                connect_timeout=10,
                read_timeout=STATEMENT_TIMEOUT_SECONDS,
                ssl_ca=ssl_ca,
                init_command=init_command,
                conv=_MYSQL_SAFE_CONVERSIONS,
            ) as connection:
                # Bump server-side timeouts for large table scans. The
                # defaults (60s each) are too low for multi-GB unbuffered
                # queries — the server drops the connection before the first
                # rows are ready.
                try:
                    with connection.cursor() as setup_cursor:
                        setup_cursor.execute(
                            f"SET SESSION net_write_timeout = {STATEMENT_TIMEOUT_SECONDS}, net_read_timeout = {STATEMENT_TIMEOUT_SECONDS}"
                        )
                except Exception as e:
                    logger.warning(f"Failed to set session timeouts on MySQL sync connection: {e}")
                with connection.cursor(SSCursor) as cursor:
                    query, args = _build_query(
                        schema,
                        table_name,
                        should_use_incremental_field,
                        incremental_field,
                        incremental_field_type,
                        db_incremental_field_last_value,
                        force_index_name=force_index_name,
                    )
                    logger.debug(f"MySQL query: {query.format(args)}")

                    # EXPLAIN before the streaming query to help diagnose
                    # failures where MySQL picks full scan + filesort over
                    # the incremental index. `explain_query` consumes its
                    # rows via fetchall(), leaving the cursor in a clean
                    # state for the streaming execute() below.
                    explorer.explain_query(cursor, query, args, logger)

                    cursor.execute(query, args)

                    column_names = [column[0] for column in cursor.description or []]

                    while True:
                        # use chunk_size to fetch rows instead of DEFAULT_CHUNK_SIZE
                        rows = cursor.fetchmany(chunk_size)
                        if not rows:
                            break

                        yield table_from_iterator((dict(zip(column_names, row)) for row in rows), arrow_schema)

    def get_rows() -> Iterator[Any]:
        # Track whether any batch reached the pipeline. If one did, the retry
        # path can't safely restart from the original cursor: the delta merge
        # only dedupes rows for `incremental` writes into an existing table
        # (see `delta_table_helper.write_to_deltalake`), so full-refresh and
        # first-ever-sync scenarios would get silent duplicates on replay.
        # The observed bad-plan failure fails before any rows stream, so this
        # guard is defensive — it enforces the invariant the PR assumes.
        yielded_any = False
        try:
            for chunk in _stream_with_optional_force_index(force_index_name=None):
                yielded_any = True
                yield chunk
            return
        except pymysql.err.OperationalError as e:
            if not _is_bad_plan_timeout(e):
                raise
            if yielded_any:
                logger.warning(
                    f"Streaming query died with bad-plan timeout (error {e.args[0] if e.args else '?'}) "
                    f"after already yielding rows — skipping FORCE INDEX fallback to avoid duplicates."
                )
                raise
            logger.warning(
                f"Streaming query died with bad-plan timeout (error {e.args[0] if e.args else '?'}). "
                f"Attempting FORCE INDEX fallback."
            )
            if not should_use_incremental_field or not incremental_field:
                # Without an incremental field there's no cursor to force an index on.
                logger.warning(
                    "Bad-plan timeout hit, but sync has no incremental field — cannot apply FORCE INDEX fallback."
                )
                raise

            with tunnel() as (host, port):
                # Match the streaming connection's PlanetScale workload hint so
                # future proxy-side policy changes don't silently break the probe.
                init_command = "SET workload = 'OLAP';" if host.endswith("psdb.cloud") else None

                with pymysql.connect(
                    host=host,
                    port=port,
                    database=database,
                    user=user,
                    password=password,
                    connect_timeout=10,
                    ssl_ca=ssl_ca,
                    init_command=init_command,
                    conv=_MYSQL_SAFE_CONVERSIONS,
                ) as probe_connection:
                    with probe_connection.cursor() as probe_cursor:
                        force_index_name = explorer.find_index_for_cursor(
                            probe_cursor, schema, table_name, incremental_field, logger
                        )

            if not force_index_name:
                logger.warning(
                    f"Bad-plan timeout hit and no usable index on "
                    f"{schema}.{table_name}.{incremental_field} — cannot apply FORCE INDEX fallback. "
                    f"Customer should add an index on the incremental field."
                )
                raise

            logger.warning(f"Retrying streaming query with FORCE INDEX ({force_index_name}) after bad-plan timeout")
            yield from _stream_with_optional_force_index(force_index_name)

    name = NamingConvention.normalize_identifier(table_name)

    return SourceResponse(
        name=name,
        items=get_rows,
        primary_keys=primary_keys,
        partition_count=partition_settings.partition_count if partition_settings else None,
        partition_size=partition_settings.partition_size if partition_settings else None,
        rows_to_sync=rows_to_sync,
    )
