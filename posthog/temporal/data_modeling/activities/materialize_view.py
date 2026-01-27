# TODO(andrew): add s3 cleanup on failure
import uuid
import typing
import asyncio
import dataclasses

from django.conf import settings

import pyarrow as pa
import deltalake
import asyncstdlib
import pyarrow.compute as pc
from structlog.contextvars import bind_contextvars
from structlog.types import FilteringBoundLogger
from temporalio import activity

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import ParsingError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_ast_for_printing, print_prepared_ast

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models import Team
from posthog.settings import HOGQL_INCREASED_MAX_EXECUTION_TIME
from posthog.settings.base_variables import TEST
from posthog.sync import database_sync_to_async
from posthog.temporal.common.clickhouse import get_client as get_clickhouse_client
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger

from products.data_modeling.backend.models import Node, NodeType
from products.data_warehouse.backend.models import get_s3_client
from products.data_warehouse.backend.models.data_modeling_job import DataModelingJob
from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_warehouse.backend.s3 import ensure_bucket_exists

LOGGER = get_logger(__name__)

MB_100_IN_BYTES = 100 * 1000 * 1000
CLICKHOUSE_MAX_BLOCK_SIZE_ROWS = 50 * 1000
DELTA_TABLE_RETENTION_HOURS = 24


class EmptyHogQLResponseColumnsError(Exception):
    def __init__(self):
        super().__init__("After running a HogQL query, no columns were returned")


class InvalidNodeTypeException(Exception):
    """Exception raised when attempting to materialize an invalid node type."""

    pass


@dataclasses.dataclass
class MaterializeViewInputs:
    team_id: int
    dag_id: str
    node_id: str
    job_id: str

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
            "dag_id": self.dag_id,
            "node_id": self.node_id,
            "job_id": self.job_id,
        }


@dataclasses.dataclass
class MaterializeViewResult:
    node_id: str
    node_name: str
    row_count: int
    table_uri: str
    file_uris: list[str]
    saved_query_id: str


def _build_model_table_uri(team_id: int, saved_query_id_hex: str, normalized_name: str) -> str:
    return f"{settings.BUCKET_URL}/team_{team_id}_model_{saved_query_id_hex}/modeling/{normalized_name}"


def _get_aws_storage_options() -> dict[str, str]:
    if settings.USE_LOCAL_SETUP:
        ensure_bucket_exists(
            settings.BUCKET_URL,
            settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY,
            settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET,
            settings.OBJECT_STORAGE_ENDPOINT,
        )

    if settings.USE_LOCAL_SETUP or TEST:
        return {
            "aws_access_key_id": settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY,
            "aws_secret_access_key": settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET,
            "region_name": settings.DATAWAREHOUSE_LOCAL_BUCKET_REGION,
            "AWS_DEFAULT_REGION": settings.DATAWAREHOUSE_LOCAL_BUCKET_REGION,
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "AWS_ALLOW_HTTP": "true",
        }

    return {
        "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
    }


def _combine_batches(batches: list[pa.RecordBatch]) -> pa.RecordBatch:
    if len(batches) == 1:
        return batches[0]

    table = pa.Table.from_batches(batches)
    table = table.combine_chunks()
    return table.to_batches(max_chunksize=table.num_rows)[0]


def _transform_date_and_datetimes(batch: pa.RecordBatch, types: list[tuple[str, str]]) -> pa.RecordBatch:
    """Transform date/datetimes from ClickHouse UInt representations back to proper types."""
    new_columns: list[pa.Array] = []
    new_fields: list[pa.Field] = []

    types_to_transform = ["Date", "Date32", "DateTime", "DateTime64"]
    for column_name, type in types:
        field = batch.schema.field(column_name)
        column = batch.column(column_name)

        if not any(t.lower() in type.lower() for t in types_to_transform) or pa.types.is_date(field.type):
            new_columns.append(column)
            new_fields.append(field)
            continue

        if "datetime64" in type.lower() and pa.types.is_timestamp(field.type):
            new_field: pa.Field = field.with_type(pa.timestamp("us", tz="UTC"))
            new_column = pc.cast(column, new_field.type)
        elif "datetime" in type.lower():
            new_field = field.with_type(pa.timestamp("us", tz="UTC"))
            int64_col = pc.cast(column, pa.int64())
            seconds_col = pc.cast(int64_col, pa.timestamp("s"))
            new_column = pc.cast(seconds_col, new_field.type)
        else:
            new_field = field.with_type(pa.date32())
            int32_col = pc.cast(column, pa.int32())
            new_column = pc.cast(int32_col, new_field.type)

        new_fields.append(new_field)
        new_columns.append(new_column)

    new_metadata: dict[str | bytes, str | bytes] | None = (
        typing.cast(dict[str | bytes, str | bytes], dict(batch.schema.metadata)) if batch.schema.metadata else None
    )

    return pa.RecordBatch.from_arrays(new_columns, schema=pa.schema(new_fields, metadata=new_metadata))


