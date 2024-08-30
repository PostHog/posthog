"""SQL database source helpers"""

from typing import (
    Any,
    Optional,
    Union,
)
from collections.abc import Iterator
import operator

import dlt
from dlt.sources.credentials import ConnectionStringCredentials
from dlt.common.configuration.specs import BaseConfiguration, configspec
from dlt.common.typing import TDataItem
from .settings import DEFAULT_CHUNK_SIZE

from sqlalchemy import Table, create_engine, Column
from sqlalchemy.engine import Engine
from sqlalchemy.sql import Select


class TableLoader:
    def __init__(
        self,
        engine: Engine,
        table: Table,
        chunk_size: int = 1000,
        incremental: Optional[dlt.sources.incremental[Any]] = None,
    ) -> None:
        self.engine = engine
        self.table = table
        self.chunk_size = chunk_size
        self.incremental = incremental
        if incremental:
            try:
                self.cursor_column: Optional[Column[Any]] = table.c[incremental.cursor_path]
            except KeyError as e:
                try:
                    self.cursor_column = table.c[incremental.cursor_path.lower()]
                except KeyError:
                    raise KeyError(
                        f"Cursor column '{incremental.cursor_path}' does not exist in table '{table.name}'"
                    ) from e
            self.last_value = incremental.last_value
        else:
            self.cursor_column = None
            self.last_value = None

    def make_query(self) -> Select[Any]:
        table = self.table
        query = table.select()
        if not self.incremental:
            return query
        last_value_func = self.incremental.last_value_func
        if last_value_func is max:  # Query ordered and filtered according to last_value function
            order_by = self.cursor_column.asc()  # type: ignore
            filter_op = operator.gt
        elif last_value_func is min:
            order_by = self.cursor_column.desc()  # type: ignore
            filter_op = operator.lt
        else:  # Custom last_value, load everything and let incremental handle filtering
            return query
        query = query.order_by(order_by)
        if self.last_value is None:
            return query
        return query.where(filter_op(self.cursor_column, self.last_value))  # type: ignore

    def load_rows(self) -> Iterator[list[TDataItem]]:
        query = self.make_query()
        with self.engine.connect() as conn:
            result = conn.execution_options(yield_per=self.chunk_size).execute(query)
            for partition in result.partitions(size=self.chunk_size):
                yield [dict(row._mapping) for row in partition]


def table_rows(
    engine: Engine,
    table: Table,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    incremental: Optional[dlt.sources.incremental[Any]] = None,
) -> Iterator[TDataItem]:
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
    yield dlt.mark.materialize_table_schema()  # type: ignore

    loader = TableLoader(engine, table, incremental=incremental, chunk_size=chunk_size)
    yield from loader.load_rows()

    engine.dispose()


def engine_from_credentials(credentials: Union[ConnectionStringCredentials, Engine, str]) -> Engine:
    if isinstance(credentials, Engine):
        return credentials
    if isinstance(credentials, ConnectionStringCredentials):
        credentials = credentials.to_native_representation()
    return create_engine(credentials, pool_pre_ping=True)


def get_primary_key(table: Table) -> list[str]:
    primary_keys = [c.name for c in table.primary_key]
    if len(primary_keys) > 0:
        return primary_keys

    column_names = [c.name for c in table.columns]
    if "id" in column_names:
        return ["id"]

    return []


@configspec
class SqlDatabaseTableConfiguration(BaseConfiguration):
    incremental: Optional[dlt.sources.incremental] = None


@configspec
class SqlTableResourceConfiguration(BaseConfiguration):
    credentials: ConnectionStringCredentials
    table: str
    schema: Optional[str]
    incremental: Optional[dlt.sources.incremental] = None


__source_name__ = "sql_database"
