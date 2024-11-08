import asyncio
import collections.abc
import contextlib
import dataclasses
import datetime as dt
import json
import typing

import psycopg
import pyarrow as pa
import structlog
from psycopg import sql
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.models import BatchExportRun
from posthog.batch_exports.service import (
    BatchExportField,
    BatchExportModel,
    BatchExportSchema,
    RedshiftBatchExportInputs,
)
from posthog.temporal.batch_exports.base import PostHogWorkflow
from posthog.temporal.batch_exports.batch_exports import (
    FinishBatchExportRunInputs,
    RecordsCompleted,
    StartBatchExportRunInputs,
    default_fields,
    execute_batch_export_insert_activity,
    get_data_interval,
    raise_on_produce_task_failure,
    start_batch_export_run,
    start_produce_batch_export_record_batches,
)
from posthog.temporal.batch_exports.metrics import get_rows_exported_metric
from posthog.temporal.batch_exports.postgres_batch_export import (
    Fields,
    PostgresInsertInputs,
    PostgreSQLClient,
    PostgreSQLField,
)
from posthog.temporal.batch_exports.utils import (
    JsonType,
    apeek_first_and_rewind,
    set_status_to_running_task,
)
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import configure_temporal_worker_logger
from posthog.temporal.common.utils import (
    BatchExportRangeHeartbeatDetails,
    DateRange,
    should_resume_from_activity_heartbeat,
)


def remove_escaped_whitespace_recursive(value):
    """Remove all escaped whitespace characters from given value.

    PostgreSQL supports constant escaped strings by appending an E' to each string that
    contains whitespace in them (amongst other characters). See:
    https://www.postgresql.org/docs/current/sql-syntax-lexical.html#SQL-SYNTAX-STRINGS-ESCAPE

    However, Redshift does not support this syntax. So, to avoid any escaping by
    underlying PostgreSQL library, we remove the whitespace ourselves as defined in the
    translation table WHITESPACE_TRANSLATE.

    This function is recursive just to be extremely careful and catch any whitespace that
    may be sneaked in a dictionary key or sequence.
    """
    match value:
        case str(s):
            return " ".join(s.replace("\b", " ").split())

        case bytes(b):
            return remove_escaped_whitespace_recursive(b.decode("utf-8"))

        case [*sequence]:
            # mypy could be bugged as it's raising a Statement unreachable error.
            # But we are definitely reaching this statement in tests; hence the ignore comment.
            # Maybe: https://github.com/python/mypy/issues/16272.
            return type(value)(remove_escaped_whitespace_recursive(sequence_value) for sequence_value in sequence)  # type: ignore

        case set(elements):
            return {remove_escaped_whitespace_recursive(element) for element in elements}

        case {**mapping}:
            return {k: remove_escaped_whitespace_recursive(v) for k, v in mapping.items()}

        case value:
            return value


