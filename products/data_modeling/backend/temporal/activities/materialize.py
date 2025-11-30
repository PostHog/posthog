import os
import re
import uuid
import typing
import datetime as dt
import dataclasses
from urllib.parse import urlparse

from django.conf import settings

import duckdb
import pyarrow as pa
import deltalake
import asyncstdlib
import pyarrow.compute as pc
import temporalio.activity
from structlog.contextvars import bind_contextvars
from structlog.types import FilteringBoundLogger

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_ast_for_printing, print_prepared_ast

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.ducklake.common import (
    attach_catalog,
    configure_connection,
    escape as ducklake_escape,
    get_config,
    normalize_endpoint,
)
from posthog.models import Team
from posthog.settings import HOGQL_INCREASED_MAX_EXECUTION_TIME
from posthog.settings.base_variables import TEST
from posthog.sync import database_sync_to_async
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger
from posthog.temporal.data_imports.util import prepare_s3_files_for_querying

from products.data_modeling.backend.models import Node, NodeType
from products.data_warehouse.backend.data_load.create_table import create_table_from_saved_query
from products.data_warehouse.backend.models import DataWarehouseTable, get_s3_client
from products.data_warehouse.backend.models.data_modeling_job import DataModelingJob
from products.data_warehouse.backend.s3 import ensure_bucket_exists

# preserve casing since we are already coming from a sql dialect
os.environ["SCHEMA__NAMING"] = "direct"

LOGGER = get_logger(__name__)
MB_50_IN_BYTES = 50 * 1000 * 1000
DUCKLAKE_WORKFLOW_PREFIX = "data_modeling"
_IDENTIFIER_SANITIZE_RE = re.compile(r"[^0-9a-zA-Z]+")


class CHQueryErrorMemoryLimitExceeded(Exception):
    """Exception raised when a ClickHouse query exceeds memory limits."""

    pass


class CannotCoerceColumnException(Exception):
    """Exception raised when column types cannot be coerced."""

    pass


class InvalidNodeTypeException(Exception):
    """Exception raised when attempting to materialize an invalid node type."""

    pass


class NodeNotFoundException(Exception):
    """Exception raised when a node is not found."""

    pass


class EmptyHogQLResponseColumnsError(Exception):
    def __init__(self):
        super().__init__("After running a HogQL query, no columns were returned")


# Activity input/output dataclasses


@dataclasses.dataclass
class CreateJobInputs:
    team_id: int
    node_id: str
    dag_id: str


@dataclasses.dataclass
class MaterializeViewInputs:
    team_id: int
    node_id: str
    dag_id: str
    job_id: str


@dataclasses.dataclass
class MaterializeViewResult:
    row_count: int
    table_uri: str
    file_uris: list[str]
    saved_query_id: str


@dataclasses.dataclass
class CopyToDuckLakeInputs:
    team_id: int
    job_id: str
    node_id: str
    saved_query_id: str
    table_uri: str
    file_uris: list[str]


@dataclasses.dataclass
class FinishMaterializationInputs:
    team_id: int
    node_id: str
    dag_id: str
    job_id: str
    row_count: int
    duration_seconds: float


@dataclasses.dataclass
class FailMaterializationInputs:
    team_id: int
    node_id: str
    dag_id: str
    job_id: str
    error: str


# Helper functions


def _build_model_table_uri(team_id: int, node_id: str, normalized_name: str) -> str:
    return f"{settings.BUCKET_URL}/team_{team_id}_model_{node_id}/modeling/{normalized_name}"


