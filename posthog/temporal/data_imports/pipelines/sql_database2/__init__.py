"""Source that loads tables form any SQLAlchemy supported database, supports batching requests and incremental loads."""

from typing import Optional, Union, Any
from collections.abc import Callable, Iterable
from sqlalchemy import MetaData, Table
from sqlalchemy.engine import Engine

import dlt
from dlt.sources import DltResource


from dlt.sources.credentials import ConnectionStringCredentials

from .helpers import (
    table_rows,
    engine_from_credentials,
    TableBackend,
    SqlDatabaseTableConfiguration,
    SqlTableResourceConfiguration,
)
from .schema_types import (
    table_to_columns,
    get_primary_key,
    ReflectionLevel,
    TTypeAdapter,
)


@dlt.source
def sql_database(
    credentials: Union[ConnectionStringCredentials, Engine, str] = dlt.secrets.value,
    schema: Optional[str] = dlt.config.value,
    metadata: Optional[MetaData] = None,
    table_names: Optional[list[str]] = dlt.config.value,
    chunk_size: int = 50000,
    backend: TableBackend = "sqlalchemy",
    detect_precision_hints: Optional[bool] = False,
    reflection_level: Optional[ReflectionLevel] = "full",
    defer_table_reflect: Optional[bool] = None,
    table_adapter_callback: Optional[Callable[[Table], None]] = None,
    backend_kwargs: Optional[dict[str, Any]] = None,
    include_views: bool = False,
    type_adapter_callback: Optional[TTypeAdapter] = None,
) -> Iterable[DltResource]:
    """
    A dlt source which loads data from an SQL database using SQLAlchemy.
    Resources are automatically created for each table in the schema or from the given list of tables.

    Args:
        credentials (Union[ConnectionStringCredentials, Engine, str]): Database credentials or an `sqlalchemy.Engine` instance.
        schema (Optional[str]): Name of the database schema to load (if different from default).
        metadata (Optional[MetaData]): Optional `sqlalchemy.MetaData` instance. `schema` argument is ignored when this is used.
        table_names (Optional[list[str]]): A list of table names to load. By default, all tables in the schema are loaded.
        chunk_size (int): Number of rows yielded in one batch. SQL Alchemy will create additional internal rows buffer twice the chunk size.
        backend (TableBackend): Type of backend to generate table data. One of: "sqlalchemy", "pyarrow", "pandas" and "connectorx".
            "sqlalchemy" yields batches as lists of Python dictionaries, "pyarrow" and "connectorx" yield batches as arrow tables, "pandas" yields panda frames.
            "sqlalchemy" is the default and does not require additional dependencies, "pyarrow" creates stable destination schemas with correct data types,
            "connectorx" is typically the fastest but ignores the "chunk_size" so you must deal with large tables yourself.
        detect_precision_hints (bool): Deprecated. Use `reflection_level`. Set column precision and scale hints for supported data types in the target schema based on the columns in the source tables.
            This is disabled by default.
        reflection_level: (ReflectionLevel): Specifies how much information should be reflected from the source database schema.
            "minimal": Only table names, nullability and primary keys are reflected. Data types are inferred from the data.
            "full": Data types will be reflected on top of "minimal". `dlt` will coerce the data into reflected types if necessary. This is the default option.
            "full_with_precision": Sets precision and scale on supported data types (ie. decimal, text, binary). Creates big and regular integer types.
        defer_table_reflect (bool): Will connect and reflect table schema only when yielding data. Requires table_names to be explicitly passed.
            Enable this option when running on Airflow. Available on dlt 0.4.4 and later.
        table_adapter_callback: (Callable): Receives each reflected table. May be used to modify the list of columns that will be selected.
        backend_kwargs (**kwargs): kwargs passed to table backend ie. "conn" is used to pass specialized connection string to connectorx.
        include_views (bool): Reflect views as well as tables. Note view names included in `table_names` are always included regardless of this setting.
        type_adapter_callback(Optional[Callable]): Callable to override type inference when reflecting columns.
            Argument is a single sqlalchemy data type (`TypeEngine` instance) and it should return another sqlalchemy data type, or `None` (type will be inferred from data)
    Returns:

        Iterable[DltResource]: A list of DLT resources for each table to be loaded.
    """

    if detect_precision_hints:
        reflection_level = "full_with_precision"
    else:
        reflection_level = reflection_level or "minimal"

    # set up alchemy engine
    engine = engine_from_credentials(credentials)
    engine.execution_options(stream_results=True, max_row_buffer=2 * chunk_size)
    metadata = metadata or MetaData(schema=schema)

    # use provided tables or all tables
    if table_names:
        tables = [Table(name, metadata, autoload_with=None if defer_table_reflect else engine) for name in table_names]
    else:
        if defer_table_reflect:
            raise ValueError("You must pass table names to defer table reflection")
        metadata.reflect(bind=engine, views=include_views)
        tables = list(metadata.tables.values())

    for table in tables:
        if table_adapter_callback and not defer_table_reflect:
            table_adapter_callback(table)

        yield dlt.resource(
            table_rows,
            name=table.name,
            primary_key=get_primary_key(table),
            spec=SqlDatabaseTableConfiguration,
            columns=table_to_columns(table, reflection_level, type_adapter_callback),
        )(
            engine,
            table,
            chunk_size,
            backend,
            reflection_level=reflection_level,
            defer_table_reflect=defer_table_reflect,
            table_adapter_callback=table_adapter_callback,
            backend_kwargs=backend_kwargs,
            type_adapter_callback=type_adapter_callback,
        )


