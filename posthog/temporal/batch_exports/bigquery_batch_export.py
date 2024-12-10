import asyncio
import collections.abc
import contextlib
import dataclasses
import datetime as dt
import json

import pyarrow as pa
import structlog
from django.conf import settings
from google.api_core.exceptions import Forbidden
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
    start_batch_export_run,
)
from posthog.temporal.batch_exports.heartbeat import (
    BatchExportRangeHeartbeatDetails,
    DateRange,
    should_resume_from_activity_heartbeat,
)
from posthog.temporal.batch_exports.spmc import (
    Consumer,
    Producer,
    RecordBatchQueue,
    run_consumer_loop,
    wait_for_schema_or_producer,
)
from posthog.temporal.batch_exports.temporary_file import (
    BatchExportTemporaryFile,
    WriterFormat,
)
from posthog.temporal.batch_exports.utils import (
    JsonType,
    set_status_to_running_task,
)
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import configure_temporal_worker_logger

logger = structlog.get_logger()

NON_RETRYABLE_ERROR_TYPES = [
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
]


def get_bigquery_fields_from_record_schema(
    record_schema: pa.Schema, known_json_columns: collections.abc.Sequence[str]
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
        if name == "_inserted_at":
            continue

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
class BigQueryHeartbeatDetails(BatchExportRangeHeartbeatDetails):
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
    data_interval_start: str | None
    data_interval_end: str
    exclude_events: list[str] | None = None
    include_events: list[str] | None = None
    use_json_type: bool = False
    run_id: str | None = None
    is_backfill: bool = False
    batch_export_model: BatchExportModel | None = None
    # TODO: Remove after updating existing batch exports
    batch_export_schema: BatchExportSchema | None = None


class BigQueryQuotaExceededError(Exception):
    """Exception raised when a BigQuery quota is exceeded.

    This error indicates that we have been exporting too much data and need to
    slow down. This error is retryable.
    """

    def __init__(self, message: str):
        super().__init__(f"A BigQuery quota has been exceeded. Error: {message}")


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
        not_found_ok: bool = True,
    ) -> None:
        """Delete a table in BigQuery."""
        fully_qualified_name = f"{project_id}.{dataset_id}.{table_id}"
        table = bigquery.Table(fully_qualified_name)

        await asyncio.to_thread(self.delete_table, table, not_found_ok=not_found_ok)

        return None

    async def aget_table(
        self,
        project_id: str,
        dataset_id: str,
        table_id: str,
    ) -> bigquery.Table:
        """Get a table in BigQuery."""
        fully_qualified_name = f"{project_id}.{dataset_id}.{table_id}"
        return await asyncio.to_thread(self.get_table, fully_qualified_name)

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
        """Manage a table in BigQuery by ensuring it exists while in context."""
        if create is True:
            table = await self.acreate_table(project_id, dataset_id, table_id, table_schema, exists_ok)
        else:
            table = await self.aget_table(project_id, dataset_id, table_id)

        try:
            yield table
        finally:
            if delete is True:
                try:
                    await self.adelete_table(project_id, dataset_id, table_id, not_found_ok)
                except Forbidden:
                    await logger.awarning(
                        "Missing delete permissions to delete %s.%s.%s", project_id, dataset_id, table_id
                    )

    async def amerge_tables(
        self,
        final_table: bigquery.Table,
        stage_table: bigquery.Table,
        mutable: bool,
        stage_fields_cast_to_json: collections.abc.Sequence[str] | None = None,
        merge_key: collections.abc.Iterable[bigquery.SchemaField] | None = None,
    ):
        """Merge two tables in BigQuery.

        When `mutable` is `False`, we will do a simple `INSERT INTO final FROM stage`,
        whereas when `mutable` is `True` we will do the more complex `MERGE` query.
        This is because inmutable tables do not need to concern themselves with
        the conflict resolution options provided by `MERGE` as each row is unique.

        Arguments:
            final_table: The BigQuery table we are merging into.
            stage_table: The BigQuery table we are merging from.
            mutable: Whether the table is mutable and requires a merge, or not.
            stage_fields_cast_to_json: Fields that must be cast to `JSON` from
                `stage_table` when inserting them in `final_table`.
            merge_key: If table is mutable, the merge key columns.
        """
        if mutable is False:
            return await self.ainsert_into_from_stage_table(
                final_table, stage_table, stage_fields_cast_to_json=stage_fields_cast_to_json
            )
        else:
            if merge_key is None:
                raise ValueError("Merge key must be defined when merging a mutable model")

            return await self.amerge_person_tables(
                final_table, stage_table, merge_key=merge_key, stage_fields_cast_to_json=stage_fields_cast_to_json
            )

    async def ainsert_into_from_stage_table(
        self,
        into_table: bigquery.Table,
        stage_table: bigquery.Table,
        stage_fields_cast_to_json: collections.abc.Sequence[str] | None = None,
    ):
        """Insert data from `stage_table` into `into_table`."""
        job_config = bigquery.QueryJobConfig()
        into_table_fields = ",".join(f"`{field.name}`" for field in into_table.schema)

        if stage_fields_cast_to_json is not None:
            fields_to_cast = set(stage_fields_cast_to_json)
        else:
            fields_to_cast = set()
        stage_table_fields = ",".join(
            f"PARSE_JSON(`{field.name}`)" if field.name in fields_to_cast else f"`{field.name}`"
            for field in into_table.schema
        )

        query = f"""
        INSERT INTO `{into_table.full_table_id.replace(":", ".", 1)}`
          ({into_table_fields})
        SELECT
          {stage_table_fields}
        FROM `{stage_table.full_table_id.replace(":", ".", 1)}`
        """

        query_job = self.query(query, job_config=job_config)
        return await asyncio.to_thread(query_job.result)

    async def amerge_person_tables(
        self,
        final_table: bigquery.Table,
        stage_table: bigquery.Table,
        merge_key: collections.abc.Iterable[bigquery.SchemaField],
        person_version_key: str = "person_version",
        person_distinct_id_version_key: str = "person_distinct_id_version",
        stage_fields_cast_to_json: collections.abc.Sequence[str] | None = None,
    ):
        """Merge two identical person model tables in BigQuery."""
        job_config = bigquery.QueryJobConfig()

        if stage_fields_cast_to_json is not None:
            fields_to_cast = set(stage_fields_cast_to_json)
        else:
            fields_to_cast = set()

        merge_condition = "ON "

        for n, field in enumerate(merge_key):
            if n > 0:
                merge_condition += " AND "
            merge_condition += f"final.`{field.name}` = stage.`{field.name}`"

        update_clause = ""
        values = ""
        field_names = ""

        for n, field in enumerate(final_table.schema):
            if n > 0:
                update_clause += ", "
                values += ", "
                field_names += ", "

            stage_field = (
                f"PARSE_JSON(stage.`{field.name}`)" if field.name in fields_to_cast else f"stage.`{field.name}`"
            )
            update_clause += f"final.`{field.name}` = {stage_field}"
            field_names += f"`{field.name}`"
            values += stage_field

        if not update_clause:
            raise ValueError("Empty update clause")

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

        await logger.adebug("Creating BigQuery load job for Parquet file '%s'", parquet_file)
        load_job = await asyncio.to_thread(
            self.load_table_from_file, parquet_file, table, job_config=job_config, rewind=True
        )
        await logger.adebug("Waiting for BigQuery load job for Parquet file '%s'", parquet_file)

        try:
            result = await asyncio.to_thread(load_job.result)
        except Forbidden as err:
            if err.reason == "quotaExceeded":
                raise BigQueryQuotaExceededError(err.message) from err
            raise

        return result

    async def load_jsonl_file(self, jsonl_file, table, table_schema):
        """Execute a COPY FROM query to copy contents of `jsonl_file`.

        Raises:
            BigQueryQuotaExceededError: If we receive a 'quotaExceeded' error from
                BigQuery when loading a file.
        """
        job_config = bigquery.LoadJobConfig(
            source_format="NEWLINE_DELIMITED_JSON",
            schema=table_schema,
        )

        await logger.adebug("Creating BigQuery load job for JSONL file '%s'", jsonl_file)
        load_job = await asyncio.to_thread(
            self.load_table_from_file, jsonl_file, table, job_config=job_config, rewind=True
        )
        await logger.adebug("Waiting for BigQuery load job for JSONL file '%s'", jsonl_file)

        try:
            result = await asyncio.to_thread(load_job.result)
        except Forbidden as err:
            if err.reason == "quotaExceeded":
                raise BigQueryQuotaExceededError(err.message) from err
            raise

        return result


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


