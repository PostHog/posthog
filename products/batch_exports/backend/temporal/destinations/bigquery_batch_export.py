import io
import json
import typing
import asyncio
import datetime as dt
import contextlib
import dataclasses
import collections.abc

from django.conf import settings

import pyarrow as pa
from google.api_core.exceptions import Forbidden
from google.cloud import bigquery
from google.oauth2 import service_account
from structlog.contextvars import bind_contextvars
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.models import BatchExportRun
from posthog.batch_exports.service import (
    BatchExportField,
    BatchExportInsertInputs,
    BatchExportModel,
    BatchExportSchema,
    BigQueryBatchExportInputs,
)
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger, get_write_only_logger

from products.batch_exports.backend.temporal.batch_exports import (
    FinishBatchExportRunInputs,
    OverBillingLimitError,
    StartBatchExportRunInputs,
    default_fields,
    execute_batch_export_insert_activity,
    get_data_interval,
    start_batch_export_run,
)
from products.batch_exports.backend.temporal.heartbeat import (
    BatchExportRangeHeartbeatDetails,
    DateRange,
    should_resume_from_activity_heartbeat,
)
from products.batch_exports.backend.temporal.pipeline.consumer import (
    Consumer as ConsumerFromStage,
    run_consumer_from_stage,
)
from products.batch_exports.backend.temporal.pipeline.entrypoint import execute_batch_export_using_internal_stage
from products.batch_exports.backend.temporal.pipeline.producer import Producer as ProducerFromInternalStage
from products.batch_exports.backend.temporal.pipeline.transformer import (
    ChunkTransformerProtocol,
    JSONLStreamTransformer,
    ParquetStreamTransformer,
)
from products.batch_exports.backend.temporal.pipeline.types import BatchExportResult
from products.batch_exports.backend.temporal.record_batch_model import resolve_batch_exports_model
from products.batch_exports.backend.temporal.spmc import (
    Consumer,
    Producer,
    RecordBatchQueue,
    run_consumer,
    wait_for_schema_or_producer,
)
from products.batch_exports.backend.temporal.temporary_file import BatchExportTemporaryFile, WriterFormat
from products.batch_exports.backend.temporal.utils import (
    JsonType,
    handle_non_retryable_errors,
    set_status_to_running_task,
)

NON_RETRYABLE_ERROR_TYPES = (
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
    # Raised when attempting to run a batch export without required BigQuery permissions.
    # Our own version of `Forbidden`.
    "MissingRequiredPermissionsError",
)

LOGGER = get_write_only_logger(__name__)
EXTERNAL_LOGGER = get_logger("EXTERNAL")


class MissingRequiredPermissionsError(Exception):
    """Raised when missing required permissions in BigQuery."""

    def __init__(self):
        super().__init__("Missing required permissions to run this batch export")


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

        repeated = False
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

        elif pa.types.is_list(pa_field.type) and pa.types.is_string(pa_field.type.value_type):
            bq_type = "STRING"
            repeated = True

        else:
            raise TypeError(f"Unsupported type in field '{name}': '{pa_field.type}'")

        bq_schema.append(bigquery.SchemaField(name, bq_type, mode="REPEATED" if repeated else "NULLABLE"))

    return bq_schema


@dataclasses.dataclass
class BigQueryHeartbeatDetails(BatchExportRangeHeartbeatDetails):
    """The BigQuery batch export details included in every heartbeat."""

    pass


@dataclasses.dataclass(kw_only=True)
class BigQueryInsertInputs(BatchExportInsertInputs):
    """Inputs for BigQuery."""

    project_id: str
    dataset_id: str
    table_id: str
    private_key: str
    private_key_id: str
    token_uri: str
    client_email: str
    use_json_type: bool = False


class BigQueryQuotaExceededError(Exception):
    """Exception raised when a BigQuery quota is exceeded.

    This error indicates that we have been exporting too much data and need to
    slow down. This error is retryable.
    """

    def __init__(self, message: str):
        super().__init__(f"A BigQuery quota has been exceeded. Error: {message}")


