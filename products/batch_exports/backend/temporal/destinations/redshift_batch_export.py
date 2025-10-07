import io
import json
import typing
import asyncio
import datetime as dt
import contextlib
import dataclasses
import collections.abc

from django.conf import settings

import psycopg
import pyarrow as pa
from psycopg import sql
from structlog.contextvars import bind_contextvars
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.models import BatchExportRun
from posthog.batch_exports.service import (
    BatchExportField,
    BatchExportModel,
    BatchExportSchema,
    RedshiftBatchExportInputs,
)
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger, get_write_only_logger

from products.batch_exports.backend.temporal.batch_exports import (
    FinishBatchExportRunInputs,
    OverBillingLimitError,
    StartBatchExportRunInputs,
    default_fields,
    execute_batch_export_insert_activity,
    get_data_interval,
    start_batch_export_run,
)
from products.batch_exports.backend.temporal.destinations.postgres_batch_export import (
    Fields,
    PostgresInsertInputs,
    PostgreSQLClient,
    PostgreSQLField,
)
from products.batch_exports.backend.temporal.heartbeat import (
    BatchExportRangeHeartbeatDetails,
    DateRange,
    should_resume_from_activity_heartbeat,
)
from products.batch_exports.backend.temporal.pipeline.consumer import (
    Consumer as ConsumerFromStage,
    run_consumer_from_stage,
)
from products.batch_exports.backend.temporal.pipeline.entrypoint import execute_batch_export_using_internal_stage
from products.batch_exports.backend.temporal.pipeline.producer import Producer as ProducerFromInternalStage
from products.batch_exports.backend.temporal.pipeline.transformer import RedshiftQueryStreamTransformer
from products.batch_exports.backend.temporal.pipeline.types import BatchExportResult
from products.batch_exports.backend.temporal.record_batch_model import resolve_batch_exports_model
from products.batch_exports.backend.temporal.spmc import (
    Consumer,
    Producer,
    RecordBatchQueue,
    run_consumer,
    wait_for_schema_or_producer,
)
from products.batch_exports.backend.temporal.temporary_file import BatchExportTemporaryFile, WriterFormat
from products.batch_exports.backend.temporal.utils import (
    JsonType,
    handle_non_retryable_errors,
    set_status_to_running_task,
)

LOGGER = get_write_only_logger(__name__)
EXTERNAL_LOGGER = get_logger()


NON_RETRYABLE_ERROR_TYPES = (
    # Raised on errors that are related to database operation.
    # For example: unexpected disconnect, database or other object not found.
    "OperationalError",
    # The schema name provided is invalid (usually because it doesn't exist).
    "InvalidSchemaName",
    # Missing permissions to, e.g., insert into table.
    "InsufficientPrivilege",
    # A column, usually properties, exceeds the limit for a VARCHAR field,
    # usually the max of 65535 bytes
    "StringDataRightTruncation",
    # Raised by our PostgreSQL client when failing to connect after several attempts.
    "PostgreSQLConnectionError",
    # Column missing in Redshift, likely the schema was altered.
    "UndefinedColumn",
    # Raised by our PostgreSQL client when a given feature is not supported.
    # This can also happen when merging tables with a different number of columns:
    # "Target relation and source relation must have the same number of columns"
    "FeatureNotSupported",
    # There is a mismatch between the schema of the table and our data. This
    # usually means the table was created by the user, as we resolve types the
    # same way every time.
    "DatatypeMismatch",
)


