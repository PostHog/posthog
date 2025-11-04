import io
import json
import typing
import asyncio
import datetime as dt
import posixpath
import contextlib
import dataclasses
import collections.abc

from django.conf import settings

import psycopg
import pyarrow as pa
import aioboto3
import botocore.exceptions
from psycopg import sql
from structlog.contextvars import bind_contextvars
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.models import BatchExportRun
from posthog.batch_exports.service import (
    AWSCredentials,
    BatchExportField,
    BatchExportInsertInputs,
    BatchExportModel,
    BatchExportSchema,
    IAMRole,
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
    PostgreSQLClient,
    PostgreSQLField,
)
from products.batch_exports.backend.temporal.destinations.s3_batch_export import ConcurrentS3Consumer
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
from products.batch_exports.backend.temporal.pipeline.transformer import (
    ParquetStreamTransformer,
    RedshiftQueryStreamTransformer,
)
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
    # Raised when multiple S3 operations failed with a ClientError.
    "ClientErrorGroup",
    # Raised by PostgreSQL client when a function doesn't exist for the specified types.
    # This can indicate, for example, attempting to compare two types that cannot be
    # compared.
    "UndefinedFunction",
)


class ClientErrorGroup(ExceptionGroup):
    """Exception group wrapping multiple `botocore.exceptions.ClientError`.

    We detail each operation that failed, summarizing the results if only one type
    of operation failed with the same error multiple times. This is common in situations
    when permissions are missing.
    """

    def __new__(cls, exceptions: collections.abc.Sequence[botocore.exceptions.ClientError]):
        ops = {}
        for err in exceptions:
            op_name = err.operation_name
            error_code = err.response.get("Error", {}).get("Code", "Unknown")

            if op_name not in ops:
                ops[op_name] = {error_code}

            else:
                ops[op_name].add(error_code)

        if len(ops) == 1:
            op_name, error_codes = next(iter(ops.items()))

            if len(error_codes) == 1:
                # One type of operation failed, one error.
                error_code = next(iter(error_codes))

                self = super().__new__(
                    ClientErrorGroup, f"S3 operation '{op_name}' failed with error: '{error_code}'", exceptions
                )
            else:
                # One type of operation failed, but with multiple errors.
                self = super().__new__(
                    ClientErrorGroup,
                    f"S3 operation '{op_name}' failed with multiple errors: {', '.join(f"'{error_code}'" for error_code in error_codes)}",
                    exceptions,
                )
        else:
            # Many operations failed with multiple errors.
            pairs = ((op_name, error_code) for op_name, error_codes in ops.items() for error_code in error_codes)

            self = super().__new__(
                ClientErrorGroup,
                f"Multiple S3 operations failed: {', '.join(f"'{op_name}' failed with error '{error_code}'" for op_name, error_code in pairs)}",
                exceptions,
            )

        # This __new__ is based on the documentation on subclassing exception groups:
        # https://docs.python.org/3.12/library/exceptions.html#ExceptionGroup
        # Not sure how to tell mypy this is "fine".
        self.ops = ops  # type: ignore

        return self

    def derive(self, excs):
        return ClientErrorGroup(excs)


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

    async def amerge_tables(
        self,
        final_table_name: str,
        stage_table_name: str,
        schema: str,
        merge_key: Fields,
        update_key: Fields,
        final_table_fields: Fields,
        update_when_matched: Fields = (),
        stage_fields_cast_to_super: collections.abc.Container[str] | None = None,
        remove_duplicates: bool = True,
    ) -> None:
        """Merge two tables in Redshift.

        This can handle transforming fields into 'SUPER' type if required by setting
        `stage_fields_cast_to_super`, with the `JSON_PARSE` Redshift function.
        """
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

        if stage_fields_cast_to_super is not None:
            select_stage_table_fields = sql.SQL(
                ",".join(
                    f"JSON_PARSE({field[0]}) AS {field[0]}" if field[0] in stage_fields_cast_to_super else field[0]
                    for field in final_table_fields
                )
            )
        else:
            select_stage_table_fields = sql.SQL(",".join(field[0] for field in final_table_fields))

        merge_query = sql.SQL(
            """\
        MERGE INTO {final_table}
        USING (SELECT {select_stage_table_fields} FROM {stage_table}) AS stage
        ON {merge_condition}
        """
        ).format(
            final_table=final_table_identifier,
            select_stage_table_fields=select_stage_table_fields,
            stage_table=stage_table_identifier,
            merge_condition=merge_condition,
        )
        if remove_duplicates:
            merge_query = merge_query + sql.SQL("REMOVE DUPLICATES")
        else:
            update_values = sql.SQL(",").join(
                sql.SQL("{final_field} = {stage_field}").format(
                    final_field=sql.Identifier(field[0]),
                    stage_field=sql.Identifier("stage", field[0]),
                )
                for field in final_table_fields
            )

            insert_values = sql.SQL(",").join(
                sql.SQL("{stage_field}").format(
                    stage_field=sql.Identifier("stage", field[0]),
                )
                for field in final_table_fields
            )

            merge_query = merge_query + sql.SQL(
                """\
                WHEN MATCHED THEN UPDATE SET {update_values}
                WHEN NOT MATCHED THEN INSERT VALUES ({insert_values})
                """
            ).format(update_values=update_values, insert_values=insert_values)

        async with self.connection.transaction():
            async with self.connection.cursor() as cursor:
                try:
                    await cursor.execute(delete_query)
                except psycopg.errors.UndefinedFunction:
                    self.logger.exception(
                        "Query failed",
                        table=final_table_name,
                        schema=schema,
                        stage_table=stage_table_name,
                        query="DELETE",
                    )
                    self.external_logger.error(  # noqa: TRY400
                        "A non-retryable 'UndefinedFunction' error happened when attempting to"
                        " delete existing rows from '%s.%s' before a 'MERGE' command can be executed."
                        " This can indicate that the schema of the table does not match what the"
                        " batch export expects."
                        " Please review the table schema before retrying again, there may be fields"
                        " that have been created with incorrect types. The batch export will always"
                        " create a table with the correct schema if it doesn't already exist.",
                        schema,
                        final_table_name,
                    )
                    raise

                await cursor.execute(merge_query)

    async def acopy_from_s3_bucket(
        self,
        table_name: str,
        parquet_fields: list[str],
        schema_name: str,
        s3_bucket: str,
        manifest_key: str,
        authorization: IAMRole | AWSCredentials,
    ) -> None:
        table_identifier = sql.Identifier(schema_name, table_name)

        s3_files = sql.Literal(f"s3://{s3_bucket}/{manifest_key}")

        if isinstance(authorization, AWSCredentials):
            credentials: sql.SQL | sql.Composed = sql.SQL(
                """
                ACCESS_KEY_ID {access_key_id}
                SECRET_ACCESS_KEY {secret_access_key}
                """
            ).format(
                access_key_id=sql.Literal(authorization.aws_access_key_id),
                secret_access_key=sql.Literal(authorization.aws_secret_access_key),
            )

        else:
            if authorization == "default":
                credentials = sql.SQL("IAM_ROLE default")
            else:
                credentials = sql.SQL("IAM_ROLE {iam_role}").format(iam_role=sql.Literal(authorization))

        copy_query = sql.SQL(
            """
        COPY {table_name} ({fields})
        FROM {s3_files}
        {credentials}
        MANIFEST
        FORMAT AS PARQUET
        SERIALIZETOJSON
        """
        ).format(
            table_name=table_identifier,
            fields=sql.SQL(",").join(sql.Identifier(field) for field in parquet_fields),
            s3_files=s3_files,
            credentials=credentials,
        )

        async with self.connection.transaction():
            async with self.connection.cursor() as cursor:
                await cursor.execute(copy_query)


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
    record_schema: pa.Schema, known_super_columns: collections.abc.Container[str], use_super: bool
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