def _transform_unsupported_decimals(batch: pa.RecordBatch) -> pa.RecordBatch:
    """Transform high-precision decimal columns to types supported by Delta Lake."""
    schema = batch.schema
    columns_to_cast: dict[str, pa.DataType] = {}

    precision = 38
    scale = 38 - 1

    for field in schema:
        if isinstance(field.type, pa.Decimal128Type | pa.Decimal256Type):
            if field.type.precision > 38:
                original_scale = field.type.scale
                new_scale = min(original_scale, scale)
                columns_to_cast[field.name] = pa.decimal128(precision, new_scale)

    if not columns_to_cast:
        return batch

    new_columns: list[pa.Array] = []
    new_fields: list[pa.Field] = []

    for field in batch.schema:
        col = batch[field.name]
        if field.name in columns_to_cast:
            decimal128_type = columns_to_cast[field.name]
            try:
                cast_col = pc.cast(col, decimal128_type)
                new_fields.append(field.with_type(decimal128_type))
                new_columns.append(cast_col)
            except Exception:
                reduced_decimal_type = pa.decimal128(precision, scale)
                # signals to the type checker that the underlying type is a pa.StringArray
                string_col = typing.cast(pa.StringArray, pc.cast(col, pa.string()))
                truncated = pc.utf8_slice_codeunits(string_col, 0, precision)
                cast_reduced = pc.cast(truncated, reduced_decimal_type)
                new_fields.append(field.with_type(reduced_decimal_type))
                new_columns.append(cast_reduced)
        else:
            new_fields.append(field)
            new_columns.append(col)

    new_metadata: dict[str | bytes, str | bytes] | None = (
        typing.cast(dict[str | bytes, str | bytes], dict(schema.metadata)) if schema.metadata else None
    )

    return pa.RecordBatch.from_arrays(new_columns, schema=pa.schema(new_fields, metadata=new_metadata))


async def get_query_row_count(query: str, team: Team, logger: FilteringBoundLogger) -> int:
    """Get the total row count for a HogQL query."""
    count_query = f"SELECT count() FROM ({query})"

    query_node = parse_select(count_query)

    settings = HogQLGlobalSettings()
    settings.max_execution_time = HOGQL_INCREASED_MAX_EXECUTION_TIME

    context = HogQLContext(
        team=team,
        enable_select_queries=True,
        limit_top_select=False,
    )
    context.output_format = "TabSeparated"
    context.database = await database_sync_to_async(Database.create_for)(team=team, modifiers=context.modifiers)

    prepared_hogql_query = await database_sync_to_async(prepare_ast_for_printing)(
        query_node, context=context, dialect="clickhouse", settings=settings, stack=[]
    )

    if prepared_hogql_query is None:
        raise EmptyHogQLResponseColumnsError()

    printed = await database_sync_to_async(print_prepared_ast)(
        prepared_hogql_query,
        context=context,
        dialect="clickhouse",
        settings=settings,
        stack=[],
    )

    await logger.adebug(f"Running count query: {printed}")

    async with get_clickhouse_client() as client:
        result = await client.read_query(printed, query_parameters=context.values)
        count = int(result.decode("utf-8").strip())
        return count


