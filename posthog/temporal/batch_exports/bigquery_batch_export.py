import asyncio
import contextlib
import dataclasses
import datetime as dt
import json

import pyarrow as pa
from django.conf import settings
from google.cloud import bigquery
from google.oauth2 import service_account
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.service import BatchExportField, BatchExportSchema, BigQueryBatchExportInputs
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

    if "timestamp" in [field.name for field in table_schema]:
        # TODO: Maybe choosing which column to use as parititoning should be a configuration parameter.
        # 'timestamp' is used for backwards compatibility.
        table.time_partitioning = bigquery.TimePartitioning(type_=bigquery.TimePartitioningType.DAY, field="timestamp")

    table = await asyncio.to_thread(bigquery_client.create_table, table, exists_ok=exists_ok)

    return table


def get_bigquery_fields_from_record_schema(
    record_schema: pa.Schema, known_json_columns: list[str]
) -> list[bigquery.SchemaField]:
    """Generate a list of supported BigQuery fields from PyArrow schema.

    This function is used to map custom schemas to BigQuery-supported types. Some loss
    of precision is expected.

    Arguments:
        record_schema: The schema of a PyArrow RecordBatch from which we'll attempt to
            derive BigQuery-supported types.
        known_json_columns: If a string type field is a known JSON column then use JSON
            as its BigQuery type.
    """
    bq_schema: list[bigquery.SchemaField] = []

    for name in record_schema.names:
        pa_field = record_schema.field(name)

        if pa.types.is_string(pa_field.type):
            if pa_field.name in known_json_columns:
                bq_type = "JSON"
            else:
                bq_type = "STRING"

        elif pa.types.is_binary(pa_field.type):
            bq_type = "BYTES"

        elif pa.types.is_signed_integer(pa_field.type):
            bq_type = "INT64"

        elif pa.types.is_floating(pa_field.type):
            bq_type = "FLOAT64"

        elif pa.types.is_boolean(pa_field.type):
            bq_type = "BOOL"

        elif pa.types.is_timestamp(pa_field.type):
            bq_type = "TIMESTAMP"

        else:
            raise TypeError(f"Unsupported type: {pa_field.type}")

        bq_schema.append(bigquery.SchemaField(name, bq_type))

    return bq_schema


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
    use_json_type: bool = False
    batch_export_schema: BatchExportSchema | None = None


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


def bigquery_default_fields() -> list[BatchExportField]:
    """Default fields for a BigQuery batch export.

    Starting from the common default fields, we add and tweak some fields for
    backwards compatibility.
    """
    batch_export_fields = default_fields()
    batch_export_fields.append(
        {
            "expression": "nullIf(JSONExtractString(properties, '$ip'), '')",
            "alias": "ip",
        }
    )
    # Fields kept or removed for backwards compatibility with legacy apps schema.
    batch_export_fields.append({"expression": "toJSONString(elements_chain)", "alias": "elements"})
    batch_export_fields.append({"expression": "''", "alias": "site_url"})
    batch_export_fields.append({"expression": "NOW64()", "alias": "bq_ingested_timestamp"})
    batch_export_fields.pop(batch_export_fields.index({"expression": "created_at", "alias": "created_at"}))

    return batch_export_fields


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

        if inputs.batch_export_schema is None:
            fields = bigquery_default_fields()
            query_parameters = None

        else:
            fields = inputs.batch_export_schema["fields"]
            query_parameters = inputs.batch_export_schema["values"]

        records_iterator = iter_records(
            client=client,
            team_id=inputs.team_id,
            interval_start=data_interval_start,
            interval_end=inputs.data_interval_end,
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            fields=fields,
            extra_query_parameters=query_parameters,
        )

        bigquery_table = None
        inserted_at = None

        async def worker_shutdown_handler():
            """Handle the Worker shutting down by heart-beating our latest status."""
            await activity.wait_for_worker_shutdown()
            logger.bind(last_inserted_at=last_inserted_at).debug("Worker shutting down!")

            if last_inserted_at is None:
                # Don't heartbeat if worker shuts down before we could even send anything
                # Just start from the beginning again.
                return

            activity.heartbeat(str(last_inserted_at))

        asyncio.create_task(worker_shutdown_handler())

        with bigquery_client(inputs) as bq_client:
            with BatchExportTemporaryFile() as jsonl_file:
                rows_exported = get_rows_exported_metric()
                bytes_exported = get_bytes_exported_metric()

                async def flush_to_bigquery(bigquery_table, table_schema):
                    logger.debug(
                        "Loading %s records of size %s bytes",
                        jsonl_file.records_since_last_reset,
                        jsonl_file.bytes_since_last_reset,
                    )
                    await load_jsonl_file_to_bigquery_table(jsonl_file, bigquery_table, table_schema, bq_client)

                    rows_exported.add(jsonl_file.records_since_last_reset)
                    bytes_exported.add(jsonl_file.bytes_since_last_reset)

                first_record, records_iterator = peek_first_and_rewind(records_iterator)

                if inputs.use_json_type is True:
                    json_type = "JSON"
                    json_columns = ["properties", "set", "set_once", "person_properties"]
                else:
                    json_type = "STRING"
                    json_columns = []

                if inputs.batch_export_schema is None:
                    schema = [
                        bigquery.SchemaField("uuid", "STRING"),
                        bigquery.SchemaField("event", "STRING"),
                        bigquery.SchemaField("properties", json_type),
                        bigquery.SchemaField("elements", "STRING"),
                        bigquery.SchemaField("set", json_type),
                        bigquery.SchemaField("set_once", json_type),
                        bigquery.SchemaField("distinct_id", "STRING"),
                        bigquery.SchemaField("team_id", "INT64"),
                        bigquery.SchemaField("ip", "STRING"),
                        bigquery.SchemaField("site_url", "STRING"),
                        bigquery.SchemaField("timestamp", "TIMESTAMP"),
                        bigquery.SchemaField("bq_ingested_timestamp", "TIMESTAMP"),
                    ]

                else:
                    column_names = [column for column in first_record.schema.names if column != "_inserted_at"]
                    record_schema = first_record.select(column_names).schema
                    schema = get_bigquery_fields_from_record_schema(record_schema, known_json_columns=json_columns)

                bigquery_table = await create_table_in_bigquery(
                    inputs.project_id,
                    inputs.dataset_id,
                    inputs.table_id,
                    schema,
                    bq_client,
                )

                # Columns need to be sorted according to BigQuery schema.
                record_columns = [field.name for field in schema] + ["_inserted_at"]

                for record_batch in records_iterator:
                    for record in record_batch.select(record_columns).to_pylist():
                        inserted_at = record.pop("_inserted_at")

                        for json_column in json_columns:
                            if json_column in record and (json_str := record.get(json_column, None)) is not None:
                                record[json_column] = json.loads(json_str)

                        # TODO: Parquet is a much more efficient format to send data to BigQuery.
                        jsonl_file.write_records_to_jsonl([record])

                        if jsonl_file.tell() > settings.BATCH_EXPORT_BIGQUERY_UPLOAD_CHUNK_SIZE_BYTES:
                            await flush_to_bigquery(bigquery_table, schema)

                            last_inserted_at = inserted_at.isoformat()
                            activity.heartbeat(last_inserted_at)

                            jsonl_file.reset()

                if jsonl_file.tell() > 0 and inserted_at is not None:
                    await flush_to_bigquery(bigquery_table, schema)

                    last_inserted_at = inserted_at.isoformat()
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
            use_json_type=inputs.use_json_type,
            batch_export_schema=inputs.batch_export_schema,
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
