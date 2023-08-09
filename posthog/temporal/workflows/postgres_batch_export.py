import csv
import datetime as dt
import json
import tempfile
from dataclasses import dataclass

import psycopg2
from django.conf import settings
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.service import PostgresBatchExportInputs
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


@dataclass
class PostgresInsertInputs:
    """Inputs for Postgres."""

    team_id: int
    user: str
    password: str
    host: str
    database: str
    schema: str
    table_name: str
    data_interval_start: str
    data_interval_end: str
    port: int = 5432


@activity.defn
async def insert_into_postgres_activity(inputs: PostgresInsertInputs):
    """Activity streams data from ClickHouse to Postgres."""
    activity.logger.info("Running Postgres export batch %s - %s", inputs.data_interval_start, inputs.data_interval_end)

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

        activity.logger.info("BatchExporting %s rows to Postgres", count)

        results_iterator = get_results_iterator(
            client=client,
            team_id=inputs.team_id,
            interval_start=inputs.data_interval_start,
            interval_end=inputs.data_interval_end,
        )
        result = None
        local_results_file = tempfile.NamedTemporaryFile(mode="w+", suffix=".csv")
        writer = csv.writer(local_results_file, delimiter="\t", quotechar="'", quoting=csv.QUOTE_MINIMAL)

        with psycopg2.connect(
            user=inputs.user,
            password=inputs.password,
            database=inputs.database,
            schema=inputs.schema,
            host=inputs.host,
            port=inputs.port,
        ) as connection:
            with connection.cursor() as cursor:
                for result in results_iterator:
                    writer.writerow(result.values())

                    if (
                        local_results_file.tell()
                        and local_results_file.tell() > settings.BATCH_EXPORT_POSTGRES_UPLOAD_CHUNK_SIZE_BYTES
                    ):
                        activity.logger.info("Copying to Postgres")

                        local_results_file.flush()
                        local_results_file.seek(0)

                        cursor.copy_from(local_results_file, inputs.table_name, null=" ")

                        local_results_file.close()
                        local_results_file = tempfile.NamedTemporaryFile(mode="w+", suffix=".csv")
                        writer = csv.writer(
                            local_results_file, delimiter="\t", quotechar="'", quoting=csv.QUOTE_MINIMAL
                        )

                local_results_file.flush()
                local_results_file.seek(0)

                cursor.copy_from(local_results_file, inputs.table_name, null=" ")
                local_results_file.close()


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

        insert_inputs = PostgresInsertInputs(
            team_id=inputs.team_id,
            user=inputs.user,
            password=inputs.password,
            host=inputs.host,
            port=inputs.port,
            database=inputs.database,
            schema=inputs.schema,
            table_name=inputs.table_name,
            data_interval_start=data_interval_start.isoformat(),
            data_interval_end=data_interval_end.isoformat(),
        )
        try:
            await workflow.execute_activity(
                insert_into_postgres_activity,
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
                    ],
                ),
            )

        except Exception as e:
            workflow.logger.exception("Snowflake BatchExport failed.", exc_info=e)
            update_inputs.status = "Failed"
            # Note: This shallows the exception type, but the message should be enough.
            # If not, swap to repr(e)
            update_inputs.latest_error = str(e)
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