class RedshiftClient(PostgreSQLClient):
    @contextlib.asynccontextmanager
    async def connect(self) -> collections.abc.AsyncIterator[typing.Self]:
        """Manage a Redshift connection.

        This just yields a Postgres connection but we adjust a couple of things required for
        psycopg to work with Redshift:
        1. Set UNICODE encoding to utf-8 as Redshift reports back UNICODE.
        2. Set prepare_threshold to None on the connection as psycopg attempts to run DEALLOCATE ALL otherwise
            which is not supported on Redshift.
        """
        psycopg._encodings._py_codecs["UNICODE"] = "utf-8"
        psycopg._encodings.py_codecs.update((k.encode(), v) for k, v in psycopg._encodings._py_codecs.items())

        async with super().connect():
            self.connection.prepare_threshold = None
            yield self

    @contextlib.asynccontextmanager
    async def async_client_cursor(self) -> collections.abc.AsyncIterator[psycopg.AsyncClientCursor]:
        """Yield a AsyncClientCursor from a psycopg.AsyncConnection.

        Keeps track of the current cursor_factory to set it after we are done.
        """
        current_factory = self.connection.cursor_factory
        self.connection.cursor_factory = psycopg.AsyncClientCursor

        try:
            async with self.connection.cursor() as cursor:
                # Not a fan of typing.cast, but we know this is an psycopg.AsyncClientCursor
                # as we have just set cursor_factory.
                cursor = typing.cast(psycopg.AsyncClientCursor, cursor)
                yield cursor
        finally:
            self.connection.cursor_factory = current_factory

    async def amerge_mutable_tables(
        self,
        final_table_name: str,
        stage_table_name: str,
        schema: str,
        merge_key: Fields,
        update_key: Fields,
        update_when_matched: Fields = (),
    ) -> None:
        """Merge two tables in Redshift."""
        if schema:
            final_table_identifier = sql.Identifier(schema, final_table_name)
            stage_table_identifier = sql.Identifier(schema, stage_table_name)

        else:
            final_table_identifier = sql.Identifier(final_table_name)
            stage_table_identifier = sql.Identifier(stage_table_name)

        and_separator = sql.SQL("AND")
        merge_condition = and_separator.join(
            sql.SQL("{final_field} = {stage_field}").format(
                final_field=sql.Identifier(schema, final_table_name, field[0]),
                stage_field=sql.Identifier("stage", field[0]),
            )
            for field in merge_key
        )

        # Redshift doesn't support adding a condition on the merge, so we have
        # to first delete any rows in stage that match those in final, where
        # stage also has a higher version. Otherwise we risk merging adding old
        # versions back.
        delete_condition = and_separator.join(
            sql.SQL("{final_field} = {stage_field}").format(
                final_field=sql.Identifier("final", field[0]),
                stage_field=sql.Identifier(schema, stage_table_name, field[0]),
            )
            for field in merge_key
        )

        or_separator = sql.SQL(" OR ")
        delete_extra_conditions = or_separator.join(
            sql.SQL("{stage_field} < {final_field}").format(
                final_field=sql.Identifier("final", field[0]),
                stage_field=sql.Identifier(schema, stage_table_name, field[0]),
            )
            for field in update_key
        )

        delete_query = sql.SQL(
            """\
        DELETE FROM {stage_table}
        USING {final_table} AS final
        WHERE {merge_condition}
        AND ({delete_extra_conditions})
        """
        ).format(
            final_table=final_table_identifier,
            stage_table=stage_table_identifier,
            merge_condition=delete_condition,
            delete_extra_conditions=delete_extra_conditions,
        )

        merge_query = sql.SQL(
            """\
        MERGE INTO {final_table}
        USING {stage_table} AS stage
        ON {merge_condition}
        REMOVE DUPLICATES
        """
        ).format(
            final_table=final_table_identifier,
            stage_table=stage_table_identifier,
            merge_condition=merge_condition,
        )

        async with self.connection.transaction():
            async with self.connection.cursor() as cursor:
                await cursor.execute(delete_query)
                await cursor.execute(merge_query)


def redshift_default_fields() -> list[BatchExportField]:
    batch_export_fields = default_fields()
    batch_export_fields.append(
        {
            "expression": "nullIf(JSONExtractString(properties, '$ip'), '')",
            "alias": "ip",
        }
    )
    # Fields kept or removed for backwards compatibility with legacy apps schema.
    batch_export_fields.append({"expression": "''", "alias": "elements"})
    batch_export_fields.append({"expression": "''", "alias": "site_url"})
    batch_export_fields.pop(batch_export_fields.index({"expression": "created_at", "alias": "created_at"}))
    # Team ID is (for historical reasons) an INTEGER (4 bytes) in PostgreSQL, but in ClickHouse is stored as Int64.
    # We can't encode it as an Int64, as this includes 4 extra bytes, and PostgreSQL will reject the data with a
    # 'incorrect binary data format' error on the column, so we cast it to Int32.
    team_id_field = batch_export_fields.pop(
        batch_export_fields.index(BatchExportField(expression="team_id", alias="team_id"))
    )
    team_id_field["expression"] = "toInt32(team_id)"
    batch_export_fields.append(team_id_field)
    return batch_export_fields


