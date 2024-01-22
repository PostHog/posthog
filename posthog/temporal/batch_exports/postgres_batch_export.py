import collections.abc
import contextlib
import datetime as dt
import json
import typing
from dataclasses import dataclass

import asyncpg
import asyncpg.utils
import pgpq
import pgpq.encoders
import pgpq.schema
import pyarrow as pa
from django.conf import settings
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.service import PostgresBatchExportInputs
from posthog.temporal.batch_exports.base import PostHogWorkflow
from posthog.temporal.batch_exports.batch_exports import (
    BatchExportField,
    BatchExportSchema,
    CreateBatchExportRunInputs,
    UpdateBatchExportRunStatusInputs,
    create_export_run,
    default_fields,
    execute_batch_export_insert_activity,
    get_data_interval,
    get_rows_count,
    iter_records,
)
from posthog.temporal.batch_exports.clickhouse import get_client
from posthog.temporal.batch_exports.metrics import (
    get_bytes_exported_metric,
    get_rows_exported_metric,
)
from posthog.temporal.common.logger import bind_temporal_worker_logger

PgConnection = asyncpg.connection.Connection


@contextlib.asynccontextmanager
async def postgres_connection(inputs) -> typing.AsyncIterator[PgConnection]:
    """Manage a PostgreSQL connection."""
    kwargs: dict[str, typing.Any] = {}
    if inputs.has_self_signed_cert:
        # Disable certificate verification for self-signed certificates.
        kwargs["sslrootcert"] = None

    connection = await asyncpg.connect(
        user=inputs.user,
        password=inputs.password,
        database=inputs.database,
        host=inputs.host,
        port=inputs.port,
        ssl="prefer" if settings.TEST else "require",
        **kwargs,
    )

    try:
        yield connection
    finally:
        await connection.close()


def postgres_export_default_fields() -> list[BatchExportField]:
    """Default fields for a PostgreSQL batch export.

    Starting from the common defualt fields, we add and tweak some fields for
    backwards compatibility.
    """
    batch_export_fields = default_fields()
    batch_export_fields.append(
        {
            "expression": "nullIf(JSONExtractString(properties, '$ip'), '')",
            "alias": "ip",
        }
    )
    # Fields kept for backwards compatibility with legacy apps schema.
    batch_export_fields.append({"expression": "toJSONString(elements_chain)", "alias": "elements"})
    batch_export_fields.append({"expression": "''", "alias": "site_url"})
    # Team ID is (for historical reasons) an INTEGER (4 bytes) in PostgreSQL, but in ClickHouse is stored as Int64.
    # We can't encode it as an Int64, as this includes 4 extra bytes, and PostgreSQL will reject the data with a
    # 'incorrect binary data format' error on the column, so we cast it to Int32.
    team_id_field = batch_export_fields.pop(
        batch_export_fields.index(BatchExportField(expression="team_id", alias="team_id"))
    )
    team_id_field["expression"] = "toInt32(team_id)"
    batch_export_fields.append(team_id_field)
    return batch_export_fields


TableColumn = tuple[str, str]
TableColumns = list[TableColumn]


def infer_table_columns_from_record_schema(record_schema: pa.Schema) -> TableColumns:
    """Generate a list of supported PostgreSQL fields from PyArrow schema.

    This function is used to map custom schemas to PostgreSQL-supported types. Some loss of precision is
    expected.
    """
    pg_schema: TableColumns = []

    encoder = pgpq.ArrowToPostgresBinaryEncoder(record_schema)
    for column_name, column in encoder.schema().columns:
        column_type = column.data_type.ddl()

        if column_type == "TIMESTAMP" and record_schema.field(column_name).type.tz is not None:
            column_type += "TZ"

        nullable = "" if column.nullable else " NOT NULL"
        pg_schema.append((column_name, f"{column_type}{nullable}"))

    return pg_schema


