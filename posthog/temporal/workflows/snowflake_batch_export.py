import asyncio
import contextlib
import datetime as dt
import json
import typing
from dataclasses import dataclass

import snowflake.connector
from django.conf import settings
from snowflake.connector.connection import SnowflakeConnection
from snowflake.connector.cursor import SnowflakeCursor
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.service import SnowflakeBatchExportInputs
from posthog.temporal.workflows.base import PostHogWorkflow
from posthog.temporal.workflows.batch_exports import (
    BatchExportTemporaryFile,
    CreateBatchExportRunInputs,
    UpdateBatchExportRunStatusInputs,
    create_export_run,
    execute_batch_export_insert_activity,
    get_batch_exports_logger,
    get_data_interval,
    get_results_iterator,
    get_rows_count,
)
from posthog.temporal.workflows.clickhouse import get_client


class SnowflakeFileNotUploadedError(Exception):
    """Raised when a PUT Snowflake query fails to upload a file."""

    def __init__(self, table_name: str, status: str, message: str):
        super().__init__(
            f"Snowflake upload for table '{table_name}' expected status 'UPLOADED' but got '{status}': {message}"
        )


class SnowflakeFileNotLoadedError(Exception):
    """Raised when a COPY INTO Snowflake query fails to copy a file to a table."""

    def __init__(self, table_name: str, status: str, errors_seen: int, first_error: str):
        super().__init__(
            f"Snowflake load for table '{table_name}' expected status 'LOADED' but got '{status}' with {errors_seen} errors: {first_error}"
        )


@dataclass
class SnowflakeInsertInputs:
    """Inputs for Snowflake."""

    # TODO: do _not_ store credentials in temporal inputs. It makes it very hard
    # to keep track of where credentials are being stored and increases the
    # attach surface for credential leaks.

    team_id: int
    user: str
    password: str
    account: str
    database: str
    warehouse: str
    schema: str
    table_name: str
    data_interval_start: str
    data_interval_end: str
    role: str | None = None
    exclude_events: list[str] | None = None
    include_events: list[str] | None = None


@contextlib.contextmanager
def snowflake_connection(inputs) -> typing.Generator[SnowflakeConnection, None, None]:
    with snowflake.connector.connect(
        user=inputs.user,
        password=inputs.password,
        account=inputs.account,
        warehouse=inputs.warehouse,
        database=inputs.database,
        schema=inputs.schema,
        role=inputs.role,
    ) as connection:
        yield connection


async def execute_async_query(
    connection: SnowflakeConnection, query: str, parameters: dict | None = None, poll_interval: float = 1.0
) -> SnowflakeCursor:
    """Wrap Snowflake connector's polling API in a coroutine.

    This enables asynchronous execution of queries to release the event loop to execute other tasks
    while we poll for a query to be done. For example, the event loop may use this time for heartbeating.

    Args:
        connection: A SnowflakeConnection object as produced by snowflake.connector.connect.
        query: A query string to run asynchronously.
        parameters: An optional dictionary of parameters to bind to the query.
        poll_interval: Specify how long to wait in between polls.
    """
    cursor = connection.cursor()

    cursor.execute_async(query, parameters or {})

    try:
        query_id = cursor.sfqid

        while connection.is_still_running(connection.get_query_status_throw_if_error(query_id)):
            await asyncio.sleep(poll_interval)

    except snowflake.connector.ProgrammingError:
        # TODO: logging
        raise

    else:
        cursor.get_results_from_sfqid(query_id)

    finally:
        pass

    return cursor


async def create_table_in_snowflake(conn: SnowflakeConnection, database: str, schema: str, table_name: str) -> None:
    """Asynchronously create the table if it doesn't exist.

    Note that we use the same schema as the snowflake-plugin for backwards compatibility."""
    await execute_async_query(
        conn,
        f"""
        CREATE TABLE IF NOT EXISTS "{database}"."{schema}"."{table_name}" (
            "uuid" STRING,
            "event" STRING,
            "properties" VARIANT,
            "elements" VARIANT,
            "people_set" VARIANT,
            "people_set_once" VARIANT,
            "distinct_id" STRING,
            "team_id" INTEGER,
            "ip" STRING,
            "site_url" STRING,
            "timestamp" TIMESTAMP
        )
        COMMENT = 'PostHog generated events table'
        """,
    )