class RedshiftClient(PostgreSQLClient):
    @contextlib.asynccontextmanager
    async def connect(self) -> typing.AsyncIterator[typing.Self]:
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
    async def async_client_cursor(self) -> typing.AsyncIterator[psycopg.AsyncClientCursor]:
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

    async def amerge_identical_tables(
        self,
        final_table_name: str,
        stage_table_name: str,
        schema: str,
        merge_key: Fields,
        person_version_key: str = "person_version",
        person_distinct_id_version_key: str = "person_distinct_id_version",
    ) -> None:
        """Merge two identical tables in PostgreSQL."""
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

        delete_condition = and_separator.join(
            sql.SQL("{final_field} = {stage_field}").format(
                final_field=sql.Identifier("final", field[0]),
                stage_field=sql.Identifier(schema, stage_table_name, field[0]),
            )
            for field in merge_key
        )

        delete_query = sql.SQL(
            """\
        DELETE FROM {stage_table}
        USING {final_table} AS final
        WHERE {merge_condition}
        AND {stage_table}.{stage_person_version_key} < final.{final_person_version_key}
        AND {stage_table}.{stage_person_distinct_id_version_key} < final.{final_person_distinct_id_version_key};
        """
        ).format(
            final_table=final_table_identifier,
            stage_table=stage_table_identifier,
            merge_condition=delete_condition,
            stage_person_version_key=sql.Identifier(person_version_key),
            final_person_version_key=sql.Identifier(person_version_key),
            stage_person_distinct_id_version_key=sql.Identifier(person_distinct_id_version_key),
            final_person_distinct_id_version_key=sql.Identifier(person_distinct_id_version_key),
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

        else:
            raise TypeError(f"Unsupported type: {pa_field.type}")

        pg_schema.append((name, pg_type))

    return pg_schema


@dataclasses.dataclass
class RedshiftHeartbeatDetails(BatchExportRangeHeartbeatDetails):
    """The BigQuery batch export details included in every heartbeat."""

    pass


async def insert_records_to_redshift(
    records: collections.abc.AsyncGenerator[tuple[dict[str, typing.Any], dt.datetime], None],
    redshift_client: RedshiftClient,
    schema: str | None,
    table: str,
    heartbeater: Heartbeater,
    heartbeat_details: RedshiftHeartbeatDetails,
    data_interval_start: dt.timedelta | None,
    batch_size: int = 100,
    use_super: bool = False,
    known_super_columns: list[str] | None = None,
) -> int:
    """Execute an INSERT query with given Redshift connection.

    The recommended way to insert multiple values into Redshift is using a COPY statement (see:
    https://docs.aws.amazon.com/redshift/latest/dg/r_COPY.html). However, Redshift cannot COPY from local
    files like Postgres, but only from files in S3 or executing commands in SSH hosts. Setting that up would
    add complexity and require more configuration from the user compared to the old Redshift export plugin.
    For this reasons, we are going with basic INSERT statements for now, and we can migrate to COPY from S3
    later if the need arises.

    Arguments:
        record: A dictionary representing the record to insert. Each key should correspond to a column
            in the destination table.
        redshift_connection: A connection to Redshift setup by psycopg2.
        schema: The schema that contains the table where to insert the record.
        table: The name of the table where to insert the record.
        batch_size: Number of records to insert in batch. Setting this too high could
            make us go OOM or exceed Redshift's SQL statement size limit (16MB). Setting this too low
            can significantly affect performance due to Redshift's poor handling of INSERTs.
    """
    first_value, records_iterator = await apeek_first_and_rewind(records)
    if first_value is None:
        return 0

    first_record_batch, _inserted_at = first_value
    columns = first_record_batch.keys()

    if schema:
        table_identifier = sql.Identifier(schema, table)
    else:
        table_identifier = sql.Identifier(table)

    pre_query = sql.SQL("INSERT INTO {table} ({fields}) VALUES").format(
        table=table_identifier,
        fields=sql.SQL(", ").join(map(sql.Identifier, columns)),
    )
    placeholders: list[sql.Composable] = []
    for column in columns:
        if use_super is True and known_super_columns is not None and column in known_super_columns:
            placeholders.append(sql.SQL("JSON_PARSE({placeholder})").format(placeholder=sql.Placeholder(column)))
        else:
            placeholders.append(sql.Placeholder(column))

    template = sql.SQL("({})").format(sql.SQL(", ").join(placeholders))
    rows_exported = get_rows_exported_metric()

    total_rows_exported = 0

    async with redshift_client.connection.transaction():
        async with redshift_client.async_client_cursor() as cursor:
            batch = []
            pre_query_str = pre_query.as_string(cursor).encode("utf-8")

            async def flush_to_redshift(batch):
                nonlocal total_rows_exported

                values = b",".join(batch).replace(b" E'", b" '")
                await cursor.execute(pre_query_str + values)
                rows_exported.add(len(batch))
                total_rows_exported += len(batch)
                # It would be nice to record BYTES_EXPORTED for Redshift, but it's not worth estimating
                # the byte size of each batch the way things are currently written. We can revisit this
                # in the future if we decide it's useful enough.

            first_inserted_at = None
            async for record, _inserted_at in records_iterator:
                if first_inserted_at is None:
                    first_inserted_at = _inserted_at

                for column in columns:
                    if known_super_columns is not None and column in known_super_columns:
                        record[column] = json.dumps(record[column], ensure_ascii=False)

                batch.append(cursor.mogrify(template, record).encode("utf-8"))
                if len(batch) < batch_size:
                    continue

                await flush_to_redshift(batch)

                if len(heartbeat_details.done_ranges) == 0:
                    if data_interval_start is None:
                        last_date_range = (dt.datetime.fromtimestamp(0, tz=dt.UTC), _inserted_at)
                    else:
                        last_date_range = (data_interval_start, _inserted_at)
                else:
                    last_date_range = (first_inserted_at, _inserted_at)
                heartbeat_details.insert_done_range(last_date_range)
                heartbeater.details = tuple(heartbeat_details.serialize_details())
                batch = []

            if len(batch) > 0:
                await flush_to_redshift(batch)

                if len(heartbeat_details.done_ranges) == 0:
                    if data_interval_start is None:
                        last_date_range = (dt.datetime.fromtimestamp(0, tz=dt.UTC), _inserted_at)
                    else:
                        last_date_range = (data_interval_start, _inserted_at)
                else:
                    last_date_range = (first_inserted_at, _inserted_at)

                heartbeat_details.insert_done_range(last_date_range)
                heartbeater.details = tuple(heartbeat_details.serialize_details())

    return total_rows_exported


@dataclasses.dataclass
class RedshiftInsertInputs(PostgresInsertInputs):
    """Inputs for Redshift insert activity.

    Inherit from PostgresInsertInputs as they are the same, but allow
    for setting property_data_type which is unique to Redshift.
    """

    properties_data_type: str = "varchar"


@activity.defn
async def insert_into_redshift_activity(inputs: RedshiftInsertInputs) -> RecordsCompleted:
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
    logger = await configure_temporal_worker_logger(
        logger=structlog.get_logger(), team_id=inputs.team_id, destination="Redshift"
    )
    await logger.ainfo(
        "Batch exporting range %s - %s to Redshift: %s.%s.%s",
        inputs.data_interval_start or "START",
        inputs.data_interval_end or "END",
        inputs.database,
        inputs.schema,
        inputs.table_name,
    )

    async with (
        Heartbeater() as heartbeater,
        set_status_to_running_task(run_id=inputs.run_id, logger=logger),
        get_client(team_id=inputs.team_id) as client,
    ):
        if not await client.is_alive():
            raise ConnectionError("Cannot establish connection to ClickHouse")

        _, details = await should_resume_from_activity_heartbeat(activity, RedshiftHeartbeatDetails, logger)
        if details is None:
            details = RedshiftHeartbeatDetails()

        done_ranges: list[DateRange] = details.done_ranges

        model: BatchExportModel | BatchExportSchema | None = None
        if inputs.batch_export_schema is None and "batch_export_model" in {
            field.name for field in dataclasses.fields(inputs)
        }:
            model = inputs.batch_export_model
            if model is not None:
                model_name = model.name
                extra_query_parameters = model.schema["values"] if model.schema is not None else None
                fields = model.schema["fields"] if model.schema is not None else None
            else:
                model_name = "events"
                extra_query_parameters = None
                fields = None
        else:
            model = inputs.batch_export_schema
            model_name = "custom"
            extra_query_parameters = model["values"] if model is not None else {}
            fields = model["fields"] if model is not None else None

        data_interval_start = (
            dt.datetime.fromisoformat(inputs.data_interval_start) if inputs.data_interval_start else None
        )
        data_interval_end = dt.datetime.fromisoformat(inputs.data_interval_end)
        full_range = (data_interval_start, data_interval_end)

        queue, produce_task = start_produce_batch_export_record_batches(
            client=client,
            model_name=model_name,
            is_backfill=inputs.is_backfill,
            team_id=inputs.team_id,
            full_range=full_range,
            done_ranges=done_ranges,
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            fields=fields,
            destination_default_fields=redshift_default_fields(),
            extra_query_parameters=extra_query_parameters,
        )

        get_schema_task = asyncio.create_task(queue.get_schema())
        await asyncio.wait(
            [get_schema_task, produce_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        # Finishing producing happens sequentially after putting to queue and setting the schema.
        # So, either we finished producing and setting the schema tasks, or we finished without
        # putting anything in the queue.
        if get_schema_task.done():
            # In the first case, we'll land here.
            # The schema is available, and the queue is not empty, so we can start the batch export.
            record_batch_schema = get_schema_task.result()
        else:
            # In the second case, we'll land here: We finished producing without putting anything.
            # Since we finished producing with an empty queue, there is nothing to batch export.
            # We could have also failed, so we need to re-raise that exception to allow a retry if
            # that's the case.
            await raise_on_produce_task_failure(produce_task)
            return 0

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

        requires_merge = (
            isinstance(inputs.batch_export_model, BatchExportModel) and inputs.batch_export_model.name == "persons"
        )
        data_interval_end_str = dt.datetime.fromisoformat(inputs.data_interval_end).strftime("%Y-%m-%d_%H-%M-%S")
        stagle_table_name = (
            f"stage_{inputs.table_name}_{data_interval_end_str}" if requires_merge else inputs.table_name
        )

        if requires_merge:
            primary_key: Fields | None = (("team_id", "INTEGER"), ("distinct_id", "VARCHAR(200)"))
        else:
            primary_key = None

        async with RedshiftClient.from_inputs(inputs).connect() as redshift_client:
            async with (
                redshift_client.managed_table(
                    inputs.schema, inputs.table_name, table_fields, delete=False, primary_key=primary_key
                ) as redshift_table,
                redshift_client.managed_table(
                    inputs.schema,
                    stagle_table_name,
                    table_fields,
                    create=requires_merge,
                    delete=requires_merge,
                    primary_key=primary_key,
                ) as redshift_stage_table,
            ):
                schema_columns = {field[0] for field in table_fields}

                def map_to_record(row: dict) -> tuple[dict, dt.datetime]:
                    """Map row to a record to insert to Redshift."""
                    record = {k: v for k, v in row.items() if k in schema_columns}

                    for column in known_super_columns:
                        if record.get(column, None) is not None:
                            # TODO: We should be able to save a json.loads here.
                            record[column] = remove_escaped_whitespace_recursive(json.loads(record[column]))

                    return record, row["_inserted_at"]

                async def record_generator() -> (
                    collections.abc.AsyncGenerator[tuple[dict[str, typing.Any], dt.datetime], None]
                ):
                    while not queue.empty() or not produce_task.done():
                        try:
                            record_batch = queue.get_nowait()
                        except asyncio.QueueEmpty:
                            if produce_task.done():
                                await logger.adebug(
                                    "Empty queue with no more events being produced, closing consumer loop"
                                )
                                return
                            else:
                                await asyncio.sleep(0.1)
                                continue

                        for record in record_batch.to_pylist():
                            yield map_to_record(record)

                records_completed = await insert_records_to_redshift(
                    record_generator(),
                    redshift_client,
                    inputs.schema,
                    redshift_stage_table if requires_merge else redshift_table,
                    heartbeater=heartbeater,
                    use_super=properties_type == "SUPER",
                    known_super_columns=known_super_columns,
                    heartbeat_details=details,
                    data_interval_start=data_interval_start,
                )

                if requires_merge:
                    merge_key: Fields = (
                        ("team_id", "INT"),
                        ("distinct_id", "TEXT"),
                    )
                    await redshift_client.amerge_identical_tables(
                        final_table_name=redshift_table,
                        stage_table_name=redshift_stage_table,
                        schema=inputs.schema,
                        merge_key=merge_key,
                    )

                return records_completed


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
        data_interval_start, data_interval_end = get_data_interval(inputs.interval, inputs.data_interval_end)
        should_backfill_from_beginning = inputs.is_backfill and inputs.is_earliest_backfill

        start_batch_export_run_inputs = StartBatchExportRunInputs(
            team_id=inputs.team_id,
            batch_export_id=inputs.batch_export_id,
            data_interval_start=data_interval_start.isoformat() if not should_backfill_from_beginning else None,
            data_interval_end=data_interval_end.isoformat(),
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            is_backfill=inputs.is_backfill,
        )
        run_id = await workflow.execute_activity(
            start_batch_export_run,
            start_batch_export_run_inputs,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=RetryPolicy(
                initial_interval=dt.timedelta(seconds=10),
                maximum_interval=dt.timedelta(seconds=60),
                maximum_attempts=0,
                non_retryable_error_types=["NotNullViolation", "IntegrityError"],
            ),
        )

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
            is_backfill=inputs.is_backfill,
            batch_export_model=inputs.batch_export_model,
            batch_export_schema=inputs.batch_export_schema,
        )

        await execute_batch_export_insert_activity(
            insert_into_redshift_activity,
            insert_inputs,
            interval=inputs.interval,
            non_retryable_error_types=[
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
            ],
            finish_inputs=finish_inputs,
        )