class BigQueryConsumer(Consumer):
    """Implementation of a SPMC pipeline Consumer for BigQuery batch exports."""

    def __init__(
        self,
        heartbeater: Heartbeater,
        heartbeat_details: BigQueryHeartbeatDetails,
        data_interval_start: dt.datetime | str | None,
        bigquery_client: BigQueryClient,
        bigquery_table: bigquery.Table,
        table_schema: list[BatchExportField],
    ):
        super().__init__(heartbeater, heartbeat_details, data_interval_start)
        self.bigquery_client = bigquery_client
        self.bigquery_table = bigquery_table
        self.table_schema = table_schema

    async def flush(
        self,
        batch_export_file: BatchExportTemporaryFile,
        records_since_last_flush: int,
        bytes_since_last_flush: int,
        flush_counter: int,
        last_date_range: DateRange,
        is_last: bool,
        error: Exception | None,
    ):
        """Implement flushing by loading batch export files to BigQuery"""
        await self.logger.adebug(
            "Loading %s records of size %s bytes to BigQuery table '%s'",
            records_since_last_flush,
            bytes_since_last_flush,
            self.bigquery_table,
        )

        await self.bigquery_client.load_parquet_file(batch_export_file, self.bigquery_table, self.table_schema)

        await self.logger.adebug("Loaded %s to BigQuery table '%s'", records_since_last_flush, self.bigquery_table)
        self.rows_exported_counter.add(records_since_last_flush)
        self.bytes_exported_counter.add(bytes_since_last_flush)

        self.heartbeat_details.track_done_range(last_date_range, self.data_interval_start)


