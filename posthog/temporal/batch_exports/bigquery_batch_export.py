import asyncio
import collections.abc
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

from posthog.batch_exports.models import BatchExportRun
from posthog.batch_exports.service import (
    BatchExportField,
    BatchExportModel,
    BatchExportSchema,
    BigQueryBatchExportInputs,
)
from posthog.temporal.batch_exports.base import PostHogWorkflow
from posthog.temporal.batch_exports.batch_exports import (
    FinishBatchExportRunInputs,
    RecordsCompleted,
    StartBatchExportRunInputs,
    default_fields,
    execute_batch_export_insert_activity,
    get_data_interval,
    iter_model_records,
    start_batch_export_run,
)
from posthog.temporal.batch_exports.metrics import (
    get_bytes_exported_metric,
    get_rows_exported_metric,
)
from posthog.temporal.batch_exports.temporary_file import (
    BatchExportWriter,
    FlushCallable,
    JSONLBatchExportWriter,
    ParquetBatchExportWriter,
)
from posthog.temporal.batch_exports.utils import (
    JsonType,
    apeek_first_and_rewind,
    cast_record_batch_json_columns,
    set_status_to_running_task,
)
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import bind_temporal_worker_logger
from posthog.temporal.common.utils import (
    BatchExportHeartbeatDetails,
    should_resume_from_activity_heartbeat,
)


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

        if pa.types.is_string(pa_field.type) or isinstance(pa_field.type, JsonType):
            if pa_field.name in known_json_columns:
                bq_type = "JSON"
            else:
                bq_type = "STRING"

        elif pa.types.is_binary(pa_field.type):
            bq_type = "BYTES"

        elif pa.types.is_signed_integer(pa_field.type) or pa.types.is_unsigned_integer(pa_field.type):
            # The latter comparison is hoping we don't overflow, but BigQuery doesn't have an uint64 type.
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
    run_id: str | None = None
    is_backfill: bool = False
    batch_export_model: BatchExportModel | None = None
    # TODO: Remove after updating existing batch exports
    batch_export_schema: BatchExportSchema | None = None


