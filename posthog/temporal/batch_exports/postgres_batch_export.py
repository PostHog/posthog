import collections.abc
import contextlib
import csv
import datetime as dt
import json
import typing
from dataclasses import dataclass

import psycopg
import pyarrow as pa
from django.conf import settings
from psycopg import sql
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.service import BatchExportField, BatchExportSchema, PostgresBatchExportInputs
from posthog.temporal.batch_exports.base import PostHogWorkflow
from posthog.temporal.batch_exports.batch_exports import (
    BatchExportTemporaryFile,
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
from posthog.temporal.batch_exports.utils import peek_first_and_rewind
from posthog.temporal.common.logger import bind_temporal_worker_logger


@contextlib.asynccontextmanager
async def postgres_connection(inputs) -> typing.AsyncIterator[psycopg.AsyncConnection]:
    """Manage a Postgres connection."""
    kwargs: dict[str, typing.Any] = {}
    if inputs.has_self_signed_cert:
        # Disable certificate verification for self-signed certificates.
        kwargs["sslrootcert"] = None

    connection = await psycopg.AsyncConnection.connect(
        user=inputs.user,
        password=inputs.password,
        dbname=inputs.database,
        host=inputs.host,
        port=inputs.port,
        sslmode="prefer" if settings.TEST else "require",
        **kwargs,
    )

    try:
        yield connection
    except Exception:
        await connection.rollback()
        raise
    else:
        await connection.commit()
    finally:
        await connection.close()


async def copy_tsv_to_postgres(
    tsv_file,
    postgres_connection: psycopg.AsyncConnection,
    schema: str,
    table_name: str,
    schema_columns: list[str],
):
    """Execute a COPY FROM query with given connection to copy contents of tsv_file.

    Arguments:
        tsv_file: A file-like object to interpret as TSV to copy its contents.
        postgres_connection: A connection to Postgres as setup by psycopg.
        schema: An existing schema where to create the table.
        table_name: The name of the table to create.
        schema_columns: A list of column names.
    """
    tsv_file.seek(0)

    async with postgres_connection.cursor() as cursor:
        if schema:
            await cursor.execute(sql.SQL("SET search_path TO {schema}").format(schema=sql.Identifier(schema)))

        async with cursor.copy(
            # TODO: Switch to binary encoding as CSV has a million edge cases.
            sql.SQL("COPY {table_name} ({fields}) FROM STDIN WITH (FORMAT CSV, DELIMITER '\t')").format(
                table_name=sql.Identifier(table_name),
                fields=sql.SQL(",").join((sql.Identifier(column) for column in schema_columns)),
            )
        ) as copy:
            while data := tsv_file.read():
                await copy.write(data)


PostgreSQLField = tuple[str, str]
Fields = collections.abc.Iterable[PostgreSQLField]


async def create_table_in_postgres(
    postgres_connection: psycopg.AsyncConnection, schema: str | None, table_name: str, fields: Fields
) -> None:
    """Create a table in a Postgres database if it doesn't exist already.

    Arguments:
        postgres_connection: A connection to Postgres as setup by psycopg.
        schema: An existing schema where to create the table.
        table_name: The name of the table to create.
        fields: An iterable of (name, type) tuples representing the fields of the table.
    """
    if schema:
        table_identifier = sql.Identifier(schema, table_name)
    else:
        table_identifier = sql.Identifier(table_name)

    async with postgres_connection.cursor() as cursor:
        await cursor.execute(
            sql.SQL(
                """
                CREATE TABLE IF NOT EXISTS {table} (
                    {fields}
                )
                """
            ).format(
                table=table_identifier,
                fields=sql.SQL(",").join(
                    # typing.LiteralString is not available in Python 3.10.
                    # So, we ignore it for now.
                    # This is safe as we are hardcoding the type values anyways.
                    sql.SQL("{field} {type}").format(
                        field=sql.Identifier(field),
                        type=sql.SQL(field_type),
                    )
                    for field, field_type in fields
                ),
            )
        )


def postgres_default_fields() -> list[BatchExportField]:
    batch_export_fields = default_fields()
    batch_export_fields.append(
        {
            "expression": "nullIf(JSONExtractString(properties, '$ip'), '')",
            "alias": "ip",
        }
    )
    # Fields kept or removed for backwards compatibility with legacy apps schema.
    batch_export_fields.append({"expression": "toJSONString(elements_chain)", "alias": "elements"})
    batch_export_fields.append({"expression": "nullIf('', '')", "alias": "site_url"})
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


def get_postgres_fields_from_record_schema(
    record_schema: pa.Schema, known_json_columns: list[str]
) -> list[PostgreSQLField]:
    """Generate a list of supported PostgreSQL fields from PyArrow schema.

    This function is used to map custom schemas to PostgreSQL-supported types. Some loss of precision is
    expected.
    """
    pg_schema: list[PostgreSQLField] = []

    for name in record_schema.names:
        pa_field = record_schema.field(name)

        if pa.types.is_string(pa_field.type):
            if pa_field.name in known_json_columns:
                pg_type = "JSONB"
            else:
                pg_type = "TEXT"

        elif pa.types.is_signed_integer(pa_field.type):
            if pa.types.is_int64(pa_field.type):
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


@dataclass
class PostgresInsertInputs:
    """Inputs for Postgres insert activity."""

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
    """Activity streams data from ClickHouse to Postgres."""
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

        logger.info("BatchExporting %s rows", count)

        if inputs.batch_export_schema is None:
            fields = postgres_default_fields()
            query_parameters = None

        else:
            fields = inputs.batch_export_schema["fields"]
            query_parameters = inputs.batch_export_schema["values"]

        record_iterator = iter_records(
            client=client,
            team_id=inputs.team_id,
            interval_start=inputs.data_interval_start,
            interval_end=inputs.data_interval_end,
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            fields=fields,
            extra_query_parameters=query_parameters,
        )

        if inputs.batch_export_schema is None:
            table_fields = [
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
                ("timestamp", "TIMESTAMP WITH TIME ZONE"),
            ]

        else:
            first_record, record_iterator = peek_first_and_rewind(record_iterator)

            column_names = [column for column in first_record.schema.names if column != "_inserted_at"]
            record_schema = first_record.select(column_names).schema
            table_fields = get_postgres_fields_from_record_schema(
                record_schema, known_json_columns=["properties", "set", "set_once", "person_properties"]
            )

        async with postgres_connection(inputs) as connection:
            await create_table_in_postgres(
                connection,
                schema=inputs.schema,
                table_name=inputs.table_name,
                fields=table_fields,
            )

        schema_columns = [field[0] for field in table_fields]

        rows_exported = get_rows_exported_metric()
        bytes_exported = get_bytes_exported_metric()

        with BatchExportTemporaryFile() as pg_file:
            async with postgres_connection(inputs) as connection:

                async def flush_to_postgres():
                    logger.debug(
                        "Copying %s records of size %s bytes",
                        pg_file.records_since_last_reset,
                        pg_file.bytes_since_last_reset,
                    )
                    await copy_tsv_to_postgres(
                        pg_file,
                        connection,
                        inputs.schema,
                        inputs.table_name,
                        schema_columns,
                    )
                    rows_exported.add(pg_file.records_since_last_reset)
                    bytes_exported.add(pg_file.bytes_since_last_reset)

                for record_batch in record_iterator:
                    for result in record_batch.select(schema_columns).to_pylist():
                        row = result

                        if "elements" in row and inputs.batch_export_schema is None:
                            row["elements"] = json.dumps(row["elements"])

                        pg_file.write_records_to_tsv(
                            [row], fieldnames=schema_columns, quoting=csv.QUOTE_MINIMAL, escapechar=None
                        )

                        if pg_file.tell() > settings.BATCH_EXPORT_POSTGRES_UPLOAD_CHUNK_SIZE_BYTES:
                            await flush_to_postgres()
                            pg_file.reset()

                if pg_file.tell() > 0:
                    await flush_to_postgres()


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
