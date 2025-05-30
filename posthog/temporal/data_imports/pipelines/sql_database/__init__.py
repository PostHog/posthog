"""Source that loads tables form any SQLAlchemy supported database, supports batching requests and incremental loads."""

import typing
from collections.abc import Callable, Iterable
from typing import Any, Optional, Union
from urllib.parse import quote

import dlt
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from dlt.common.libs.pyarrow import pyarrow as pa
from dlt.sources import DltResource, DltSource
from dlt.sources.credentials import ConnectionStringCredentials
from sqlalchemy import MetaData, Table, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy_bigquery import BigQueryDialect, __all__
from sqlalchemy_bigquery._types import _type_map

from posthog.settings.utils import get_from_env
from posthog.temporal.data_imports.pipelines.helpers import incremental_type_to_initial_value
from posthog.temporal.data_imports.pipelines.sql_database._json import BigQueryJSON
from posthog.temporal.data_imports.pipelines.sql_database.settings import DEFAULT_CHUNK_SIZE
from posthog.utils import str_to_bool
from posthog.warehouse.types import IncrementalFieldType

from .helpers import (
    SelectAny,
    SqlTableResourceConfiguration,
    TableBackend,
    _detect_precision_hints_deprecated,
    engine_from_credentials,
    table_rows,
)
from .schema_types import (
    ReflectionLevel,
    TTypeAdapter,
    default_table_adapter,
    get_primary_key,
    table_to_columns,
)

# Workaround to get JSON support in the BigQuery Dialect
BigQueryDialect.JSON = BigQueryJSON
_type_map["JSON"] = BigQueryJSON
__all__.append("JSON")


def sql_source_for_type(
    source_type,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    sslmode: str,
    schema: str,
    table_names: list[str],
    db_incremental_field_last_value: Optional[Any],
    using_ssl: Optional[bool] = True,
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

    connect_args = []

    if source_type == "Postgres":
        credentials = ConnectionStringCredentials(
            f"postgresql+psycopg://{user}:{password}@{host}:{port}/{database}?sslmode={sslmode}"
        )
    elif source_type == "MySQL":
        query_params = ""

        if using_ssl:
            # We have to get DEBUG in temporal workers cos we're not loading Django in the same way as the app
            is_debug = get_from_env("DEBUG", False, type_cast=str_to_bool)
            ssl_ca = "/etc/ssl/cert.pem" if is_debug else "/etc/ssl/certs/ca-certificates.crt"
            query_params = f"ssl_ca={ssl_ca}&ssl_verify_cert=false"

        credentials = ConnectionStringCredentials(
            f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}?{query_params}"
        )

        # PlanetScale needs this to be set
        if host.endswith("psdb.cloud"):
            connect_args = ["SET workload = 'OLAP';"]
    elif source_type == "MSSQL":
        credentials = ConnectionStringCredentials(
            f"mssql+pyodbc://{user}:{password}@{host}:{port}/{database}?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes"
        )
    else:
        raise Exception("Unsupported source_type")

    db_source = sql_database(
        credentials=credentials,
        schema=schema,
        table_names=table_names,
        incremental=incremental,
        db_incremental_field_last_value=db_incremental_field_last_value,
        team_id=team_id,
        connect_args=connect_args,
        chunk_size=DEFAULT_CHUNK_SIZE,
    )

    return db_source


@dlt.source(max_table_nesting=0)
def sql_database(
    db_incremental_field_last_value: Optional[Any],
    credentials: Union[ConnectionStringCredentials, Engine, str] = dlt.secrets.value,
    schema: Optional[str] = dlt.config.value,
    metadata: Optional[MetaData] = None,
    table_names: Optional[list[str]] = dlt.config.value,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    backend: TableBackend = "pyarrow",
    detect_precision_hints: Optional[bool] = False,
    reflection_level: Optional[ReflectionLevel] = "full",
    defer_table_reflect: Optional[bool] = None,
    table_adapter_callback: Optional[Callable[[Table], None]] = None,
    backend_kwargs: Optional[dict[str, Any]] = None,
    include_views: bool = False,
    type_adapter_callback: Optional[TTypeAdapter] = None,
    incremental: Optional[dlt.sources.incremental] = None,
    team_id: Optional[int] = None,
    connect_args: Optional[list[str]] = None,
) -> Iterable[DltResource]:
    """
    A dlt source which loads data from an SQL database using SQLAlchemy.
    Resources are automatically created for each table in the schema or from the given list of tables.

    Args:
        credentials (Union[ConnectionStringCredentials, Engine, str]): Database credentials or an `sqlalchemy.Engine` instance.
        schema (Optional[str]): Name of the database schema to load (if different from default).
        metadata (Optional[MetaData]): Optional `sqlalchemy.MetaData` instance. `schema` argument is ignored when this is used.
        table_names (Optional[List[str]]): A list of table names to load. By default, all tables in the schema are loaded.
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
        query_adapter_callback(Optional[Callable[Select, Table], Select]): Callable to override the SELECT query used to fetch data from the table.
            The callback receives the sqlalchemy `Select` and corresponding `Table` objects and should return the modified `Select`.

    Returns:
        Iterable[DltResource]: A list of DLT resources for each table to be loaded.
    """
    # detect precision hints is deprecated
    _detect_precision_hints_deprecated(detect_precision_hints)

    if detect_precision_hints:
        reflection_level = "full_with_precision"
    else:
        reflection_level = reflection_level or "minimal"

    # set up alchemy engine
    engine = engine_from_credentials(credentials).execution_options(stream_results=True, max_row_buffer=2 * chunk_size)
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
        yield sql_table(
            credentials=engine,
            table=table.name,
            schema=table.schema,
            metadata=metadata,
            chunk_size=chunk_size,
            backend=backend,
            reflection_level=reflection_level,
            defer_table_reflect=defer_table_reflect,
            table_adapter_callback=table_adapter_callback,
            backend_kwargs=backend_kwargs,
            type_adapter_callback=type_adapter_callback,
            incremental=incremental,
            db_incremental_field_last_value=db_incremental_field_last_value,
            team_id=team_id,
            connect_args=connect_args,
        )


