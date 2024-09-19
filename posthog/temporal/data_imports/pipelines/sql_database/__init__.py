"""Source that loads tables form any SQLAlchemy supported database, supports batching requests and incremental loads."""

from datetime import datetime, date
from typing import Any, Optional, Union, List, cast  # noqa: UP035
from collections.abc import Iterable
from zoneinfo import ZoneInfo
from sqlalchemy import MetaData, Table, create_engine
from sqlalchemy.engine import Engine, CursorResult

import dlt
from dlt.sources import DltResource, DltSource
from dlt.common.schema.typing import TColumnSchema


from dlt.sources.credentials import ConnectionStringCredentials
from urllib.parse import quote

from posthog.warehouse.types import IncrementalFieldType
from posthog.warehouse.models.external_data_source import ExternalDataSource
from sqlalchemy.sql import text

from .helpers import (
    table_rows,
    engine_from_credentials,
    get_primary_key,
    SqlDatabaseTableConfiguration,
)
from dlt.common.data_types.typing import TDataType

POSTGRES_TO_DLT_TYPES: dict[str, TDataType] = {
    # Text types
    "char": "text",
    "character": "text",
    "varchar": "text",
    "character varying": "text",
    "text": "text",
    "xml": "text",
    "uuid": "text",
    "cidr": "text",
    "inet": "text",
    "macaddr": "text",
    "macaddr8": "text",
    "tsvector": "text",
    "tsquery": "text",
    # Bigint types
    "bigint": "bigint",
    "bigserial": "bigint",
    # Boolean type
    "boolean": "bool",
    # Timestamp types
    "timestamp": "timestamp",
    "timestamp with time zone": "timestamp",
    "timestamp without time zone": "timestamp",
    # Complex types (geometric types, ranges, json, etc.)
    "point": "complex",
    "line": "complex",
    "lseg": "complex",
    "box": "complex",
    "path": "complex",
    "polygon": "complex",
    "circle": "complex",
    "int4range": "complex",
    "int8range": "complex",
    "numrange": "complex",
    "tsrange": "complex",
    "tstzrange": "complex",
    "daterange": "complex",
    "json": "complex",
    "jsonb": "complex",
    # Decimal types
    "real": "decimal",
    "double precision": "decimal",
    "numeric": "decimal",
    "decimal": "decimal",
    # Date type
    "date": "date",
    # Additional mappings
    "smallint": "bigint",
    "integer": "bigint",
    "serial": "bigint",
    "money": "decimal",
    "bytea": "text",
    "time": "timestamp",
    "time with time zone": "timestamp",
    "time without time zone": "timestamp",
    "interval": "complex",
    "bit": "text",
    "bit varying": "text",
    "enum": "text",
    "oid": "bigint",
    "pg_lsn": "text",
}


def incremental_type_to_initial_value(field_type: IncrementalFieldType) -> Any:
    if field_type == IncrementalFieldType.Integer or field_type == IncrementalFieldType.Numeric:
        return 0
    if field_type == IncrementalFieldType.DateTime or field_type == IncrementalFieldType.Timestamp:
        return datetime(1970, 1, 1, 0, 0, 0, 0, tzinfo=ZoneInfo("UTC"))
    if field_type == IncrementalFieldType.Date:
        return date(1970, 1, 1)


def sql_source_for_type(
    source_type: ExternalDataSource.Type,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    sslmode: str,
    schema: str,
    table_names: list[str],
    team_id: Optional[int] = None,
    incremental_field: Optional[str] = None,
    incremental_field_type: Optional[IncrementalFieldType] = None,
) -> DltSource:
    host = quote(host)
    user = quote(user)
    password = quote(password)
    database = quote(database)
    sslmode = quote(sslmode)

    if incremental_field is not None and incremental_field_type is not None:
        incremental: dlt.sources.incremental | None = dlt.sources.incremental(
            cursor_path=incremental_field, initial_value=incremental_type_to_initial_value(incremental_field_type)
        )
    else:
        incremental = None

    if source_type == ExternalDataSource.Type.POSTGRES:
        credentials = ConnectionStringCredentials(
            f"postgresql://{user}:{password}@{host}:{port}/{database}?sslmode={sslmode}"
        )
    elif source_type == ExternalDataSource.Type.MYSQL:
        credentials = ConnectionStringCredentials(f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}")
    elif source_type == ExternalDataSource.Type.MSSQL:
        credentials = ConnectionStringCredentials(
            f"mssql+pyodbc://{user}:{password}@{host}:{port}/{database}?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes"
        )
    else:
        raise Exception("Unsupported source_type")

    db_source = sql_database(
        credentials, schema=schema, table_names=table_names, incremental=incremental, team_id=team_id
    )

    return db_source


def snowflake_source(
    account_id: str,
    user: str,
    password: str,
    database: str,
    warehouse: str,
    schema: str,
    table_names: list[str],
    role: Optional[str] = None,
    incremental_field: Optional[str] = None,
    incremental_field_type: Optional[IncrementalFieldType] = None,
) -> DltSource:
    account_id = quote(account_id)
    user = quote(user)
    password = quote(password)
    database = quote(database)
    warehouse = quote(warehouse)
    role = quote(role) if role else None

    if incremental_field is not None and incremental_field_type is not None:
        incremental: dlt.sources.incremental | None = dlt.sources.incremental(
            cursor_path=incremental_field, initial_value=incremental_type_to_initial_value(incremental_field_type)
        )
    else:
        incremental = None

    credentials = ConnectionStringCredentials(
        f"snowflake://{user}:{password}@{account_id}/{database}/{schema}?warehouse={warehouse}{f'&role={role}' if role else ''}"
    )
    db_source = sql_database(credentials, schema=schema, table_names=table_names, incremental=incremental)

    return db_source


