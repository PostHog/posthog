import os
import tempfile
import collections
from collections.abc import Iterator
from typing import Any, Optional

import snowflake.connector
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from dlt.common.normalizers.naming.snake_case import NamingConvention
from snowflake.connector.cursor import SnowflakeCursor
from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception
from posthog.temporal.data_imports.pipelines.helpers import incremental_type_to_initial_value
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.generated_configs import SnowflakeSourceConfig

from products.data_warehouse.backend.types import IncrementalFieldType


def filter_snowflake_incremental_fields(columns: list[tuple[str, str]]) -> list[tuple[str, IncrementalFieldType]]:
    results: list[tuple[str, IncrementalFieldType]] = []
    for column_name, type in columns:
        type = type.lower()
        if type.startswith("timestamp"):
            results.append((column_name, IncrementalFieldType.Timestamp))
        elif type == "date":
            results.append((column_name, IncrementalFieldType.Date))
        elif type == "datetime":
            results.append((column_name, IncrementalFieldType.DateTime))
        elif type == "numeric":
            results.append((column_name, IncrementalFieldType.Numeric))

    return results


def get_schemas(config: SnowflakeSourceConfig) -> dict[str, list[tuple[str, str]]]:
    auth_connect_args: dict[str, str | None] = {}
    file_name: str | None = None

    if config.auth_type.selection == "keypair" and config.auth_type.private_key is not None:
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(config.auth_type.private_key.encode("utf-8"))
            file_name = tf.name

        auth_connect_args = {
            "user": config.auth_type.user,
            "private_key_file": file_name,
            "private_key_file_pwd": config.auth_type.passphrase
            if config.auth_type.passphrase and len(config.auth_type.passphrase) > 0
            else None,
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
        schema="information_schema",
        role=config.role,
        **auth_connect_args,
    ) as connection:
        with connection.cursor() as cursor:
            if cursor is None:
                raise Exception("Can't create cursor to Snowflake")

            cursor.execute(
                "SELECT table_name, column_name, data_type FROM information_schema.columns WHERE table_schema = %(schema)s ORDER BY table_name ASC",
                {"schema": config.schema},
            )
            result = cursor.fetchall()

            schema_list = collections.defaultdict(list)
            for row in result:
                schema_list[row[0]].append((row[1], row[2]))

    if file_name is not None:
        os.unlink(file_name)

    return schema_list


def _get_connection(
    account_id: str,
    user: Optional[str],
    password: Optional[str],
    passphrase: Optional[str],
    private_key: Optional[str],
    auth_type: str,
    database: str,
    warehouse: str,
    schema: str,
    role: Optional[str] = None,
) -> snowflake.connector.SnowflakeConnection:
    if auth_type == "password" and user is not None and password is not None:
        return snowflake.connector.connect(
            account=account_id,
            user=user,
            password=password,
            warehouse=warehouse,
            database=database,
            schema=schema,
            role=role if role else None,
        )

    if private_key is None:
        raise ValueError("Private key is missing for snowflake")

    p_key = serialization.load_pem_private_key(
        private_key.encode("utf-8"),
        password=passphrase.encode() if passphrase is not None else None,
        backend=default_backend(),
    )

    pkb = p_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    return snowflake.connector.connect(
        account=account_id,
        user=user,
        warehouse=warehouse,
        database=database,
        schema=schema,
        role=role if role else None,
        private_key=pkb,
    )


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

    return "SELECT * FROM IDENTIFIER(%s) WHERE IDENTIFIER(%s) >= %s ORDER BY IDENTIFIER(%s) ASC", (
        f"{database}.{schema}.{table_name}",
        incremental_field,
        db_incremental_field_last_value,
        incremental_field,
    )


def _get_rows_to_sync(
    cursor: SnowflakeCursor, inner_query: str, inner_query_args: tuple[Any, ...], logger: FilteringBoundLogger
) -> int:
    try:
        query = f"SELECT COUNT(*) FROM ({inner_query}) as t"

        cursor.execute(query, inner_query_args)
        row = cursor.fetchone()

        if row is None:
            logger.debug(f"_get_rows_to_sync: No results returned. Using 0 as rows to sync")
            return 0

        rows_to_sync = row[0] or 0
        rows_to_sync_int = int(rows_to_sync)

        logger.debug(f"_get_rows_to_sync: rows_to_sync_int={rows_to_sync_int}")

        return int(rows_to_sync)
    except Exception as e:
        logger.debug(f"_get_rows_to_sync: Error: {e}. Using 0 as rows to sync", exc_info=e)
        capture_exception(e)

        return 0


def _get_primary_keys(cursor: SnowflakeCursor, database: str, schema: str, table_name: str) -> list[str] | None:
    cursor.execute("SHOW PRIMARY KEYS IN IDENTIFIER(%s)", (f"{database}.{schema}.{table_name}",))

    column_index = next((i for i, row in enumerate(cursor.description) if row.name == "column_name"), -1)

    if column_index == -1:
        raise ValueError("column_name not found in Snowflake cursor description")

    keys = [row[column_index] for row in cursor]

    return keys if len(keys) > 0 else None


def snowflake_source(
    account_id: str,
    user: Optional[str],
    password: Optional[str],
    passphrase: Optional[str],
    private_key: Optional[str],
    auth_type: str,
    database: str,
    warehouse: str,
    schema: str,
    table_names: list[str],
    should_use_incremental_field: bool,
    logger: FilteringBoundLogger,
    db_incremental_field_last_value: Optional[Any],
    role: Optional[str] = None,
    incremental_field: Optional[str] = None,
    incremental_field_type: Optional[IncrementalFieldType] = None,
) -> SourceResponse:
    table_name = table_names[0]
    if not table_name:
        raise ValueError("Table name is missing")

    with _get_connection(
        account_id, user, password, passphrase, private_key, auth_type, database, warehouse, schema, role
    ) as connection:
        with connection.cursor() as cursor:
            inner_query, inner_query_params = _build_query(
                database,
                schema,
                table_name,
                should_use_incremental_field,
                incremental_field,
                incremental_field_type,
                db_incremental_field_last_value,
            )
            primary_keys = _get_primary_keys(cursor, database, schema, table_name)
            rows_to_sync = _get_rows_to_sync(cursor, inner_query, inner_query_params, logger)

    def get_rows() -> Iterator[Any]:
        with _get_connection(
            account_id, user, password, passphrase, private_key, auth_type, database, warehouse, schema, role
        ) as connection:
            with connection.cursor() as cursor:
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
                cursor.execute(query, params)

                # We cant control the batch size from snowflake when using the arrow function
                # https://github.com/snowflakedb/snowflake-connector-python/issues/1712
                yield from cursor.fetch_arrow_batches()

    name = NamingConvention().normalize_identifier(table_name)

    return SourceResponse(name=name, items=get_rows, primary_keys=primary_keys, rows_to_sync=rows_to_sync)