async def put_file_to_snowflake_table(
    connection: SnowflakeConnection,
    file: BatchExportTemporaryFile,
    table_name: str,
    database: str | None = None,
    schema: str | None = None,
):
    """Executes a PUT query using the provided cursor to the provided table_name.

    Args:
        connection: A SnowflakeConnection object as produced by snowflake.connector.connect.
        file: The name of the local file to PUT.
        table_name: The name of the Snowflake table where to PUT the file.

    Raises:
        TypeError: If we don't get a tuple back from Snowflake (should never happen).
        SnowflakeFileNotUploadedError: If the upload status is not 'UPLOADED'.
    """
    file.flush()

    if database is not None and schema is not None:
        namespace = f"{database}.{schema}."
    else:
        namespace = ""

    cursor = await execute_async_query(
        connection,
        f"""
        PUT file://{file.name} @%{namespace}"{table_name}"
        """,
    )

    result = cursor.fetchone()
    if not isinstance(result, tuple):
        # Mostly to appease mypy, as this query should always return a tuple.
        raise TypeError(f"Expected tuple from Snowflake PUT query but got: '{result.__class__.__name__}'")

    status, message = result[6:8]
    if status != "UPLOADED":
        raise SnowflakeFileNotUploadedError(table_name, status, message)


async def copy_loaded_files_to_snowflake_table(
    connection: SnowflakeConnection,
    table_name: str,
    database: str | None = None,
    schema: str | None = None,
):
    if database is not None and schema is not None:
        namespace = f"{database}.{schema}."
    else:
        namespace = ""

    cursor = await execute_async_query(
        connection,
        f"""
            COPY INTO {namespace}"{table_name}"
            FILE_FORMAT = (TYPE = 'JSON')
            MATCH_BY_COLUMN_NAME = CASE_SENSITIVE
            PURGE = TRUE
            """,
    )
    results = cursor.fetchall()

    for query_result in results:
        if not isinstance(query_result, tuple):
            # Mostly to appease mypy, as this query should always return a tuple.
            raise TypeError(f"Expected tuple from Snowflake COPY INTO query but got: '{type(query_result)}'")

        if len(query_result) < 2:
            raise SnowflakeFileNotLoadedError(
                table_name,
                "NO STATUS",
                0,
                query_result[1] if len(query_result) == 1 else "NO ERROR MESSAGE",
            )

        _, status = query_result[0:2]

        if status != "LOADED":
            errors_seen, first_error = query_result[5:7]
            raise SnowflakeFileNotLoadedError(
                table_name,
                status or "NO STATUS",
                errors_seen or 0,
                first_error or "NO ERROR MESSAGE",
            )


