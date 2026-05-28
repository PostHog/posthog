"""Snowflake driver for PostHog's data-warehouse import pipeline.

Everything Snowflake-specific — connection lifecycle (with password vs
keypair auth and the keypair tempfile dance), schema listing, per-cursor
metadata, and the dlt pipeline build — lives on
`SnowflakeImplementation`. The source-class `SnowflakeSource` is a thin
PostHog-layer wrapper that just holds an instance and validates
credentials.
"""

from __future__ import annotations

import collections
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Optional

import structlog
import snowflake.connector
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception
from posthog.temporal.data_imports.naming_convention import NamingConvention
from posthog.temporal.data_imports.pipelines.helpers import (
    incremental_type_to_initial_value,
    incremental_type_to_operator,
)
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.sql.implementation import SQLSourceImplementation
from posthog.temporal.data_imports.sources.common.sql.incremental import IncrementalFieldFilter
from posthog.temporal.data_imports.sources.generated_configs import SnowflakeSourceConfig

from products.data_warehouse.backend.types import IncrementalFieldType

__all__ = [
    "SnowflakeImplementation",
    "filter_snowflake_incremental_fields",
]


def filter_snowflake_incremental_fields(
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
        elif type in ("number", "numeric"):
            results.append((column_name, IncrementalFieldType.Numeric, nullable))

    return results


def _build_query(
    database: str,
    schema: str,
    table_name: str,
    should_use_incremental_field: bool,
    incremental_field: Optional[str],
    incremental_field_type: Optional[IncrementalFieldType],
    db_incremental_field_last_value: Optional[Any],
) -> tuple[str, tuple[Any, ...]]:
    if not should_use_incremental_field:
        return "SELECT * FROM IDENTIFIER(%s)", (f"{database}.{schema}.{table_name}",)

    if incremental_field is None or incremental_field_type is None:
        raise ValueError("incremental_field and incremental_field_type can't be None")

    if db_incremental_field_last_value is None:
        db_incremental_field_last_value = incremental_type_to_initial_value(incremental_field_type)

    operator = incremental_type_to_operator(incremental_field_type)
    return f"SELECT * FROM IDENTIFIER(%s) WHERE IDENTIFIER(%s) {operator} %s ORDER BY IDENTIFIER(%s) ASC", (
        f"{database}.{schema}.{table_name}",
        incremental_field,
        db_incremental_field_last_value,
        incremental_field,
    )


def _parse_clustering_key_leading_column(clustering_key: str | None) -> str | None:
    """Extract the leading column from a Snowflake CLUSTERING_KEY string.

    Snowflake stores clustering keys as expressions like ``LINEAR(col1, col2)``.
    We unwrap the optional ``LINEAR(...)`` envelope, take the first comma-
    separated entry, and return its identifier in the same case Snowflake uses
    for ``INFORMATION_SCHEMA.COLUMNS.COLUMN_NAME`` so the caller can compare
    directly: unquoted identifiers are uppercased (matching Snowflake's
    identifier resolution rules), quoted identifiers have the quotes stripped
    and their case preserved. Returns None if the entry is empty or appears to
    be a function expression rather than a plain column reference (we can't
    tell whether `DATE_TRUNC('day', x)` accelerates predicate pruning the same
    way).
    """
    if not clustering_key:
        return None
    expr = clustering_key.strip()
    if expr.upper().startswith("LINEAR("):
        if not expr.endswith(")"):
            return None
        expr = expr[len("LINEAR(") : -1]
    leading = expr.split(",", 1)[0].strip()
    if not leading or "(" in leading:
        return None
    if leading.startswith('"') and leading.endswith('"') and len(leading) >= 2:
        return leading[1:-1]
    return leading.upper()


class SnowflakeImplementation(
    SQLSourceImplementation[SnowflakeSourceConfig, snowflake.connector.SnowflakeConnection, Any]
):
    """Snowflake driver implementation paired with `SnowflakeSource`.

    One class owns everything Snowflake-specific: the connection
    lifecycle (password vs keypair, with private-key tempfile cleanup),
    `information_schema`-style batch queries used during schema listing,
    per-cursor metadata used during the streaming sync (primary keys),
    and the dlt pipeline factory (`build_pipeline`).

    Snowflake does not currently use the optional streaming-side hooks
    (`fetch_table_stats`, `fetch_average_row_size`, `get_table_metadata`)
    — it streams via `cursor.fetch_arrow_batches()` and lets the base
    class return `None` for partition settings and the default chunk
    size. That preserves current behavior.
    """

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    @contextmanager
    def connect(
        self,
        config: SnowflakeSourceConfig,
    ) -> Iterator[snowflake.connector.SnowflakeConnection]:
        """Open a Snowflake connection for the duration of the context.

        Branches on `config.auth_type.selection`. In keypair mode the
        PEM private key is parsed in process and handed to the
        connector as DER bytes via `private_key=` — never written to
        disk, matching the streaming-side helper that the pre-refactor
        code used.

        Uses `config.schema` as the session schema. All listing queries
        use fully qualified `information_schema.<table>` references so
        the session schema does not affect their results.
        """
        auth_connect_args: dict[str, Any] = {}

        if config.auth_type.selection == "keypair" and config.auth_type.private_key is not None:
            p_key = serialization.load_pem_private_key(
                config.auth_type.private_key.encode("utf-8"),
                password=config.auth_type.passphrase.encode() if config.auth_type.passphrase else None,
                backend=default_backend(),
            )
            pkb = p_key.private_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
            auth_connect_args = {
                "user": config.auth_type.user,
                "private_key": pkb,
            }
        else:
            auth_connect_args = {
                "password": config.auth_type.password,
                "user": config.auth_type.user,
            }

        with snowflake.connector.connect(
            account=config.account_id,
            warehouse=config.warehouse,
            database=config.database,
            schema=config.schema,
            role=config.role,
            **auth_connect_args,
        ) as connection:
            yield connection

    # ------------------------------------------------------------------
    # Listing — batch queries run once during `get_schemas`
    # ------------------------------------------------------------------

    def get_columns(
        self,
        conn: snowflake.connector.SnowflakeConnection,
        config: SnowflakeSourceConfig,
        names: list[str] | None,
    ) -> dict[str, list[tuple[str, str, bool]]]:
        with conn.cursor() as cursor:
            if cursor is None:
                raise Exception("Can't create cursor to Snowflake")

            cursor.execute(
                "SELECT table_name, column_name, data_type, is_nullable"
                " FROM information_schema.columns"
                " WHERE table_schema = %(schema)s"
                " ORDER BY table_name ASC",
                {"schema": config.schema},
            )
            result = cursor.fetchall()

        schema_list: dict[str, list[tuple[str, str, bool]]] = collections.defaultdict(list)
        for row in result:
            schema_list[row[0]].append((row[1], row[2], row[3] == "YES"))

        if names is not None:
            names_set = set(names)
            schema_list = collections.defaultdict(list, {k: v for k, v in schema_list.items() if k in names_set})

        return dict(schema_list)

    def get_primary_keys(
        self,
        conn: snowflake.connector.SnowflakeConnection,
        config: SnowflakeSourceConfig,
        tables: list[str],
    ) -> dict[str, list[str] | None]:
        """Detect primary keys for all tables by iterating SHOW PRIMARY KEYS.

        Permission-sensitive — some Snowflake roles can't see
        catalog-level PK metadata. Swallow and log per-table failures so
        schema discovery keeps working without PKs.
        """
        result: dict[str, list[str] | None] = dict.fromkeys(tables)
        if not tables:
            return result

        try:
            with conn.cursor() as cursor:
                if cursor is None:
                    raise Exception("Can't create cursor to Snowflake")

                for tbl in tables:
                    try:
                        cursor.execute(
                            "SHOW PRIMARY KEYS IN IDENTIFIER(%s)",
                            (f"{config.database}.{config.schema}.{tbl}",),
                        )

                        column_index = next(
                            (i for i, row in enumerate(cursor.description) if row.name == "column_name"), -1
                        )
                        if column_index == -1:
                            continue

                        keys = [row[column_index] for row in cursor]
                        if keys:
                            result[tbl] = keys
                    except Exception as e:
                        structlog.get_logger().warning(
                            "Failed to detect primary keys for Snowflake table",
                            table=tbl,
                            exc_info=e,
                        )
                        continue
        except Exception as e:
            structlog.get_logger().warning("Failed to detect primary keys for Snowflake schemas", exc_info=e)

        return result

    def get_leading_index_columns(
        self,
        conn: snowflake.connector.SnowflakeConnection,
        config: SnowflakeSourceConfig,
        tables: list[str],
    ) -> dict[str, set[str]] | None:
        """Return the leading column of the clustering key per table.

        Snowflake doesn't have B-tree indexes; clustering keys are the
        structure that enables partition pruning for `WHERE col >= …`
        predicates. Tables without a clustering key map to an empty set
        so the UI warning fires. Returns None when discovery fails so
        the caller defaults to no warning.
        """
        if not tables:
            return {}

        result: dict[str, set[str]] = {table: set() for table in tables}

        try:
            with conn.cursor() as cursor:
                if cursor is None:
                    raise Exception("Can't create cursor to Snowflake")

                placeholders = ",".join(["%s"] * len(tables))
                cursor.execute(
                    f"""
                    SELECT TABLE_NAME, CLUSTERING_KEY
                    FROM INFORMATION_SCHEMA.TABLES
                    WHERE TABLE_CATALOG = %s
                      AND TABLE_SCHEMA = %s
                      AND TABLE_NAME IN ({placeholders})
                    """,
                    (config.database, config.schema, *tables),
                )

                for table_name, clustering_key in cursor:
                    leading = _parse_clustering_key_leading_column(clustering_key)
                    if leading is not None:
                        result.setdefault(table_name, set()).add(leading)
        except Exception as e:
            structlog.get_logger().warning("Failed to detect clustering keys for Snowflake schemas", exc_info=e)
            return None

        return result

    def get_incremental_filter(self) -> IncrementalFieldFilter:
        return filter_snowflake_incremental_fields

    # ------------------------------------------------------------------
    # Per-cursor metadata — used during `build_pipeline`
    # ------------------------------------------------------------------

    def get_primary_keys_for_table(
        self,
        cursor: Any,
        database: str,
        schema: str,
        table_name: str,
    ) -> list[str] | None:
        """Return the primary-key column names for a single table, or None.

        Snowflake's `SHOW PRIMARY KEYS IN IDENTIFIER(...)` requires the
        fully qualified `database.schema.table` reference, so this method
        takes `database` in addition to schema/table_name — the only
        driver to do so.
        """
        cursor.execute("SHOW PRIMARY KEYS IN IDENTIFIER(%s)", (f"{database}.{schema}.{table_name}",))

        column_index = next((i for i, row in enumerate(cursor.description) if row.name == "column_name"), -1)

        if column_index == -1:
            raise ValueError("column_name not found in Snowflake cursor description")

        keys = [row[column_index] for row in cursor]

        return keys if len(keys) > 0 else None

    def get_rows_to_sync(
        self,
        cursor: Any,
        inner_query: str,
        inner_query_args: tuple[Any, ...],
        logger: FilteringBoundLogger,
    ) -> int:
        """Count the rows the given `inner_query` will produce. Returns 0 on error."""
        try:
            query = f"SELECT COUNT(*) FROM ({inner_query}) as t"

            cursor.execute(query, inner_query_args)
            row = cursor.fetchone()

            if row is None:
                logger.debug("get_rows_to_sync: No results returned. Using 0 as rows to sync")
                return 0

            rows_to_sync = row[0] or 0
            rows_to_sync_int = int(rows_to_sync)

            logger.debug(f"get_rows_to_sync: rows_to_sync_int={rows_to_sync_int}")
            return rows_to_sync_int
        except Exception as e:
            logger.debug(f"get_rows_to_sync: Error: {e}. Using 0 as rows to sync", exc_info=e)
            capture_exception(e)
            return 0

    # ------------------------------------------------------------------
    # Pipeline build — the dlt `SourceResponse` for a single table
    # ------------------------------------------------------------------

    def build_pipeline(self, config: SnowflakeSourceConfig, inputs: SourceInputs) -> SourceResponse:
        table_name = inputs.schema_name
        if not table_name:
            raise ValueError("Table name is missing")

        database = config.database
        schema = config.schema
        logger = inputs.logger
        should_use_incremental_field = inputs.should_use_incremental_field
        incremental_field = inputs.incremental_field
        incremental_field_type = inputs.incremental_field_type
        db_incremental_field_last_value = inputs.db_incremental_field_last_value

        with self.connect(config) as connection:
            with connection.cursor() as cursor:
                if cursor is None:
                    raise Exception("Can't create cursor to Snowflake")
                inner_query, inner_query_params = _build_query(
                    database,
                    schema,
                    table_name,
                    should_use_incremental_field,
                    incremental_field,
                    incremental_field_type,
                    db_incremental_field_last_value,
                )
                primary_keys = self.get_primary_keys_for_table(cursor, database, schema, table_name)
                rows_to_sync = self.get_rows_to_sync(cursor, inner_query, inner_query_params, logger)

        def get_rows() -> Iterator[Any]:
            with self.connect(config) as streaming_connection:
                with streaming_connection.cursor() as streaming_cursor:
                    if streaming_cursor is None:
                        raise Exception("Can't create cursor to Snowflake")
                    query, params = _build_query(
                        database,
                        schema,
                        table_name,
                        should_use_incremental_field,
                        incremental_field,
                        incremental_field_type,
                        db_incremental_field_last_value,
                    )
                    logger.debug(f"Snowflake query: {query.format(params)}")
                    streaming_cursor.execute(query, params)

                    # We cant control the batch size from snowflake when using the arrow function
                    # https://github.com/snowflakedb/snowflake-connector-python/issues/1712
                    yield from streaming_cursor.fetch_arrow_batches()

        name = NamingConvention.normalize_identifier(table_name)

        return SourceResponse(name=name, items=get_rows, primary_keys=primary_keys, rows_to_sync=rows_to_sync)
