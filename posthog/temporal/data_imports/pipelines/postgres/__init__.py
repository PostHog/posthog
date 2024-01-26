"""Source that loads tables form any SQLAlchemy supported database, supports batching requests and incremental loads."""

from typing import List, Optional, Union, Iterable, Any
from sqlalchemy import MetaData, Table, text
from sqlalchemy.engine import Engine

import dlt
from dlt.sources import DltResource, DltSource


from dlt.sources.credentials import ConnectionStringCredentials

from .helpers import (
    table_rows,
    engine_from_credentials,
    get_primary_key,
    SqlDatabaseTableConfiguration,
    SqlTableResourceConfiguration,
)


def postgres_source(
    host: str, port: int, user: str, password: str, database: str, sslmode: str, schema: str, table_names: list[str]
) -> DltSource:
    credentials = ConnectionStringCredentials(
        f"postgresql://{user}:{password}@{host}:{port}/{database}?sslmode={sslmode}"
    )
    db_source = sql_database(credentials, schema=schema, table_names=table_names)

    return db_source


@dlt.source
def sql_database(
    credentials: Union[ConnectionStringCredentials, Engine, str] = dlt.secrets.value,
    schema: Optional[str] = dlt.config.value,
    metadata: Optional[MetaData] = None,
    table_names: Optional[List[str]] = dlt.config.value,
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
        yield dlt.resource(
            table_rows,
            name=table.name,
            primary_key=get_primary_key(table),
            spec=SqlDatabaseTableConfiguration,
        )(engine, table)