def get_redshift_fields_from_record_schema(
    record_schema: pa.Schema, known_super_columns: list[str], use_super: bool
) -> Fields:
    """Generate a list of supported Redshift fields from PyArrow schema.

    This function is used to map custom schemas to Redshift-supported types. Some loss of precision is
    expected.
    """
    pg_schema: list[PostgreSQLField] = []

    for name in record_schema.names:
        if name == "_inserted_at":
            continue

        pa_field = record_schema.field(name)

        if pa.types.is_string(pa_field.type) or isinstance(pa_field.type, JsonType):
            if pa_field.name in known_super_columns and use_super is True:
                pg_type = "SUPER"
            else:
                # Redshift treats `TEXT` as `VARCHAR(256)`, not as unlimited length like PostgreSQL.
                # So, instead of `TEXT` we use the largest possible `VARCHAR`.
                # See: https://docs.aws.amazon.com/redshift/latest/dg/r_Character_types.html
                pg_type = "VARCHAR(65535)"

        elif pa.types.is_signed_integer(pa_field.type) or pa.types.is_unsigned_integer(pa_field.type):
            if pa.types.is_uint64(pa_field.type) or pa.types.is_int64(pa_field.type):
                pg_type = "BIGINT"
            else:
                pg_type = "INTEGER"

        elif pa.types.is_floating(pa_field.type):
            if pa.types.is_float64(pa_field.type):
                pg_type = "DOUBLE PRECISION"
            else:
                pg_type = "REAL"

        elif pa.types.is_boolean(pa_field.type):
            pg_type = "BOOLEAN"

        elif pa.types.is_timestamp(pa_field.type):
            if pa_field.type.tz is not None:
                pg_type = "TIMESTAMPTZ"
            else:
                pg_type = "TIMESTAMP"

        elif pa.types.is_list(pa_field.type) and pa.types.is_string(pa_field.type.value_type):
            pg_type = "SUPER"

        else:
            raise TypeError(f"Unsupported type in field '{name}': '{pa_field.type}'")

        pg_schema.append((name, pg_type))

    return pg_schema


@dataclasses.dataclass
class RedshiftHeartbeatDetails(BatchExportRangeHeartbeatDetails):
    """The Redshift batch export details included in every heartbeat."""

    pass


class RedshiftConsumer(Consumer):
    def __init__(
        self,
        heartbeater: Heartbeater,
        heartbeat_details: RedshiftHeartbeatDetails,
        data_interval_start: dt.datetime | str | None,
        data_interval_end: dt.datetime | str,
        redshift_client: RedshiftClient,
        redshift_table: str,
    ):
        """Implementation of a record batch consumer for Redshift batch export.

        This consumer will execute an INSERT query on every flush using provided
        Redshift client. The recommended way to insert multiple values into Redshift
        is using a COPY statement (see:
        https://docs.aws.amazon.com/redshift/latest/dg/r_COPY.html). However,
        Redshift cannot COPY from local files like Postgres, but only from files in
        S3 or executing commands in SSH hosts. Setting that up would add complexity
        and require more configuration from the user compared to the old Redshift
        export plugin. For these reasons, we are going with basic INSERT statements
        for now, but should eventually migrate to COPY from S3 for performance.
        """
        super().__init__(
            heartbeater,
            heartbeat_details,
            data_interval_start,
            data_interval_end,
            writer_format=WriterFormat.REDSHIFT_INSERT,
        )
        self.redshift_client = redshift_client
        self.redshift_table = redshift_table

    async def flush(
        self,
        batch_export_file: BatchExportTemporaryFile,
        records_since_last_flush: int,
        bytes_since_last_flush: int,
        flush_counter: int,
        last_date_range: DateRange,
        is_last: bool,
        error: Exception | None,
    ):
        self.external_logger.info(
            "Loading %d records of size %d bytes to Redshift table '%s'",
            records_since_last_flush,
            bytes_since_last_flush,
            self.redshift_table,
        )

        async with self.redshift_client.async_client_cursor() as cursor:
            async with self.redshift_client.connection.transaction():
                await cursor.execute(batch_export_file.read())

        self.external_logger.info(
            "Loaded %d records to Redshift table '%s'", records_since_last_flush, self.redshift_table
        )
        self.rows_exported_counter.add(records_since_last_flush)
        self.bytes_exported_counter.add(bytes_since_last_flush)

        self.heartbeat_details.records_completed += records_since_last_flush
        self.heartbeat_details.track_done_range(last_date_range, self.data_interval_start)