async def create_table_in_postgres(
    postgres_connection: PgConnection,
    schema_name: str | None,
    table_name: str,
    table_columns: TableColumns,
) -> None:
    """Create a table in a Postgres database if it doesn't exist already.

    Arguments:
        postgres_connection: A connection to Postgres as setup by psycopg.
        schema_name: An existing schema where to create the table.
        table_name: The name of the table to create.
        fields: An iterable of (name, type) tuples representing the fields of the table.
    """
    create_table_query = """
        CREATE TABLE IF NOT EXISTS {table}(
            {fields}
        )
        """.format(
        table=asyncpg.utils._quote_ident(schema_name) + "." + asyncpg.utils._quote_ident(table_name),
        fields=",\n".join(
            "{field} {type}".format(
                field=asyncpg.utils._quote_ident(field),
                type=field_type,
            )
            for field, field_type in table_columns
        ),
    )

    await postgres_connection.execute(create_table_query)


T = typing.TypeVar("T")


async def peek_first_and_rewind(
    gen: collections.abc.AsyncGenerator[T, None]
) -> tuple[T, collections.abc.AsyncGenerator[T, None]]:
    """Peek into the first element in a generator and rewind the advance.

    The generator is advanced and cannot be reversed, so we create a new one that first
    yields the element we popped before yielding the rest of the generator.

    Returns:
        A tuple with the first element of the generator and the generator itself.
    """
    first = await anext(gen)

    async def rewind_gen() -> collections.abc.AsyncGenerator[T, None]:
        """Yield the item we popped to rewind the generator."""
        yield first
        async for i in gen:
            yield i

    return (first, rewind_gen())


BytesGenerator = collections.abc.AsyncGenerator[bytes, None]
RecordsGenerator = collections.abc.AsyncGenerator[pa.RecordBatch, None]


async def encode_records_generator(
    records: RecordsGenerator,
    column_names: list[str],
) -> BytesGenerator:
    """Generator that yields records encoded in PostgreSQL binary format.

    Certain string fields are encoded as JSONB.
    """
    first_record_batch, records = await peek_first_and_rewind(records)
    record_schema = first_record_batch.select(column_names).schema

    encoders_for_known_fields = {
        "properties": pgpq.encoders.StringEncoderBuilder.new_with_output(
            pa.field("properties", pa.string()), pgpq.schema.Jsonb()
        ),
        "set": pgpq.encoders.StringEncoderBuilder.new_with_output(pa.field("set", pa.string()), pgpq.schema.Jsonb()),
        "set_once": pgpq.encoders.StringEncoderBuilder.new_with_output(
            pa.field("set_once", pa.string()), pgpq.schema.Jsonb()
        ),
        "elements": pgpq.encoders.StringEncoderBuilder.new_with_output(
            pa.field("elements", pa.string()), pgpq.schema.Jsonb()
        ),
    }
    encoders = {
        field.name: pgpq.ArrowToPostgresBinaryEncoder.infer_encoder(field)
        if field.name not in encoders_for_known_fields
        else encoders_for_known_fields[field.name]
        for field in record_schema
    }

    encoder = pgpq.ArrowToPostgresBinaryEncoder.new_with_encoders(record_schema, encoders)

    header = encoder.write_header()
    yield header

    async for record_batch in records:
        encoded = encoder.write_batch(record_batch.select(column_names))
        yield encoded

    finisher = encoder.finish()
    yield finisher


async def copy_records_to_postgres(
    postgres_connection: PgConnection,
    records: RecordsGenerator,
    schema_name: str,
    table_name: str,
    table_columns: TableColumns,
    logger,
) -> tuple[int, int]:
    """Copy records to PostgreSQL table using binary format.

    Arguments:
        postgres_connection: A connection to PostgreSQL as setup by asyncpg.
        records: Iterator of records to copy to PostgreSQL table.
        schema_name: An existing schema where the table to copy to resides.
        table_name: The name of the table to copy to.
        schema_columns: A list of column names.

    References:
        PostgreSQL COPY: https://www.postgresql.org/docs/current/sql-copy.html
    """
    column_names = [column[0] for column in table_columns]

    n_rows = 0
    n_bytes = 0

    async def track_rows_generator(
        records: RecordsGenerator,
    ) -> RecordsGenerator:
        """Yield from a generator of RecordBatches, tracking of the rows in each one."""
        nonlocal n_rows

        async for record in records:
            n_rows += record.num_rows

            yield record

    async def track_bytes_generator(
        encoded: BytesGenerator,
    ) -> BytesGenerator:
        """Yield from a generator of bytes, tracking the length of bytes."""
        nonlocal n_bytes

        async for b in encoded:
            n_bytes += len(b)

            yield b

    encoded_records_pipeline = track_bytes_generator(
        encode_records_generator(track_rows_generator(records), column_names)
    )

    result = await postgres_connection.copy_to_table(
        table_name, source=encoded_records_pipeline, format="binary", columns=column_names, schema_name=schema_name
    )

    try:
        # Parsing the resulting 'COPY XXXX'
        result_n_rows = int(result.split(" ")[1])
    except ValueError:
        pass
    else:
        if result_n_rows != n_rows:
            # This could be a problem with the underlying COPY or encoding.
            # But let's only log it for now, hopefully this never fires.
            logger.warning(f"Rows copied to PostgreSQL (%s) differ from expected (%s)", result_n_rows, n_rows)

    return n_rows, n_bytes