@dlt.resource(name=lambda args: args["table"], standalone=True, spec=SqlTableResourceConfiguration)
def sql_table(
    credentials: Union[ConnectionStringCredentials, Engine, str] = dlt.secrets.value,
    table: str = dlt.config.value,
    schema: Optional[str] = dlt.config.value,
    metadata: Optional[MetaData] = None,
    incremental: Optional[dlt.sources.incremental[Any]] = None,
    chunk_size: int = 50000,
    backend: TableBackend = "sqlalchemy",
    detect_precision_hints: Optional[bool] = None,
    reflection_level: Optional[ReflectionLevel] = "full",
    defer_table_reflect: Optional[bool] = None,
    table_adapter_callback: Optional[Callable[[Table], None]] = None,
    backend_kwargs: Optional[dict[str, Any]] = None,
    type_adapter_callback: Optional[TTypeAdapter] = None,
) -> DltResource:
    """
    A dlt resource which loads data from an SQL database table using SQLAlchemy.

    Args:
        credentials (Union[ConnectionStringCredentials, Engine, str]): Database credentials or an `Engine` instance representing the database connection.
        table (str): Name of the table or view to load.
        schema (Optional[str]): Optional name of the schema the table belongs to.
        metadata (Optional[MetaData]): Optional `sqlalchemy.MetaData` instance. If provided, the `schema` argument is ignored.
        incremental (Optional[dlt.sources.incremental[Any]]): Option to enable incremental loading for the table.
            E.g., `incremental=dlt.sources.incremental('updated_at', pendulum.parse('2022-01-01T00:00:00Z'))`
        chunk_size (int): Number of rows yielded in one batch. SQL Alchemy will create additional internal rows buffer twice the chunk size.
        backend (TableBackend): Type of backend to generate table data. One of: "sqlalchemy", "pyarrow", "pandas" and "connectorx".
            "sqlalchemy" yields batches as lists of Python dictionaries, "pyarrow" and "connectorx" yield batches as arrow tables, "pandas" yields panda frames.
            "sqlalchemy" is the default and does not require additional dependencies, "pyarrow" creates stable destination schemas with correct data types,
            "connectorx" is typically the fastest but ignores the "chunk_size" so you must deal with large tables yourself.
        reflection_level: (ReflectionLevel): Specifies how much information should be reflected from the source database schema.
            "minimal": Only table names, nullability and primary keys are reflected. Data types are inferred from the data.
            "full": Data types will be reflected on top of "minimal". `dlt` will coerce the data into reflected types if necessary. This is the default option.
            "full_with_precision": Sets precision and scale on supported data types (ie. decimal, text, binary). Creates big and regular integer types.
        detect_precision_hints (bool): Deprecated. Use `reflection_level`. Set column precision and scale hints for supported data types in the target schema based on the columns in the source tables.
            This is disabled by default.
        defer_table_reflect (bool): Will connect and reflect table schema only when yielding data. Enable this option when running on Airflow. Available
            on dlt 0.4.4 and later
        table_adapter_callback: (Callable): Receives each reflected table. May be used to modify the list of columns that will be selected.
        backend_kwargs (**kwargs): kwargs passed to table backend ie. "conn" is used to pass specialized connection string to connectorx.
        type_adapter_callback(Optional[Callable]): Callable to override type inference when reflecting columns.
            Argument is a single sqlalchemy data type (`TypeEngine` instance) and it should return another sqlalchemy data type, or `None` (type will be inferred from data)

    Returns:
        DltResource: The dlt resource for loading data from the SQL database table.
    """

    if detect_precision_hints:
        reflection_level = "full_with_precision"
    else:
        reflection_level = reflection_level or "minimal"

    engine = engine_from_credentials(credentials, may_dispose_after_use=True)
    engine.execution_options(stream_results=True, max_row_buffer=2 * chunk_size)
    metadata = metadata or MetaData(schema=schema)

    table_obj = Table(table, metadata, autoload_with=None if defer_table_reflect else engine)
    if table_adapter_callback and not defer_table_reflect:
        table_adapter_callback(table_obj)

    return dlt.resource(
        table_rows,
        name=table_obj.name,
        primary_key=get_primary_key(table_obj),
        columns=table_to_columns(table_obj, reflection_level, type_adapter_callback),
    )(
        engine,
        table_obj,
        chunk_size,
        backend,
        incremental=incremental,
        reflection_level=reflection_level,
        defer_table_reflect=defer_table_reflect,
        table_adapter_callback=table_adapter_callback,
        backend_kwargs=backend_kwargs,
        type_adapter_callback=type_adapter_callback,
    )