def _get_credentials() -> dict[str, str]:
    if settings.USE_LOCAL_SETUP:
        ensure_bucket_exists(
            settings.BUCKET_URL,
            settings.AIRBYTE_BUCKET_KEY,
            settings.AIRBYTE_BUCKET_SECRET,
            settings.OBJECT_STORAGE_ENDPOINT,
        )

        return {
            "aws_access_key_id": settings.AIRBYTE_BUCKET_KEY,
            "aws_secret_access_key": settings.AIRBYTE_BUCKET_SECRET,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "region_name": settings.AIRBYTE_BUCKET_REGION,
            "AWS_DEFAULT_REGION": settings.AIRBYTE_BUCKET_REGION,
            "AWS_ALLOW_HTTP": "true",
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    if TEST:
        return {
            "aws_access_key_id": settings.AIRBYTE_BUCKET_KEY,
            "aws_secret_access_key": settings.AIRBYTE_BUCKET_SECRET,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "region_name": settings.AIRBYTE_BUCKET_REGION,
            "AWS_DEFAULT_REGION": settings.AIRBYTE_BUCKET_REGION,
            "AWS_ALLOW_HTTP": "true",
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    return {
        "aws_access_key_id": settings.AIRBYTE_BUCKET_KEY,
        "aws_secret_access_key": settings.AIRBYTE_BUCKET_SECRET,
        "region_name": settings.AIRBYTE_BUCKET_REGION,
        "AWS_DEFAULT_REGION": settings.AIRBYTE_BUCKET_REGION,
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
                string_col = pc.cast(col, pa.string())
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
        team_id=team.id,
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

    async with get_client() as client:
        result = await client.read_query(printed, query_parameters=context.values)
        count = int(result.decode("utf-8").strip())
        return count


async def hogql_table(query: str, team: Team, logger: FilteringBoundLogger):
    """Execute a HogQL query and yield batches of results."""
    query_node = parse_select(query)
    assert query_node is not None

    settings = HogQLGlobalSettings()
    settings.max_execution_time = HOGQL_INCREASED_MAX_EXECUTION_TIME

    context = HogQLContext(
        team=team,
        team_id=team.id,
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

    async with get_client() as client:
        query_typings: list[tuple[str, str, tuple[str, tuple[ast.Constant, ...]] | None]] = []
        has_type_to_convert = False

        async with client.apost_query(
            query=table_describe_query, query_parameters=context.values, query_id=str(uuid.uuid4())
        ) as ch_response:
            table_describe_response = await ch_response.content.read()
            for line in table_describe_response.decode("utf-8").splitlines():
                split_arr = line.strip().split("\t")
                column_name = split_arr[0]
                ch_type = split_arr[1]

                if any(uat.lower() in ch_type.lower() for uat in arrow_type_conversion.keys()):
                    call_tuples = [
                        call_tuple
                        for uat, call_tuple in arrow_type_conversion.items()
                        if uat.lower() in ch_type.lower()
                    ]
                    call_tuple = call_tuples[0]
                    has_type_to_convert = True
                    query_typings.append((column_name, ch_type, call_tuple))
                else:
                    query_typings.append((column_name, ch_type, None))

    if has_type_to_convert:
        await logger.adebug("Query has fields that need converting")

        select_fields: list[ast.Expr] = []
        for column_name, ch_type, call_tuple in query_typings:
            if call_tuple:
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
    settings.preferred_block_size_bytes = MB_50_IN_BYTES

    arrow_prepared_hogql_query = await database_sync_to_async(prepare_ast_for_printing)(
        query_node, context=context, dialect="clickhouse", stack=[], settings=settings
    )

    if arrow_prepared_hogql_query is None:
        raise EmptyHogQLResponseColumnsError()

    arrow_printed = await database_sync_to_async(print_prepared_ast)(
        arrow_prepared_hogql_query, context=context, dialect="clickhouse", stack=[], settings=settings
    )

    await logger.adebug(f"Running clickhouse query: {arrow_printed}")

    async with get_client(max_block_size=50_000) as client:
        batches = []
        batches_size = 0
        async for batch in client.astream_query_as_arrow(arrow_printed, query_parameters=context.values):
            batches_size = batches_size + batch.nbytes
            batches.append(batch)

            if batches_size >= MB_50_IN_BYTES:
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


# DuckLake helper functions


def _sanitize_ducklake_identifier(raw: str, *, default_prefix: str) -> str:
    """Normalize identifiers so they are safe for DuckDB."""
    cleaned = _IDENTIFIER_SANITIZE_RE.sub("_", (raw or "").strip()).strip("_").lower()
    if not cleaned:
        cleaned = default_prefix
    if cleaned[0].isdigit():
        cleaned = f"{default_prefix}_{cleaned}"
    return cleaned[:63]


def _build_ducklake_source_glob(file_uris: list[str]) -> str:
    """Derive a glob covering all Parquet files that make up the saved query snapshot."""
    if not file_uris:
        raise ValueError("DuckLake copy requires at least one Parquet file URI")

    base: str | None = None
    directory_segments: list[list[str]] = []
    for uri in file_uris:
        parsed = urlparse(uri)
        scheme = (parsed.scheme or "s3").lower()
        if scheme.startswith("s3"):
            scheme = "s3"
        if not parsed.netloc:
            raise ValueError(f"Unable to determine host/bucket for DuckLake URI '{uri}'")
        current_base = f"{scheme}://{parsed.netloc}"
        if base is None:
            base = current_base
        elif current_base != base:
            raise ValueError("DuckLake copy inputs must share the same base URI")

        stripped_path = parsed.path.lstrip("/")
        directory = stripped_path.rsplit("/", 1)[0] if "/" in stripped_path else ""
        directory_segments.append([segment for segment in directory.split("/") if segment])

    if base is None:
        raise ValueError("Invalid DuckLake file URIs - missing base path")

    common_segments = directory_segments[0][:]
    for segments in directory_segments[1:]:
        new_common: list[str] = []
        for left, right in zip(common_segments, segments):
            if left != right:
                break
            new_common.append(left)
        common_segments = new_common
        if not common_segments:
            break

    if not common_segments and any(directory_segments):
        raise ValueError("DuckLake copy inputs must share a common directory prefix")

    relative_prefix = "/".join(common_segments)
    normalized_base = base.rstrip("/")
    if relative_prefix:
        normalized_base = f"{normalized_base}/{relative_prefix}"

    return f"{normalized_base.rstrip('/')}/**/*.parquet"


def _configure_source_storage(conn: duckdb.DuckDBPyConnection, logger: FilteringBoundLogger) -> None:
    conn.execute("INSTALL httpfs")
    conn.execute("LOAD httpfs")
    conn.execute("INSTALL delta")
    conn.execute("LOAD delta")

    access_key = settings.AIRBYTE_BUCKET_KEY
    secret_key = settings.AIRBYTE_BUCKET_SECRET
    region = getattr(settings, "AIRBYTE_BUCKET_REGION", "")

    endpoint = getattr(settings, "OBJECT_STORAGE_ENDPOINT", "") or ""
    normalized_endpoint = ""
    use_ssl = True
    if endpoint:
        parsed = endpoint.strip()
        if parsed:
            if "://" in parsed:
                normalized_endpoint, use_ssl = normalize_endpoint(parsed)
            else:
                use_ssl = parsed.lower().startswith("https")
                normalized_endpoint = parsed.rstrip("/")

    secret_parts = ["TYPE S3"]
    if access_key:
        secret_parts.append(f"KEY_ID '{ducklake_escape(access_key)}'")
    if secret_key:
        secret_parts.append(f"SECRET '{ducklake_escape(secret_key)}'")
    if region:
        secret_parts.append(f"REGION '{ducklake_escape(region)}'")
    if normalized_endpoint:
        secret_parts.append(f"ENDPOINT '{ducklake_escape(normalized_endpoint)}'")
    secret_parts.append(f"USE_SSL {'true' if use_ssl else 'false'}")
    secret_parts.append("URL_STYLE 'path'")
    conn.execute(f"CREATE OR REPLACE SECRET ducklake_minio ({', '.join(secret_parts)})")


def _ensure_ducklake_bucket_exists(config: dict[str, str]) -> None:
    if not settings.USE_LOCAL_SETUP:
        return

    ensure_bucket_exists(
        f"s3://{config['DUCKLAKE_DATA_BUCKET'].rstrip('/')}",
        config["DUCKLAKE_S3_ACCESS_KEY"],
        config["DUCKLAKE_S3_SECRET_KEY"],
        settings.OBJECT_STORAGE_ENDPOINT,
    )


def _attach_ducklake_catalog(conn: duckdb.DuckDBPyConnection, config: dict[str, str], alias: str) -> None:
    """Attach the DuckLake catalog, swallowing the error if already attached."""
    try:
        attach_catalog(conn, config, alias=alias)
    except duckdb.CatalogException as exc:
        if alias not in str(exc):
            raise


def _update_node_system_properties(
    node: Node,
    *,
    status: str,
    job_id: str,
    rows: int | None = None,
    duration_seconds: float | None = None,
    error: str | None = None,
) -> None:
    """Update the system properties on a node."""
    if "system" not in node.properties:
        node.properties["system"] = {}

    system = node.properties["system"]
    system["last_run_at"] = dt.datetime.now(dt.UTC).isoformat()
    system["last_run_status"] = status
    system["last_run_job_id"] = job_id

    if rows is not None:
        system["last_run_rows"] = rows
    if duration_seconds is not None:
        system["last_run_duration_seconds"] = duration_seconds
    if error is not None:
        system["last_run_error"] = error
    elif "last_run_error" in system:
        system["last_run_error"] = None


# Activities


@temporalio.activity.defn
async def create_materialization_job_activity(inputs: CreateJobInputs) -> str:
    """Create a DataModelingJob record in RUNNING status."""
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    await logger.adebug(f"Creating DataModelingJob for node {inputs.node_id}")

    node = await database_sync_to_async(Node.objects.select_related("saved_query", "team").get)(
        id=inputs.node_id, team_id=inputs.team_id, dag_id=inputs.dag_id
    )

    workflow_id = temporalio.activity.info().workflow_id
    workflow_run_id = temporalio.activity.info().workflow_run_id

    job = await database_sync_to_async(DataModelingJob.objects.create)(
        team_id=inputs.team_id,
        saved_query=node.saved_query,
        status=DataModelingJob.Status.RUNNING,
        workflow_id=workflow_id,
        workflow_run_id=workflow_run_id,
        created_by_id=node.saved_query.created_by_id if node.saved_query else None,
    )

    await logger.ainfo(f"Created DataModelingJob {job.id} for node {inputs.node_id}")
    return str(job.id)


@temporalio.activity.defn
async def materialize_view_activity(inputs: MaterializeViewInputs) -> MaterializeViewResult:
    """Materialize a view by executing its query and writing to delta lake."""
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    tag_queries(team_id=inputs.team_id, product=Product.WAREHOUSE, feature=Feature.DATA_MODELING)

    node = await database_sync_to_async(Node.objects.select_related("saved_query", "team").get)(
        id=inputs.node_id, team_id=inputs.team_id, dag_id=inputs.dag_id
    )

    if node.type == NodeType.TABLE:
        raise InvalidNodeTypeException(f"Cannot materialize a TABLE node: {node.name}")

    if node.saved_query is None:
        raise InvalidNodeTypeException(f"Node {node.name} has no saved_query")

    saved_query = node.saved_query
    team = await database_sync_to_async(Team.objects.get)(id=inputs.team_id)
    job = await database_sync_to_async(DataModelingJob.objects.get)(id=inputs.job_id)

    await logger.adebug(f"Starting materialization for node {node.name}")

    query_columns = saved_query.columns
    if not query_columns:
        query_columns = await database_sync_to_async(saved_query.get_columns)()

    hogql_query = saved_query.query["query"]

    row_count = 0
    table_uri = _build_model_table_uri(team.pk, str(node.id), saved_query.normalized_name)
    storage_options = _get_credentials()

    await logger.adebug(f"Delta table URI = {table_uri}")

    # Delete existing table first to avoid schema conflicts
    s3 = get_s3_client()
    try:
        await logger.adebug(f"Deleting existing delta table at {table_uri}")
        s3.delete(table_uri, recursive=True)
        await logger.adebug("Table deleted")
    except FileNotFoundError:
        await logger.adebug(f"Table at {table_uri} not found - skipping deletion")

    try:
        rows_expected = await get_query_row_count(hogql_query, team, logger)
        await logger.ainfo(f"Expected rows: {rows_expected}")
        job.rows_expected = rows_expected
        await database_sync_to_async(job.save)()
    except Exception as e:
        await logger.awarning(f"Failed to get expected row count: {str(e)}. Continuing without progress tracking.")
        job.rows_expected = None
        await database_sync_to_async(job.save)()

    delta_table: deltalake.DeltaTable | None = None

    async with Heartbeater():
        async for index, res in asyncstdlib.enumerate(hogql_table(hogql_query, team, logger)):
            batch, ch_types = res
            batch = _transform_unsupported_decimals(batch)
            batch = _transform_date_and_datetimes(batch, ch_types)

            if delta_table is None:
                delta_table = deltalake.DeltaTable.create(
                    table_uri=table_uri,
                    schema=batch.schema,
                    storage_options=storage_options,
                )

            mode: typing.Literal["error", "append", "overwrite", "ignore"] = "append"
            schema_mode: typing.Literal["merge", "overwrite"] | None = "merge"
            if index == 0:
                mode = "overwrite"
                schema_mode = "overwrite"

            await logger.adebug(
                f"Writing batch to delta table. index={index}. mode={mode}. batch_row_count={batch.num_rows}"
            )

            deltalake.write_deltalake(
                table_or_uri=delta_table,
                storage_options=storage_options,
                data=batch,
                mode=mode,
                schema_mode=schema_mode,
                engine="rust",
            )

            row_count = row_count + batch.num_rows
            job.rows_materialized = row_count
            await database_sync_to_async(job.save)()

    await logger.adebug(f"Finished writing to delta table. row_count={row_count}")

    if delta_table is None:
        delta_table = deltalake.DeltaTable(table_uri=table_uri, storage_options=storage_options)

    await logger.adebug("Compacting delta table")
    delta_table.optimize.compact()
    await logger.adebug("Vacuuming delta table")
    delta_table.vacuum(retention_hours=24, enforce_retention_duration=False, dry_run=False)

    file_uris = delta_table.file_uris()

    saved_query_table: DataWarehouseTable | None = None
    if saved_query.table_id:
        saved_query_table = await database_sync_to_async(DataWarehouseTable.objects.get)(id=saved_query.table_id)

    await logger.adebug("Copying query files in S3")
    folder_path = prepare_s3_files_for_querying(
        folder_path=saved_query.folder_path,
        table_name=saved_query.normalized_name,
        file_uris=file_uris,
        preserve_table_name_casing=True,
        existing_queryable_folder=saved_query_table.queryable_folder if saved_query_table else None,
        logger=logger,
    )

    saved_query.is_materialized = True
    await database_sync_to_async(saved_query.save)()

    await logger.adebug("Creating DataWarehouseTable model")
    dwh_table = await create_table_from_saved_query(str(job.id), str(saved_query.id), team.pk, folder_path)

    await database_sync_to_async(saved_query.refresh_from_db)()
    saved_query.table_id = dwh_table.id
    await database_sync_to_async(saved_query.save)()

    # Update table row count
    if dwh_table:
        dwh_table.row_count = row_count
        await database_sync_to_async(dwh_table.save)()
        await logger.ainfo(f"Updated row count for table {saved_query.name} to {row_count}")

    await logger.ainfo(f"Materialized node {node.name} with {row_count} rows")

    return MaterializeViewResult(
        row_count=row_count,
        table_uri=table_uri,
        file_uris=file_uris,
        saved_query_id=str(saved_query.id),
    )


@temporalio.activity.defn
def copy_to_ducklake_activity(inputs: CopyToDuckLakeInputs) -> bool:
    """Copy materialized data to DuckLake."""
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind(node_id=inputs.node_id, job_id=inputs.job_id)

    if not inputs.file_uris:
        logger.info("No file URIs to copy to DuckLake - skipping")
        return False

    config = get_config()
    conn = duckdb.connect()
    alias = "ducklake_dev"

    try:
        _configure_source_storage(conn, logger)
        configure_connection(conn, config, install_extension=True)
        _ensure_ducklake_bucket_exists(config)
        _attach_ducklake_catalog(conn, config, alias=alias)

        schema_name = _sanitize_ducklake_identifier(
            f"{DUCKLAKE_WORKFLOW_PREFIX}_team_{inputs.team_id}",
            default_prefix=DUCKLAKE_WORKFLOW_PREFIX,
        )
        table_name = _sanitize_ducklake_identifier(inputs.node_id, default_prefix="model")

        qualified_schema = f"{alias}.{schema_name}"
        qualified_table = f"{qualified_schema}.{table_name}"
        source_glob = _build_ducklake_source_glob(inputs.file_uris)
        escaped_glob = ducklake_escape(source_glob)

        logger.info(
            "Creating DuckLake table from Parquet snapshot",
            ducklake_table=qualified_table,
            source_glob=source_glob,
        )
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {qualified_schema}")
        conn.execute(f"CREATE OR REPLACE TABLE {qualified_table} AS SELECT * FROM read_parquet('{escaped_glob}')")
        logger.info("Successfully materialized DuckLake table", ducklake_table=qualified_table)

        return True
    finally:
        conn.close()


@temporalio.activity.defn
async def finish_materialization_activity(inputs: FinishMaterializationInputs) -> None:
    """Mark materialization as complete and update node properties."""
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    node = await database_sync_to_async(Node.objects.get)(
        id=inputs.node_id, team_id=inputs.team_id, dag_id=inputs.dag_id
    )
    job = await database_sync_to_async(DataModelingJob.objects.get)(id=inputs.job_id)

    # Update job status
    job.status = DataModelingJob.Status.COMPLETED
    job.last_run_at = dt.datetime.now(dt.UTC)
    job.error = None
    await database_sync_to_async(job.save)()

    # Update node system properties
    _update_node_system_properties(
        node,
        status="completed",
        job_id=inputs.job_id,
        rows=inputs.row_count,
        duration_seconds=inputs.duration_seconds,
    )
    await database_sync_to_async(node.save)()

    await logger.ainfo(f"Finished materialization for node {node.name}")


@temporalio.activity.defn
async def fail_materialization_activity(inputs: FailMaterializationInputs) -> None:
    """Mark materialization as failed and update node properties."""
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    node = await database_sync_to_async(Node.objects.get)(
        id=inputs.node_id, team_id=inputs.team_id, dag_id=inputs.dag_id
    )
    job = await database_sync_to_async(DataModelingJob.objects.get)(id=inputs.job_id)

    # Update job status
    job.status = DataModelingJob.Status.FAILED
    job.error = inputs.error
    await database_sync_to_async(job.save)()

    # Update node system properties
    _update_node_system_properties(
        node,
        status="failed",
        job_id=inputs.job_id,
        error=inputs.error,
    )
    await database_sync_to_async(node.save)()

    await logger.aerror(f"Failed materialization for node {node.name}: {inputs.error}")
