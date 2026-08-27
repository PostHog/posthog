import uuid
import typing
import asyncio
import dataclasses

from django.conf import settings

import pyarrow as pa
import deltalake
import pyarrow.compute as pc
import pyarrow.parquet as pq
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
from posthog.hogql.visitor import CloningVisitor

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.exceptions_capture import capture_exception
from posthog.models import Team
from posthog.ph_client import feature_enabled_or_false
from posthog.settings import HOGQL_INCREASED_MAX_EXECUTION_TIME
from posthog.settings.base_variables import TEST
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.clickhouse import get_client as get_clickhouse_client
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger
from posthog.temporal.data_modeling.activities.incremental_write import (
    IncrementalWriteError,
    SchemaDriftError,
    UniqueKeyTracker,
    assert_schema_matches,
    max_of,
    table_exists,
    upsert_batch,
    upsert_stats_fields,
)
from posthog.temporal.data_modeling.activities.utils import bind_data_modeling_log_context

from products.data_modeling.backend.facade.api import (
    IncrementalConfig,
    IncrementalFilterError,
    clear_incremental_state,
    definition_fingerprint,
    get_incremental_config,
    get_incremental_state,
    inject_incremental_filter,
    set_incremental_state,
    window_start,
)
from products.data_modeling.backend.facade.modeling import bounded_resolver_factory_for_view
from products.data_modeling.backend.facade.models import DataModelingJob, DataWarehouseSavedQuery, Node, NodeType
from products.data_quality.backend.facade import api as data_quality_facade
from products.data_quality.backend.facade.contracts import QUALITY_AUDIT_SKIP, QualityAuditMode
from products.data_warehouse.backend.facade.api import ensure_bucket_exists, get_s3_client
from products.endpoints.backend.facade.temporal import prepare_executable_query
from products.warehouse_sources.backend.facade.hooks import saved_query_binding
from products.warehouse_sources.backend.facade.pipelines import CDPProducer
from products.warehouse_sources.backend.facade.temporal import AccountPropertyRowSink, PersonPropertyRowSink

LOGGER = get_logger(__name__)

MB_100_IN_BYTES = 100 * 1000 * 1000

# ClickHouse builds every GLOBAL IN subquery as a temporary table while it plans a query, and
# DESCRIBE plans the query too, so the schema probe scans the source tables just to return column
# types. The probe therefore prints a copy of the query with GLOBAL IN downgraded to plain IN and
# runs with the two settings that would add GLOBAL back pinned off (the cluster profile sets
# distributed_product_mode=global). Joins keep their GLOBAL prefix: the resolver adds it to
# events-to-S3 join chains to work around a ClickHouse bug, not for cost. The materialization query
# itself is printed from the untouched AST.
DESCRIBE_QUERY_SETTINGS = {"distributed_product_mode": "allow", "prefer_global_in_and_join": "0"}

_LOCAL_COMPARE_OPS = {
    ast.CompareOperationOp.GlobalIn: ast.CompareOperationOp.In,
    ast.CompareOperationOp.GlobalNotIn: ast.CompareOperationOp.NotIn,
}


class _DowngradeGlobalIn(CloningVisitor):
    def __init__(self) -> None:
        super().__init__(clear_types=False, clear_locations=False)

    def visit_compare_operation(self, node: ast.CompareOperation) -> ast.CompareOperation:
        cloned = super().visit_compare_operation(node)
        cloned.op = _LOCAL_COMPARE_OPS.get(cloned.op, cloned.op)
        return cloned


def _print_describe_variant(
    prepared_query: ast.SelectQuery | ast.SelectSetQuery, context: HogQLContext, settings: HogQLGlobalSettings
) -> str:
    downgraded = _DowngradeGlobalIn().visit(prepared_query)
    return print_prepared_ast(downgraded, context=context, dialect="clickhouse", settings=settings, stack=[])


CLICKHOUSE_MAX_BLOCK_SIZE_ROWS = 50 * 1000
DELTA_TABLE_RETENTION_HOURS = 24

# The only gate. Incremental is also the only path that writes through deltalite, so turning this
# off falls back to full refresh on delta-rs and takes the engine with it.
INCREMENTAL_FLAG = "data-modeling-incremental-views"

# Above this many files, the per-run compaction is worth its full-table rewrite. Below it, skipping
# keeps an incremental run's cost proportional to the rows it changed rather than the table's size.
INCREMENTAL_COMPACT_FILE_THRESHOLD = 200

# how often the producer/consumer wake from a blocking queue op to re-check the
# stop flag
QUEUE_POLL_SECONDS = 1.0

# Limits concurrent ClickHouse queries per worker. Each worker pod runs a single
# process with a single event loop — all async activities share it, so this
# module-level semaphore gates every activity on the same worker.
MAX_CONCURRENT_CLICKHOUSE_QUERIES = 10
_clickhouse_query_semaphore = asyncio.Semaphore(MAX_CONCURRENT_CLICKHOUSE_QUERIES)


