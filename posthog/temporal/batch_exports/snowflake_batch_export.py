import asyncio
import contextlib
import dataclasses
import datetime as dt
import functools
import io
import json
import typing

import snowflake.connector
from django.conf import settings
from snowflake.connector.connection import SnowflakeConnection
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.service import SnowflakeBatchExportInputs
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
from posthog.temporal.common.utils import (
    BatchExportHeartbeatDetails,
    HeartbeatParseError,
    NotEnoughHeartbeatValuesError,
    should_resume_from_activity_heartbeat,
)


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


@dataclasses.dataclass
class SnowflakeHeartbeatDetails(BatchExportHeartbeatDetails):
    """The Snowflake batch export details included in every heartbeat.

    Attributes:
        file_no: The file number of the last file we managed to upload.
    """

    file_no: int

    @classmethod
    def from_activity(cls, activity):
        details = super().from_activity(activity)

        if details.total_details < 2:
            raise NotEnoughHeartbeatValuesError(details.total_details, 2)

        try:
            file_no = int(details._remaining[1])
        except (TypeError, ValueError) as e:
            raise HeartbeatParseError("file_no") from e

        return cls(last_inserted_at=details.last_inserted_at, file_no=file_no, _remaining=details._remaining[2:])


@dataclasses.dataclass
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


def use_namespace(connection: SnowflakeConnection, database: str, schema: str) -> None:
    """Switch to a namespace given by database and schema.

    This allows all queries that follow to ignore database and schema.
    """
    cursor = connection.cursor()
    cursor.execute(f'USE DATABASE "{database}"')
    cursor.execute(f'USE SCHEMA "{schema}"')


@contextlib.contextmanager
def snowflake_connection(inputs) -> typing.Generator[SnowflakeConnection, None, None]:
    """Context manager that yields a Snowflake connection.

    Before yielding we ensure we are in the right namespace, and we set ABORT_DETACHED_QUERY
    to FALSE to avoid Snowflake cancelling any async queries.
    """
    with snowflake.connector.connect(
        user=inputs.user,
        password=inputs.password,
        account=inputs.account,
        warehouse=inputs.warehouse,
        database=inputs.database,
        schema=inputs.schema,
        role=inputs.role,
    ) as connection:
        use_namespace(connection, inputs.database, inputs.schema)
        connection.cursor().execute("SET ABORT_DETACHED_QUERY = FALSE")

        yield connection


async def execute_async_query(
    connection: SnowflakeConnection,
    query: str,
    parameters: dict | None = None,
    file_stream=None,
    poll_interval: float = 1.0,
) -> str:
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

    # Snowflake docs incorrectly state that the 'params' argument is named 'parameters'.
    result = cursor.execute_async(query, params=parameters, file_stream=file_stream)
    query_id = cursor.sfqid or result["queryId"]

    # Snowflake does a blocking HTTP request, so we send it to a thread.
    query_status = await asyncio.to_thread(connection.get_query_status_throw_if_error, query_id)

    while connection.is_still_running(query_status):
        query_status = await asyncio.to_thread(connection.get_query_status_throw_if_error, query_id)
        await asyncio.sleep(poll_interval)

    return query_id