async def hogql_table(query: str, team: Team, logger: FilteringBoundLogger):
    """Execute a HogQL query and yield batches of results."""
    query_node = parse_select(query)
    if query_node is None:
        raise ParsingError(f"Failed to parse query node from query, parse_select() returned None: query={query}")

    settings = HogQLGlobalSettings()
    settings.max_execution_time = HOGQL_INCREASED_MAX_EXECUTION_TIME

    context = HogQLContext(
        team=team,
        enable_select_queries=True,
        limit_top_select=False,
    )
    context.database = await database_sync_to_async(Database.create_for)(team=team, modifiers=context.modifiers)

    prepared_hogql_query = await database_sync_to_async(prepare_ast_for_printing)(
        query_node, context=context, dialect="clickhouse", settings=settings, stack=[]
    )
    if prepared_hogql_query is None:
        raise EmptyHogQLResponseColumnsError()

    printed = await database_sync_to_async(print_prepared_ast)(
        prepared_hogql_query,
        context=context,
        dialect="clickhouse",
        settings=settings,
        stack=[],
    )

    table_describe_query = f"DESCRIBE TABLE ({printed}) FORMAT TabSeparatedRaw"
    arrow_type_conversion: dict[str, tuple[str, tuple[ast.Constant, ...]]] = {
        "DateTime": ("toTimeZone", (ast.Constant(value="UTC"),)),
        "Nullable(Nothing)": ("toNullableString", ()),
        "FIXED_SIZE_BINARY": ("toString", ()),
        "JSON": ("toString", ()),
        "UUID": ("toString", ()),
        "ENUM": ("toString", ()),
        "IPv4": ("toString", ()),
        "IPv6": ("toString", ()),
    }

    has_type_to_convert = lambda ch_type: any(uat.lower() in ch_type.lower() for uat in arrow_type_conversion)
    get_call_tuple = lambda ch_type: next(
        iter([call_tuple for uat, call_tuple in arrow_type_conversion.items() if uat.lower() in ch_type.lower()])
    )

    query_typings: list[tuple[str, str, tuple[str, tuple[ast.Constant, ...]] | None]] = []
    async with get_clickhouse_client() as client:
        async with client.apost_query(
            query=table_describe_query, query_parameters=context.values, query_id=str(uuid.uuid4())
        ) as ch_response:
            table_describe_response = await ch_response.content.read()
            for line in table_describe_response.decode("utf-8").splitlines():
                column_name, ch_type = line.strip().split("\t")
                if has_type_to_convert(ch_type):
                    query_typings.append((column_name, ch_type, get_call_tuple(ch_type)))
                else:
                    query_typings.append((column_name, ch_type, None))

    if query_typings:
        await logger.adebug("Query has fields that need converting")
        select_fields: list[ast.Expr] = []
        for column_name, ch_type, call_tuple in query_typings:
            if call_tuple is not None:
                await logger.adebug(
                    f"Converting {column_name} of type {ch_type} to be wrapped with {call_tuple[0]}(..)"
                )
                select_fields.append(
                    ast.Alias(
                        expr=ast.Call(name=call_tuple[0], args=[ast.Field(chain=[column_name]), *call_tuple[1]]),
                        alias=column_name,
                    )
                )
            else:
                select_fields.append(ast.Field(chain=[column_name]))
        query_node = ast.SelectQuery(select=select_fields, select_from=ast.JoinExpr(table=query_node))

    context.output_format = "ArrowStream"
    settings.preferred_block_size_bytes = MB_100_IN_BYTES

    arrow_prepared_hogql_query = await database_sync_to_async(prepare_ast_for_printing)(
        query_node, context=context, dialect="clickhouse", stack=[], settings=settings
    )

    if arrow_prepared_hogql_query is None:
        raise EmptyHogQLResponseColumnsError()

    arrow_printed = await database_sync_to_async(print_prepared_ast)(
        arrow_prepared_hogql_query, context=context, dialect="clickhouse", stack=[], settings=settings
    )

    await logger.adebug(f"Running clickhouse query: {arrow_printed}")

    async with get_clickhouse_client(max_block_size=CLICKHOUSE_MAX_BLOCK_SIZE_ROWS) as client:
        batches = []
        batches_size = 0
        async for batch in client.astream_query_as_arrow(arrow_printed, query_parameters=context.values):
            batches_size = batches_size + batch.nbytes
            batches.append(batch)

            if batches_size >= MB_100_IN_BYTES:
                await logger.adebug(f"Yielding {len(batches)} batches for total size of {batches_size / 1000 / 1000}MB")
                yield (
                    _combine_batches(batches),
                    [(column_name, column_type) for column_name, column_type, _ in query_typings],
                )
                batches_size = 0
                batches = []

        if len(batches) > 0:
            await logger.adebug(f"Yielding {len(batches)} batches for total size of {batches_size / 1000 / 1000}MB")
            yield (
                _combine_batches(batches),
                [(column_name, column_type) for column_name, column_type, _ in query_typings],
            )


@database_sync_to_async
def _get_matview_input_objects(
    inputs: MaterializeViewInputs,
) -> tuple[Team, Node, DataWarehouseSavedQuery, DataModelingJob]:
    team = Team.objects.get(id=inputs.team_id)
    node = Node.objects.prefetch_related("saved_query").get(
        id=inputs.node_id, team_id=inputs.team_id, dag_id=inputs.dag_id
    )
    if node.type == NodeType.TABLE:
        raise InvalidNodeTypeException(f"Cannot materialize a TABLE node: {node.name}")
    if node.saved_query is None:
        raise InvalidNodeTypeException(f"Node {node.name} has no saved_query")
    # we explicitly get the saved query to avoid sync_to_async issues later for things like folder_path
    saved_query = (
        DataWarehouseSavedQuery.objects.prefetch_related("team")
        .exclude(deleted=True)
        .get(id=node.saved_query.id, team_id=inputs.team_id)
    )
    job = DataModelingJob.objects.get(id=inputs.job_id, team_id=inputs.team_id)
    return (team, node, saved_query, job)


