"""Source that loads tables form any SQLAlchemy supported database, supports batching requests and incremental loads."""

from datetime import datetime, date
from typing import Any, Optional, Union, List  # noqa: UP035
from collections.abc import Iterable
from zoneinfo import ZoneInfo
from sqlalchemy import MetaData, Table
from sqlalchemy.engine import Engine

import dlt
from dlt.sources import DltResource, DltSource


from dlt.sources.credentials import ConnectionStringCredentials
from urllib.parse import quote

from posthog.warehouse.types import IncrementalFieldType

from .helpers import (
    table_rows,
    engine_from_credentials,
    get_primary_key,
    SqlDatabaseTableConfiguration,
)


def incremental_type_to_initial_value(field_type: IncrementalFieldType) -> Any:
    if field_type == IncrementalFieldType.Integer or field_type == IncrementalFieldType.Numeric:
        return 0
    if field_type == IncrementalFieldType.DateTime or field_type == IncrementalFieldType.Timestamp:
        return datetime(1970, 1, 1, 0, 0, 0, 0, tzinfo=ZoneInfo("UTC"))
    if field_type == IncrementalFieldType.Date:
        return date(1970, 1, 1)


def postgres_source(
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    sslmode: str,
    schema: str,
    table_names: list[str],
    incremental_field: Optional[str] = None,
    incremental_field_type: Optional[IncrementalFieldType] = None,
) -> DltSource:
    host = quote(host)
    user = quote(user)
    password = quote(password)
    database = quote(database)
    sslmode = quote(sslmode)

    credentials = ConnectionStringCredentials(
        f"postgresql://{user}:{password}@{host}:{port}/{database}?sslmode={sslmode}"
    )

    if incremental_field is not None and incremental_field_type is not None:
        incremental: dlt.sources.incremental | None = dlt.sources.incremental(
            cursor_path=incremental_field, initial_value=incremental_type_to_initial_value(incremental_field_type)
        )
    else:
        incremental = None

    db_source = sql_database(credentials, schema=schema, table_names=table_names, incremental=incremental)

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
    incremental_field_type: Optional[str] = None,
) -> DltSource:
    account_id = quote(account_id)
    user = quote(user)
    password = quote(password)
    database = quote(database)
    warehouse = quote(warehouse)
    role = quote(role) if role else None

    credentials = ConnectionStringCredentials(
        f"snowflake://{user}:{password}@{account_id}/{database}/{schema}?warehouse={warehouse}{f'&role={role}' if role else ''}"
    )
    db_source = sql_database(credentials, schema=schema, table_names=table_names)

    return db_source


@dlt.source(max_table_nesting=0)
def sql_database(
    credentials: Union[ConnectionStringCredentials, Engine, str] = dlt.secrets.value,
    schema: Optional[str] = dlt.config.value,
    metadata: Optional[MetaData] = None,
    table_names: Optional[List[str]] = dlt.config.value,  # noqa: UP006
    incremental: Optional[dlt.sources.incremental] = None,
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
        yield dlt.resource(
            table_rows,
            name=table.name,
            primary_key=get_primary_key(table),
            merge_key=get_primary_key(table),
            write_disposition="merge" if incremental else "replace",
            spec=SqlDatabaseTableConfiguration,
        )(
            engine=engine,
            table=table,
            incremental=incremental,
        )
