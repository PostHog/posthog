import collections.abc
import contextlib
import datetime as dt
import json
import typing
from dataclasses import dataclass

import psycopg
from django.conf import settings
from psycopg import sql
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.service import PostgresBatchExportInputs
from posthog.temporal.batch_exports.base import PostHogWorkflow
from posthog.temporal.batch_exports.batch_exports import (
    BatchExportTemporaryFile,
    CreateBatchExportRunInputs,
    UpdateBatchExportRunStatusInputs,
    create_export_run,
    execute_batch_export_insert_activity,
    get_data_interval,
    get_results_iterator,
    get_rows_count,
)
from posthog.temporal.batch_exports.clickhouse import get_client
from posthog.temporal.common.logger import bind_temporal_worker_logger
from posthog.temporal.batch_exports.metrics import (
    get_bytes_exported_metric,
    get_rows_exported_metric,
)


@contextlib.asynccontextmanager
async def postgres_connection(inputs) -> typing.AsyncIterator[psycopg.AsyncConnection]:
    """Manage a Postgres connection."""
    connection = await psycopg.AsyncConnection.connect(
        user=inputs.user,
        password=inputs.password,
        dbname=inputs.database,
        host=inputs.host,
        port=inputs.port,
        # The 'hasSelfSignedCert' parameter in the postgres-plugin was provided mainly
        # for users of Heroku and RDS. It was used to set 'rejectUnauthorized' to false if a self-signed cert was used.
        # Mapping this to sslmode is not straight-forward, but going by Heroku's recommendation (see below) we should use 'disable'.
        # Reference: https://devcenter.heroku.com/articles/connecting-heroku-postgres#connecting-in-node-js
        sslmode="disable" if inputs.has_self_signed_cert is True else "prefer",
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
                sql.SQL("COPY {table_name} ({fields}) FROM STDIN WITH DELIMITER AS '\t'").format(
                    table_name=sql.Identifier(table_name),
                    fields=sql.SQL(",").join((sql.Identifier(column) for column in schema_columns)),
                )
            ) as copy:
                while data := tsv_file.read():
                    await copy.write(data)


Field = tuple[str, str]
Fields = collections.abc.Iterable[Field]


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

        results_iterator = get_results_iterator(
            client=client,
            team_id=inputs.team_id,
            interval_start=inputs.data_interval_start,
            interval_end=inputs.data_interval_end,
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
        )
        async with postgres_connection(inputs) as connection:
            await create_table_in_postgres(
                connection,
                schema=inputs.schema,
                table_name=inputs.table_name,
                fields=[
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
                ],
            )

        schema_columns = [
            "uuid",
            "event",
            "properties",
            "elements",
            "set",
            "set_once",
            "distinct_id",
            "team_id",
            "ip",
            "site_url",
            "timestamp",
        ]
        json_columns = ("properties", "elements", "set", "set_once")

        rows_exported = get_rows_exported_metric()
        bytes_exported = get_bytes_exported_metric()

        with BatchExportTemporaryFile() as pg_file:
            async with postgres_connection(inputs) as connection:
                for result in results_iterator:
                    row = {
                        key: json.dumps(result[key]) if key in json_columns else result[key] for key in schema_columns
                    }
                    pg_file.write_records_to_tsv([row], fieldnames=schema_columns)

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

                for result in results_iterator:
                    row = {
                        key: json.dumps(result[key]) if key in json_columns and result[key] is not None else result[key]
                        for key in schema_columns
                    }
                    pg_file.write_records_to_tsv([row], fieldnames=schema_columns)

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
