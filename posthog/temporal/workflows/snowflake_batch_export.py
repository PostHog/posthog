import datetime as dt
import json
from dataclasses import dataclass
from string import Template
import tempfile
from uuid import UUID

from django.conf import settings
import snowflake.connector
from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from posthog.batch_exports.service import SnowflakeBatchExportInputs, afetch_batch_export_run
from posthog.batch_exports.models import afetch_batch_export

from posthog.temporal.workflows.base import (
    CreateBatchExportRunInputs,
    PostHogWorkflow,
    UpdateBatchExportRunStatusInputs,
    create_export_run,
    update_export_run_status,
)
from posthog.temporal.workflows.batch_exports import (
    get_results_iterator,
    get_rows_count,
    get_workflow_scheduled_start_time,
)
from posthog.temporal.workflows.clickhouse import get_client


SELECT_QUERY_TEMPLATE = Template(
    """
    SELECT $fields
    FROM events
    WHERE
        timestamp >= toDateTime({data_interval_start}, 'UTC')
        AND timestamp < toDateTime({data_interval_end}, 'UTC')
        AND team_id = {team_id}
    """
)


@dataclass
class SnowflakeInsertInputs:
    """Inputs for Snowflake."""

    run_id: str


@activity.defn
async def insert_into_snowflake_activity(inputs: SnowflakeInsertInputs):
    """
    Activity streams data from ClickHouse to Snowflake.

    TODO: We're using JSON here, it's not the most efficient way to do this.

    TODO: at the moment this doesn't do anything about catching data that might
    be late being ingested into the specified time range. To work around this,
    as a little bit of a hack we should export data only up to an hour ago with
    the assumption that that will give it enough time to settle. I is a little
    tricky with the existing setup to properly partition the data into data we
    have or haven't processed yet. We have `_timestamp` in the events table, but
    this is the time
    """
    activity.logger.info("Running Snowflake export run: %s", inputs.run_id)

    run = await afetch_batch_export_run(UUID(inputs.run_id))
    if run is None:
        activity.logger.info("Run %s does not exist. Exiting.", inputs.run_id)
        return

    export = await afetch_batch_export(run.batch_export_id)
    if export is None:
        activity.logger.info("Run %s has no batch export. Exiting.", run.batch_export_id)
        return

    config = export.destination.config
    user = config.get("user")
    password = config.get("password")
    account = config.get("account")
    warehouse = config.get("warehouse")
    database = config.get("database")
    schema = config.get("schema")
    table_name = config.get("table_name")

    async with get_client() as client:
        if not await client.is_alive():
            raise ConnectionError("Cannot establish connection to ClickHouse")

        count = await get_rows_count(
            client=client,
            team_id=export.team_id,
            interval_start=run.data_interval_start,
            interval_end=run.data_interval_end,
        )

        if count == 0:
            activity.logger.info(
                "Nothing to export in batch %s - %s. Exiting.",
                run.data_interval_start,
                run.data_interval_end,
            )
            return

        activity.logger.info("BatchExporting %s rows to S3", count)

        conn = snowflake.connector.connect(
            user=user,
            password=password,
            account=account,
            warehouse=warehouse,
            database=database,
            schema=schema,
        )

        try:
            cursor = conn.cursor()
            cursor.execute(f'USE DATABASE "{database}"')
            cursor.execute(f'USE SCHEMA "{schema}"')

            # Create the table if it doesn't exist. Note that we use the same schema
            # as the snowflake-plugin for backwards compatibility.
            cursor.execute(
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
                """
            )

            results_iterator = get_results_iterator(
                client=client,
                team_id=export.team_id,
                interval_start=run.data_interval_start,
                interval_end=run.data_interval_end,
            )

            local_results_file = tempfile.NamedTemporaryFile()
            try:
                while True:
                    try:
                        result = await results_iterator.__anext__()
                    except StopAsyncIteration:
                        break

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
                        cursor.execute(
                            f"""
                            PUT file://{local_results_file.name} @%"{table_name}"
                            """
                        )

                        # Delete the temporary file and create a new one
                        local_results_file.close()
                        local_results_file = tempfile.NamedTemporaryFile()

                # Flush the file to make sure everything is written
                local_results_file.flush()
                cursor.execute(
                    f"""
                    PUT file://{local_results_file.name} @%"{table_name}"
                    """
                )

                # We don't need the file anymore, close (and delete) it.
                local_results_file.close()

                cursor.execute(
                    f"""
                    COPY INTO "{table_name}"
                    FILE_FORMAT = (TYPE = 'JSON')
                    MATCH_BY_COLUMN_NAME = CASE_SENSITIVE
                    PURGE = TRUE
                    """
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
        """Workflow implementation to export data to Snowflake."""
        workflow.logger.info("Starting Snowflake export")

        workflow_schedule_time = get_workflow_scheduled_start_time(workflow.info())

        data_interval_end = inputs.data_interval_end or workflow_schedule_time
        if not data_interval_end:
            raise ValueError("Either data_interval_end or TemporalScheduledStartTime must be set")

        create_export_run_inputs = CreateBatchExportRunInputs(
            batch_export_id=inputs.batch_export_id,
            data_interval_end=data_interval_end,
        )

        run_id = await workflow.execute_activity(
            create_export_run,
            create_export_run_inputs,
            start_to_close_timeout=dt.timedelta(minutes=20),
            schedule_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=RetryPolicy(
                maximum_attempts=3,
                non_retryable_error_types=["NotNullViolation", "IntegrityError"],
            ),
        )

        if not run_id:
            raise ValueError("Failed to create BatchExportRun")

        update_inputs = UpdateBatchExportRunStatusInputs(id=run_id, status="Completed")

        insert_inputs = SnowflakeInsertInputs(run_id=run_id)
        try:
            await workflow.execute_activity(
                insert_into_snowflake_activity,
                insert_inputs,
                start_to_close_timeout=dt.timedelta(minutes=20),
                schedule_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=RetryPolicy(
                    maximum_attempts=3,
                    non_retryable_error_types=[
                        # If we can't connect to ClickHouse, no point in
                        # retrying.
                        "ConnectionError",
                        # Validation failed, and will keep failing.
                        "ValueError",
                    ],
                ),
            )

        except Exception as e:
            workflow.logger.exception("Snowflake BatchExport failed.", exc_info=e)
            update_inputs.status = "Failed"
            raise

        finally:
            await workflow.execute_activity(
                update_export_run_status,
                update_inputs,
                start_to_close_timeout=dt.timedelta(minutes=20),
                schedule_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