class EmptyHogQLResponseColumnsError(Exception):
    def __init__(self):
        super().__init__("After running a HogQL query, no columns were returned")


def _incremental_enabled(team_id: int) -> bool:
    """Fails closed: a flag-service outage produces a full refresh, which costs money but is
    never wrong."""
    try:
        team = Team.objects.only("organization_id").get(id=team_id)
        return feature_enabled_or_false(
            INCREMENTAL_FLAG,
            str(team_id),
            groups={"organization": str(team.organization_id), "project": str(team_id)},
            group_properties={
                "organization": {"id": str(team.organization_id)},
                "project": {"id": str(team_id)},
            },
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    except Exception:
        LOGGER.warning("Failed to evaluate incremental flag; falling back to full refresh", team_id=team_id)
        return False


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class WritePlan:
    """Whether this run rebuilds the table or updates it, and why. The reason is surfaced on the
    job so an unexpectedly expensive run explains itself."""

    incremental: bool
    reason: str
    since: typing.Any = None
    fingerprint: str | None = None
    config: IncrementalConfig | None = None


@database_sync_to_async_pool
def _resolve_write_plan(saved_query: DataWarehouseSavedQuery, team_id: int) -> WritePlan:
    config = get_incremental_config(saved_query)
    if config is None:
        return WritePlan(incremental=False, reason="not configured for incremental materialization")

    if not _incremental_enabled(team_id):
        return WritePlan(incremental=False, reason="incremental materialization is not enabled")

    fingerprint = definition_fingerprint(typing.cast(dict, saved_query.query), config)
    state = get_incremental_state(saved_query)

    if state.watermark is None:
        return WritePlan(incremental=False, reason="first run", fingerprint=fingerprint, config=config)

    if fingerprint is None or fingerprint != state.definition_fingerprint:
        # The query or its config changed, so existing rows were computed by a definition that no
        # longer applies. Rebuilding is the only way the table still matches the SQL the user sees.
        return WritePlan(incremental=False, reason="definition changed", fingerprint=fingerprint, config=config)

    since = window_start(state, config)
    if since is None:
        return WritePlan(incremental=False, reason="no usable watermark", fingerprint=fingerprint, config=config)

    return WritePlan(
        incremental=True,
        reason="incremental",
        since=since,
        fingerprint=fingerprint,
        config=config,
    )


def _is_s3_permission_denied(error: BaseException) -> bool:
    """True for an S3 access-denied error on our own bucket, from either client this pipeline uses.

    `s3fs`/aiobotocore (used by `CDPProducer._list_files_to_produce`) maps an AccessDenied response
    onto the builtin `PermissionError`. pyarrow's `S3FileSystem` (used by `stage_chunk`'s parquet
    write) doesn't set an errno for it, so the same AWS error surfaces as a plain `OSError` with the
    AWS error code embedded in the message instead.
    """
    if isinstance(error, PermissionError):
        return True
    return isinstance(error, OSError) and "ACCESS_DENIED" in str(error)


class _CDPRowSink:
    """Stages the rows a run wrote so CDP destinations and workflows subscribed to the view can act
    on them.

    Best effort by design: the materialization is the product and the trigger is not, so a staging
    failure never fails the run. A partial stage is worse than none, though — a subscriber would get
    some of the run's rows and silently miss the rest — so the first failure discards everything
    staged and the run produces nothing.
    """

    def __init__(self, producer: CDPProducer, logger: FilteringBoundLogger) -> None:
        self._producer = producer
        self._logger = logger
        self._chunk = 0
        self.enabled = False

    async def prepare(self) -> None:
        """Resolve the gate once, then clear anything a previous attempt of this activity staged."""
        try:
            self.enabled = await self._producer.should_run()
            if self.enabled:
                await self._producer.clear()
        except Exception as e:
            capture_exception(e)
            await self._logger.awarning(f"Could not prepare CDP row staging; skipping it for this run: {e}")
            self.enabled = False

    async def stage(self, batch: pa.RecordBatch) -> None:
        if not self.enabled or batch.num_rows == 0:
            return

        try:
            await self._producer.stage_chunk(self._chunk, batch)
            self._chunk += 1
        except Exception as e:
            # A missing write grant on the cdp_producer/ prefix is the same anticipated
            # provisioning gap `_list_files_to_produce` already tolerates quietly for reads (see its
            # `except PermissionError` branch) — not a bug worth paging on.
            if not _is_s3_permission_denied(e):
                capture_exception(e)
            await self._logger.awarning(f"Failed to stage rows for CDP; discarding this run's staged rows: {e}")
            self.enabled = False
            await self.discard()

    async def discard(self) -> None:
        try:
            await self._producer.clear()
        except Exception as e:
            capture_exception(e)
            await self._logger.awarning(f"Failed to clear staged CDP rows: {e}")


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


@dataclasses.dataclass(frozen=True)
class MaterializeViewResult:
    node_id: str
    node_name: str
    row_count: int
    table_uri: str
    file_uris: list[str]
    saved_query_id: str
    quality_audit: QualityAuditMode = QUALITY_AUDIT_SKIP
    # Whether this run upserted a window rather than rebuilding. Defaulted so old workflow
    # histories decode without it.
    incremental: bool = False
    # Whether this run staged row projections for a person/group-target warehouse property, which is
    # what the workflow gates the person-property child on. Defaulted to the skip value so an old
    # history decodes without it and never fires that child during replay.
    person_property_sync_enabled: bool = False
    # Defaulted so workflow histories recorded before account staging do not start new children on replay.
    account_property_sync_enabled: bool = False
    delta_version: int | None = None
    # Whether this run staged rows for a warehouse-view CDP trigger, so the workflow knows to start
    # the producer job. Defaulted so old workflow histories decode without it.
    should_trigger_cdp_producer: bool = False


def _build_model_table_uri(team_id: int, saved_query_id_hex: str, normalized_name: str) -> str:
    return f"{settings.BUCKET_URL}/team_{team_id}_model_{saved_query_id_hex}/modeling/{normalized_name}"


def get_aws_storage_options() -> dict[str, str]:
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

        # Handle array/list types (e.g., Array(DateTime))
        if pa.types.is_list(field.type):
            if "datetime" in type.lower():
                list_element_type: pa.DataType = pa.timestamp("us", tz="UTC")
                list_type = pa.list_(list_element_type)
                list_field = field.with_type(list_type)
                list_int64 = pc.cast(column, pa.list_(pa.int64()))
                list_timestamp_s = pc.cast(list_int64, pa.list_(pa.timestamp("s")))
                list_column = pc.cast(list_timestamp_s, list_type)
            else:
                list_element_type = pa.date32()
                list_type = pa.list_(list_element_type)
                list_field = field.with_type(list_type)
                list_int32 = pc.cast(column, pa.list_(pa.int32()))
                list_column = pc.cast(list_int32, list_type)

            new_fields.append(list_field)
            new_columns.append(list_column)
            continue

        # Handle scalar types
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


def _force_nullable(batch: pa.RecordBatch) -> pa.RecordBatch:
    """Mark every column nullable so batch schemas don't diverge across delta commits.

    ClickHouse emits non-nullable columns for expressions, constants, concat()/toString(),
    and non-Nullable source columns. When such a query spans more than one batch, the first
    batch's overwrite pins a non-nullable delta schema and the later append routes through
    delta-rs's DataFusion writer to reconcile schemas. DataFusion lowercases identifiers and
    then fails to resolve case-sensitive columns, e.g. "No field named userid. ... Did you
    mean 'userId'?" — breaking any column with uppercase characters. Pinning every column to
    nullable keeps each batch's schema identical to the first overwrite, so the append never
    triggers that path and camelCase column names survive.
    """
    nullable_schema = pa.schema(
        [pa.field(field.name, field.type, nullable=True, metadata=field.metadata) for field in batch.schema],
        metadata=typing.cast("dict[bytes | str, bytes | str] | None", batch.schema.metadata),
    )
    return batch.cast(nullable_schema)


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


async def _write_empty_parquet_for_zero_rows(table_uri: str, schema: pa.Schema, logger: FilteringBoundLogger) -> str:
    """Write a single empty parquet file under ``table_uri`` so a zero-row materialization
    is still queryable.
    """
    buf = pa.BufferOutputStream()
    # write_table() on an empty table emits a 0-row row group, which ClickHouse rejects,
    # so write only the schema with no row groups.
    with pq.ParquetWriter(buf, schema):
        pass
    parquet_bytes = buf.getvalue().to_pybytes()
    file_uri = f"{table_uri}/empty_{uuid.uuid4().hex}.parquet"
    s3 = get_s3_client()

    def _upload() -> None:
        with s3.open(file_uri, "wb") as f:
            f.write(parquet_bytes)

    await asyncio.to_thread(_upload)
    await logger.ainfo(f"Wrote empty parquet for zero-row materialization: uri={file_uri} bytes={len(parquet_bytes)}")
    return file_uri


async def hogql_table(
    query: str,
    team: Team,
    logger: FilteringBoundLogger,
    view_name: str | None = None,
    window: "IncrementalWindow | None" = None,
):
    """Execute a HogQL query and yield batches of results.

    With a ``window``, the query is narrowed to rows at or after its lower bound before anything
    else happens — in particular before the arrow type-conversion wrapper below re-wraps the node,
    so the guard's column reference still resolves against the user's own output.
    """
    if window is not None:
        query_node = inject_incremental_filter(query, incremental_key=window.incremental_key, since=window.since)
    else:
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
    # Userless materialization context; bypass warehouse HogQL access control so the model query
    # can resolve its source tables/views.
    context.database = await database_sync_to_async_pool(Database.create_for)(
        team=team, modifiers=context.modifiers, bypass_warehouse_access_control=True
    )

    factory = bounded_resolver_factory_for_view(view_name)
    prepared_hogql_query = await database_sync_to_async_pool(prepare_ast_for_printing)(
        query_node,
        context=context,
        dialect="clickhouse",
        settings=settings,
        stack=[],
        resolver_factory=factory,
    )
    if prepared_hogql_query is None:
        raise EmptyHogQLResponseColumnsError()

    printed = await database_sync_to_async_pool(_print_describe_variant)(prepared_hogql_query, context, settings)

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

    def _needs_conversion(ch_type: str) -> bool:
        # Skip array types from conversion — they are already properly typed by ClickHouse
        # and attempting to convert them causes errors like:
        # "Illegal type Array(DateTime) of argument of function toTimezone"
        is_array_type = ch_type.lower().startswith("array(")
        if is_array_type:
            return False
        return any(uat.lower() in ch_type.lower() for uat in arrow_type_conversion)

    get_call_tuple = lambda ch_type: next(
        iter([call_tuple for uat, call_tuple in arrow_type_conversion.items() if uat.lower() in ch_type.lower()])
    )

    query_typings: list[tuple[str, str, tuple[str, tuple[ast.Constant, ...]] | None]] = []
    async with _clickhouse_query_semaphore, get_clickhouse_client() as client:
        async with client.apost_query(
            query=table_describe_query,
            query_parameters=context.values,
            query_id=str(uuid.uuid4()),
            settings=DESCRIBE_QUERY_SETTINGS,
        ) as ch_response:
            table_describe_response = await ch_response.content.read()
            for line in table_describe_response.decode("utf-8").splitlines():
                column_name, ch_type = line.strip().split("\t")
                if _needs_conversion(ch_type):
                    query_typings.append((column_name, ch_type, get_call_tuple(ch_type)))
                else:
                    query_typings.append((column_name, ch_type, None))

    has_type_to_convert = any(call_tuple is not None for _, _, call_tuple in query_typings)
    if has_type_to_convert:
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

    # each prepare pass owns its deadline clock, so the DESCRIBE round trip above is not charged
    # to view resolution
    arrow_prepared_hogql_query = await database_sync_to_async_pool(prepare_ast_for_printing)(
        query_node,
        context=context,
        dialect="clickhouse",
        stack=[],
        settings=settings,
        resolver_factory=bounded_resolver_factory_for_view(view_name),
    )

    if arrow_prepared_hogql_query is None:
        raise EmptyHogQLResponseColumnsError()

    arrow_printed = await database_sync_to_async_pool(print_prepared_ast)(
        arrow_prepared_hogql_query, context=context, dialect="clickhouse", stack=[], settings=settings
    )

    # The query goes in a field rather than the message: only the message is copied into the
    # log_entries row users can read, and the compiled query is the saved query's own SQL.
    await logger.adebug("Running clickhouse query", query=arrow_printed)

    async with (
        _clickhouse_query_semaphore,
        get_clickhouse_client(max_block_size=CLICKHOUSE_MAX_BLOCK_SIZE_ROWS) as client,
    ):
        batches = []
        batches_size = 0
        yielded_results = False
        arrow_schema: pa.Schema | None = None
        ch_typings_pairs = [(column_name, column_type) for column_name, column_type, _ in query_typings]

        def capture_arrow_schema(schema: pa.Schema) -> None:
            nonlocal arrow_schema
            arrow_schema = schema

        async for batch in client.astream_query_as_arrow(
            arrow_printed,
            query_parameters=context.values,
            on_schema=capture_arrow_schema,
        ):
            batches_size = batches_size + batch.nbytes
            batches.append(batch)

            if batches_size >= MB_100_IN_BYTES:
                await logger.adebug(f"Yielding {len(batches)} batches for total size of {batches_size / 1000 / 1000}MB")
                yield (_combine_batches(batches), ch_typings_pairs)
                yielded_results = True
                batches_size = 0
                batches = []

        if len(batches) > 0:
            await logger.adebug(f"Yielding {len(batches)} batches for total size of {batches_size / 1000 / 1000}MB")
            yield (_combine_batches(batches), ch_typings_pairs)
            yielded_results = True

        if not yielded_results:
            # zero-row result. yield a single empty batch carrying the query's schema so
            # downstream can still write a delta table (and an empty queryable parquet)
            # instead of leaving the model with no DataWarehouseTable at all.
            await logger.adebug(
                "Query returned zero batches; yielding empty batch with schema for queryable empty table"
            )
            if arrow_schema is None:
                raise EmptyHogQLResponseColumnsError()
            empty_batch = pa.RecordBatch.from_arrays(
                [pa.array([], type=field.type) for field in arrow_schema], schema=arrow_schema
            )
            yield (empty_batch, ch_typings_pairs)


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class IncrementalWindow:
    incremental_key: str
    since: typing.Any


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class MatviewInputObjects:
    team: Team
    node: Node
    saved_query: DataWarehouseSavedQuery
    job: DataModelingJob


@database_sync_to_async_pool
def _get_matview_input_objects(
    inputs: MaterializeViewInputs,
) -> MatviewInputObjects:
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
    if saved_query.origin == DataWarehouseSavedQuery.Origin.ENDPOINT:
        prepare_executable_query(saved_query)

    job = DataModelingJob.objects.get(id=inputs.job_id, team_id=inputs.team_id)
    return MatviewInputObjects(team=team, node=node, saved_query=saved_query, job=job)


async def _build_person_property_sink(
    objects: MatviewInputObjects, job_id: str, logger: FilteringBoundLogger, *, incremental: bool
) -> PersonPropertyRowSink | None:
    """A sink for this view, or None when no warehouse property reads it.

    The gate is one query behind ``should_run()``, so a view nobody maps pays that and nothing else.
    A failure to resolve it must not fail the materialization, which is the run that matters.
    """
    sink = PersonPropertyRowSink(
        team_id=objects.team.pk,
        binding=saved_query_binding(objects.saved_query.id),
        job_id=job_id,
        logger=logger,
        is_incremental=incremental,
    )
    try:
        return sink if await sink.should_run() else None
    except Exception as e:
        await logger.awarning(f"Could not resolve person-property staging for this view: {e}")
        capture_exception(e)
        return None


async def _account_property_sync_enabled(
    objects: MatviewInputObjects, job_id: str, logger: FilteringBoundLogger
) -> bool:
    sink = AccountPropertyRowSink(
        team_id=objects.team.pk,
        binding=saved_query_binding(objects.saved_query.id),
        job_id=job_id,
        logger=logger,
    )
    try:
        return await sink.should_run()
    except Exception as error:
        await logger.awarning(f"Could not resolve account-property staging for this view: {error}")
        capture_exception(error)
        return False


async def _clear_person_property_staging(sink: PersonPropertyRowSink, logger: FilteringBoundLogger) -> None:
    """Clear stale staged rows at run start. Never raises, for the same reason staging doesn't."""
    try:
        await sink.clear()
    except Exception as e:
        await logger.awarning(f"Could not clear stale person-property staging: {e}")
        capture_exception(e)


async def _stage_person_property_batch(
    sink: PersonPropertyRowSink | None, batch_index: int, batch: pa.RecordBatch, *, fatal: bool
) -> None:
    """Stage one written batch's projected columns, if a warehouse property reads this view.

    Staged from the transformed batch, so the values a person property gets are the ones the Delta
    table gets.

    ``fatal`` follows the write path. A full rebuild re-stages every row on its next run, so there a
    staging failure only costs that run's updates and is swallowed (``fatal=False``). An incremental
    run stages only its own window and then advances the watermark past it, so a swallowed failure
    would move the watermark past rows that never reached staging, which no later incremental run
    re-stages until they change again. The incremental path therefore raises (``fatal=True``) to fail
    the run before the watermark is recorded — matching the import pipeline's sink contract — so
    Temporal retries the whole window.
    """
    if sink is None:
        return
    try:
        await sink.stage_chunk(batch_index, pa.Table.from_batches([batch]))
    except Exception as e:
        await sink.logger.awarning(f"Failed to stage person-property batch {batch_index}: {e}")
        if fatal:
            raise
        capture_exception(e)


async def _materialize_fully(
    objects: MatviewInputObjects,
    plan: WritePlan,
    hogql_query: str,
    table_uri: str,
    storage_options: dict[str, str],
    logger: FilteringBoundLogger,
    cdp_sink: "_CDPRowSink",
    person_property_sink: PersonPropertyRowSink | None = None,
) -> tuple[int, list[str]]:
    """Rebuild the whole table from the query. The only path that creates a Delta table, and the
    fallback for every case the incremental path cannot serve."""
    # delete existing table first to avoid schema conflicts
    s3 = get_s3_client()
    try:
        # non-blocking delete returns control to the event loop so heartbeats continue
        await asyncio.to_thread(s3.delete, table_uri, recursive=True)
        await logger.adebug(f"Table recursively deleted: uri={table_uri}")
    except FileNotFoundError:
        await logger.adebug(f"Skipping deletion because table not found: uri={table_uri}")

    row_count = 0
    delta_table: deltalake.DeltaTable | None = None
    # cache the schema of the first batch so we can synthesize an empty parquet for
    # zero-row results without going through delta-rs (whose Schema is arro3, not
    # pyarrow).
    pa_schema: pa.Schema | None = None
    watermark: typing.Any = None
    # The declared unique key is enforced while seeding too: a table born with null or duplicate
    # keys would break every later upsert's contract, silently.
    tracker = UniqueKeyTracker(plan.config.unique_key) if plan.config is not None else None

    # write each batch as its own delta commit, imitating the data_imports pipeline
    # (DeltaWriter.write): the first batch overwrites — creating the
    # table from the exact arrow schema, which pins column case like `personId` — and
    # later batches append with schema_mode="merge". this keeps peak memory at ~one
    # batch (hogql_table yields ~100MB combined batches) and, because each write is a
    # brief to_thread released between batches, never pins a worker thread for the whole
    # read — which is what starved the shared executor that heartbeats/db/logging use.
    batch_index = 0
    async for batch, ch_types in hogql_table(hogql_query, objects.team, logger):
        batch = _transform_unsupported_decimals(batch)
        batch = _transform_date_and_datetimes(batch, ch_types)
        batch = _force_nullable(batch)
        if tracker is not None:
            await asyncio.to_thread(tracker.check, batch)
        await _stage_person_property_batch(person_property_sink, batch_index, batch, fatal=False)
        batch_index += 1
        if delta_table is None:
            pa_schema = batch.schema
            await asyncio.to_thread(
                deltalake.write_deltalake,
                table_or_uri=table_uri,
                data=batch,
                mode="overwrite",
                schema_mode="overwrite",
                storage_options=storage_options,
            )
            delta_table = deltalake.DeltaTable(table_uri, storage_options=storage_options)
        else:
            await asyncio.to_thread(
                deltalake.write_deltalake,
                table_or_uri=delta_table,
                data=batch,
                mode="append",
                schema_mode="merge",
                storage_options=storage_options,
            )
        # Staged only once the batch is committed: a run that announces rows it then fails to write
        # cannot take the announcement back.
        await cdp_sink.stage(batch)
        if plan.config is not None and plan.config.incremental_key in batch.schema.names:
            watermark = max_of(batch, plan.config.incremental_key, watermark)
        row_count = row_count + batch.num_rows
        objects.job.rows_materialized = row_count
        await database_sync_to_async_pool(objects.job.save)()

    await logger.ainfo(f"Finished writing to delta table. row_count={row_count}")
    file_uris: list[str] = []
    if delta_table is not None:
        await logger.ainfo("Compacting delta table")
        await asyncio.to_thread(delta_table.optimize.compact)
        await _vacuum(delta_table, logger)
        file_uris = delta_table.file_uris()
        if not file_uris and row_count == 0 and pa_schema is not None:
            # delta-rs writes no parquet for an empty batch. emit one so the
            # queryable folder has a file with a schema attached that's queryable
            empty_parquet_uri = await _write_empty_parquet_for_zero_rows(table_uri, pa_schema, logger)
            file_uris = [empty_parquet_uri]

    # Recording the watermark here is what lets the *next* run go incremental. A rebuild that
    # can't produce one (no config, or the key missing from the output) simply leaves the query
    # on the full-refresh path.
    if plan.config is not None and plan.fingerprint is not None and watermark is not None:
        await database_sync_to_async_pool(set_incremental_state)(
            objects.saved_query, watermark=watermark, fingerprint=plan.fingerprint, mode="full_refresh"
        )
    return row_count, file_uris


async def _materialize_incrementally(
    objects: MatviewInputObjects,
    plan: WritePlan,
    hogql_query: str,
    table_uri: str,
    storage_options: dict[str, str],
    logger: FilteringBoundLogger,
    cdp_sink: "_CDPRowSink",
    person_property_sink: PersonPropertyRowSink | None = None,
) -> tuple[int, list[str]]:
    """Upsert only the rows at or after the watermark into the existing table.

    The watermark is saved after the last upsert but before the queryable publish. That is only
    safe because ``prepare_s3_files_for_querying`` re-copies the whole table's ``file_uris()`` on
    every run: if the publish dies, the next run's publish still picks up these rows. Changing the
    publish to copy incrementally would break that, so the two decisions are linked.
    """
    config = plan.config
    assert config is not None  # _resolve_write_plan only sets incremental with a config

    delta_table = deltalake.DeltaTable(table_uri, storage_options=storage_options)
    # Wrapped in pa.schema() because delta-rs hands back an arro3 schema, whose DataType does not
    # compare equal to pyarrow's. arro3 exposes the Arrow PyCapsule interface, which pa.schema()
    # consumes at runtime even though its stubs don't advertise it.
    target_schema = pa.schema(typing.cast(typing.Any, delta_table.schema().to_arrow()))
    window = IncrementalWindow(incremental_key=config.incremental_key, since=plan.since)

    row_count = 0
    watermark: typing.Any = None
    tracker = UniqueKeyTracker(config.unique_key)
    # Staged per attempt, never cleared: a retry resumes past the watermark the failed attempt
    # already saved, so its staged rows are that window's only record (see PersonPropertyRowSink).
    batch_index = 0

    try:
        async for batch, ch_types in hogql_table(hogql_query, objects.team, logger, window=window):
            batch = _transform_unsupported_decimals(batch)
            batch = _transform_date_and_datetimes(batch, ch_types)
            batch = _force_nullable(batch)

            if batch.num_rows == 0:
                # A quiet window is normal. Nothing to upsert, and no watermark to advance.
                continue

            assert_schema_matches(batch, target_schema)
            # Checked before the upsert so a duplicate split across batches fails the run instead
            # of the later batch silently replacing the earlier one.
            await asyncio.to_thread(tracker.check, batch)
            await _stage_person_property_batch(person_property_sink, batch_index, batch, fatal=True)
            batch_index += 1

            stats = await asyncio.to_thread(
                upsert_batch,
                table_uri,
                storage_options,
                batch,
                config.unique_key,
                commit_metadata={"posthog_job_id": str(objects.job.id)},
            )
            await logger.ainfo("Upserted batch into delta table", **upsert_stats_fields(stats))
            await cdp_sink.stage(batch)

            watermark = max_of(batch, config.incremental_key, watermark)
            row_count = row_count + batch.num_rows
            objects.job.rows_materialized = row_count
            await database_sync_to_async_pool(objects.job.save)()
    except (IncrementalWriteError, IncrementalFilterError) as err:
        # Every one of these means the table and the query have diverged in a way an upsert can't
        # reconcile. Dropping the watermark makes the retry rebuild instead of writing rows that
        # would be wrong, so the failure costs a full refresh rather than silent corruption.
        await database_sync_to_async_pool(clear_incremental_state)(objects.saved_query)
        if isinstance(err, SchemaDriftError):
            await logger.awarning(f"Rebuilding after schema drift: {err}")
        raise

    if watermark is not None:
        await database_sync_to_async_pool(set_incremental_state)(
            objects.saved_query, watermark=watermark, fingerprint=plan.fingerprint, mode="incremental"
        )

    # Reopened because deltalite commits through its own handle, leaving this one pinned to the
    # snapshot from before the upserts. Maintaining or listing files off the stale handle would
    # publish the pre-run file set and lose everything this run wrote.
    delta_table = deltalake.DeltaTable(table_uri, storage_options=storage_options)

    file_uris = delta_table.file_uris()
    if len(file_uris) > INCREMENTAL_COMPACT_FILE_THRESHOLD:
        await logger.ainfo(f"Compacting delta table ({len(file_uris)} files)")
        await asyncio.to_thread(delta_table.optimize.compact)
    await _vacuum(delta_table, logger)

    # Re-listed after maintenance: compaction rewrites files, so the pre-compaction list would
    # name parquet the publish can no longer copy.
    return row_count, delta_table.file_uris()


async def _vacuum(delta_table: deltalake.DeltaTable, logger: FilteringBoundLogger) -> None:
    """Full vacuum, not the delta-rs 1.x default of lite.

    A killed upsert leaves parquet that was never committed, so it carries no tombstone, and lite
    vacuum only reclaims tombstoned files. Those orphans would otherwise accumulate forever and
    inflate every later publish copy and folder-size read.
    """
    await logger.ainfo("Vacuuming delta table")
    await asyncio.to_thread(
        delta_table.vacuum,
        retention_hours=DELTA_TABLE_RETENTION_HOURS,
        enforce_retention_duration=False,
        dry_run=False,
        full=True,
    )


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class ClearCDPStagingInputs:
    team_id: int
    saved_query_id: str
    job_id: str

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
            "saved_query_id": self.saved_query_id,
            "job_id": self.job_id,
        }