@activity.defn
async def materialize_view_activity(inputs: MaterializeViewInputs) -> MaterializeViewResult:
    """Materialize a view by executing its query and writing to delta lake."""
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    tag_queries(team_id=inputs.team_id, product=Product.WAREHOUSE, feature=Feature.DATA_MODELING)

    team, node, saved_query, job = await _get_matview_input_objects(inputs)
    await logger.adebug(f"Starting materialization for node {node.name}")

    table_uri = _build_model_table_uri(team.pk, saved_query.id.hex, saved_query.normalized_name)
    await logger.adebug(f"Delta table URI = {table_uri}")

    # delete existing table first to avoid schema conflicts
    s3 = get_s3_client()
    try:
        # non-blocking delete returns control to the event loop so heartbeats continue
        await asyncio.to_thread(s3.delete, table_uri, recursive=True)
        await logger.adebug(f"Table recursively deleted: uri={table_uri}")
    except FileNotFoundError:
        await logger.adebug(f"Skipping deletion because table not found: uri={table_uri}")

    hogql_query = typing.cast(dict, saved_query.query)["query"]
    try:
        rows_expected = await get_query_row_count(hogql_query, team, logger)
        await logger.ainfo(f"Expected rows: {rows_expected}")
        job.rows_expected = rows_expected
        await database_sync_to_async(job.save)()
    except Exception as e:
        await logger.awarning(f"Failed to get expected row count: {str(e)}. Continuing without progress tracking.")
        job.rows_expected = None
        await database_sync_to_async(job.save)()

    row_count = 0
    storage_options = _get_aws_storage_options()
    delta_table: deltalake.DeltaTable | None = None
    async with Heartbeater():
        async for index, res in asyncstdlib.enumerate(hogql_table(hogql_query, team, logger)):
            batch, ch_types = res
            batch = _transform_unsupported_decimals(batch)
            batch = _transform_date_and_datetimes(batch, ch_types)
            # i know this isn't DRY but it was the only way to make type checking shut up
            if index == 0:
                await logger.adebug(
                    f"Writing batch to delta table: index={index} mode=overwrite schema_mode=overwrite batch_row_count={batch.num_rows}"
                )
                await asyncio.to_thread(
                    deltalake.write_deltalake,
                    table_or_uri=table_uri,
                    data=batch,
                    mode="overwrite",
                    schema_mode="overwrite",
                    storage_options=storage_options,
                    engine="rust",
                )
            else:
                await logger.adebug(
                    f"Writing batch to delta table: index={index} mode=append schema_mode=merge batch_row_count={batch.num_rows}"
                )
                await asyncio.to_thread(
                    deltalake.write_deltalake,
                    table_or_uri=table_uri,
                    data=batch,
                    mode="append",
                    schema_mode="merge",
                    storage_options=storage_options,
                    engine="rust",
                )
            if index == 0:
                delta_table = deltalake.DeltaTable(table_uri, storage_options=storage_options)
            row_count = row_count + batch.num_rows
            job.rows_materialized = row_count
            await database_sync_to_async(job.save)()

    await logger.adebug(f"Finished writing to delta table. row_count={row_count}")
    # row count validation warning
    if job.rows_expected is not None:
        if row_count != job.rows_expected:
            await logger.awarning(
                "Row count mismatch after materialization",
                expected=job.rows_expected,
                actual=row_count,
            )

    if delta_table is None:
        delta_table = deltalake.DeltaTable(table_uri=table_uri, storage_options=storage_options)

    await logger.adebug("Compacting delta table")
    delta_table.optimize.compact()
    await logger.adebug("Vacuuming delta table")
    delta_table.vacuum(retention_hours=DELTA_TABLE_RETENTION_HOURS, enforce_retention_duration=False, dry_run=False)

    file_uris = delta_table.file_uris()

    await logger.ainfo(f"Materialized node {node.name} with {row_count} rows")
    return MaterializeViewResult(
        node_id=node.id,
        node_name=node.name,
        row_count=row_count,
        table_uri=table_uri,
        file_uris=file_uris,
        saved_query_id=str(saved_query.id),
    )