class BigQueryClient(bigquery.Client):
    async def acreate_table(
        self,
        project_id: str,
        dataset_id: str,
        table_id: str,
        table_schema: list[bigquery.SchemaField],
        exists_ok: bool = True,
    ) -> bigquery.Table:
        """Create a table in BigQuery."""
        fully_qualified_name = f"{project_id}.{dataset_id}.{table_id}"
        table = bigquery.Table(fully_qualified_name, schema=table_schema)

        if "timestamp" in [field.name for field in table_schema]:
            # TODO: Maybe choosing which column to use as parititoning should be a configuration parameter.
            # 'timestamp' is used for backwards compatibility.
            table.time_partitioning = bigquery.TimePartitioning(
                type_=bigquery.TimePartitioningType.DAY, field="timestamp"
            )

        table = await asyncio.to_thread(self.create_table, table, exists_ok=exists_ok)

        return table

    async def adelete_table(
        self,
        project_id: str,
        dataset_id: str,
        table_id: str,
        table_schema: list[bigquery.SchemaField],
        not_found_ok: bool = True,
    ) -> None:
        """Delete a table in BigQuery."""
        fully_qualified_name = f"{project_id}.{dataset_id}.{table_id}"
        table = bigquery.Table(fully_qualified_name, schema=table_schema)

        await asyncio.to_thread(self.delete_table, table, not_found_ok=not_found_ok)

        return None

    @contextlib.asynccontextmanager
    async def managed_table(
        self,
        project_id: str,
        dataset_id: str,
        table_id: str,
        table_schema: list[bigquery.SchemaField],
        exists_ok: bool = True,
        not_found_ok: bool = True,
        delete: bool = True,
        create: bool = True,
    ) -> collections.abc.AsyncGenerator[bigquery.Table, None]:
        """Manage a table in BigQuery by ensure it exists while in context."""
        if create is True:
            table = await self.acreate_table(project_id, dataset_id, table_id, table_schema, exists_ok)
        else:
            fully_qualified_name = f"{project_id}.{dataset_id}.{table_id}"
            table = bigquery.Table(fully_qualified_name, schema=table_schema)

        try:
            yield table
        finally:
            if delete is True:
                await self.adelete_table(project_id, dataset_id, table_id, table_schema, not_found_ok)

    async def amerge_person_tables(
        self,
        final_table: bigquery.Table,
        stage_table: bigquery.Table,
        merge_key: collections.abc.Iterable[bigquery.SchemaField],
        update_fields: collections.abc.Iterable[bigquery.SchemaField] | None = None,
        person_version_key: str = "person_version",
        person_distinct_id_version_key: str = "person_distinct_id_version",
    ):
        """Merge two identical person model tables in BigQuery."""
        job_config = bigquery.QueryJobConfig()

        merge_condition = "ON "

        for n, field in enumerate(merge_key):
            if n > 0:
                merge_condition += " AND "
            merge_condition += f"final.`{field.name}` = stage.`{field.name}`"

        update_clause = ""
        values = ""
        field_names = ""

        if not update_fields:
            update_clause_fields = final_table.schema
        else:
            update_clause_fields = update_fields

        for n, field in enumerate(update_clause_fields):
            if n > 0:
                update_clause += ", "
                values += ", "
                field_names += ", "

            update_clause += f"final.`{field.name}` = stage.`{field.name}`"
            field_names += f"`{field.name}`"
            values += f"stage.`{field.name}`"

        merge_query = f"""
        MERGE `{final_table.full_table_id.replace(":", ".", 1)}` final
        USING `{stage_table.full_table_id.replace(":", ".", 1)}` stage
        {merge_condition}

        WHEN MATCHED AND (stage.`{person_version_key}` > final.`{person_version_key}` OR stage.`{person_distinct_id_version_key}` > final.`{person_distinct_id_version_key}`) THEN
            UPDATE SET
                {update_clause}
        WHEN NOT MATCHED BY TARGET THEN
            INSERT ({field_names})
            VALUES ({values});
        """

        query_job = self.query(merge_query, job_config=job_config)
        return await asyncio.to_thread(query_job.result)

    async def load_parquet_file(self, parquet_file, table, table_schema):
        """Execute a COPY FROM query with given connection to copy contents of parquet_file."""
        job_config = bigquery.LoadJobConfig(
            source_format="PARQUET",
            schema=table_schema,
        )

        load_job = self.load_table_from_file(parquet_file, table, job_config=job_config, rewind=True)
        return await asyncio.to_thread(load_job.result)

    async def load_jsonl_file(self, jsonl_file, table, table_schema):
        """Execute a COPY FROM query with given connection to copy contents of jsonl_file."""
        job_config = bigquery.LoadJobConfig(
            source_format="NEWLINE_DELIMITED_JSON",
            schema=table_schema,
        )

        load_job = self.load_table_from_file(jsonl_file, table, job_config=job_config, rewind=True)
        return await asyncio.to_thread(load_job.result)


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
    client = BigQueryClient(
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
async def insert_into_bigquery_activity(inputs: BigQueryInsertInputs) -> RecordsCompleted:
    """Activity streams data from ClickHouse to BigQuery."""
    logger = await bind_temporal_worker_logger(team_id=inputs.team_id, destination="BigQuery")
    logger.info(
        "Batch exporting range %s - %s to BigQuery: %s.%s.%s",
        inputs.data_interval_start,
        inputs.data_interval_end,
        inputs.project_id,
        inputs.dataset_id,
        inputs.table_id,
    )

    async with (
        Heartbeater() as heartbeater,
        set_status_to_running_task(run_id=inputs.run_id, logger=logger),
        get_client(team_id=inputs.team_id) as client,
    ):
        if not await client.is_alive():
            raise ConnectionError("Cannot establish connection to ClickHouse")

        should_resume, details = await should_resume_from_activity_heartbeat(activity, BigQueryHeartbeatDetails, logger)

        if should_resume is True and details is not None:
            data_interval_start = details.last_inserted_at.isoformat()
        else:
            data_interval_start = inputs.data_interval_start

        model: BatchExportModel | BatchExportSchema | None = None
        if inputs.batch_export_schema is None and "batch_export_model" in {
            field.name for field in dataclasses.fields(inputs)
        }:
            model = inputs.batch_export_model
        else:
            model = inputs.batch_export_schema

        records_iterator = iter_model_records(
            client=client,
            model=model,
            team_id=inputs.team_id,
            interval_start=data_interval_start,
            interval_end=inputs.data_interval_end,
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            destination_default_fields=bigquery_default_fields(),
            is_backfill=inputs.is_backfill,
        )

        first_record_batch, records_iterator = await apeek_first_and_rewind(records_iterator)
        if first_record_batch is None:
            return 0

        if inputs.use_json_type is True:
            json_type = "JSON"
            json_columns = ["properties", "set", "set_once", "person_properties"]
        else:
            json_type = "STRING"
            json_columns = []

        first_record_batch = cast_record_batch_json_columns(first_record_batch, json_columns=json_columns)

        if model is None or (isinstance(model, BatchExportModel) and model.name == "events"):
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
            column_names = [column for column in first_record_batch.schema.names if column != "_inserted_at"]
            record_schema = first_record_batch.select(column_names).schema
            schema = get_bigquery_fields_from_record_schema(record_schema, known_json_columns=json_columns)

        rows_exported = get_rows_exported_metric()
        bytes_exported = get_bytes_exported_metric()

        # TODO: Expose this as a configuration parameter
        # Currently, only allow merging persons model, as it's required.
        # Although all exports could potentially benefit from merging, merging can have an impact on cost,
        # so users should decide whether to opt-in or not.
        requires_merge = (
            isinstance(inputs.batch_export_model, BatchExportModel) and inputs.batch_export_model.name == "persons"
        )
        data_interval_end_str = dt.datetime.fromisoformat(inputs.data_interval_end).strftime("%Y-%m-%d_%H-%M-%S")
        stage_table_name = f"stage_{inputs.table_id}_{data_interval_end_str}" if requires_merge else inputs.table_id

        with bigquery_client(inputs) as bq_client:
            async with (
                bq_client.managed_table(
                    inputs.project_id,
                    inputs.dataset_id,
                    inputs.table_id,
                    schema,
                    delete=False,
                ) as bigquery_table,
                bq_client.managed_table(
                    inputs.project_id,
                    inputs.dataset_id,
                    stage_table_name,
                    schema,
                    create=requires_merge,
                    delete=requires_merge,
                ) as bigquery_stage_table,
            ):

                async def flush_to_bigquery(
                    local_results_file,
                    records_since_last_flush: int,
                    bytes_since_last_flush: int,
                    flush_counter: int,
                    last_inserted_at,
                    last: bool,
                    error: Exception | None,
                ):
                    logger.debug(
                        "Loading %s records of size %s bytes",
                        records_since_last_flush,
                        bytes_since_last_flush,
                    )
                    table = bigquery_stage_table if requires_merge else bigquery_table

                    await bq_client.load_jsonl_file(local_results_file, table, schema)

                    rows_exported.add(records_since_last_flush)
                    bytes_exported.add(bytes_since_last_flush)

                    heartbeater.details = (str(last_inserted_at),)

                record_schema = pa.schema(
                    # NOTE: For some reason, some batches set non-nullable fields as non-nullable, whereas other
                    # record batches have them as nullable.
                    # Until we figure it out, we set all fields to nullable. There are some fields we know
                    # are not nullable, but I'm opting for the more flexible option until we out why schemas differ
                    # between batches.
                    [
                        field.with_nullable(True)
                        for field in first_record_batch.select([field.name for field in schema]).schema
                    ]
                )
                writer = JSONLBatchExportWriter(
                    max_bytes=settings.BATCH_EXPORT_BIGQUERY_UPLOAD_CHUNK_SIZE_BYTES,
                    flush_callable=flush_to_bigquery,
                )

                async with writer.open_temporary_file():
                    async for record_batch in records_iterator:
                        record_batch = cast_record_batch_json_columns(record_batch, json_columns=json_columns)

                        await writer.write_record_batch(record_batch)

                if requires_merge:
                    merge_key = (
                        bigquery.SchemaField("team_id", "INT64"),
                        bigquery.SchemaField("distinct_id", "STRING"),
                    )
                    await bq_client.amerge_person_tables(
                        final_table=bigquery_table,
                        stage_table=bigquery_stage_table,
                        merge_key=merge_key,
                        update_fields=schema,
                    )

                return writer.records_total


def get_batch_export_writer(
    inputs: BigQueryInsertInputs, flush_callable: FlushCallable, max_bytes: int, schema: pa.Schema | None = None
) -> BatchExportWriter:
    """Return the `BatchExportWriter` corresponding to the inputs for this BigQuery batch export."""
    writer: BatchExportWriter

    if inputs.use_json_type is False:
        # JSON field is not supported with Parquet
        writer = ParquetBatchExportWriter(
            max_bytes=max_bytes,
            flush_callable=flush_callable,
            schema=schema,
        )
    else:
        writer = JSONLBatchExportWriter(
            max_bytes=settings.BATCH_EXPORT_BIGQUERY_UPLOAD_CHUNK_SIZE_BYTES,
            flush_callable=flush_callable,
        )

    return writer


@workflow.defn(name="bigquery-export", failure_exception_types=[workflow.NondeterminismError])
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

        start_batch_export_run_inputs = StartBatchExportRunInputs(
            team_id=inputs.team_id,
            batch_export_id=inputs.batch_export_id,
            data_interval_start=data_interval_start.isoformat(),
            data_interval_end=data_interval_end.isoformat(),
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            is_backfill=inputs.is_backfill,
        )
        run_id = await workflow.execute_activity(
            start_batch_export_run,
            start_batch_export_run_inputs,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=RetryPolicy(
                initial_interval=dt.timedelta(seconds=10),
                maximum_interval=dt.timedelta(seconds=60),
                maximum_attempts=0,
                non_retryable_error_types=["NotNullViolation", "IntegrityError"],
            ),
        )

        finish_inputs = FinishBatchExportRunInputs(
            id=run_id,
            batch_export_id=inputs.batch_export_id,
            status=BatchExportRun.Status.COMPLETED,
            team_id=inputs.team_id,
        )

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
            run_id=run_id,
            is_backfill=inputs.is_backfill,
            batch_export_model=inputs.batch_export_model,
            # TODO: Remove after updating existing batch exports.
            batch_export_schema=inputs.batch_export_schema,
        )

        await execute_batch_export_insert_activity(
            insert_into_bigquery_activity,
            insert_inputs,
            interval=inputs.interval,
            non_retryable_error_types=[
                # Raised on missing permissions.
                "Forbidden",
                # Invalid token.
                "RefreshError",
                # Usually means the dataset or project doesn't exist.
                "NotFound",
                # Raised when something about dataset is wrong (not alphanumeric, too long, etc).
                "BadRequest",
                # Raised when table_id isn't valid. Sadly, `ValueError` is rather generic, but we
                # don't anticipate a `ValueError` thrown from our own export code.
                "ValueError",
            ],
            finish_inputs=finish_inputs,
        )