@activity.defn
async def clear_cdp_staging_activity(inputs: ClearCDPStagingInputs) -> None:
    """Drop the rows a run staged for CDP but never published.

    The staging prefix is keyed on the job, so the next run's own clear never reaches this one's.
    A run that ends without producing has to clean up after itself or the objects stay forever.
    """
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    producer = CDPProducer.for_view(
        team_id=inputs.team_id,
        saved_query_id=inputs.saved_query_id,
        job_id=inputs.job_id,
        logger=logger,
    )
    await producer.clear()


@activity.defn
async def materialize_view_activity(inputs: MaterializeViewInputs) -> MaterializeViewResult:
    """Materialize a view by executing its query and writing to delta lake."""
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    tag_queries(team_id=inputs.team_id, product=Product.WAREHOUSE, feature=Feature.DATA_MODELING)

    objects = await _get_matview_input_objects(inputs)
    bind_data_modeling_log_context(inputs.team_id, objects.saved_query.id)
    await logger.ainfo(f"Starting materialization for node {objects.node.name}")

    table_uri = _build_model_table_uri(objects.team.pk, objects.saved_query.id.hex, objects.saved_query.normalized_name)
    await logger.adebug(f"Delta table URI = {table_uri}")

    storage_options = get_aws_storage_options()
    plan = await _resolve_write_plan(objects.saved_query, inputs.team_id)
    if plan.incremental and not await asyncio.to_thread(table_exists, table_uri, storage_options):
        # deltalite can only open a table, never create one, so a missing table has to rebuild.
        plan = dataclasses.replace(plan, incremental=False, reason="table missing")
    await logger.ainfo(f"Materializing node {objects.node.name}: {plan.reason}")

    # Recorded on the job so the runs UI can tell a rebuild's row count (the whole table) apart
    # from an incremental run's (only the rows synced in its window).
    objects.job.run_mode = (
        DataModelingJob.RunMode.INCREMENTAL if plan.incremental else DataModelingJob.RunMode.FULL_REFRESH
    )
    await database_sync_to_async_pool(objects.job.save)()

    person_property_sink = await _build_person_property_sink(
        objects, inputs.job_id, logger, incremental=plan.incremental
    )
    if person_property_sink is not None:
        # Cleared once at run start, like the import pipeline's sinks. The sink itself decides what to
        # drop: a rebuild re-reads every row so a dead attempt's files are safe to remove, while an
        # incremental retry resumes past its saved watermark and must keep them. Either way this is
        # what sweeps long-abandoned sibling job prefixes.
        await _clear_person_property_staging(person_property_sink, logger)

    cdp_sink = _CDPRowSink(
        CDPProducer.for_view(
            team_id=inputs.team_id,
            saved_query_id=str(objects.saved_query.id),
            job_id=str(objects.job.id),
            logger=logger,
        ),
        logger,
    )
    await cdp_sink.prepare()

    # Staged rows are only safe to leave in place once MaterializeViewResult is actually returned:
    # that is the one signal the workflow's own cleanup keys off. Anything that leaves this block
    # early - a write failure, a cancellation mid-write, or a cancellation during the logging,
    # heartbeat teardown, or quality-audit lookup that follow it - must discard what was staged
    # itself, because the workflow will never see a result to clean up after. CancelledError is a
    # BaseException, not an Exception, so it has to be named explicitly to be caught here at all.
    # cdp_sink.discard() only clears a non-empty prefix, so catching it at both this level and the
    # inner write-loop level below is safe to double up on.
    published = False
    try:
        async with Heartbeater():
            hogql_query = typing.cast(dict, objects.saved_query.query)["query"]

            try:
                if plan.incremental:
                    row_count, file_uris = await _materialize_incrementally(
                        objects,
                        plan,
                        hogql_query,
                        table_uri,
                        storage_options,
                        logger,
                        cdp_sink,
                        person_property_sink,
                    )
                else:
                    row_count, file_uris = await _materialize_fully(
                        objects,
                        plan,
                        hogql_query,
                        table_uri,
                        storage_options,
                        logger,
                        cdp_sink,
                        person_property_sink,
                    )
            except (Exception, asyncio.CancelledError):
                # A retry stages from scratch and a terminal failure produces nothing, so whatever
                # this attempt wrote is only ever waste.
                await cdp_sink.discard()
                raise

            await logger.ainfo(f"Materialized node {objects.node.name} with {row_count} rows")
        quality_audit = await database_sync_to_async_pool(data_quality_facade.quality_audit_mode)(
            inputs.team_id, str(objects.saved_query.id)
        )
        account_property_sync_enabled = await _account_property_sync_enabled(objects, inputs.job_id, logger)
        delta_version: int | None = None
        if account_property_sync_enabled:
            try:
                delta_table = await asyncio.to_thread(
                    deltalake.DeltaTable,
                    table_uri,
                    storage_options=storage_options,
                )
                delta_version = delta_table.version()
            except Exception as error:
                await logger.awarning(f"Could not resolve account-property Delta snapshot: {error}")
                capture_exception(error)
                account_property_sync_enabled = False
        result = MaterializeViewResult(
            node_id=objects.node.id,
            node_name=objects.node.name,
            row_count=row_count,
            table_uri=table_uri,
            file_uris=file_uris,
            saved_query_id=str(objects.saved_query.id),
            quality_audit=quality_audit,
            incremental=plan.incremental,
            person_property_sync_enabled=person_property_sink is not None,
            account_property_sync_enabled=account_property_sync_enabled,
            delta_version=delta_version,
            should_trigger_cdp_producer=cdp_sink.enabled,
        )
        published = True
        return result
    except (Exception, asyncio.CancelledError):
        if not published:
            await cdp_sink.discard()
        raise