@dataclasses.dataclass(kw_only=True)
class RedshiftInsertInputs(PostgresInsertInputs):
    """Inputs for Redshift insert activity.

    Inherit from PostgresInsertInputs as they are the same, but allow
    for setting property_data_type which is unique to Redshift.
    """

    properties_data_type: str = "varchar"


@activity.defn
@handle_non_retryable_errors(NON_RETRYABLE_ERROR_TYPES)
async def insert_into_redshift_activity(inputs: RedshiftInsertInputs) -> BatchExportResult:
    """Activity to insert data from ClickHouse to Redshift.

    This activity executes the following steps:
    1. Check if anything is to be exported.
    2. Create destination table if not present.
    3. Query rows to export.
    4. Insert rows into Redshift.

    Args:
        inputs: The dataclass holding inputs for this activity. The inputs
            include: connection configuration (e.g. host, user, port), batch export
            query parameters (e.g. team_id, data_interval_start, include_events), and
            the Redshift-specific properties_data_type to indicate the type of JSON-like
            fields.
    """
    bind_contextvars(
        team_id=inputs.team_id,
        destination="Redshift",
        data_interval_start=inputs.data_interval_start,
        data_interval_end=inputs.data_interval_end,
    )
    external_logger = EXTERNAL_LOGGER.bind()

    external_logger.info(
        "Batch exporting range %s - %s to Redshift: %s.%s.%s",
        inputs.data_interval_start or "START",
        inputs.data_interval_end or "END",
        inputs.database,
        inputs.schema,
        inputs.table_name,
    )

    async with (
        Heartbeater() as heartbeater,
        set_status_to_running_task(run_id=inputs.run_id),
    ):
        _, details = await should_resume_from_activity_heartbeat(activity, RedshiftHeartbeatDetails)
        if details is None:
            details = RedshiftHeartbeatDetails()

        done_ranges: list[DateRange] = details.done_ranges

        model, record_batch_model, model_name, fields, filters, extra_query_parameters = resolve_batch_exports_model(
            inputs.team_id, inputs.batch_export_model, inputs.batch_export_schema
        )

        data_interval_start = (
            dt.datetime.fromisoformat(inputs.data_interval_start) if inputs.data_interval_start else None
        )
        data_interval_end = dt.datetime.fromisoformat(inputs.data_interval_end)
        full_range = (data_interval_start, data_interval_end)

        queue = RecordBatchQueue(max_size_bytes=settings.BATCH_EXPORT_REDSHIFT_RECORD_BATCH_QUEUE_MAX_SIZE_BYTES)
        producer = Producer(record_batch_model)
        producer_task = await producer.start(
            queue=queue,
            model_name=model_name,
            is_backfill=inputs.get_is_backfill(),
            backfill_details=inputs.backfill_details,
            team_id=inputs.team_id,
            full_range=full_range,
            done_ranges=done_ranges,
            fields=fields,
            filters=filters,
            destination_default_fields=redshift_default_fields(),
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            extra_query_parameters=extra_query_parameters,
            max_record_batch_size_bytes=1024 * 1024 * 2,  # 2MB
        )

        record_batch_schema = await wait_for_schema_or_producer(queue, producer_task)
        if record_batch_schema is None:
            external_logger.info(
                "Batch export will finish early as there is no data matching specified filters in range %s - %s",
                inputs.data_interval_start or "START",
                inputs.data_interval_end or "END",
            )

            return BatchExportResult(records_completed=details.records_completed)

        record_batch_schema = pa.schema(
            [field.with_nullable(True) for field in record_batch_schema if field.name != "_inserted_at"]
        )
        known_super_columns = ["properties", "set", "set_once", "person_properties"]
        if inputs.properties_data_type != "varchar":
            properties_type = "SUPER"

        else:
            properties_type = "VARCHAR(65535)"

        if model is None or (isinstance(model, BatchExportModel) and model.name == "events"):
            table_fields: Fields = [
                ("uuid", "VARCHAR(200)"),
                ("event", "VARCHAR(200)"),
                ("properties", properties_type),
                ("elements", "VARCHAR(65535)"),
                ("set", properties_type),
                ("set_once", properties_type),
                ("distinct_id", "VARCHAR(200)"),
                ("team_id", "INTEGER"),
                ("ip", "VARCHAR(200)"),
                ("site_url", "VARCHAR(200)"),
                ("timestamp", "TIMESTAMP WITH TIME ZONE"),
            ]
        else:
            table_fields = get_redshift_fields_from_record_schema(
                record_batch_schema, known_super_columns=known_super_columns, use_super=properties_type == "SUPER"
            )

        requires_merge = False
        merge_key: Fields = []
        update_key: Fields = []
        primary_key: Fields | None = None
        if isinstance(inputs.batch_export_model, BatchExportModel):
            if inputs.batch_export_model.name == "persons":
                requires_merge = True
                merge_key = [
                    ("team_id", "INT"),
                    ("distinct_id", "TEXT"),
                ]
                update_key = [
                    ("person_version", "INT"),
                    ("person_distinct_id_version", "INT"),
                ]
                primary_key = (("team_id", "INTEGER"), ("distinct_id", "VARCHAR(200)"))

            elif inputs.batch_export_model.name == "sessions":
                requires_merge = True
                merge_key = [
                    ("team_id", "INT"),
                    ("session_id", "TEXT"),
                ]
                update_key = [
                    ("end_timestamp", "TIMESTAMP"),
                ]
                primary_key = (("team_id", "INTEGER"), ("session_id", "TEXT"))

        data_interval_end_str = dt.datetime.fromisoformat(inputs.data_interval_end).strftime("%Y-%m-%d_%H-%M-%S")
        attempt = activity.info().attempt
        stage_table_name = (
            f"stage_{inputs.table_name}_{data_interval_end_str}_{inputs.team_id}_{attempt}"
            if requires_merge
            else inputs.table_name
        )

        async with RedshiftClient.from_inputs(inputs).connect() as redshift_client:
            # filter out fields that are not in the destination table
            try:
                columns = await redshift_client.aget_table_columns(inputs.schema, inputs.table_name)
                table_fields = [field for field in table_fields if field[0] in columns]
            except psycopg.errors.UndefinedTable:
                pass

            async with (
                redshift_client.managed_table(
                    inputs.schema, inputs.table_name, table_fields, delete=False, primary_key=primary_key
                ) as redshift_table,
                redshift_client.managed_table(
                    inputs.schema,
                    stage_table_name,
                    table_fields,
                    create=requires_merge,
                    delete=requires_merge,
                    primary_key=primary_key,
                ) as redshift_stage_table,
            ):
                schema_columns = {field[0] for field in table_fields}

                consumer = RedshiftConsumer(
                    heartbeater=heartbeater,
                    heartbeat_details=details,
                    data_interval_end=data_interval_end,
                    data_interval_start=data_interval_start,
                    redshift_client=redshift_client,
                    redshift_table=redshift_stage_table if requires_merge else redshift_table,
                )
                try:
                    _ = await run_consumer(
                        consumer=consumer,
                        queue=queue,
                        producer_task=producer_task,
                        schema=record_batch_schema,
                        max_bytes=settings.BATCH_EXPORT_REDSHIFT_UPLOAD_CHUNK_SIZE_BYTES,
                        json_columns=known_super_columns,
                        writer_file_kwargs={
                            "redshift_table": redshift_stage_table if requires_merge else redshift_table,
                            "redshift_schema": inputs.schema,
                            "table_columns": schema_columns,
                            "known_json_columns": set(known_super_columns),
                            "use_super": properties_type == "SUPER",
                            "redshift_client": redshift_client,
                        },
                        multiple_files=True,
                    )

                finally:
                    if requires_merge:
                        await redshift_client.amerge_mutable_tables(
                            final_table_name=redshift_table,
                            stage_table_name=redshift_stage_table,
                            schema=inputs.schema,
                            merge_key=merge_key,
                            update_key=update_key,
                        )

                return BatchExportResult(records_completed=details.records_completed)