@dataclasses.dataclass
class S3StageBucketParameters:
    name: str
    region_name: str
    # TODO: We should support AWS RBAC in S3 batch export.
    credentials: AWSCredentials


@dataclasses.dataclass
class CopyParameters:
    s3_bucket: S3StageBucketParameters
    s3_key_prefix: str
    authorization: IAMRole | AWSCredentials


@dataclasses.dataclass
class ConnectionParameters:
    user: str
    password: str
    host: str
    port: int
    database: str
    has_self_signed_cert: bool = False


@dataclasses.dataclass
class TableParameters:
    schema_name: str
    name: str
    properties_data_type: str = "varchar"


@dataclasses.dataclass
class RedshiftCopyActivityInputs:
    """Inputs for Redshift copy activity."""

    batch_export: BatchExportInsertInputs
    connection: ConnectionParameters
    table: TableParameters
    copy: CopyParameters


@dataclasses.dataclass
class RedshiftInsertInputs:
    """Inputs for Redshift insert activity."""

    batch_export: BatchExportInsertInputs
    connection: ConnectionParameters
    table: TableParameters


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
        team_id=inputs.batch_export.team_id,
        destination="Redshift",
        data_interval_start=inputs.batch_export.data_interval_start,
        data_interval_end=inputs.batch_export.data_interval_end,
    )
    external_logger = EXTERNAL_LOGGER.bind()

    external_logger.info(
        "Batch exporting range %s - %s to Redshift: %s.%s.%s",
        inputs.batch_export.data_interval_start or "START",
        inputs.batch_export.data_interval_end or "END",
        inputs.connection.database,
        inputs.table.schema_name,
        inputs.table.name,
    )

    async with (
        Heartbeater() as heartbeater,
        set_status_to_running_task(run_id=inputs.batch_export.run_id),
    ):
        _, details = await should_resume_from_activity_heartbeat(activity, RedshiftHeartbeatDetails)
        if details is None:
            details = RedshiftHeartbeatDetails()

        done_ranges: list[DateRange] = details.done_ranges

        model, record_batch_model, model_name, fields, filters, extra_query_parameters = resolve_batch_exports_model(
            inputs.batch_export.team_id, inputs.batch_export.batch_export_model, inputs.batch_export.batch_export_schema
        )

        data_interval_start = (
            dt.datetime.fromisoformat(inputs.batch_export.data_interval_start)
            if inputs.batch_export.data_interval_start
            else None
        )
        data_interval_end = dt.datetime.fromisoformat(inputs.batch_export.data_interval_end)
        full_range = (data_interval_start, data_interval_end)

        queue = RecordBatchQueue(max_size_bytes=settings.BATCH_EXPORT_REDSHIFT_RECORD_BATCH_QUEUE_MAX_SIZE_BYTES)
        producer = Producer(record_batch_model)
        producer_task = await producer.start(
            queue=queue,
            model_name=model_name,
            is_backfill=inputs.batch_export.get_is_backfill(),
            backfill_details=inputs.batch_export.backfill_details,
            team_id=inputs.batch_export.team_id,
            full_range=full_range,
            done_ranges=done_ranges,
            fields=fields,
            filters=filters,
            destination_default_fields=redshift_default_fields(),
            exclude_events=inputs.batch_export.exclude_events,
            include_events=inputs.batch_export.include_events,
            extra_query_parameters=extra_query_parameters,
            max_record_batch_size_bytes=1024 * 1024 * 2,  # 2MB
        )

        record_batch_schema = await wait_for_schema_or_producer(queue, producer_task)
        if record_batch_schema is None:
            external_logger.info(
                "Batch export will finish early as there is no data matching specified filters in range %s - %s",
                inputs.batch_export.data_interval_start or "START",
                inputs.batch_export.data_interval_end or "END",
            )

            return BatchExportResult(records_completed=details.records_completed)

        record_batch_schema = pa.schema(
            [field.with_nullable(True) for field in record_batch_schema if field.name != "_inserted_at"]
        )
        known_super_columns = ["properties", "set", "set_once", "person_properties"]
        if inputs.table.properties_data_type != "varchar":
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
        if isinstance(inputs.batch_export.batch_export_model, BatchExportModel):
            if inputs.batch_export.batch_export_model.name == "persons":
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

            elif inputs.batch_export.batch_export_model.name == "sessions":
                requires_merge = True
                merge_key = [
                    ("team_id", "INT"),
                    ("session_id", "TEXT"),
                ]
                update_key = [
                    ("end_timestamp", "TIMESTAMP"),
                ]
                primary_key = (("team_id", "INTEGER"), ("session_id", "TEXT"))

        data_interval_end_str = dt.datetime.fromisoformat(inputs.batch_export.data_interval_end).strftime(
            "%Y-%m-%d_%H-%M-%S"
        )
        attempt = activity.info().attempt
        stage_table_name = (
            f"stage_{inputs.table.name}_{data_interval_end_str}_{inputs.batch_export.team_id}_{attempt}"
            if requires_merge
            else inputs.table.name
        )

        async with RedshiftClient.from_inputs(inputs.connection).connect() as redshift_client:
            # filter out fields that are not in the destination table
            try:
                columns = await redshift_client.aget_table_columns(inputs.table.schema_name, inputs.table.name)
                table_fields = [field for field in table_fields if field[0] in columns]

            except psycopg.errors.UndefinedTable:
                pass

            async with (
                redshift_client.managed_table(
                    inputs.table.schema_name, inputs.table.name, table_fields, delete=False, primary_key=primary_key
                ) as redshift_table,
                redshift_client.managed_table(
                    inputs.table.schema_name,
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
                            "redshift_schema": inputs.table.schema_name,
                            "table_columns": schema_columns,
                            "known_json_columns": set(known_super_columns),
                            "use_super": properties_type == "SUPER",
                            "redshift_client": redshift_client,
                        },
                        multiple_files=True,
                    )

                finally:
                    if requires_merge:
                        await redshift_client.amerge_tables(
                            final_table_name=redshift_table,
                            final_table_fields=table_fields,
                            stage_table_name=redshift_stage_table,
                            schema=inputs.table.schema_name,
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

        self.logger = self.logger.bind(table=table)

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
    stage_table_schema: Fields
    super_columns: set[str]
    use_super: bool


def _get_table_schemas(
    model: BatchExportModel | BatchExportSchema | None,
    record_batch_schema: pa.Schema,
    properties_data_type: str,
) -> TableSchemas:
    """Return the schemas used for main and stage tables."""
    known_super_columns = {"properties", "set", "set_once", "person_properties"}
    if properties_data_type != "varchar":
        properties_type = "SUPER"
        use_super = True

    else:
        properties_type = "VARCHAR(65535)"
        use_super = False

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

    if properties_type == "SUPER":
        # Update stage schema to first load as VARBYTE, and later JSON_PARSE to SUPER
        stage_table_schema: Fields = [
            (field[0], field[1] if field[0] not in known_super_columns else "VARBYTE(16777216)")
            for field in table_schema
        ]
    else:
        stage_table_schema = table_schema

    return TableSchemas(table_schema, stage_table_schema, known_super_columns, use_super)


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
    use_super: bool = False,
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
    elif (model is None or (isinstance(model, BatchExportModel) and model.name == "events")) and use_super is True:
        merge_key = [("uuid", "TEXT")]
        update_key = [("timestamp", "TIMESTAMP")]
        primary_key = [("uuid", "TEXT")]

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
    4. Insert rows into Redshift stage table (if required) or directly into final table.
    5. Merge data from stage table (if required) into final table.

    This MERGE step handles updates to mutable models, and converts fields from
    'VARBYTE' to 'SUPER' type if required. We use 'VARBYTE' as the stage type due to
    size restrictions: Executing a COPY directly to 'SUPER' type requires casting the
    value to 'VARCHAR', which imposes a 64KB limit on the entire document. In contrast,
    'VARBYTE' can ingest up to 16MB, and the 64KB limit only applies per value in the
    document.

    Args:
        inputs: The dataclass holding inputs for this activity. The inputs
            include: connection configuration (e.g. host, user, port), batch export
            query parameters (e.g. team_id, data_interval_start, include_events), and
            the Redshift-specific properties_data_type to indicate the type of JSON-like
            fields.
    """
    bind_contextvars(
        team_id=inputs.batch_export.team_id,
        destination="Redshift",
        data_interval_start=inputs.batch_export.data_interval_start,
        data_interval_end=inputs.batch_export.data_interval_end,
        database=inputs.connection.database,
        schema=inputs.table.schema_name,
    )
    external_logger = EXTERNAL_LOGGER.bind()

    external_logger.info(
        "Batch exporting range %s - %s to Redshift: %s.%s.%s",
        inputs.batch_export.data_interval_start or "START",
        inputs.batch_export.data_interval_end or "END",
        inputs.connection.database,
        inputs.table.schema_name,
        inputs.table.name,
    )

    async with Heartbeater():
        model: BatchExportModel | BatchExportSchema | None = None
        if inputs.batch_export.batch_export_schema is None:
            model = inputs.batch_export.batch_export_model
        else:
            model = inputs.batch_export.batch_export_schema

        queue = RecordBatchQueue(max_size_bytes=settings.BATCH_EXPORT_REDSHIFT_RECORD_BATCH_QUEUE_MAX_SIZE_BYTES)
        producer = ProducerFromInternalStage()
        assert inputs.batch_export.batch_export_id is not None
        producer_task = await producer.start(
            queue=queue,
            batch_export_id=inputs.batch_export.batch_export_id,
            data_interval_start=inputs.batch_export.data_interval_start,
            data_interval_end=inputs.batch_export.data_interval_end,
            max_record_batch_size_bytes=1024 * 1024 * 2,  # 2MB
        )

        record_batch_schema = await wait_for_schema_or_producer(queue, producer_task)
        if record_batch_schema is None:
            external_logger.info(
                "Batch export will finish early as there is no data matching specified filters in range %s - %s",
                inputs.batch_export.data_interval_start or "START",
                inputs.batch_export.data_interval_end or "END",
            )

            return BatchExportResult(records_completed=0, bytes_exported=0)

        record_batch_schema = pa.schema(
            [field.with_nullable(True) for field in record_batch_schema if field.name != "_inserted_at"]
        )

        table_schemas = _get_table_schemas(
            model=model, record_batch_schema=record_batch_schema, properties_data_type=inputs.table.properties_data_type
        )
        merge_settings = _get_merge_settings(model=model, use_super=table_schemas.use_super)

        data_interval_end_str = dt.datetime.fromisoformat(inputs.batch_export.data_interval_end).strftime(
            "%Y-%m-%d_%H-%M-%S"
        )
        stage_table_name = (
            f"stage_{inputs.table.name}_{data_interval_end_str}_{inputs.batch_export.team_id}"
            if merge_settings.requires_merge
            else inputs.table.name
        )

        async with RedshiftClient.from_inputs(inputs.connection).connect() as redshift_client:
            remove_duplicates = True
            # filter out fields that are not in the destination table
            try:
                columns = await redshift_client.aget_table_columns(inputs.table.schema_name, inputs.table.name)
                if len(columns) > len(tuple(table_schemas.table_schema)):
                    # MERGE cannot remove duplicates if table columns don't match.
                    remove_duplicates = False
                    external_logger.warning(
                        "Table %s.%s has %d columns instead of %d as expected. "
                        "MERGE command may perform worse and not properly clean up duplicates",
                        inputs.table.schema_name,
                        inputs.table.name,
                        len(columns),
                        len(tuple(table_schemas.table_schema)),
                    )

                table_fields = [field for field in table_schemas.table_schema if field[0] in columns]
            except psycopg.errors.UndefinedTable:
                table_fields = list(table_schemas.table_schema)

            primary_key = merge_settings.primary_key if merge_settings.requires_merge is True else None
            async with (
                redshift_client.managed_table(
                    inputs.table.schema_name, inputs.table.name, table_fields, delete=False, primary_key=primary_key
                ) as redshift_table,
                redshift_client.managed_table(
                    inputs.table.schema_name,
                    stage_table_name,
                    table_schemas.stage_table_schema,
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
                    redshift_schema=inputs.table.schema_name,
                    table_columns=[field[0] for field in table_fields],
                    known_json_columns=table_schemas.super_columns,
                    redshift_client=redshift_client,
                    max_query_size_bytes=settings.BATCH_EXPORT_REDSHIFT_UPLOAD_CHUNK_SIZE_BYTES,
                )
                result = await run_consumer_from_stage(
                    queue=queue,
                    consumer=consumer,
                    producer_task=producer_task,
                    transformer=transformer,
                )

                if merge_settings.requires_merge is True:
                    await redshift_client.amerge_tables(
                        final_table_name=redshift_table,
                        final_table_fields=table_fields,
                        stage_table_name=redshift_stage_table,
                        schema=inputs.table.schema_name,
                        merge_key=merge_settings.merge_key,
                        update_key=merge_settings.update_key,
                        stage_fields_cast_to_super=table_schemas.super_columns if table_schemas.use_super else None,
                        remove_duplicates=remove_duplicates,
                    )

                return result


async def upload_manifest_file(
    bucket: str,
    region_name: str,
    aws_access_key_id: str | None,
    aws_secret_access_key: str | None,
    files_uploaded: list[str],
    manifest_key: str,
    endpoint_url: str | None = None,
):
    """Upload manifest file used by Redshift COPY.

    The manifest file Redshift uses is slightly different to the manifest file that our
    `ConcurrentS3Consumer` produces: The top level key is `"entries"` and each entry has
    a `"meta"` key with the `"content_length"` of each file. The content length is a
    requirement when using Parquet. Since we don't track exactly the size of bytes of
    each Parquet file produced, this function gets it from S3 instead.
    """
    session = aioboto3.Session()
    async with session.client(
        "s3",
        region_name=region_name,
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
        endpoint_url=endpoint_url,
    ) as client:
        entries = []

        async def populate_entry(f: str):
            """Obtain size for file `f` and construct entry dictionary."""
            nonlocal entries

            response = await client.list_objects_v2(Bucket=bucket, Prefix=f)

            if "Contents" not in response or len(response["Contents"]) == 0:
                # Unlikely as this should be called after the files have been
                # successfully uploaded.
                raise ValueError(f"File {f} not found in bucket {bucket}")

            entries.append(
                {
                    "url": f"s3://{bucket}/{f}",
                    "mandatory": True,
                    "meta": {"content_length": response["Contents"][0]["Size"]},
                }
            )

        try:
            async with asyncio.TaskGroup() as tg:
                for f in files_uploaded:
                    tg.create_task(populate_entry(f))
        except* botocore.exceptions.ClientError as err_group:
            LOGGER.exception("Failed to populate manifest entries")

            # According to type hints, ExceptionGroup.exceptions can be either
            # ClientError or nested ExceptionGroup[ClientError]. At the moment, there
            # isn't a good way to flatten these without a recursive function, so we keep
            # only the top level ClientErrors for analysis. There shouldn't be any
            # nested ExceptionGroup as the populate_entry task doesn't run a
            # TaskGroup, so this should be good enough.
            # There is an ongoing discussion in PEP-0785:
            # https://peps.python.org/pep-0785/#a-leaf-exceptions-helper-function.
            top_level_errors = tuple(
                err for err in err_group.exceptions if isinstance(err, botocore.exceptions.ClientError)
            )

            error_codes = {err.response.get("Error", {}).get("Code", None) for err in top_level_errors}
            for error_code in error_codes:
                if error_code == "AccessDenied":
                    # This reports the error to the user, we have already logged the exception above.
                    EXTERNAL_LOGGER.error(  # noqa: TRY400
                        "Missing permissions when attempting to list uploaded files while preparing for manifest upload. Have you granted 's3:ListBucket' permissions to the provided user on the bucket '%s'?",
                        bucket,
                    )
                else:
                    EXTERNAL_LOGGER.error(  # noqa: TRY400
                        "Unknown error when attempting to list uploaded files: %s",
                        error_code,
                    )

            raise ClientErrorGroup(top_level_errors)

        manifest = {"entries": entries}

        await client.put_object(
            Bucket=bucket,
            Key=manifest_key,
            Body=json.dumps(manifest),
        )


async def delete_uploaded_files(
    bucket: str,
    region_name: str,
    aws_access_key_id: str | None,
    aws_secret_access_key: str | None,
    files_uploaded: list[str],
    manifest_key: str,
):
    """Delete files uploaded to S3 bucket during 'COPY' activity.

    This includes the `files_uploaded` and the manifest in `manifest_key`.

    The delete itself is a "best-effort" as we don't want to fail the batch export if
    this fails.
    """
    session = aioboto3.Session()
    async with session.client(
        "s3",
        region_name=region_name,
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
    ) as client:

        async def delete_key(f: str):
            """Delete key `f` in S3."""
            try:
                _ = await client.delete_object(Bucket=bucket, Key=f)
            except Exception:
                LOGGER.exception("S3 delete failed", key=f, bucket=bucket)

        async with asyncio.TaskGroup() as tg:
            for f in files_uploaded:
                tg.create_task(delete_key(f))
            tg.create_task(delete_key(manifest_key))


@activity.defn
@handle_non_retryable_errors(NON_RETRYABLE_ERROR_TYPES)
async def copy_into_redshift_activity_from_stage(inputs: RedshiftCopyActivityInputs) -> BatchExportResult:
    """Activity to COPY data to Redshift.

    Note that Redshift's COPY requires data to first be available in an S3 bucket that
    is different from the S3 stage bucket used in batch exports. I will call the
    buckets the "user's bucket" and the "stage bucket" respectively to differentiate
    them.

    The user's bucket must be in the same region as the Redshift instance, and Redshift
    must be able to access the bucket via credentials or assuming an IAM role. Since the
    stage bucket is an internal bucket, not publicly accessible, and in a fixed region
    it cannot play the role of the user's bucket.

    So, this activity first exports a Parquet file from our stage bucket to the user's
    bucket. Then, the Parquet file is copied into Redshift with a COPY command into a
    stage table. Finally, we MERGE the stage table into the final table.

    This MERGE step handles updates to mutable models, and converts fields from
    'VARBYTE' to 'SUPER' type if required. We use 'VARBYTE' as the stage type due to
    size restrictions: Executing a COPY directly to 'SUPER' type requires casting the
    value to 'VARCHAR', which imposes a 64KB limit on the entire document. In contrast,
    'VARBYTE' can ingest up to 16MB, and the 64KB limit only applies per value in the
    document.

    To move the data to the user's bucket we make use of the tools available in our S3
    batch export, as it is functionally the same operation.

    Args:
        inputs: The dataclass holding inputs for this activity. The inputs
            include: connection configuration (e.g. host, user, port), batch export
            query parameters (e.g. team_id, data_interval_start, include_events), and
            the Redshift-specific properties_data_type to indicate the type of JSON-like
            fields.
    """
    bind_contextvars(
        team_id=inputs.batch_export.team_id,
        destination="Redshift",
        data_interval_start=inputs.batch_export.data_interval_start,
        data_interval_end=inputs.batch_export.data_interval_end,
        database=inputs.connection.database,
        schema=inputs.table.schema_name,
    )
    external_logger = EXTERNAL_LOGGER.bind()

    external_logger.info(
        "Batch exporting range %s - %s to Redshift: %s.%s.%s",
        inputs.batch_export.data_interval_start or "START",
        inputs.batch_export.data_interval_end or "END",
        inputs.connection.database,
        inputs.table.schema_name,
        inputs.table.name,
    )

    async with Heartbeater():
        model: BatchExportModel | BatchExportSchema | None = None
        if inputs.batch_export.batch_export_schema is None:
            model = inputs.batch_export.batch_export_model
        else:
            model = inputs.batch_export.batch_export_schema

        queue = RecordBatchQueue(max_size_bytes=settings.BATCH_EXPORT_S3_RECORD_BATCH_QUEUE_MAX_SIZE_BYTES)
        producer = ProducerFromInternalStage()
        assert inputs.batch_export.batch_export_id is not None
        producer_task = await producer.start(
            queue=queue,
            batch_export_id=inputs.batch_export.batch_export_id,
            data_interval_start=inputs.batch_export.data_interval_start,
            data_interval_end=inputs.batch_export.data_interval_end,
            max_record_batch_size_bytes=1024 * 1024 * 60,  # 60MB
        )

        record_batch_schema = await wait_for_schema_or_producer(queue, producer_task)
        if record_batch_schema is None:
            external_logger.info(
                "Batch export will finish early as there is no data matching specified filters in range %s - %s",
                inputs.batch_export.data_interval_start or "START",
                inputs.batch_export.data_interval_end or "END",
            )

            return BatchExportResult(records_completed=0, bytes_exported=0)

        record_batch_schema = pa.schema(
            [field.with_nullable(True) for field in record_batch_schema if field.name != "_inserted_at"]
        )

        # Redshift recommends files should be between 1MB-1GB, and that we
        # should aim for files to be equally distributed across cluster slices.
        # We don't know the number of slices in our user's cluster, so I've chosen
        # some nice round somewhere in the range (100MB).
        # TODO: Maybe derive this from user's input?
        max_file_size_mb = 100
        consumer = ConcurrentS3Consumer(
            bucket=inputs.copy.s3_bucket.name,
            region_name=inputs.copy.s3_bucket.region_name,
            prefix=inputs.copy.s3_key_prefix,
            data_interval_start=inputs.batch_export.data_interval_start,
            data_interval_end=inputs.batch_export.data_interval_end,
            batch_export_model=inputs.batch_export.batch_export_model,
            file_format="Parquet",
            compression="zstd",
            encryption=None,
            aws_access_key_id=inputs.copy.s3_bucket.credentials.aws_access_key_id,
            aws_secret_access_key=inputs.copy.s3_bucket.credentials.aws_secret_access_key,
            max_file_size_mb=max_file_size_mb,
            part_size=settings.BATCH_EXPORT_S3_UPLOAD_CHUNK_SIZE_BYTES,
            max_concurrent_uploads=settings.BATCH_EXPORT_S3_MAX_CONCURRENT_UPLOADS,
        )

        table_schemas = _get_table_schemas(
            model=model,
            record_batch_schema=record_batch_schema,
            properties_data_type=inputs.table.properties_data_type,
        )

        transformer = ParquetStreamTransformer(
            compression="zstd",
            include_inserted_at=False,
            max_file_size_bytes=max_file_size_mb * 1024**2,
        )

        merge_settings = _get_merge_settings(model=model, use_super=table_schemas.use_super)

        data_interval_end_str = dt.datetime.fromisoformat(inputs.batch_export.data_interval_end).strftime(
            "%Y-%m-%d_%H-%M-%S"
        )
        attempt = activity.info().attempt
        stage_table_name = (
            f"stage_{inputs.table.name}_{data_interval_end_str}_{inputs.batch_export.team_id}_{attempt}"
            if merge_settings.requires_merge
            else inputs.table.name
        )

        result = await run_consumer_from_stage(
            queue=queue,
            consumer=consumer,
            producer_task=producer_task,
            transformer=transformer,
        )

        if result.error is not None:
            return result

        async with RedshiftClient.from_inputs(inputs.connection).connect() as redshift_client:
            remove_duplicates = True

            # filter out fields that are not in the destination table
            try:
                columns = await redshift_client.aget_table_columns(inputs.table.schema_name, inputs.table.name)
                if len(columns) > len(tuple(table_schemas.table_schema)):
                    # MERGE cannot remove duplicates if table columns don't match.
                    remove_duplicates = False
                    external_logger.warning(
                        "Table %s.%s has %d columns instead of %d as expected. "
                        "MERGE command may perform worse and not properly clean up duplicates",
                        inputs.table.schema_name,
                        inputs.table.name,
                        len(columns),
                        len(tuple(table_schemas.table_schema)),
                    )

                table_fields = [field for field in table_schemas.table_schema if field[0] in columns]

            except psycopg.errors.UndefinedTable:
                table_fields = list(table_schemas.table_schema)

            primary_key = merge_settings.primary_key if merge_settings.requires_merge is True else None
            async with (
                redshift_client.managed_table(
                    inputs.table.schema_name,
                    inputs.table.name,
                    table_fields,
                    delete=False,
                    primary_key=primary_key,
                ) as redshift_table,
                redshift_client.managed_table(
                    inputs.table.schema_name,
                    stage_table_name,
                    table_schemas.stage_table_schema,
                    create=merge_settings.requires_merge,
                    delete=merge_settings.requires_merge,
                    primary_key=primary_key,
                ) as redshift_stage_table,
            ):
                manifest_key = posixpath.join(
                    inputs.copy.s3_key_prefix,
                    f"{inputs.batch_export.data_interval_start}-{inputs.batch_export.data_interval_end}_manifest.json",
                )

                if posixpath.isabs(manifest_key):
                    manifest_key = posixpath.relpath(manifest_key, "/")

                await upload_manifest_file(
                    bucket=inputs.copy.s3_bucket.name,
                    region_name=inputs.copy.s3_bucket.region_name,
                    aws_access_key_id=inputs.copy.s3_bucket.credentials.aws_access_key_id,
                    files_uploaded=consumer.files_uploaded,
                    aws_secret_access_key=inputs.copy.s3_bucket.credentials.aws_secret_access_key,
                    # manifest_key is always str, but posixpath.relpath can return both str and bytes.
                    manifest_key=manifest_key if isinstance(manifest_key, str) else manifest_key.decode("utf-8"),
                )

                try:
                    external_logger.info(f"Copying {len(consumer.files_uploaded)} file/s into Redshift")

                    await redshift_client.acopy_from_s3_bucket(
                        table_name=redshift_stage_table,
                        parquet_fields=[field.name for field in record_batch_schema],
                        schema_name=inputs.table.schema_name,
                        s3_bucket=inputs.copy.s3_bucket.name,
                        manifest_key=manifest_key,
                        authorization=inputs.copy.authorization,
                    )

                    if merge_settings.requires_merge is True:
                        await redshift_client.amerge_tables(
                            final_table_name=redshift_table,
                            final_table_fields=table_fields,
                            stage_table_name=redshift_stage_table,
                            schema=inputs.table.schema_name,
                            merge_key=merge_settings.merge_key,
                            update_key=merge_settings.update_key,
                            stage_fields_cast_to_super=table_schemas.super_columns if table_schemas.use_super else None,
                            remove_duplicates=remove_duplicates,
                        )

                    external_logger.info(f"Finished {len(consumer.files_uploaded)} copying file/s into Redshift")

                finally:
                    await delete_uploaded_files(
                        bucket=inputs.copy.s3_bucket.name,
                        region_name=inputs.copy.s3_bucket.region_name,
                        aws_access_key_id=inputs.copy.s3_bucket.credentials.aws_access_key_id,
                        files_uploaded=consumer.files_uploaded,
                        aws_secret_access_key=inputs.copy.s3_bucket.credentials.aws_secret_access_key,
                        # manifest_key is always str, but posixpath.relpath can return both str and bytes.
                        manifest_key=manifest_key if isinstance(manifest_key, str) else manifest_key.decode("utf-8"),
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

        batch_export_inputs = BatchExportInsertInputs(
            team_id=inputs.team_id,
            data_interval_start=data_interval_start.isoformat() if not should_backfill_from_beginning else None,
            data_interval_end=data_interval_end.isoformat(),
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            run_id=run_id,
            backfill_details=inputs.backfill_details,
            is_backfill=is_backfill,
            batch_export_model=inputs.batch_export_model,
            batch_export_schema=inputs.batch_export_schema,
            batch_export_id=inputs.batch_export_id,
            destination_default_fields=redshift_default_fields(),
        )
        connection_parameters = ConnectionParameters(
            user=inputs.user,
            password=inputs.password,
            host=inputs.host,
            port=inputs.port,
            database=inputs.database,
        )
        table_parameters = TableParameters(
            schema_name=inputs.schema,
            name=inputs.table_name,
            properties_data_type=inputs.properties_data_type,
        )

        if (
            str(inputs.team_id) in settings.BATCH_EXPORT_REDSHIFT_USE_STAGE_TEAM_IDS
            or inputs.team_id % 100 < settings.BATCH_EXPORT_REDSHIFT_USE_INTERNAL_STAGE_ROLLOUT_PERCENTAGE
            or inputs.mode == "COPY"
        ):
            if inputs.mode == "COPY" and inputs.copy_inputs is not None:
                await execute_batch_export_using_internal_stage(
                    copy_into_redshift_activity_from_stage,
                    RedshiftCopyActivityInputs(  # type: ignore
                        batch_export=batch_export_inputs,
                        connection=connection_parameters,
                        table=table_parameters,
                        copy=CopyParameters(
                            s3_bucket=S3StageBucketParameters(
                                name=inputs.copy_inputs.s3_bucket,
                                region_name=inputs.copy_inputs.region_name,
                                credentials=inputs.copy_inputs.bucket_credentials,
                            ),
                            s3_key_prefix=inputs.copy_inputs.s3_key_prefix,
                            authorization=inputs.copy_inputs.authorization,
                        ),
                    ),
                    interval=inputs.interval,
                    maximum_retry_interval_seconds=240,
                )
            else:
                await execute_batch_export_using_internal_stage(
                    insert_into_redshift_activity_from_stage,
                    RedshiftInsertInputs(  # type: ignore
                        batch_export=batch_export_inputs,
                        connection=connection_parameters,
                        table=table_parameters,
                    ),
                    interval=inputs.interval,
                    # TODO: Temporarily bump start to close timeout until we speed up
                    # Redshift inserts.
                    override_start_to_close_timeout_seconds=60 * 60 * 24,  # 24 hours
                    maximum_retry_interval_seconds=240,
                )
        else:
            await execute_batch_export_insert_activity(
                insert_into_redshift_activity,
                RedshiftInsertInputs(  # type: ignore
                    batch_export=batch_export_inputs,
                    connection=connection_parameters,
                    table=table_parameters,
                ),
                interval=inputs.interval,
                finish_inputs=finish_inputs,
                maximum_retry_interval_seconds=240,
            )