@dataclass
class PostgresInsertInputs:
    """Inputs for Postgres insert activity.

    Attributes:
        team_id: The ID of the team we are batch exporting to.
        user: The user used for authentication in PostgreSQL.
        password: The password for the user.
        host: The host of the PostgreSQL instance.
        database: The database where to export data.
        table_name: The name of the table where to export data. If it doesn't exist, it
            will be created.
        data_interval_start: Start of the batch export interval. Needs to be JSON
            serializable so it should come from a `datetime.datetime.isoformat()`.
        data_interval_end: Start of the batch export interval. Needs to be JSON
            serializable so it should come from a `datetime.datetime.isoformat()`.
        has_self_signed_cert:
        schema: The name of the schema where to export data.
        port: The port where the PostgresSQL instance listens on.
        exclude_events: A list of event names to exclude from the export. If `None` or
            empty, all events will be exported.
        include_events: A list of event names to include in the export.
        batch_export_schema: A dictionary specifying the schema for a batch export.
    """

    team_id: int
    user: str
    password: str
    host: str
    database: str
    table_name: str
    data_interval_start: str
    data_interval_end: str
    has_self_signed_cert: bool = False
    schema: str = "public"
    port: int = 5432
    exclude_events: list[str] | None = None
    include_events: list[str] | None = None
    batch_export_schema: BatchExportSchema | None = None


@activity.defn
async def insert_into_postgres_activity(inputs: PostgresInsertInputs):
    """Activity to batch export data from ClickHouse to PostgreSQL.

    For historical reasons, this activity is called `insert_*` but the underlying
    operation is a PostgreSQL COPY.

    A PostgreSQL table need not exist as one will be created. However, schema changes
    are not (yet) supported to the point no schema checks are done on an existing table:
    If it exists, we assume it matches the input's `batch_export_schema`.

    Arguments:
        inputs: See `PostgresInsertInputs`.

    Returns:
        A tuple with the number of records and bytes exported.
    """
    logger = await bind_temporal_worker_logger(team_id=inputs.team_id, destination="PostgreSQL")
    logger.info(
        "Exporting batch %s - %s",
        inputs.data_interval_start,
        inputs.data_interval_end,
    )

    async with get_client() as client:
        if not await client.is_alive():
            raise ConnectionError("Cannot establish connection to ClickHouse")

        count = await get_rows_count(
            client=client,
            team_id=inputs.team_id,
            interval_start=inputs.data_interval_start,
            interval_end=inputs.data_interval_end,
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
        )

        if count == 0:
            logger.info(
                "Nothing to export in batch %s - %s",
                inputs.data_interval_start,
                inputs.data_interval_end,
            )
            return

        logger.info(
            "Exporting %s rows in batch %s - %s",
            count,
            inputs.data_interval_start,
            inputs.data_interval_end,
        )

        if inputs.batch_export_schema is None:
            batch_export_fields = postgres_export_default_fields()
            extra_query_parameters = {}

        else:
            batch_export_fields = inputs.batch_export_schema["fields"]
            extra_query_parameters = inputs.batch_export_schema["values"]

        records_iterator = iter_records(
            client=client,
            team_id=inputs.team_id,
            interval_start=inputs.data_interval_start,
            interval_end=inputs.data_interval_end,
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            fields=batch_export_fields,
            extra_query_parameters=extra_query_parameters,
        )

        rows_exported = get_rows_exported_metric()
        bytes_exported = get_bytes_exported_metric()

        async with postgres_connection(inputs) as connection:
            first_record, records_iterator = await peek_first_and_rewind(records_iterator)

            if inputs.batch_export_schema is None:
                table_columns = [
                    ("uuid", "VARCHAR(200)"),
                    ("event", "VARCHAR(200)"),
                    ("properties", "JSONB"),
                    ("elements", "JSONB"),
                    ("set", "JSONB"),
                    ("set_once", "JSONB"),
                    ("distinct_id", "VARCHAR(200)"),
                    ("team_id", "INTEGER"),
                    ("ip", "VARCHAR(200)"),
                    ("site_url", "VARCHAR(200)"),
                    ("timestamp", "TIMESTAMPTZ"),
                ]
            else:
                table_columns = infer_table_columns_from_record_schema(first_record.schema)

            await create_table_in_postgres(
                connection,
                schema_name=inputs.schema,
                table_name=inputs.table_name,
                table_columns=table_columns,
            )

            n_records, n_bytes = await copy_records_to_postgres(
                connection,
                records_iterator,
                schema_name=inputs.schema,
                table_name=inputs.table_name,
                table_columns=table_columns,
                logger=logger,
            )

        logger.info(
            "Fishined batch %s - %s with %s rows and %s bytes exported",
            inputs.data_interval_start,
            inputs.data_interval_end,
            n_records,
            n_bytes,
        )

        rows_exported.add(n_records)
        bytes_exported.add(n_bytes)

        return n_records, n_bytes


