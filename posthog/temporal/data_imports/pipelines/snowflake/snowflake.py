from typing import Any, Optional
from collections.abc import Iterator

from posthog.temporal.common.logger import FilteringBoundLogger
from posthog.temporal.data_imports.pipelines.helpers import incremental_type_to_initial_value
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.warehouse.types import IncrementalFieldType
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from dlt.common.normalizers.naming.snake_case import NamingConvention
import snowflake.connector
from snowflake.connector.cursor import SnowflakeCursor


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
    is_incremental: bool,
    incremental_field: Optional[str],
    incremental_field_type: Optional[IncrementalFieldType],
    db_incremental_field_last_value: Optional[Any],
) -> tuple[str, tuple[Any, ...]]:
    if not is_incremental:
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
    is_incremental: bool,
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
            primary_keys = _get_primary_keys(cursor, database, schema, table_name)

    def get_rows() -> Iterator[Any]:
        with _get_connection(
            account_id, user, password, passphrase, private_key, auth_type, database, warehouse, schema, role
        ) as connection:
            with connection.cursor() as cursor:
                query, params = _build_query(
                    database,
                    schema,
                    table_name,
                    is_incremental,
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

    return SourceResponse(name=name, items=get_rows(), primary_keys=primary_keys)
