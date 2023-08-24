import contextlib
import datetime as dt
import json
from dataclasses import dataclass

from django.conf import settings
from google.cloud import bigquery
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.service import BigQueryBatchExportInputs
from posthog.temporal.workflows.base import (
    CreateBatchExportRunInputs,
    PostHogWorkflow,
    UpdateBatchExportRunStatusInputs,
    create_export_run,
    update_export_run_status,
)
from posthog.temporal.workflows.batch_exports import (
    BatchExportTemporaryFile,
    get_data_interval,
    get_results_iterator,
    get_rows_count,
)
from posthog.temporal.workflows.clickhouse import get_client


def load_file_to_bigquery_table(tsv_file, table, bigquery_client):
    """Execute a COPY FROM query with given connection to copy contents of tsv_file."""
    bigquery_client.load_table_from_file(tsv_file, table, rewind=True)


def create_table_in_bigquery(
    table_id: str,
    table_schema: list[bigquery.SchemaField],
    bigquery_client: bigquery.Client,
    exists_ok: bool = True,
) -> bigquery.Table:
    table = bigquery.Table(table_id, schema=table_schema)

    table = bigquery_client.create_table(table, exists_ok=exists_ok)

    return table


@dataclass
class BigQueryInsertInputs:
    """Inputs for BigQuery."""

    team_id: int
    dataset_id: str
    table_id: str
    data_interval_start: str
    data_interval_end: str


@contextlib.contextmanager
def bigquery_client(inputs: BigQueryInsertInputs):
    """Manage a BigQuery client."""
    client = bigquery.Client()

    try:
        yield client
    finally:
        client.close()


@activity.defn
async def insert_into_bigquery_activity(inputs: BigQueryInsertInputs):
    """Activity streams data from ClickHouse to BigQuery."""
    activity.logger.info("Running BigQuery export batch %s - %s", inputs.data_interval_start, inputs.data_interval_end)

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
                count,
            )
            return

        activity.logger.info("BatchExporting %s rows to BigQuery", count)

        results_iterator = get_results_iterator(
            client=client,
            team_id=inputs.team_id,
            interval_start=inputs.data_interval_start,
            interval_end=inputs.data_interval_end,
        )
        table_schema = [
            bigquery.SchemaField("uuid", "STRING"),
            bigquery.SchemaField("event", "STRING"),
            bigquery.SchemaField("properties", "STRING"),
            bigquery.SchemaField("elements", "STRING"),
            bigquery.SchemaField("set", "STRING"),
            bigquery.SchemaField("set_once", "STRING"),
            bigquery.SchemaField("distinct_id", "STRING"),
            bigquery.SchemaField("team_id", "INT64"),
            bigquery.SchemaField("ip", "STRING"),
            bigquery.SchemaField("site_url", "STRING"),
            bigquery.SchemaField("timestamp", "TIMESTAMP"),
            bigquery.SchemaField("bq_ingested_timestamp", "TIMESTAMP"),
        ]
        json_columns = ("properties", "elements", "set", "set_once")

        with bigquery_client(inputs) as client:
            bigquery_table = create_table_in_bigquery(inputs.table_id, table_schema, client)

            with BatchExportTemporaryFile() as bigquery_file:
                for result in results_iterator:
                    row = {
                        field.name: json.dumps(result[field.name])
                        if field.name in json_columns and result[field.name] is not None
                        else result[field.name]
                        for field in table_schema
                    }
                    bigquery_file.write_records_to_tsv([row], fieldnames=[field.name for field in table_schema])

                    if bigquery_file.tell() > settings.BATCH_EXPORT_BIGQUERY_UPLOAD_CHUNK_SIZE_BYTES:
                        activity.logger.info(
                            "Copying %s records of size %s bytes to BigQuery",
                            bigquery_file.records_since_last_reset,
                            bigquery_file.bytes_since_last_reset,
                        )
                        load_file_to_bigquery_table(
                            bigquery_file,
                            bigquery_table,
                            client,
                        )
                        bigquery_file.reset()

                if bigquery_file.tell() > 0:
                    activity.logger.info(
                        "Copying %s records of size %s bytes to BigQuery",
                        bigquery_file.records_since_last_reset,
                        bigquery_file.bytes_since_last_reset,
                    )
                    load_file_to_bigquery_table(bigquery_file, bigquery_table, client)


@workflow.defn(name="bigquery-export")
class BigQueryBatchExportWorkflow(PostHogWorkflow):
    """A Temporal Workflow to export ClickHouse data into BigQuery.

    This Workflow is intended to be executed both manually and by a Temporal
    Schedule. When ran by a schedule, `data_interval_end` should be set to
    `None` so that we will fetch the end of the interval from the Temporal
    search attribute `TemporalScheduledStartTime`.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> BigQueryBatchExportInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return BigQueryBatchExportInputs(**loaded)

    @workflow.run
    async def run(self, inputs: BigQueryBatchExportInputs):
        """Workflow implementation to export data to BigQuery."""
        workflow.logger.info("Starting BigQuery export")

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

        insert_inputs = BigQueryInsertInputs(
            team_id=inputs.team_id,
            table_id=inputs.table_id,
            dataset_id=inputs.dataset_id,
            data_interval_start=data_interval_start.isoformat(),
            data_interval_end=data_interval_end.isoformat(),
        )

        try:
            await workflow.execute_activity(
                insert_into_bigquery_activity,
                insert_inputs,
                start_to_close_timeout=dt.timedelta(hours=1),
                retry_policy=RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(seconds=120),
                    maximum_attempts=10,
                    non_retryable_error_types=[],
                ),
            )

        except Exception as e:
            workflow.logger.exception("Bigquery BatchExport failed.", exc_info=e)
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