@workflow.defn(name="postgres-export")
class PostgresBatchExportWorkflow(PostHogWorkflow):
    """A Temporal Workflow to export ClickHouse data into Postgres.

    This Workflow is intended to be executed both manually and by a Temporal
    Schedule. When ran by a schedule, `data_interval_end` should be set to
    `None` so that we will fetch the end of the interval from the Temporal
    search attribute `TemporalScheduledStartTime`.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> PostgresBatchExportInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return PostgresBatchExportInputs(**loaded)

    @workflow.run
    async def run(self, inputs: PostgresBatchExportInputs):
        """Workflow implementation to export data to Postgres."""
        data_interval_start, data_interval_end = get_data_interval(inputs.interval, inputs.data_interval_end)

        create_export_run_inputs = CreateBatchExportRunInputs(
            team_id=inputs.team_id,
            batch_export_id=inputs.batch_export_id,
            data_interval_start=data_interval_start.isoformat(),
            data_interval_end=data_interval_end.isoformat(),
        )
        run_id = await workflow.execute_activity(
            create_export_run,
            create_export_run_inputs,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=RetryPolicy(
                initial_interval=dt.timedelta(seconds=10),
                maximum_interval=dt.timedelta(seconds=60),
                maximum_attempts=0,
                non_retryable_error_types=["NotNullViolation", "IntegrityError"],
            ),
        )

        update_inputs = UpdateBatchExportRunStatusInputs(
            id=run_id,
            status="Completed",
            team_id=inputs.team_id,
        )

        insert_inputs = PostgresInsertInputs(
            team_id=inputs.team_id,
            user=inputs.user,
            password=inputs.password,
            host=inputs.host,
            port=inputs.port,
            database=inputs.database,
            schema=inputs.schema,
            table_name=inputs.table_name,
            has_self_signed_cert=inputs.has_self_signed_cert,
            data_interval_start=data_interval_start.isoformat(),
            data_interval_end=data_interval_end.isoformat(),
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            batch_export_schema=inputs.batch_export_schema,
        )

        await execute_batch_export_insert_activity(
            insert_into_postgres_activity,
            insert_inputs,
            non_retryable_error_types=[
                # Raised on errors that are related to database operation.
                # For example: unexpected disconnect, database or other object not found.
                "OperationalError"
                # The schema name provided is invalid (usually because it doesn't exist).
                "InvalidSchemaName"
                # Missing permissions to, e.g., insert into table.
                "InsufficientPrivilege"
            ],
            update_inputs=update_inputs,
            # Disable heartbeat timeout until we add heartbeat support.
            heartbeat_timeout_seconds=None,
        )