class RedshiftConsumerFromStage(ConsumerFromStage):
    def __init__(
        self,
        client: RedshiftClient,
        table: str,
    ):
        super().__init__()

        self.client = client
        self.current_file_index = 0
        self.current_buffer = io.BytesIO()

        self.logger.bind(table=table)

    async def consume_chunk(self, data: bytes):
        self.current_buffer.write(data)
        await asyncio.sleep(0)

    async def finalize_file(self):
        await self._upload_current_buffer()
        self._start_new_file()

    def _start_new_file(self):
        """Start a new file (reset state for file splitting)."""
        self.current_file_index += 1

    async def finalize(self):
        """Finalize by uploading any remaining data."""
        await self._upload_current_buffer()

    async def _upload_current_buffer(self):
        buffer_size = self.current_buffer.tell()
        if buffer_size == 0:
            return

        self.logger.debug(
            "Insert query starting",
            current_file_index=self.current_file_index,
            buffer_size=buffer_size,
        )

        self.current_buffer.seek(0)

        async with self.client.async_client_cursor() as cursor:
            async with self.client.connection.transaction():
                await cursor.execute(self.current_buffer.read())

        self.logger.debug(
            "Insert query finished",
            current_file_index=self.current_file_index,
            buffer_size=buffer_size,
        )

        self.current_buffer = io.BytesIO()


