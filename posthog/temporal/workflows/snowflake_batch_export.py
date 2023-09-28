import datetime as dt
import json
import tempfile
from dataclasses import dataclass

import snowflake.connector
from django.conf import settings
from snowflake.connector.cursor import SnowflakeCursor
from temporalio import activity, exceptions, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.service import SnowflakeBatchExportInputs
from posthog.temporal.workflows.base import (
    CreateBatchExportRunInputs,
    PostHogWorkflow,
    UpdateBatchExportRunStatusInputs,
    create_export_run,
    update_export_run_status,
)
from posthog.temporal.workflows.batch_exports import (
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


def put_file_to_snowflake_table(cursor: SnowflakeCursor, file_name: str, table_name: str):
    """Executes a PUT query using the provided cursor to the provided table_name.

    Args:
        cursor: A Snowflake cursor to execute the PUT query.
        file_name: The name of the file to PUT.
        table_name: The name of the table where to PUT the file.

    Raises:
        TypeError: If we don't get a tuple back from Snowflake (should never happen).
        SnowflakeFileNotUploadedError: If the upload status is not 'UPLOADED'.
    """
    cursor.execute(
        f"""
        PUT file://{file_name} @%"{table_name}"
        """
    )
    result = cursor.fetchone()
    if not isinstance(result, tuple):
        # Mostly to appease mypy, as this query should always return a tuple.
        raise TypeError(f"Expected tuple from Snowflake PUT query but got: '{result.__class__.__name__}'")

    status, message = result[6:8]
    if status != "UPLOADED":
        raise SnowflakeFileNotUploadedError(table_name, status, message)


@activity.defn
async def insert_into_snowflake_activity(inputs: SnowflakeInsertInputs):
    """Activity streams data from ClickHouse to Snowflake.

    TODO: We're using JSON here, it's not the most efficient way to do this.
    """
    activity.logger.info("Running Snowflake export batch %s - %s", inputs.data_interval_start, inputs.data_interval_end)

    async with get_client() as client:
        if not await client.is_alive():
            raise ConnectionError("Cannot establish connection to ClickHouse")

        count = await get_rows_count(
            client=client,
            team_id=inputs.team_id,
            interval_start=inputs.data_interval_start,
            interval_end=inputs.data_interval_end,
        )

        if count == 0:
            activity.logger.info(
                "Nothing to export in batch %s - %s. Exiting.",
                inputs.data_interval_start,
                inputs.data_interval_end,
            )
            return

        activity.logger.info("BatchExporting %s rows to Snowflake", count)

        conn = snowflake.connector.connect(
            user=inputs.user,
            password=inputs.password,
            account=inputs.account,
            warehouse=inputs.warehouse,
            database=inputs.database,
            schema=inputs.schema,
            role=inputs.role,
        )

        try:
            cursor = conn.cursor()
            cursor.execute(f'USE DATABASE "{inputs.database}"')
            cursor.execute(f'USE SCHEMA "{inputs.schema}"')

            # Create the table if it doesn't exist. Note that we use the same schema
            # as the snowflake-plugin for backwards compatibility.
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS "{inputs.database}"."{inputs.schema}"."{inputs.table_name}" (
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
                """
            )

            results_iterator = get_results_iterator(
                client=client,
                team_id=inputs.team_id,
                interval_start=inputs.data_interval_start,
                interval_end=inputs.data_interval_end,
            )
            result = None
            local_results_file = tempfile.NamedTemporaryFile(suffix=".jsonl")
            try:
                while True:
                    try:
                        result = results_iterator.__next__()

                    except StopIteration:
                        break

                    except json.JSONDecodeError:
                        activity.logger.info(
                            "Failed to decode a JSON value while iterating, potentially due to a ClickHouse error"
                        )
                        # This is raised by aiochclient as we try to decode an error message from ClickHouse.
                        # So far, this error message only indicated that we were too slow consuming rows.
                        # So, we can resume from the last result.
                        if result is None:
                            # We failed right at the beginning
                            new_interval_start = None
                        else:
                            new_interval_start = result.get("inserted_at", None)

                        if not isinstance(new_interval_start, str):
                            new_interval_start = inputs.data_interval_start

                        results_iterator = get_results_iterator(
                            client=client,
                            team_id=inputs.team_id,
                            interval_start=new_interval_start,  # This means we'll generate at least one duplicate.
                            interval_end=inputs.data_interval_end,
                        )
                        continue

                    if not result:
                        break

                    # Write the results to a local file
                    local_results_file.write(json.dumps(result).encode("utf-8"))
                    local_results_file.write("\n".encode("utf-8"))

                    # Write results to Snowflake when the file reaches 50MB and
                    # reset the file, or if there is nothing else to write.
                    if (
                        local_results_file.tell()
                        and local_results_file.tell() > settings.BATCH_EXPORT_SNOWFLAKE_UPLOAD_CHUNK_SIZE_BYTES
                    ):
                        activity.logger.info("Uploading to Snowflake")

                        # Flush the file to make sure everything is written
                        local_results_file.flush()
                        put_file_to_snowflake_table(cursor, local_results_file.name, inputs.table_name)

                        # Delete the temporary file and create a new one
                        local_results_file.close()
                        local_results_file = tempfile.NamedTemporaryFile(suffix=".jsonl")

                # Flush the file to make sure everything is written
                local_results_file.flush()
                put_file_to_snowflake_table(cursor, local_results_file.name, inputs.table_name)

                # We don't need the file anymore, close (and delete) it.
                local_results_file.close()
                cursor.execute(
                    f"""
                    COPY INTO "{inputs.table_name}"
                    FILE_FORMAT = (TYPE = 'JSON')
                    MATCH_BY_COLUMN_NAME = CASE_SENSITIVE
                    PURGE = TRUE
                    """
                )
                results = cursor.fetchall()

                for query_result in results:
                    if not isinstance(query_result, tuple):
                        # Mostly to appease mypy, as this query should always return a tuple.
                        raise TypeError(f"Expected tuple from Snowflake COPY INTO query but got: '{type(result)}'")

                    if len(query_result) < 2:
                        raise SnowflakeFileNotLoadedError(
                            inputs.table_name,
                            "NO STATUS",
                            0,
                            query_result[1] if len(query_result) == 1 else "NO ERROR MESSAGE",
                        )

                    _, status = query_result[0:2]

                    if status != "LOADED":
                        errors_seen, first_error = query_result[5:7]
                        raise SnowflakeFileNotLoadedError(
                            inputs.table_name,
                            status or "NO STATUS",
                            errors_seen or 0,
                            first_error or "NO ERROR MESSAGE",
                        )

            finally:
                local_results_file.close()
        finally:
            conn.close()


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
        """Workflow implementation to export data to S3 bucket."""
        workflow.logger.info("Starting S3 export")

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
        )
        try:
            await workflow.execute_activity(
                insert_into_snowflake_activity,
                insert_inputs,
                start_to_close_timeout=dt.timedelta(hours=1),
                retry_policy=RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(seconds=120),
                    maximum_attempts=10,
                    non_retryable_error_types=[
                        # Raised when we cannot connect to Snowflake.
                        "DatabaseError",
                        # Raised by Snowflake when a query cannot be compiled.
                        # Usually this means we don't have table permissions or something doesn't exist (db, schema).
                        "ProgrammingError",
                        # Raised by Snowflake with an incorrect account name.
                        "ForbiddenError",
                    ],
                ),
            )

        except exceptions.ActivityError as e:
            if isinstance(e.cause, exceptions.CancelledError):
                workflow.logger.exception("Snowflake BatchExport was cancelled.")
                update_inputs.status = "Cancelled"
            else:
                workflow.logger.exception("Snowflake BatchExport failed.", exc_info=e)
                update_inputs.status = "Failed"

            update_inputs.latest_error = str(e.cause)
            raise

        except Exception as e:
            workflow.logger.exception("Snowflake BatchExport failed with an unexpected exception.", exc_info=e)
            update_inputs.status = "Failed"
            update_inputs.latest_error = "An unexpected error has ocurred"
            raise

        finally:
            await workflow.execute_activity(
                update_export_run_status,
                update_inputs,
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(seconds=60),
                    maximum_attempts=0,
                    non_retryable_error_types=["NotNullViolation", "IntegrityError"],
                ),
            )