@activity.defn
async def insert_into_bigquery_activity(inputs: BigQueryInsertInputs) -> RecordsCompleted:
    """Activity streams data from ClickHouse to BigQuery."""
    logger = await configure_temporal_worker_logger(
        logger=structlog.get_logger(), team_id=inputs.team_id, destination="BigQuery"
    )
    await logger.ainfo(
        "Batch exporting range %s - %s to BigQuery: %s.%s.%s",
        inputs.data_interval_start or "START",
        inputs.data_interval_end or "END",
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

        _, details = await should_resume_from_activity_heartbeat(activity, BigQueryHeartbeatDetails)
        if details is None:
            details = BigQueryHeartbeatDetails()

        done_ranges: list[DateRange] = details.done_ranges

        model: BatchExportModel | BatchExportSchema | None = None
        if inputs.batch_export_schema is None and "batch_export_model" in {
            field.name for field in dataclasses.fields(inputs)
        }:
            model = inputs.batch_export_model
            if model is not None:
                model_name = model.name
                extra_query_parameters = model.schema["values"] if model.schema is not None else None
                fields = model.schema["fields"] if model.schema is not None else None
            else:
                model_name = "events"
                extra_query_parameters = None
                fields = None
        else:
            model = inputs.batch_export_schema
            model_name = "custom"
            extra_query_parameters = model["values"] if model is not None else {}
            fields = model["fields"] if model is not None else None

        data_interval_start = (
            dt.datetime.fromisoformat(inputs.data_interval_start) if inputs.data_interval_start else None
        )
        data_interval_end = dt.datetime.fromisoformat(inputs.data_interval_end)
        full_range = (data_interval_start, data_interval_end)

        queue = RecordBatchQueue(max_size_bytes=settings.BATCH_EXPORT_BIGQUERY_RECORD_BATCH_QUEUE_MAX_SIZE_BYTES)
        producer = Producer(clickhouse_client=client)
        producer_task = producer.start(
            queue=queue,
            model_name=model_name,
            is_backfill=inputs.is_backfill,
            team_id=inputs.team_id,
            full_range=full_range,
            done_ranges=done_ranges,
            fields=fields,
            destination_default_fields=bigquery_default_fields(),
            use_latest_schema=True,
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            extra_query_parameters=extra_query_parameters,
        )
        records_completed = 0

        record_batch_schema = await wait_for_schema_or_producer(queue, producer_task)
        if record_batch_schema is None:
            return records_completed

        record_batch_schema = pa.schema(
            # NOTE: For some reason, some batches set non-nullable fields as non-nullable, whereas other
            # record batches have them as nullable.
            # Until we figure it out, we set all fields to nullable. There are some fields we know
            # are not nullable, but I'm opting for the more flexible option until we out why schemas differ
            # between batches.
            [field.with_nullable(True) for field in record_batch_schema if field.name != "_inserted_at"]
        )
        if inputs.use_json_type is True:
            json_type = "JSON"
            json_columns = ["properties", "set", "set_once", "person_properties"]
        else:
            json_type = "STRING"
            json_columns = []

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
            schema = get_bigquery_fields_from_record_schema(record_batch_schema, known_json_columns=json_columns)

        stage_schema = [
            bigquery.SchemaField(field.name, "STRING") if field.name in json_columns else field for field in schema
        ]
        data_interval_end_str = dt.datetime.fromisoformat(inputs.data_interval_end).strftime("%Y-%m-%d_%H-%M-%S")
        stage_table_name = f"stage_{inputs.table_id}_{data_interval_end_str}"

        with bigquery_client(inputs) as bq_client:
            async with (
                bq_client.managed_table(
                    project_id=inputs.project_id,
                    dataset_id=inputs.dataset_id,
                    table_id=inputs.table_id,
                    table_schema=schema,
                    delete=False,
                ) as bigquery_table,
                bq_client.managed_table(
                    project_id=inputs.project_id,
                    dataset_id=inputs.dataset_id,
                    table_id=stage_table_name,
                    table_schema=stage_schema,
                    create=True,
                    delete=True,
                ) as bigquery_stage_table,
            ):
                records_completed = await run_consumer_loop(
                    queue=queue,
                    consumer_cls=BigQueryConsumer,
                    producer_task=producer_task,
                    heartbeater=heartbeater,
                    heartbeat_details=details,
                    data_interval_end=data_interval_end,
                    data_interval_start=data_interval_start,
                    schema=record_batch_schema,
                    writer_format=WriterFormat.PARQUET,
                    max_bytes=settings.BATCH_EXPORT_BIGQUERY_UPLOAD_CHUNK_SIZE_BYTES,
                    json_columns=(),
                    bigquery_client=bq_client,
                    bigquery_table=bigquery_stage_table,
                    table_schema=stage_schema,
                    writer_file_kwargs={"compression": "zstd"},
                    multiple_files=True,
                )

                merge_key = (
                    bigquery.SchemaField("team_id", "INT64"),
                    bigquery.SchemaField("distinct_id", "STRING"),
                )
                await bq_client.amerge_tables(
                    final_table=bigquery_table,
                    stage_table=bigquery_stage_table,
                    mutable=True if model_name == "persons" else False,
                    merge_key=merge_key,
                    stage_fields_cast_to_json=json_columns,
                )

        return records_completed


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
        should_backfill_from_beginning = inputs.is_backfill and inputs.is_earliest_backfill

        start_batch_export_run_inputs = StartBatchExportRunInputs(
            team_id=inputs.team_id,
            batch_export_id=inputs.batch_export_id,
            data_interval_start=data_interval_start.isoformat() if not should_backfill_from_beginning else None,
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
            data_interval_start=data_interval_start.isoformat() if not should_backfill_from_beginning else None,
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
            non_retryable_error_types=NON_RETRYABLE_ERROR_TYPES,
            finish_inputs=finish_inputs,
            maximum_retry_interval_seconds=240,
        )