class TableSchemas(typing.NamedTuple):
    table_schema: Fields
    super_columns: collections.abc.Sequence[str]


def _get_table_schemas(
    model: BatchExportModel | BatchExportSchema | None, record_batch_schema: pa.Schema, properties_data_type: str
) -> TableSchemas:
    """Return the schemas used for main and stage tables."""
    known_super_columns = ["properties", "set", "set_once", "person_properties"]
    if properties_data_type != "varchar":
        properties_type = "SUPER"

    else:
        properties_type = "VARCHAR(65535)"

    if model is None or (isinstance(model, BatchExportModel) and model.name == "events"):
        table_schema: Fields = [
            ("uuid", "VARCHAR(200)"),
            ("event", "VARCHAR(200)"),
            ("properties", properties_type),
            ("elements", "VARCHAR(65535)"),
            ("set", properties_type),
            ("set_once", properties_type),
            ("distinct_id", "VARCHAR(200)"),
            ("team_id", "INTEGER"),
            ("ip", "VARCHAR(200)"),
            ("site_url", "VARCHAR(200)"),
            ("timestamp", "TIMESTAMP WITH TIME ZONE"),
        ]

    else:
        table_schema = get_redshift_fields_from_record_schema(
            record_batch_schema, known_super_columns=known_super_columns, use_super=properties_type == "SUPER"
        )

    return TableSchemas(table_schema, known_super_columns)


class RequiredMergeSettings(typing.NamedTuple):
    requires_merge: typing.Literal[True]
    merge_key: Fields
    update_key: Fields
    primary_key: Fields


class NotRequiredMergeSettings(typing.NamedTuple):
    requires_merge: typing.Literal[False]


MergeSettings = RequiredMergeSettings | NotRequiredMergeSettings


def _get_merge_settings(
    model: BatchExportModel | BatchExportSchema | None,
) -> MergeSettings:
    """Return merge settings for models that require merging."""
    merge_key: Fields
    update_key: Fields
    primary_key: Fields

    if isinstance(model, BatchExportModel) and model.name == "persons":
        merge_key = [
            ("team_id", "INT"),
            ("distinct_id", "TEXT"),
        ]
        update_key = [
            ("person_version", "INT"),
            ("person_distinct_id_version", "INT"),
        ]
        primary_key = (("team_id", "INTEGER"), ("distinct_id", "VARCHAR(200)"))

        return RequiredMergeSettings(
            requires_merge=True, merge_key=merge_key, update_key=update_key, primary_key=primary_key
        )

    elif isinstance(model, BatchExportModel) and model.name == "sessions":
        merge_key = [
            ("team_id", "INT"),
            ("session_id", "TEXT"),
        ]
        update_key = [
            ("end_timestamp", "TIMESTAMP"),
        ]
        primary_key = (("team_id", "INTEGER"), ("session_id", "TEXT"))

        return RequiredMergeSettings(
            requires_merge=True, merge_key=merge_key, update_key=update_key, primary_key=primary_key
        )
    else:
        return NotRequiredMergeSettings(requires_merge=False)