def bigquery_source(
    dataset_id: str,
    project_id: str,
    private_key: str,
    private_key_id: str,
    client_email: str,
    token_uri: str,
    table_name: str,
    incremental_field: Optional[str] = None,
    incremental_field_type: Optional[IncrementalFieldType] = None,
) -> DltSource:
    if incremental_field is not None and incremental_field_type is not None:
        incremental: dlt.sources.incremental | None = dlt.sources.incremental(
            cursor_path=incremental_field, initial_value=incremental_type_to_initial_value(incremental_field_type)
        )
    else:
        incremental = None

    credentials_info = {
        "type": "service_account",
        "project_id": project_id,
        "private_key": private_key,
        "private_key_id": private_key_id,
        "client_email": client_email,
        "token_uri": token_uri,
    }

    engine = create_engine(f"bigquery://{project_id}/{dataset_id}", credentials_info=credentials_info)

    return sql_database(engine, schema=None, table_names=[table_name], incremental=incremental)


# Temp while DLT doesn't support `interval` columns
def remove_columns(columns_to_drop: list[str], team_id: Optional[int]):
    def internal_remove(doc: dict) -> dict:
        if team_id == 1 or team_id == 2:
            if "sync_frequency_interval" in doc:
                del doc["sync_frequency_interval"]

        for col in columns_to_drop:
            if col in doc:
                del doc[col]

        return doc

    return internal_remove


@dlt.source(max_table_nesting=0)
def sql_database(
    credentials: Union[ConnectionStringCredentials, Engine, str] = dlt.secrets.value,
    schema: Optional[str] = dlt.config.value,
    metadata: Optional[MetaData] = None,
    table_names: Optional[List[str]] = dlt.config.value,  # noqa: UP006
    incremental: Optional[dlt.sources.incremental] = None,
    team_id: Optional[int] = None,
) -> Iterable[DltResource]:
    """
    A DLT source which loads data from an SQL database using SQLAlchemy.
    Resources are automatically created for each table in the schema or from the given list of tables.

    Args:
        credentials (Union[ConnectionStringCredentials, Engine, str]): Database credentials or an `sqlalchemy.Engine` instance.
        schema (Optional[str]): Name of the database schema to load (if different from default).
        metadata (Optional[MetaData]): Optional `sqlalchemy.MetaData` instance. `schema` argument is ignored when this is used.
        table_names (Optional[List[str]]): A list of table names to load. By default, all tables in the schema are loaded.

    Returns:
        Iterable[DltResource]: A list of DLT resources for each table to be loaded.
    """

    # set up alchemy engine
    engine = engine_from_credentials(credentials)
    engine.execution_options(stream_results=True)
    metadata = metadata or MetaData(schema=schema)

    # use provided tables or all tables
    if table_names:
        tables = [Table(name, metadata, autoload_with=engine) for name in table_names]
    else:
        metadata.reflect(bind=engine)
        tables = list(metadata.tables.values())

    for table in tables:
        # TODO(@Gilbert09): Read column types, convert them to DLT types
        # and pass them in here to get empty table materialization
        binary_columns_to_drop = get_binary_columns(engine, schema or "", table.name)

        yield (
            dlt.resource(
                table_rows,
                name=table.name,
                primary_key=get_primary_key(table),
                merge_key=get_primary_key(table),
                write_disposition={
                    "disposition": "merge",
                    "strategy": "upsert",
                }
                if incremental
                else "replace",
                spec=SqlDatabaseTableConfiguration,
                table_format="delta",
                columns=get_column_hints(engine, schema or "", table.name),
            ).add_map(remove_columns(binary_columns_to_drop, team_id))(
                engine=engine,
                table=table,
                incremental=incremental,
            )
        )


def get_binary_columns(engine: Engine, schema_name: str, table_name: str) -> list[str]:
    # TODO(@Gilbert09): Add support for querying bigquery here
    if engine.url.drivername == "bigquery":
        return []

    with engine.connect() as conn:
        execute_result: CursorResult = conn.execute(
            text(
                "SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = :schema_name AND table_name = :table_name"
            ),
            {"schema_name": schema_name, "table_name": table_name},
        )

        cursor_result = cast(CursorResult, execute_result)
        results = cursor_result.fetchall()

    binary_cols: list[str] = []

    for column_name, data_type in results:
        lower_data_type = data_type.lower()
        if lower_data_type == "bytea" or lower_data_type == "binary" or lower_data_type == "varbinary":
            binary_cols.append(column_name)

    return binary_cols


def get_column_hints(engine: Engine, schema_name: str, table_name: str) -> dict[str, TColumnSchema]:
    # TODO(@Gilbert09): Add support for querying bigquery here
    if engine.url.drivername == "bigquery":
        return {}

    with engine.connect() as conn:
        execute_result: CursorResult = conn.execute(
            text(
                "SELECT column_name, data_type, numeric_precision, numeric_scale, is_nullable FROM information_schema.columns WHERE table_schema = :schema_name AND table_name = :table_name"
            ),
            {"schema_name": schema_name, "table_name": table_name},
        )

        cursor_result = cast(CursorResult, execute_result)
        results = cursor_result.fetchall()

    columns: dict[str, TColumnSchema] = {}

    for column_name, data_type, numeric_precision, numeric_scale, is_nullable in results:
        if data_type == "numeric":
            columns[column_name] = {
                "data_type": "decimal",
                "precision": numeric_precision or 76,
                "scale": numeric_scale or 32,
                "nullable": is_nullable == "YES",
            }
        else:
            columns[column_name] = {
                "name": column_name,
                "data_type": POSTGRES_TO_DLT_TYPES.get(data_type, "text"),
                "nullable": is_nullable == "YES",
            }

    return columns