async def create_table_in_snowflake(connection: SnowflakeConnection, table_name: str) -> None:
    """Asynchronously create the table if it doesn't exist.

    Note that we use the same schema as the snowflake-plugin for backwards compatibility."""
    await execute_async_query(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS "{table_name}" (
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
    file_no: int,
):
    """Executes a PUT query using the provided cursor to the provided table_name.

    Sadly, Snowflake's execute_async does not work with PUT statements. So, we pass the execute
    call to run_in_executor: Since execute ends up boiling down to blocking IO (HTTP request),
    the event loop should not be locked up.

    We add a file_no to the file_name when executing PUT as Snowflake will reject any files with the same
    name. Since batch exports re-use the same file, our name does not change, but we don't want Snowflake
    to reject or overwrite our new data.

    Args:
        connection: A SnowflakeConnection object as produced by snowflake.connector.connect.
        file: The name of the local file to PUT.
        table_name: The name of the Snowflake table where to PUT the file.
        file_no: An int to identify which file number this is.

    Raises:
        TypeError: If we don't get a tuple back from Snowflake (should never happen).
        SnowflakeFileNotUploadedError: If the upload status is not 'UPLOADED'.
    """
    file.rewind()

    # We comply with the file-like interface of io.IOBase.
    # So we ask mypy to be nice with us.
    reader = io.BufferedReader(file)  # type: ignore
    query = f'PUT file://{file.name}_{file_no}.jsonl @%"{table_name}"'
    cursor = connection.cursor()

    execute_put = functools.partial(cursor.execute, query, file_stream=reader)

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, func=execute_put)
    reader.detach()  # BufferedReader closes the file otherwise.

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
):
    """Execute a COPY query in Snowflake to load any files PUT into the table.

    The query is executed asynchronously using Snowflake's polling API.

    Args:
        connection: A SnowflakeConnection as returned by snowflake.connector.connect.
        table_name: The table we are COPY-ing files into.
    """
    query = f"""
    COPY INTO "{table_name}"
    FILE_FORMAT = (TYPE = 'JSON')
    MATCH_BY_COLUMN_NAME = CASE_SENSITIVE
    PURGE = TRUE
    """
    query_id = await execute_async_query(connection, query)

    cursor = connection.cursor()
    cursor.get_results_from_sfqid(query_id)
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
                query_result[0] if len(query_result) == 1 else "NO ERROR MESSAGE",
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
    logger = await bind_temporal_worker_logger(team_id=inputs.team_id, destination="Snowflake")
    logger.info(
        "Exporting batch %s - %s",
        inputs.data_interval_start,
        inputs.data_interval_end,
    )

    should_resume, details = await should_resume_from_activity_heartbeat(activity, SnowflakeHeartbeatDetails, logger)

    if should_resume is True and details is not None:
        data_interval_start = details.last_inserted_at.isoformat()
        last_inserted_at = details.last_inserted_at
        file_no = details.file_no
    else:
        data_interval_start = inputs.data_interval_start
        last_inserted_at = None
        file_no = 0

    async with get_client() as client:
        if not await client.is_alive():
            raise ConnectionError("Cannot establish connection to ClickHouse")

        count = await get_rows_count(
            client=client,
            team_id=inputs.team_id,
            interval_start=data_interval_start,
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

        rows_exported = get_rows_exported_metric()
        bytes_exported = get_bytes_exported_metric()

        async def flush_to_snowflake(
            connection: SnowflakeConnection,
            file: BatchExportTemporaryFile,
            table_name: str,
            file_no: int,
            last: bool = False,
        ):
            logger.info(
                "Putting %sfile %s containing %s records with size %s bytes",
                "last " if last else "",
                file_no,
                file.records_since_last_reset,
                file.bytes_since_last_reset,
            )

            await put_file_to_snowflake_table(connection, file, table_name, file_no)
            rows_exported.add(file.records_since_last_reset)
            bytes_exported.add(file.bytes_since_last_reset)

        with snowflake_connection(inputs) as connection:
            await create_table_in_snowflake(connection, inputs.table_name)

            results_iterator = get_results_iterator(
                client=client,
                team_id=inputs.team_id,
                interval_start=inputs.data_interval_start,
                interval_end=inputs.data_interval_end,
                exclude_events=inputs.exclude_events,
                include_events=inputs.include_events,
            )

            result = None

            async def worker_shutdown_handler():
                """Handle the Worker shutting down by heart-beating our latest status."""
                await activity.wait_for_worker_shutdown()
                logger.bind(last_inserted_at=last_inserted_at, file_no=file_no).debug("Worker shutting down!")

                if last_inserted_at is None:
                    # Don't heartbeat if worker shuts down before we could even send anything
                    # Just start from the beginning again.
                    return

                activity.heartbeat(last_inserted_at, file_no)

            asyncio.create_task(worker_shutdown_handler())

            with BatchExportTemporaryFile() as local_results_file:
                for result in results_iterator:
                    record = {
                        "uuid": result["uuid"],
                        "event": result["event"],
                        "properties": result["properties"],
                        "elements": result["elements"],
                        "people_set": result["set"],
                        "people_set_once": result["set_once"],
                        "distinct_id": result["distinct_id"],
                        "team_id": result["team_id"],
                        "ip": result["ip"],
                        "site_url": result["site_url"],
                        "timestamp": result["timestamp"],
                    }
                    local_results_file.write_records_to_jsonl([record])

                    if local_results_file.tell() > settings.BATCH_EXPORT_SNOWFLAKE_UPLOAD_CHUNK_SIZE_BYTES:
                        await flush_to_snowflake(connection, local_results_file, inputs.table_name, file_no)

                        last_inserted_at = result["inserted_at"]
                        file_no += 1

                        activity.heartbeat(last_inserted_at, file_no)

                        local_results_file.reset()

                if local_results_file.tell() > 0 and result is not None:
                    await flush_to_snowflake(connection, local_results_file, inputs.table_name, file_no, last=True)

                    last_inserted_at = result["inserted_at"]
                    file_no += 1

                    activity.heartbeat(last_inserted_at, file_no)

            await copy_loaded_files_to_snowflake_table(connection, inputs.table_name)


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
        )