@activity.defn
@handle_non_retryable_errors(NON_RETRYABLE_ERROR_TYPES)
async def insert_into_redshift_activity_from_stage(inputs: RedshiftInsertInputs) -> BatchExportResult:
    """Activity to insert data from ClickHouse to Redshift.

    This activity executes the following steps:
    1. Check if anything is to be exported.
    2. Create destination table if not present.
    3. Query rows to export.
    4. Insert rows into Redshift.

    Args:
        inputs: The dataclass holding inputs for this activity. The inputs
            include: connection configuration (e.g. host, user, port), batch export
            query parameters (e.g. team_id, data_interval_start, include_events), and
            the Redshift-specific properties_data_type to indicate the type of JSON-like
            fields.
    """
    bind_contextvars(
        team_id=inputs.team_id,
        destination="Redshift",
        data_interval_start=inputs.data_interval_start,
        data_interval_end=inputs.data_interval_end,
        database=inputs.database,
        schema=inputs.schema,
    )
    external_logger = EXTERNAL_LOGGER.bind()

    external_logger.info(
        "Batch exporting range %s - %s to Redshift: %s.%s.%s",
        inputs.data_interval_start or "START",
        inputs.data_interval_end or "END",
        inputs.database,
        inputs.schema,
        inputs.table_name,
    )

    async with Heartbeater():
        model: BatchExportModel | BatchExportSchema | None = None
        if inputs.batch_export_schema is None:
            model = inputs.batch_export_model
        else:
            model = inputs.batch_export_schema

        queue = RecordBatchQueue(max_size_bytes=settings.BATCH_EXPORT_REDSHIFT_RECORD_BATCH_QUEUE_MAX_SIZE_BYTES)
        producer = ProducerFromInternalStage()
        assert inputs.batch_export_id is not None
        producer_task = await producer.start(
            queue=queue,
            batch_export_id=inputs.batch_export_id,
            data_interval_start=inputs.data_interval_start,
            data_interval_end=inputs.data_interval_end,
            max_record_batch_size_bytes=1024 * 1024 * 60,  # 60MB
        )

        record_batch_schema = await wait_for_schema_or_producer(queue, producer_task)
        if record_batch_schema is None:
            external_logger.info(
                "Batch export will finish early as there is no data matching specified filters in range %s - %s",
                inputs.data_interval_start or "START",
                inputs.data_interval_end or "END",
            )

            return BatchExportResult(records_completed=0, bytes_exported=0)

        record_batch_schema = pa.schema(
            [field.with_nullable(True) for field in record_batch_schema if field.name != "_inserted_at"]
        )

        table_schemas = _get_table_schemas(
            model=model, record_batch_schema=record_batch_schema, properties_data_type=inputs.properties_data_type
        )

        merge_settings = _get_merge_settings(model=model)

        data_interval_end_str = dt.datetime.fromisoformat(inputs.data_interval_end).strftime("%Y-%m-%d_%H-%M-%S")
        stage_table_name = (
            f"stage_{inputs.table_name}_{data_interval_end_str}_{inputs.team_id}"
            if merge_settings.requires_merge
            else inputs.table_name
        )

        async with RedshiftClient.from_inputs(inputs).connect() as redshift_client:
            # filter out fields that are not in the destination table
            try:
                columns = await redshift_client.aget_table_columns(inputs.schema, inputs.table_name)
                table_fields = [field for field in table_schemas.table_schema if field[0] in columns]
            except psycopg.errors.UndefinedTable:
                table_fields = list(table_schemas.table_schema)

            primary_key = merge_settings.primary_key if merge_settings.requires_merge is True else None
            async with (
                redshift_client.managed_table(
                    inputs.schema, inputs.table_name, table_fields, delete=False, primary_key=primary_key
                ) as redshift_table,
                redshift_client.managed_table(
                    inputs.schema,
                    stage_table_name,
                    table_fields,
                    create=merge_settings.requires_merge,
                    delete=merge_settings.requires_merge,
                    primary_key=primary_key,
                ) as redshift_stage_table,
            ):
                consumer = RedshiftConsumerFromStage(
                    client=redshift_client,
                    table=redshift_stage_table if merge_settings.requires_merge else redshift_table,
                )
                transformer = RedshiftQueryStreamTransformer(
                    schema=record_batch_schema,
                    redshift_table=redshift_stage_table if merge_settings.requires_merge else redshift_table,
                    redshift_schema=inputs.schema,
                    table_columns=[field[0] for field in table_fields],
                    known_json_columns=table_schemas.super_columns,
                    use_super=inputs.properties_data_type != "varchar",
                    redshift_client=redshift_client,
                )
                result = await run_consumer_from_stage(
                    queue=queue,
                    consumer=consumer,
                    producer_task=producer_task,
                    transformer=transformer,
                    schema=record_batch_schema,
                    max_file_size_bytes=settings.BATCH_EXPORT_REDSHIFT_UPLOAD_CHUNK_SIZE_BYTES,
                )

                if merge_settings.requires_merge is True:
                    await redshift_client.amerge_mutable_tables(
                        final_table_name=redshift_table,
                        stage_table_name=redshift_stage_table,
                        schema=inputs.schema,
                        merge_key=merge_settings.merge_key,
                        update_key=merge_settings.update_key,
                    )

                return result


