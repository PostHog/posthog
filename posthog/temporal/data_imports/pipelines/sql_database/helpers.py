"""SQL database source helpers"""

import warnings
from typing import (
    Any,
    Literal,
    Optional,
    Union,
)
from collections.abc import Callable, Iterator
import operator

import dlt
from dlt.common.configuration.specs import BaseConfiguration, configspec
from dlt.common.exceptions import MissingDependencyException
from dlt.common.schema import TTableSchemaColumns
from dlt.common.typing import TDataItem, TSortOrder

from dlt.sources.credentials import ConnectionStringCredentials

from posthog.temporal.data_imports.pipelines.sql_database.settings import DEFAULT_CHUNK_SIZE

from .arrow_helpers import row_tuples_to_arrow
from .schema_types import (
    default_table_adapter,
    table_to_columns,
    get_primary_key,
    SelectAny,
    ReflectionLevel,
    TTypeAdapter,
)

from sqlalchemy import Table, create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import CompileError


TableBackend = Literal["sqlalchemy", "pyarrow", "pandas", "connectorx"]
TQueryAdapter = Callable[[SelectAny, Table], SelectAny]


class TableLoader:
    def __init__(
        self,
        engine: Engine,
        backend: TableBackend,
        table: Table,
        columns: TTableSchemaColumns,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        incremental: Optional[dlt.sources.incremental[Any]] = None,
        db_incremental_field_last_value: Optional[Any] = None,
        query_adapter_callback: Optional[TQueryAdapter] = None,
        connect_args: Optional[list[str]] = None,
    ) -> None:
        self.engine = engine
        self.backend = backend
        self.table = table
        self.columns = columns
        self.chunk_size = chunk_size
        self.query_adapter_callback = query_adapter_callback
        self.incremental = incremental
        self.connect_args = connect_args
        if incremental:
            try:
                self.cursor_column = table.c[incremental.cursor_path]
            except KeyError as e:
                raise KeyError(
                    f"Cursor column '{incremental.cursor_path}' does not exist in table '{table.name}'"
                ) from e
            self.last_value = (
                db_incremental_field_last_value
                if db_incremental_field_last_value is not None
                else incremental.last_value
            )
            self.end_value = incremental.end_value
            self.row_order: TSortOrder = self.incremental.row_order
        else:
            self.cursor_column = None
            self.last_value = None
            self.end_value = None
            self.row_order = None

    def _make_query(self) -> SelectAny:
        table = self.table
        query = table.select()
        if not self.incremental:
            return query
        last_value_func = self.incremental.last_value_func

        # generate where
        if last_value_func is max:  # Query ordered and filtered according to last_value function
            filter_op = operator.ge
            filter_op_end = operator.lt
        elif last_value_func is min:
            filter_op = operator.le
            filter_op_end = operator.gt
        else:  # Custom last_value, load everything and let incremental handle filtering
            return query

        if self.last_value is not None:
            query = query.where(filter_op(self.cursor_column, self.last_value))
            if self.end_value is not None:
                query = query.where(filter_op_end(self.cursor_column, self.end_value))

        # generate order by from declared row order - default to asc
        order_by = self.cursor_column.asc()

        if (self.row_order == "asc" and last_value_func is max) or (
            self.row_order == "desc" and last_value_func is min
        ):
            order_by = self.cursor_column.asc()
        elif (self.row_order == "asc" and last_value_func is min) or (
            self.row_order == "desc" and last_value_func is max
        ):
            order_by = self.cursor_column.desc()
        if order_by is not None:
            query = query.order_by(order_by)

        return query

    def make_query(self) -> SelectAny:
        if self.query_adapter_callback:
            return self.query_adapter_callback(self._make_query(), self.table)
        return self._make_query()

    def load_rows(self, backend_kwargs: Optional[dict[str, Any]] = None) -> Iterator[TDataItem]:
        # make copy of kwargs
        backend_kwargs = dict(backend_kwargs or {})
        query = self.make_query()
        if self.backend == "connectorx":
            yield from self._load_rows_connectorx(query, backend_kwargs)
        else:
            yield from self._load_rows(query, backend_kwargs)

    def _load_rows(self, query: SelectAny, backend_kwargs: Optional[dict[str, Any]]) -> TDataItem:
        with self.engine.connect() as conn:
            if self.connect_args:
                for stmt in self.connect_args:
                    conn.execute(text(stmt))
            result = conn.execution_options(
                yield_per=self.chunk_size, max_row_buffer=DEFAULT_CHUNK_SIZE * 2, stream_results=True
            ).execute(query)
            # NOTE: cursor returns not normalized column names! may be quite useful in case of Oracle dialect
            # that normalizes columns
            # columns = [c[0] for c in result.cursor.description]
            columns = list(result.keys())
            for partition in result.partitions(size=self.chunk_size):
                if self.backend == "sqlalchemy":
                    yield [dict(row._mapping) for row in partition]
                elif self.backend == "pandas":
                    from dlt.common.libs.pandas_sql import _wrap_result

                    df = _wrap_result(
                        partition,
                        columns,
                        **{"dtype_backend": "pyarrow", **(backend_kwargs or {})},
                    )
                    yield df
                elif self.backend == "pyarrow":
                    yield row_tuples_to_arrow(partition, self.columns, tz=backend_kwargs.get("tz", "UTC"))

    def _load_rows_connectorx(self, query: SelectAny, backend_kwargs: Optional[dict[str, Any]]) -> Iterator[TDataItem]:
        try:
            import connectorx as cx
        except ImportError:
            raise MissingDependencyException("Connector X table backend", ["connectorx"])

        # default settings
        backend_kwargs = {
            "return_type": "arrow2",
            "protocol": "binary",
            **(backend_kwargs or {}),
        }
        conn = backend_kwargs.pop(
            "conn",
            self.engine.url._replace(drivername=self.engine.url.get_backend_name()).render_as_string(
                hide_password=False
            ),
        )
        try:
            query_str = str(query.compile(self.engine, compile_kwargs={"literal_binds": True}))
        except CompileError as ex:
            raise NotImplementedError(
                f"Query for table {self.table.name} could not be compiled to string to execute it on ConnectorX. If you are on SQLAlchemy 1.4.x the causing exception is due to literals that cannot be rendered, upgrade to 2.x: {str(ex)}"
            ) from ex
        df = cx.read_sql(conn, query_str, **backend_kwargs)
        yield df


