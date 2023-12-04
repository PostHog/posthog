import asyncio
import contextlib
import dataclasses
import datetime as dt
import json

from django.conf import settings
from google.cloud import bigquery
from google.oauth2 import service_account
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.service import BigQueryBatchExportInputs
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
    should_resume_from_activity_heartbeat,
)


async def load_jsonl_file_to_bigquery_table(jsonl_file, table, table_schema, bigquery_client):
    """Execute a COPY FROM query with given connection to copy contents of jsonl_file."""
    job_config = bigquery.LoadJobConfig(
        source_format="NEWLINE_DELIMITED_JSON",
        schema=table_schema,
    )

    load_job = bigquery_client.load_table_from_file(jsonl_file, table, job_config=job_config, rewind=True)
    await asyncio.to_thread(load_job.result)


async def create_table_in_bigquery(
    project_id: str,
    dataset_id: str,
    table_id: str,
    table_schema: list[bigquery.SchemaField],
    bigquery_client: bigquery.Client,
    exists_ok: bool = True,
) -> bigquery.Table:
    """Create a table in BigQuery."""
    fully_qualified_name = f"{project_id}.{dataset_id}.{table_id}"
    table = bigquery.Table(fully_qualified_name, schema=table_schema)
    table.time_partitioning = bigquery.TimePartitioning(type_=bigquery.TimePartitioningType.DAY, field="timestamp")
    table = await asyncio.to_thread(bigquery_client.create_table, table, exists_ok=exists_ok)

    return table


@dataclasses.dataclass
class BigQueryHeartbeatDetails(BatchExportHeartbeatDetails):
    """The BigQuery batch export details included in every heartbeat."""

    pass


@dataclasses.dataclass
class BigQueryInsertInputs:
    """Inputs for BigQuery."""

    team_id: int
    project_id: str
    dataset_id: str
    table_id: str
    private_key: str
    private_key_id: str
    token_uri: str
    client_email: str
    data_interval_start: str
    data_interval_end: str
    exclude_events: list[str] | None = None
    include_events: list[str] | None = None


@contextlib.contextmanager
def bigquery_client(inputs: BigQueryInsertInputs):
    """Manage a BigQuery client."""
    credentials = service_account.Credentials.from_service_account_info(
        {
            "private_key": inputs.private_key,
            "private_key_id": inputs.private_key_id,
            "token_uri": inputs.token_uri,
            "client_email": inputs.client_email,
            "project_id": inputs.project_id,
        },
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    client = bigquery.Client(
        project=inputs.project_id,
        credentials=credentials,
    )

    try:
        yield client
    finally:
        client.close()


@activity.defn
async def insert_into_bigquery_activity(inputs: BigQueryInsertInputs):
    """Activity streams data from ClickHouse to BigQuery."""
    logger = await bind_temporal_worker_logger(team_id=inputs.team_id, destination="BigQuery")
    logger.info(
        "Exporting batch %s - %s",
        inputs.data_interval_start,
        inputs.data_interval_end,
    )

    should_resume, details = await should_resume_from_activity_heartbeat(activity, BigQueryHeartbeatDetails, logger)

    if should_resume is True and details is not None:
        data_interval_start = details.last_inserted_at.isoformat()
        last_inserted_at = details.last_inserted_at
    else:
        data_interval_start = inputs.data_interval_start
        last_inserted_at = None

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

        results_iterator = get_results_iterator(
            client=client,
            team_id=inputs.team_id,
            interval_start=data_interval_start,
            interval_end=inputs.data_interval_end,
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
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

        result = None

        async def worker_shutdown_handler():
            """Handle the Worker shutting down by heart-beating our latest status."""
            await activity.wait_for_worker_shutdown()
            logger.bind(last_inserted_at=last_inserted_at).debug("Worker shutting down!")

            if last_inserted_at is None:
                # Don't heartbeat if worker shuts down before we could even send anything
                # Just start from the beginning again.
                return

            activity.heartbeat(last_inserted_at)

        asyncio.create_task(worker_shutdown_handler())

        with bigquery_client(inputs) as bq_client:
            bigquery_table = await create_table_in_bigquery(
                inputs.project_id,
                inputs.dataset_id,
                inputs.table_id,
                table_schema,
                bq_client,
            )

            with BatchExportTemporaryFile() as jsonl_file:
                rows_exported = get_rows_exported_metric()
                bytes_exported = get_bytes_exported_metric()

                async def flush_to_bigquery():
                    logger.debug(
                        "Loading %s records of size %s bytes",
                        jsonl_file.records_since_last_reset,
                        jsonl_file.bytes_since_last_reset,
                    )
                    await load_jsonl_file_to_bigquery_table(jsonl_file, bigquery_table, table_schema, bq_client)

                    rows_exported.add(jsonl_file.records_since_last_reset)
                    bytes_exported.add(jsonl_file.bytes_since_last_reset)

                for result in results_iterator:
                    row = {
                        field.name: json.dumps(result[field.name]) if field.name in json_columns else result[field.name]
                        for field in table_schema
                        if field.name != "bq_ingested_timestamp"
                    }
                    row["bq_ingested_timestamp"] = str(dt.datetime.utcnow())

                    jsonl_file.write_records_to_jsonl([row])

                    if jsonl_file.tell() > settings.BATCH_EXPORT_BIGQUERY_UPLOAD_CHUNK_SIZE_BYTES:
                        await flush_to_bigquery()

                        last_inserted_at = result["inserted_at"]
                        activity.heartbeat(last_inserted_at)

                        jsonl_file.reset()

                if jsonl_file.tell() > 0 and result is not None:
                    await flush_to_bigquery()

                    last_inserted_at = result["inserted_at"]
                    activity.heartbeat(last_inserted_at)

                    jsonl_file.reset()


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

        update_inputs = UpdateBatchExportRunStatusInputs(id=run_id, status="Completed", team_id=inputs.team_id)

        insert_inputs = BigQueryInsertInputs(
            team_id=inputs.team_id,
            table_id=inputs.table_id,
            dataset_id=inputs.dataset_id,
            project_id=inputs.project_id,
            private_key=inputs.private_key,
            private_key_id=inputs.private_key_id,
            token_uri=inputs.token_uri,
            client_email=inputs.client_email,
            data_interval_start=data_interval_start.isoformat(),
            data_interval_end=data_interval_end.isoformat(),
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
        )

        await execute_batch_export_insert_activity(
            insert_into_bigquery_activity,
            insert_inputs,
            non_retryable_error_types=[
                # Raised on missing permissions.
                "Forbidden",
                # Invalid token.
                "RefreshError",
                # Usually means the dataset or project doesn't exist.
                "NotFound",
            ],
            update_inputs=update_inputs,
        )