@workflow.defn(name="redshift-export", failure_exception_types=[workflow.NondeterminismError])
class RedshiftBatchExportWorkflow(PostHogWorkflow):
    """A Temporal Workflow to export ClickHouse data into Postgres.

    This Workflow is intended to be executed both manually and by a Temporal
    Schedule. When ran by a schedule, `data_interval_end` should be set to
    `None` so that we will fetch the end of the interval from the Temporal
    search attribute `TemporalScheduledStartTime`.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> RedshiftBatchExportInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return RedshiftBatchExportInputs(**loaded)

    @workflow.run
    async def run(self, inputs: RedshiftBatchExportInputs):
        """Workflow implementation to export data to Redshift."""
        is_backfill = inputs.get_is_backfill()
        is_earliest_backfill = inputs.get_is_earliest_backfill()
        data_interval_start, data_interval_end = get_data_interval(inputs.interval, inputs.data_interval_end)
        should_backfill_from_beginning = is_backfill and is_earliest_backfill

        start_batch_export_run_inputs = StartBatchExportRunInputs(
            team_id=inputs.team_id,
            batch_export_id=inputs.batch_export_id,
            data_interval_start=data_interval_start.isoformat() if not should_backfill_from_beginning else None,
            data_interval_end=data_interval_end.isoformat(),
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            backfill_id=inputs.backfill_details.backfill_id if inputs.backfill_details else None,
        )
        try:
            run_id = await workflow.execute_activity(
                start_batch_export_run,
                start_batch_export_run_inputs,
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(seconds=60),
                    maximum_attempts=0,
                    non_retryable_error_types=["NotNullViolation", "IntegrityError", "OverBillingLimitError"],
                ),
            )
        except OverBillingLimitError:
            return

        finish_inputs = FinishBatchExportRunInputs(
            id=run_id,
            batch_export_id=inputs.batch_export_id,
            status=BatchExportRun.Status.COMPLETED,
            team_id=inputs.team_id,
        )

        insert_inputs = RedshiftInsertInputs(
            team_id=inputs.team_id,
            user=inputs.user,
            password=inputs.password,
            host=inputs.host,
            port=inputs.port,
            database=inputs.database,
            schema=inputs.schema,
            table_name=inputs.table_name,
            has_self_signed_cert=inputs.has_self_signed_cert,
            data_interval_start=data_interval_start.isoformat() if not should_backfill_from_beginning else None,
            data_interval_end=data_interval_end.isoformat(),
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            properties_data_type=inputs.properties_data_type,
            run_id=run_id,
            backfill_details=inputs.backfill_details,
            is_backfill=is_backfill,
            batch_export_model=inputs.batch_export_model,
            batch_export_schema=inputs.batch_export_schema,
            batch_export_id=inputs.batch_export_id,
            destination_default_fields=redshift_default_fields(),
        )

        if (
            str(inputs.team_id) in settings.BATCH_EXPORT_REDSHIFT_USE_STAGE_TEAM_IDS
            or inputs.team_id % 100 < settings.BATCH_EXPORT_REDSHIFT_USE_INTERNAL_STAGE_ROLLOUT_PERCENTAGE
        ):
            await execute_batch_export_using_internal_stage(
                insert_into_redshift_activity_from_stage,
                insert_inputs,
                interval=inputs.interval,
                maximum_retry_interval_seconds=240,
            )
        else:
            await execute_batch_export_insert_activity(
                insert_into_redshift_activity,
                insert_inputs,
                interval=inputs.interval,
                finish_inputs=finish_inputs,
                maximum_retry_interval_seconds=240,
            )