@activity.defn
async def insert_into_snowflake_activity(inputs: SnowflakeInsertInputs):
    """Activity streams data from ClickHouse to Snowflake.

    TODO: We're using JSON here, it's not the most efficient way to do this.
    """
    logger = get_batch_exports_logger(inputs=inputs)
    logger.info(
        "Running Snowflake export batch %s - %s",
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

        logger.info("BatchExporting %s rows to Snowflake", count)

        with snowflake_connection(inputs) as connection:
            await create_table_in_snowflake(connection, inputs.database, inputs.schema, inputs.table_name)

            results_iterator = get_results_iterator(
                client=client,
                team_id=inputs.team_id,
                interval_start=inputs.data_interval_start,
                interval_end=inputs.data_interval_end,
                exclude_events=inputs.exclude_events,
                include_events=inputs.include_events,
            )

            result = None
            last_uploaded_file_timestamp = None

            async def worker_shutdown_handler():
                """Handle the Worker shutting down by heart-beating our latest status."""
                await activity.wait_for_worker_shutdown()
                logger.warn(
                    f"Worker shutting down! Reporting back latest exported part {last_uploaded_file_timestamp}",
                )
                activity.heartbeat(last_uploaded_file_timestamp)

            asyncio.create_task(worker_shutdown_handler())

            with BatchExportTemporaryFile() as local_results_file:
                for result in results_iterator:
                    local_results_file.write_records_to_jsonl([result])

                    if local_results_file.tell() > settings.BATCH_EXPORT_SNOWFLAKE_UPLOAD_CHUNK_SIZE_BYTES:
                        logger.info(
                            "Putting file containing %s records with size %s bytes",
                            local_results_file.records_since_last_reset,
                            local_results_file.bytes_since_last_reset,
                        )

                        await put_file_to_snowflake_table(
                            connection, local_results_file, inputs.table_name, inputs.database, inputs.schema
                        )

                        last_uploaded_file_timestamp = result["inserted_at"]
                        activity.heartbeat(last_uploaded_file_timestamp)

                        local_results_file.reset()

                if local_results_file.tell() > 0 and result is not None:
                    logger.info(
                        "Putting last file containing %s records with size %s bytes",
                        local_results_file.records_since_last_reset,
                        local_results_file.bytes_since_last_reset,
                    )
                    last_uploaded_file_timestamp = result["inserted_at"]

                    await put_file_to_snowflake_table(
                        connection, local_results_file, inputs.table_name, inputs.database, inputs.schema
                    )

                    last_uploaded_file_timestamp = result["inserted_at"]
                    activity.heartbeat(last_uploaded_file_timestamp)

            await copy_loaded_files_to_snowflake_table(connection, inputs.table_name, inputs.database, inputs.schema)


@workflow.defn(name="snowflake-export")
class SnowflakeBatchExportWorkflow(PostHogWorkflow):
    """A Temporal Workflow to export ClickHouse data into Snowflake.

    This Workflow is intended to be executed both manually and by a Temporal
    Schedule. When ran by a schedule, `data_interval_end` should be set to
    `None` so that we will fetch the end of the interval from the Temporal
    search attribute `TemporalScheduledStartTime`.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> SnowflakeBatchExportInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return SnowflakeBatchExportInputs(**loaded)

    @workflow.run
    async def run(self, inputs: SnowflakeBatchExportInputs):
        """Workflow implementation to export data to Snowflake table."""
        logger = get_batch_exports_logger(inputs=inputs)
        data_interval_start, data_interval_end = get_data_interval(inputs.interval, inputs.data_interval_end)
        logger.info(
            "Starting Snowflake export batch %s - %s",
            data_interval_start,
            data_interval_end,
        )

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

        update_inputs = UpdateBatchExportRunStatusInputs(id=run_id, status="Completed")

        insert_inputs = SnowflakeInsertInputs(
            team_id=inputs.team_id,
            user=inputs.user,
            password=inputs.password,
            account=inputs.account,
            warehouse=inputs.warehouse,
            database=inputs.database,
            schema=inputs.schema,
            table_name=inputs.table_name,
            data_interval_start=data_interval_start.isoformat(),
            data_interval_end=data_interval_end.isoformat(),
            role=inputs.role,
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
        )

        await execute_batch_export_insert_activity(
            insert_into_snowflake_activity,
            insert_inputs,
            non_retryable_error_types=[
                # Raised when we cannot connect to Snowflake.
                "DatabaseError",
                # Raised by Snowflake when a query cannot be compiled.
                # Usually this means we don't have table permissions or something doesn't exist (db, schema).
                "ProgrammingError",
                # Raised by Snowflake with an incorrect account name.
                "ForbiddenError",
            ],
            update_inputs=update_inputs,
            # Disable heartbeat timeout until we add heartbeat support.
            heartbeat_timeout_seconds=None,
        )