def table_rows(
    engine: Engine,
    table: Table,
    chunk_size: int,
    backend: TableBackend,
    incremental: Optional[dlt.sources.incremental[Any]] = None,
    db_incremental_field_last_value: Optional[Any] = None,
    defer_table_reflect: bool = False,
    table_adapter_callback: Optional[Callable[[Table], None]] = None,
    reflection_level: ReflectionLevel = "minimal",
    backend_kwargs: Optional[dict[str, Any]] = None,
    type_adapter_callback: Optional[TTypeAdapter] = None,
    included_columns: Optional[list[str]] = None,
    query_adapter_callback: Optional[TQueryAdapter] = None,
    connect_args: Optional[list[str]] = None,
) -> Iterator[TDataItem]:
    columns: TTableSchemaColumns | None = None
    if defer_table_reflect:
        table = Table(table.name, table.metadata, autoload_with=engine, extend_existing=True)
        default_table_adapter(table, included_columns)
        if table_adapter_callback:
            table_adapter_callback(table)
        columns = table_to_columns(table, reflection_level, type_adapter_callback)

        # set the primary_key in the incremental
        if incremental and incremental.primary_key is None:
            primary_key = get_primary_key(table)
            if primary_key is not None:
                incremental.primary_key = primary_key

        # yield empty record to set hints
        yield dlt.mark.with_hints(
            [],
            dlt.mark.make_hints(
                primary_key=get_primary_key(table),
                columns=columns,
            ),
        )
    else:
        # table was already reflected
        columns = table_to_columns(table, reflection_level, type_adapter_callback)

    yield dlt.mark.materialize_table_schema()

    loader = TableLoader(
        engine,
        backend,
        table,
        columns,
        incremental=incremental,
        db_incremental_field_last_value=db_incremental_field_last_value,
        chunk_size=chunk_size,
        query_adapter_callback=query_adapter_callback,
        connect_args=connect_args,
    )

    yield from loader.load_rows(backend_kwargs)

    engine.dispose()


def engine_from_credentials(
    credentials: Union[ConnectionStringCredentials, Engine, str],
    may_dispose_after_use: bool = False,
    **backend_kwargs: Any,
) -> Engine:
    if isinstance(credentials, Engine):
        return credentials
    if isinstance(credentials, ConnectionStringCredentials):
        credentials = credentials.to_native_representation()
    engine = create_engine(credentials, **backend_kwargs)
    setattr(engine, "may_dispose_after_use", may_dispose_after_use)  # noqa
    return engine


def unwrap_json_connector_x(field: str) -> TDataItem:
    """Creates a transform function to be added with `add_map` that will unwrap JSON columns
    ingested via connectorx. Such columns are additionally quoted and translate SQL NULL to json "null"
    """
    import pyarrow.compute as pc
    import pyarrow as pa

    def _unwrap(table: TDataItem) -> TDataItem:
        col_index = table.column_names.index(field)
        # remove quotes
        column = pc.replace_substring_regex(table[field], '"(.*)"', "\\1")
        # convert json null to null
        column = pc.replace_with_mask(
            column,
            pc.equal(column, "null").combine_chunks(),
            pa.scalar(None, pa.large_string()),
        )
        return table.set_column(col_index, table.schema.field(col_index), column)

    return _unwrap


def _detect_precision_hints_deprecated(value: Optional[bool]) -> None:
    if value is None:
        return

    msg = "`detect_precision_hints` argument is deprecated and will be removed in a future release. "
    if value:
        msg += "Use `reflection_level='full_with_precision'` which has the same effect instead."

    warnings.warn(msg, DeprecationWarning, stacklevel=1)


@configspec
class SqlDatabaseTableConfiguration(BaseConfiguration):
    incremental: Optional[dlt.sources.incremental] = None
    included_columns: Optional[list[str]] = None


@configspec
class SqlTableResourceConfiguration(BaseConfiguration):
    credentials: Optional[Union[ConnectionStringCredentials, Engine, str]] = None
    table: Optional[str] = None
    schema: Optional[str] = None
    incremental: Optional[dlt.sources.incremental] = None
    chunk_size: int = DEFAULT_CHUNK_SIZE
    backend: TableBackend = "sqlalchemy"
    detect_precision_hints: Optional[bool] = None
    defer_table_reflect: Optional[bool] = False
    reflection_level: Optional[ReflectionLevel] = "full"
    included_columns: Optional[list[str]] = None