# Temp while we dont support binary columns in HogQL
def remove_columns(columns_to_drop: list[str], team_id: Optional[int]):
    col_len = len(columns_to_drop)

    def internal_remove(table: pa.Table) -> pa.Table:
        if col_len == 0:
            return table

        table_cols = [n for n in columns_to_drop if n in table.column_names]
        if len(table_cols) > 0:
            return table.drop(columns_to_drop)

        return table

    return internal_remove


@dlt.resource(name=lambda args: args["table"], standalone=True, spec=SqlTableResourceConfiguration)
def sql_table(
    db_incremental_field_last_value: Optional[Any],
    credentials: Union[ConnectionStringCredentials, Engine, str] = dlt.secrets.value,
    table: str = dlt.config.value,
    schema: Optional[str] = dlt.config.value,
    metadata: Optional[MetaData] = None,
    incremental: Optional[dlt.sources.incremental[Any]] = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    backend: TableBackend = "pyarrow",
    detect_precision_hints: Optional[bool] = None,
    reflection_level: Optional[ReflectionLevel] = "full",
    defer_table_reflect: Optional[bool] = None,
    table_adapter_callback: Optional[Callable[[Table], None]] = None,
    backend_kwargs: Optional[dict[str, Any]] = None,
    type_adapter_callback: Optional[TTypeAdapter] = None,
    included_columns: Optional[list[str]] = None,
    team_id: Optional[int] = None,
    connect_args: Optional[list[str]] = None,
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
        included_columns (Optional[List[str]): List of column names to select from the table. If not provided, all columns are loaded.
        query_adapter_callback(Optional[Callable[Select, Table], Select]): Callable to override the SELECT query used to fetch data from the table.
            The callback receives the sqlalchemy `Select` and corresponding `Table` objects and should return the modified `Select`.

    Returns:
        DltResource: The dlt resource for loading data from the SQL database table.
    """
    _detect_precision_hints_deprecated(detect_precision_hints)

    if detect_precision_hints:
        reflection_level = "full_with_precision"
    else:
        reflection_level = reflection_level or "minimal"

    engine = engine_from_credentials(credentials, may_dispose_after_use=True).execution_options(
        stream_results=True, max_row_buffer=2 * chunk_size
    )
    metadata = metadata or MetaData(schema=schema)

    table_obj: Table | None = metadata.tables.get("table")
    if table_obj is None:
        table_obj = Table(table, metadata, autoload_with=None if defer_table_reflect else engine)

    if not defer_table_reflect:
        default_table_adapter(table_obj, included_columns)
        if table_adapter_callback:
            table_adapter_callback(table_obj)

    columns = table_to_columns(table_obj, reflection_level, type_adapter_callback)

    def query_adapter_callback(query: SelectAny, table: Table):
        cols_to_select = list(columns.keys())

        return query.with_only_columns(table.c[*cols_to_select])

    return dlt.resource(
        table_rows,
        name=table_obj.name,
        primary_key=get_primary_key(table_obj),
        merge_key=get_primary_key(table_obj),
        columns=columns,
        write_disposition={
            "disposition": "merge",
            "strategy": "upsert",
        }
        if incremental
        else "replace",
        table_format="delta",
    )(
        engine=engine,
        table=table_obj,
        chunk_size=chunk_size,
        backend=backend,
        incremental=incremental,
        db_incremental_field_last_value=db_incremental_field_last_value,
        reflection_level=reflection_level,
        defer_table_reflect=defer_table_reflect,
        table_adapter_callback=table_adapter_callback,
        backend_kwargs=backend_kwargs,
        type_adapter_callback=type_adapter_callback,
        included_columns=included_columns,
        query_adapter_callback=query_adapter_callback,
        connect_args=connect_args,
    )