class BigQueryClient(bigquery.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.logger = LOGGER.bind(project=self.project)
        self.external_logger = EXTERNAL_LOGGER.bind(project_id=self.project)

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
        table_schema: collections.abc.Sequence[bigquery.SchemaField],
        exists_ok: bool = True,
        not_found_ok: bool = True,
        delete: bool = True,
        create: bool = True,
    ) -> collections.abc.AsyncGenerator[bigquery.Table, None]:
        """Manage a table in BigQuery by ensuring it exists while in context."""
        if create is True:
            table = await self.acreate_table(project_id, dataset_id, table_id, list(table_schema), exists_ok)
        else:
            table = await self.aget_table(project_id, dataset_id, table_id)

        try:
            yield table
        finally:
            if delete is True:
                try:
                    await self.adelete_table(project_id, dataset_id, table_id, not_found_ok)
                except Forbidden:
                    self.external_logger.warning(
                        "Missing delete permissions to delete %s.%s.%s", project_id, dataset_id, table_id
                    )

    async def amerge_tables(
        self,
        final_table: bigquery.Table,
        stage_table: bigquery.Table,
        mutable: bool,
        stage_fields_cast_to_json: collections.abc.Sequence[str] | None = None,
        merge_key: collections.abc.Iterable[bigquery.SchemaField] | None = None,
        update_key: collections.abc.Iterable[str] | None = None,
    ):
        """Merge two tables in BigQuery.

        When `mutable` is `False`, we will do a simple `INSERT INTO final FROM stage`,
        whereas when `mutable` is `True` we will do the more complex `MERGE` query.
        This is because immutable tables do not need to concern themselves with
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
            if merge_key is None or update_key is None:
                raise ValueError("Merge key and update key must be defined when merging a mutable model")

            return await self.amerge_mutable_tables(
                final_table,
                stage_table,
                merge_key=merge_key,
                update_key=update_key,
                stage_fields_cast_to_json=stage_fields_cast_to_json,
            )

    async def acheck_for_query_permissions_on_table(
        self,
        table: bigquery.Table,
    ):
        """Attempt to SELECT from table to check for query permissions."""
        job_config = bigquery.QueryJobConfig()

        if "timestamp" in [field.name for field in table.schema]:
            query = f"""
            SELECT 1 FROM  `{table.full_table_id.replace(":", ".", 1)}` TABLESAMPLE SYSTEM (0.0001 PERCENT) WHERE timestamp IS NOT NULL
            """

            if table.time_partitioning is not None and table.time_partitioning.field == "timestamp":
                today = dt.date.today()
                query += f" AND DATE(timestamp) = '{today.isoformat()}'"

            query += " LIMIT 1"

        else:
            query = f"""
            SELECT 1 FROM  `{table.full_table_id.replace(":", ".", 1)}` TABLESAMPLE SYSTEM (0.0001 PERCENT) LIMIT 1
            """

        try:
            query_job = self.query(query, job_config=job_config)
            await asyncio.to_thread(query_job.result)
        except Forbidden:
            return False
        return True

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

        # The following `REGEXP_REPLACE` functions are used to clean-up un-paired
        # surrogates, as they are rejected by `PARSE_JSON`. Since BigQuery's regex
        # engine has no lookahead / lookback, we instead use an OR to match both
        # valid pairs and invalid single high or low surrogates, and replacing only
        # with the valid pair in both cases.
        stage_table_fields = ",".join(
            f"""
            PARSE_JSON(
              REGEXP_REPLACE(
                REGEXP_REPLACE(
                  REGEXP_REPLACE(
                    `{field.name}`,
                    r'(\\\\u[dD][89A-Fa-f][0-9A-Fa-f]{{2}}\\\\u[dD][c-fC-F][0-9A-Fa-f]{{2}})|(\\\\u[dD][89A-Fa-f][0-9A-Fa-f]{{2}})',
                    '\\\\1'
                  ),
                  r'(\\\\u[dD][89A-Fa-f][0-9A-Fa-f]{{2}}\\\\u[dD][c-fC-F][0-9A-Fa-f]{{2}})|(\\\\u[dD][c-fC-F][0-9A-Fa-f]{{2}})',
                  '\\\\1'
                ),
                r'[\\n\\r]',
                r'\\\\n'
              ),
              wide_number_mode=>'round'
            )
            """
            if field.name in fields_to_cast
            else f"`{field.name}`"
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

    async def amerge_mutable_tables(
        self,
        final_table: bigquery.Table,
        stage_table: bigquery.Table,
        merge_key: collections.abc.Iterable[bigquery.SchemaField],
        update_key: collections.abc.Iterable[str],
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

        update_condition = "AND ("

        for index, field_name in enumerate(update_key):
            if index > 0:
                update_condition += " OR "
            update_condition += f"final.`{field_name}` < stage.`{field_name}`"
        update_condition += ")"

        update_clause = ""
        values = ""
        field_names = ""

        for n, field in enumerate(final_table.schema):
            if n > 0:
                update_clause += ", "
                values += ", "
                field_names += ", "

            # The following `REGEXP_REPLACE` functions are used to clean-up un-paired
            # surrogates, as they are rejected by `PARSE_JSON`. Since BigQuery's regex
            # engine has no lookahead / lookback, we instead use an OR to match both
            # valid pairs and invalid single high or low surrogates, and replacing only
            # with the valid pair in both cases.
            stage_field = (
                f"""
                PARSE_JSON(
                  REGEXP_REPLACE(
                    REGEXP_REPLACE(
                      REGEXP_REPLACE(
                        stage.`{field.name}`,
                        r'(\\\\u[dD][89A-Ba-b][0-9A-Fa-f]{{2}}\\\\u[dD][c-fC-F][0-9A-Fa-f]{{2}})|(\\\\u[dD][89A-Fa-f][0-9A-Fa-f]{{2}})',
                        '\\\\1'
                      ),
                      r'(\\\\u[dD][89A-Ba-b][0-9A-Fa-f]{{2}}\\\\u[dD][c-fC-F][0-9A-Fa-f]{{2}})|(\\\\u[dD][c-fC-F][0-9A-Fa-f]{{2}})',
                      '\\\\1'
                    ),
                    r'[\\n\\r]',
                    r'\\\\n'
                  ),
                  wide_number_mode=>'round'
                )
                """
                if field.name in fields_to_cast
                else f"stage.`{field.name}`"
            )

            update_clause += f"final.`{field.name}` = {stage_field}"
            field_names += f"`{field.name}`"
            values += stage_field

        if not update_clause:
            raise ValueError("Empty update clause")

        merge_query = f"""
        MERGE `{final_table.full_table_id.replace(":", ".", 1)}` final
        USING (
            SELECT * FROM
            (
              SELECT
              *,
              ROW_NUMBER() OVER (PARTITION BY {",".join(field.name for field in merge_key)}) row_num
            FROM
              `{stage_table.full_table_id.replace(":", ".", 1)}`
            )
            WHERE row_num = 1
        ) stage
        {merge_condition}

        WHEN MATCHED {update_condition} THEN
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

        self.logger.debug("Creating BigQuery load job for Parquet file '%s'", parquet_file)
        load_job = await asyncio.to_thread(
            self.load_table_from_file, parquet_file, table, job_config=job_config, rewind=True
        )
        self.logger.debug("Waiting for BigQuery load job for Parquet file '%s'", parquet_file)

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

        self.logger.debug("Creating BigQuery load job for JSONL file '%s'", jsonl_file)
        load_job = await asyncio.to_thread(
            self.load_table_from_file, jsonl_file, table, job_config=job_config, rewind=True
        )
        self.logger.debug("Waiting for BigQuery load job for JSONL file '%s'", jsonl_file)

        try:
            result = await asyncio.to_thread(load_job.result)
        except Forbidden as err:
            if err.reason == "quotaExceeded":
                raise BigQueryQuotaExceededError(err.message) from err
            raise

        return result

    @classmethod
    def from_service_account_inputs(
        cls, private_key: str, private_key_id: str, token_uri: str, client_email: str, project_id: str
    ) -> typing.Self:
        credentials = service_account.Credentials.from_service_account_info(
            {
                "private_key": private_key,
                "private_key_id": private_key_id,
                "token_uri": token_uri,
                "client_email": client_email,
                "project_id": project_id,
            },
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        client = cls(
            project=project_id,
            credentials=credentials,
        )
        return client


@contextlib.contextmanager
def bigquery_client(inputs: BigQueryInsertInputs):
    """Manage a BigQuery client."""
    client = BigQueryClient.from_service_account_inputs(
        inputs.private_key, inputs.private_key_id, inputs.token_uri, inputs.client_email, inputs.project_id
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
        data_interval_end: dt.datetime | str,
        writer_format: WriterFormat,
        bigquery_client: BigQueryClient,
        bigquery_table: bigquery.Table,
        table_schema: list[bigquery.SchemaField],
    ):
        super().__init__(
            heartbeater=heartbeater,
            heartbeat_details=heartbeat_details,
            data_interval_start=data_interval_start,
            data_interval_end=data_interval_end,
            writer_format=writer_format,
        )
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
        self.external_logger.info(
            "Loading %d records of size %d bytes to BigQuery table '%s'",
            records_since_last_flush,
            bytes_since_last_flush,
            self.bigquery_table,
        )

        if self.writer_format == WriterFormat.PARQUET:
            await self.bigquery_client.load_parquet_file(batch_export_file, self.bigquery_table, self.table_schema)
        else:
            await self.bigquery_client.load_jsonl_file(batch_export_file, self.bigquery_table, self.table_schema)

        self.external_logger.info(
            "Loaded %d records to BigQuery table '%s'", records_since_last_flush, self.bigquery_table
        )
        self.rows_exported_counter.add(records_since_last_flush)
        self.bytes_exported_counter.add(bytes_since_last_flush)

        self.heartbeat_details.records_completed += records_since_last_flush
        self.heartbeat_details.track_done_range(last_date_range, self.data_interval_start)


@activity.defn
@handle_non_retryable_errors(NON_RETRYABLE_ERROR_TYPES)
async def insert_into_bigquery_activity(inputs: BigQueryInsertInputs) -> BatchExportResult:
    """Activity streams data from ClickHouse to BigQuery."""
    bind_contextvars(
        team_id=inputs.team_id,
        destination="BigQuery",
        data_interval_start=inputs.data_interval_start,
        data_interval_end=inputs.data_interval_end,
    )
    external_logger = EXTERNAL_LOGGER.bind()

    external_logger.info(
        "Batch exporting range %s - %s to BigQuery: %s.%s.%s",
        inputs.data_interval_start or "START",
        inputs.data_interval_end or "END",
        inputs.project_id,
        inputs.dataset_id,
        inputs.table_id,
    )

    async with (
        Heartbeater() as heartbeater,
        set_status_to_running_task(run_id=inputs.run_id),
    ):
        is_orderless = str(inputs.team_id) in settings.BATCH_EXPORT_ORDERLESS_TEAM_IDS

        _, details = await should_resume_from_activity_heartbeat(activity, BigQueryHeartbeatDetails)
        if details is None or is_orderless:
            details = BigQueryHeartbeatDetails()

        done_ranges: list[DateRange] = details.done_ranges

        model, record_batch_model, model_name, fields, filters, extra_query_parameters = resolve_batch_exports_model(
            inputs.team_id, inputs.batch_export_model, inputs.batch_export_schema
        )
        data_interval_start = (
            dt.datetime.fromisoformat(inputs.data_interval_start) if inputs.data_interval_start else None
        )
        data_interval_end = dt.datetime.fromisoformat(inputs.data_interval_end)
        full_range = (data_interval_start, data_interval_end)

        queue = RecordBatchQueue(max_size_bytes=settings.BATCH_EXPORT_BIGQUERY_RECORD_BATCH_QUEUE_MAX_SIZE_BYTES)
        producer = Producer(record_batch_model)
        producer_task = await producer.start(
            queue=queue,
            model_name=model_name,
            is_backfill=inputs.get_is_backfill(),
            backfill_details=inputs.backfill_details,
            team_id=inputs.team_id,
            full_range=full_range,
            done_ranges=done_ranges,
            fields=fields,
            filters=filters,
            destination_default_fields=bigquery_default_fields(),
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            extra_query_parameters=extra_query_parameters,
        )

        record_batch_schema = await wait_for_schema_or_producer(queue, producer_task)
        if record_batch_schema is None:
            external_logger.info(
                "Batch export will finish early as there is no data matching specified filters in range %s - %s",
                inputs.data_interval_start or "START",
                inputs.data_interval_end or "END",
            )

            return BatchExportResult(records_completed=details.records_completed)

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

        mutable = False
        merge_key = None
        update_key = None
        if isinstance(inputs.batch_export_model, BatchExportModel):
            if inputs.batch_export_model.name == "persons":
                mutable = True
                merge_key = (
                    bigquery.SchemaField("team_id", "INT64"),
                    bigquery.SchemaField("distinct_id", "STRING"),
                )

                update_key = ["person_version", "person_distinct_id_version"]
            elif inputs.batch_export_model.name == "sessions":
                mutable = True
                merge_key = (
                    bigquery.SchemaField("team_id", "INT64"),
                    bigquery.SchemaField("session_id", "STRING"),
                )
                update_key = ["end_timestamp"]

        data_interval_end_str = dt.datetime.fromisoformat(inputs.data_interval_end).strftime("%Y-%m-%d_%H-%M-%S")
        attempt = activity.info().attempt
        stage_table_name = f"stage_{inputs.table_id}_{data_interval_end_str}_{inputs.team_id}_{attempt}"

        with bigquery_client(inputs) as bq_client:
            async with bq_client.managed_table(
                project_id=inputs.project_id,
                dataset_id=inputs.dataset_id,
                table_id=inputs.table_id,
                table_schema=schema,
                delete=False,
            ) as bigquery_table:
                can_perform_merge = await bq_client.acheck_for_query_permissions_on_table(bigquery_table)

                if not can_perform_merge:
                    if model_name == "persons":
                        raise MissingRequiredPermissionsError()

                    external_logger.warning(
                        "Missing query permissions on BigQuery table required for merging, will attempt direct load into final table"
                    )

                async with bq_client.managed_table(
                    project_id=inputs.project_id,
                    dataset_id=inputs.dataset_id,
                    table_id=stage_table_name if can_perform_merge else inputs.table_id,
                    table_schema=stage_schema,
                    create=can_perform_merge,
                    delete=can_perform_merge,
                ) as bigquery_stage_table:
                    consumer = BigQueryConsumer(
                        heartbeater=heartbeater,
                        heartbeat_details=details,
                        data_interval_end=data_interval_end,
                        data_interval_start=data_interval_start,
                        writer_format=WriterFormat.PARQUET if can_perform_merge else WriterFormat.JSONL,
                        bigquery_client=bq_client,
                        bigquery_table=bigquery_stage_table if can_perform_merge else bigquery_table,
                        table_schema=stage_schema if can_perform_merge else schema,
                    )

                    try:
                        await run_consumer(
                            consumer=consumer,
                            queue=queue,
                            producer_task=producer_task,
                            schema=record_batch_schema,
                            max_bytes=settings.BATCH_EXPORT_BIGQUERY_UPLOAD_CHUNK_SIZE_BYTES,
                            json_columns=() if can_perform_merge else json_columns,
                            writer_file_kwargs={"compression": "zstd"} if can_perform_merge else {},
                            multiple_files=True,
                        )

                    except Exception:
                        # Ensure we always write data to final table,  even if
                        # we fail halfway through, as if we resume from a
                        # heartbeat, we can continue without losing data
                        # However, orderless batch exports should not merge
                        # partial data as they will resume from the beginning.
                        if can_perform_merge and not is_orderless:
                            await bq_client.amerge_tables(
                                final_table=bigquery_table,
                                stage_table=bigquery_stage_table,
                                mutable=mutable,
                                merge_key=merge_key,
                                update_key=update_key,
                                stage_fields_cast_to_json=json_columns,
                            )
                        raise

                    else:
                        if can_perform_merge:
                            await bq_client.amerge_tables(
                                final_table=bigquery_table,
                                stage_table=bigquery_stage_table,
                                mutable=mutable,
                                merge_key=merge_key,
                                update_key=update_key,
                                stage_fields_cast_to_json=json_columns,
                            )

        return BatchExportResult(records_completed=details.records_completed)


class BigQueryConsumerFromStage(ConsumerFromStage):
    def __init__(
        self,
        client: BigQueryClient,
        table: bigquery.Table,
        table_schema: collections.abc.Sequence[bigquery.SchemaField],
        file_format: typing.Literal["Parquet", "JSONLines"],
    ):
        super().__init__()

        self.client = client
        self.table = table
        self.table_schema = table_schema
        self.file_format = file_format

        self.logger = self.logger.bind(table=self.table)

        self.current_file_index = 0
        self.current_buffer = io.BytesIO()

    async def consume_chunk(self, data: bytes):
        self.current_buffer.write(data)
        await asyncio.sleep(0)

    async def finalize_file(self):
        await self._upload_current_buffer()
        self._start_new_file()

    def _start_new_file(self):
        """Start a new file (reset state for file splitting)."""
        self.current_file_index += 1

    async def finalize(self):
        """Finalize by uploading any remaining data."""
        await self._upload_current_buffer()

    async def _upload_current_buffer(self):
        buffer_size = self.current_buffer.tell()
        if buffer_size == 0:
            return

        self.logger.debug(
            "Load job starting",
            current_file_index=self.current_file_index,
            buffer_size=buffer_size,
        )

        if self.file_format == "Parquet":
            await self.client.load_parquet_file(self.current_buffer, table=self.table, table_schema=self.table_schema)
        elif self.file_format == "JSONLines":
            await self.client.load_jsonl_file(self.current_buffer, table=self.table, table_schema=self.table_schema)
        else:
            raise ValueError(f"Unsupported file format: '{self.file_format}'")

        self.logger.debug(
            "Load job finished",
            current_file_index=self.current_file_index,
            buffer_size=buffer_size,
        )

        self.current_buffer = io.BytesIO()


class TableSchemas(typing.NamedTuple):
    table_schema: collections.abc.Sequence[bigquery.SchemaField]
    stage_table_schema: collections.abc.Sequence[bigquery.SchemaField]
    json_columns: collections.abc.Sequence[str]


def _get_table_schemas(
    model: BatchExportModel | BatchExportSchema | None, record_batch_schema: pa.Schema, use_json_type: bool
) -> TableSchemas:
    """Return the schemas used for main and stage tables."""
    if use_json_type is True:
        json_type = "JSON"
        json_columns = ["properties", "set", "set_once", "person_properties"]
    else:
        json_type = "STRING"
        json_columns = []

    if model is None or (isinstance(model, BatchExportModel) and model.name == "events"):
        table_schema = [
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
        table_schema = get_bigquery_fields_from_record_schema(record_batch_schema, known_json_columns=json_columns)

    stage_table_schema = [
        bigquery.SchemaField(field.name, "STRING") if field.name in json_columns else field for field in table_schema
    ]

    return TableSchemas(table_schema, stage_table_schema, json_columns)


class MergeSettings(typing.NamedTuple):
    requires_merge: bool
    merge_key: collections.abc.Sequence[bigquery.SchemaField] | None
    update_key: collections.abc.Sequence[str] | None


def _get_merge_settings(
    model: BatchExportModel | BatchExportSchema | None,
) -> MergeSettings:
    """Return merge settings for models that require merging."""
    requires_merge = False
    merge_key = None
    update_key = None

    if isinstance(model, BatchExportModel):
        if model.name == "persons":
            requires_merge = True
            merge_key = (
                bigquery.SchemaField("team_id", "INT64"),
                bigquery.SchemaField("distinct_id", "STRING"),
            )

            update_key = ["person_version", "person_distinct_id_version"]
        elif model.name == "sessions":
            requires_merge = True
            merge_key = (
                bigquery.SchemaField("team_id", "INT64"),
                bigquery.SchemaField("session_id", "STRING"),
            )
            update_key = ["end_timestamp"]

    return MergeSettings(requires_merge, merge_key, update_key)


@activity.defn
@handle_non_retryable_errors(NON_RETRYABLE_ERROR_TYPES)
async def insert_into_bigquery_activity_from_stage(inputs: BigQueryInsertInputs) -> BatchExportResult:
    """Activity streams data from ClickHouse to BigQuery."""
    bind_contextvars(
        team_id=inputs.team_id,
        destination="BigQuery",
        data_interval_start=inputs.data_interval_start,
        data_interval_end=inputs.data_interval_end,
        batch_export_id=inputs.batch_export_id,
        project_id=inputs.project_id,
        dataset_id=inputs.dataset_id,
        table_id=inputs.table_id,
    )
    external_logger = EXTERNAL_LOGGER.bind()

    external_logger.info(
        "Batch exporting range %s - %s to BigQuery: %s.%s.%s",
        inputs.data_interval_start or "START",
        inputs.data_interval_end or "END",
        inputs.project_id,
        inputs.dataset_id,
        inputs.table_id,
    )

    async with Heartbeater():
        model: BatchExportModel | BatchExportSchema | None = None
        if inputs.batch_export_schema is None:
            model = inputs.batch_export_model
        else:
            model = inputs.batch_export_schema

        queue = RecordBatchQueue(max_size_bytes=settings.BATCH_EXPORT_BIGQUERY_RECORD_BATCH_QUEUE_MAX_SIZE_BYTES)
        producer = ProducerFromInternalStage()
        assert inputs.batch_export_id is not None
        producer_task = await producer.start(
            queue=queue,
            batch_export_id=inputs.batch_export_id,
            data_interval_start=inputs.data_interval_start,
            data_interval_end=inputs.data_interval_end,
            max_record_batch_size_bytes=1024 * 1024 * 60,  # 60MB
        )

        record_batch_schema = await wait_for_schema_or_producer(queue, producer_task)
        if record_batch_schema is None:
            external_logger.info(
                "Batch export will finish early as there is no data matching specified filters in range %s - %s",
                inputs.data_interval_start or "START",
                inputs.data_interval_end or "END",
            )

            return BatchExportResult(records_completed=0, bytes_exported=0)

        record_batch_schema = pa.schema(
            [field.with_nullable(True) for field in record_batch_schema if field.name != "_inserted_at"]
        )
        table_schemas = _get_table_schemas(
            model=model, record_batch_schema=record_batch_schema, use_json_type=inputs.use_json_type
        )

        merge_settings = _get_merge_settings(model=model)

        data_interval_end_str = dt.datetime.fromisoformat(inputs.data_interval_end).strftime("%Y-%m-%d_%H-%M-%S")
        attempt = activity.info().attempt
        stage_table_name = f"stage_{inputs.table_id}_{data_interval_end_str}_{inputs.team_id}_{attempt}"

        with bigquery_client(inputs) as bq_client:
            async with bq_client.managed_table(
                project_id=inputs.project_id,
                dataset_id=inputs.dataset_id,
                table_id=inputs.table_id,
                table_schema=table_schemas.table_schema,
                delete=False,
            ) as bigquery_table:
                can_perform_merge = await bq_client.acheck_for_query_permissions_on_table(bigquery_table)

                if not can_perform_merge:
                    if merge_settings.requires_merge:
                        raise MissingRequiredPermissionsError()

                    external_logger.warning(
                        "Missing query permissions on BigQuery table required for merging, will attempt direct load into final table"
                    )

                async with bq_client.managed_table(
                    project_id=inputs.project_id,
                    dataset_id=inputs.dataset_id,
                    table_id=stage_table_name if can_perform_merge else inputs.table_id,
                    table_schema=table_schemas.stage_table_schema,
                    create=can_perform_merge,
                    delete=can_perform_merge,
                ) as bigquery_stage_table:
                    consumer = BigQueryConsumerFromStage(
                        client=bq_client,
                        table=bigquery_stage_table if can_perform_merge else bigquery_table,
                        table_schema=table_schemas.stage_table_schema
                        if can_perform_merge
                        else table_schemas.table_schema,
                        file_format="Parquet" if can_perform_merge else "JSONLines",
                    )

                    if can_perform_merge:
                        transformer: ChunkTransformerProtocol = ParquetStreamTransformer(
                            compression="zstd",
                            max_file_size_bytes=settings.BATCH_EXPORT_BIGQUERY_UPLOAD_CHUNK_SIZE_BYTES,
                        )
                    else:
                        transformer = JSONLStreamTransformer()

                    result = await run_consumer_from_stage(
                        queue=queue,
                        consumer=consumer,
                        producer_task=producer_task,
                        transformer=transformer,
                    )

                    if can_perform_merge:
                        _ = await bq_client.amerge_tables(
                            final_table=bigquery_table,
                            stage_table=bigquery_stage_table,
                            mutable=merge_settings.requires_merge,
                            merge_key=merge_settings.merge_key,
                            update_key=merge_settings.update_key,
                            stage_fields_cast_to_json=table_schemas.json_columns,
                        )

                    return result


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
        is_backfill = inputs.get_is_backfill()
        is_earliest_backfill = inputs.get_is_earliest_backfill()
        data_interval_start, data_interval_end = get_data_interval(inputs.interval, inputs.data_interval_end)
        should_backfill_from_beginning = is_backfill and is_earliest_backfill

        start_batch_export_run_inputs = StartBatchExportRunInputs(
            team_id=inputs.team_id,
            batch_export_id=inputs.batch_export_id,
            data_interval_start=data_interval_start.isoformat() if not should_backfill_from_beginning else None,
            data_interval_end=data_interval_end.isoformat(),
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            backfill_id=inputs.backfill_details.backfill_id if inputs.backfill_details else None,
        )
        try:
            run_id = await workflow.execute_activity(
                start_batch_export_run,
                start_batch_export_run_inputs,
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(seconds=60),
                    maximum_attempts=0,
                    non_retryable_error_types=["NotNullViolation", "IntegrityError", "OverBillingLimitError"],
                ),
            )
        except OverBillingLimitError:
            return

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
            backfill_details=inputs.backfill_details,
            is_backfill=is_backfill,
            batch_export_model=inputs.batch_export_model,
            # TODO: Remove after updating existing batch exports.
            batch_export_schema=inputs.batch_export_schema,
            batch_export_id=inputs.batch_export_id,
            destination_default_fields=bigquery_default_fields(),
        )

        if (
            str(inputs.team_id) in settings.BATCH_EXPORT_BIGQUERY_USE_STAGE_TEAM_IDS
            or inputs.team_id % 100 < settings.BATCH_EXPORT_BIGQUERY_USE_INTERNAL_STAGE_ROLLOUT_PERCENTAGE
        ):
            await execute_batch_export_using_internal_stage(
                insert_into_bigquery_activity_from_stage,
                insert_inputs,
                interval=inputs.interval,
                maximum_retry_interval_seconds=240,
            )
        else:
            await execute_batch_export_insert_activity(
                insert_into_bigquery_activity,
                insert_inputs,
                interval=inputs.interval,
                finish_inputs=finish_inputs,
                maximum_retry_interval_seconds=240,
            )
