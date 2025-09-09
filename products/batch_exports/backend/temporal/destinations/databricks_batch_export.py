import io
import json
import time
import typing as t
import asyncio
import datetime as dt
import contextlib
import dataclasses
import collections.abc

from django.conf import settings

import pyarrow as pa
from databricks import sql
from databricks.sdk.core import Config, oauth_service_principal
from databricks.sql.client import Connection
from databricks.sql.exc import OperationalError
from databricks.sql.types import Row
from structlog.contextvars import bind_contextvars
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.service import (
    BatchExportField,
    BatchExportInsertInputs,
    BatchExportModel,
    BatchExportSchema,
    DatabricksBatchExportInputs,
)
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_produce_only_logger, get_write_only_logger

from products.batch_exports.backend.temporal.batch_exports import (
    StartBatchExportRunInputs,
    events_model_default_fields,
    get_data_interval,
    start_batch_export_run,
)
from products.batch_exports.backend.temporal.pipeline.consumer import Consumer, run_consumer_from_stage
from products.batch_exports.backend.temporal.pipeline.entrypoint import execute_batch_export_using_internal_stage
from products.batch_exports.backend.temporal.pipeline.producer import Producer
from products.batch_exports.backend.temporal.pipeline.types import BatchExportResult
from products.batch_exports.backend.temporal.spmc import RecordBatchQueue, wait_for_schema_or_producer
from products.batch_exports.backend.temporal.utils import JsonType, handle_non_retryable_errors

LOGGER = get_write_only_logger(__name__)
EXTERNAL_LOGGER = get_produce_only_logger("EXTERNAL")


NON_RETRYABLE_ERROR_TYPES: list[str] = []

DatabricksField = tuple[str, str]


class DatabricksConnectionError(Exception):
    """Error for Databricks connection."""

    pass


@dataclasses.dataclass(kw_only=True)
class DatabricksInsertInputs(BatchExportInsertInputs):
    """Inputs for Databricks.

    server_hostname: the Server Hostname value for user's all-purpose compute or SQL warehouse.
    http_path: HTTP Path value for user's all-purpose compute or SQL warehouse.
    client_id: the service principal's UUID or Application ID value.
    client_secret: the Secret value for the service principal's OAuth secret.
    use_variant_type: whether to use the VARIANT data type for storing JSON data.
        If False, we will use the STRING data type. Using VARIANT for storing JSON data is recommended by Databricks,
        however, VARIANT is only available in Databricks Runtime 15.3 and above.
        See: https://docs.databricks.com/aws/en/semi-structured/variant
    use_automatic_schema_evolution: whether to use automatic schema evolution for the merge operation.
        If True, we will use `WITH SCHEMA EVOLUTION` to enable [automatic schema
        evolution](https://docs.databricks.com/aws/en/delta/update-schema#automatic-schema-evolution-for-delta-lake-merge).
        This means the target table will automatically be updated with the schema of the source table (however, no
        columns will be dropped from the target table).
    """

    # TODO - some of this will go in the integration model once ready

    server_hostname: str
    http_path: str
    client_id: str
    client_secret: str
    catalog: str
    schema: str
    table_name: str
    use_variant_type: bool = True
    use_automatic_schema_evolution: bool = True


class DatabricksClient:
    # How often to poll for query status. This is a trade-off between responsiveness and number of
    # queries we make to Databricks. 1 second has been chosen rather arbitrarily.
    DEFAULT_POLL_INTERVAL = 1.0

    def __init__(
        self,
        server_hostname: str,
        http_path: str,
        client_id: str,
        client_secret: str,
        catalog: str,
        schema: str,
    ):
        self.server_hostname = server_hostname
        self.http_path = http_path
        self.client_id = client_id
        self.client_secret = client_secret
        self.catalog = catalog
        self.schema = schema

        self._connection: None | Connection = None

        self.logger = LOGGER.bind(server_hostname=server_hostname, http_path=http_path)
        self.external_logger = EXTERNAL_LOGGER.bind(server_hostname=server_hostname, http_path=http_path)

    @classmethod
    def from_inputs(cls, inputs: DatabricksInsertInputs) -> t.Self:
        return cls(
            server_hostname=inputs.server_hostname,
            http_path=inputs.http_path,
            client_id=inputs.client_id,
            client_secret=inputs.client_secret,
            catalog=inputs.catalog,
            schema=inputs.schema,
        )

    @property
    def connection(self) -> Connection:
        """Raise if a `Connection` hasn't been established, else return it."""
        if self._connection is None:
            # this should never happen and inidicates a bug in our code (i.e. trying to execute a query before
            # establishing a connection)
            raise Exception("Not connected, open a connection by calling `connect`")
        return self._connection

    def get_credential_provider(self):
        config = Config(
            host=f"https://{self.server_hostname}", client_id=self.client_id, client_secret=self.client_secret
        )
        return oauth_service_principal(config)

    @contextlib.asynccontextmanager
    async def connect(self):
        """Manage a Databricks connection.

        Methods that require a connection should be ran within this block.

        We call `use_catalog` and `use_schema` to ensure that all queries are run in the correct catalog and schema.
        """
        self.logger.debug("Initializing Databricks connection")

        try:
            self._connection = await asyncio.to_thread(
                sql.connect,
                server_hostname=self.server_hostname,
                http_path=self.http_path,
                credentials_provider=self.get_credential_provider,
                # user agent can be used for usage tracking
                user_agent_entry="PostHog batch exports",
                # TODO
                # staging_allowed_local_path=str(staging_allowed_local_path),
            )
        except OperationalError as err:
            # TODO: check what kinds of errors we get here
            raise DatabricksConnectionError(f"Failed to connect to Databricks: {err}") from err

        self.logger.debug("Connected to Databricks")

        await self.use_catalog(self.catalog)
        await self.use_schema(self.schema)

        try:
            yield self
        finally:
            await asyncio.to_thread(self._connection.close)
            self._connection = None

    async def execute_query(
        self, query: str, parameters: dict | None = None, query_kwargs: dict | None = None, fetch_results: bool = True
    ) -> list[Row] | None:
        """Execute a query and wait for it to complete.

        We run the query in a separate thread to avoid blocking the event loop in the main thread.
        """
        query_kwargs = query_kwargs or {}
        # TODO - ensure errors are raised correctly
        query_start_time = time.time()
        self.logger.debug("Executing query: %s", query)

        with self.connection.cursor() as cursor:
            try:
                await asyncio.to_thread(cursor.execute, query, parameters, **query_kwargs)
            finally:
                query_execution_time = time.time() - query_start_time
                self.logger.debug("Query completed in %.2fs", query_execution_time)

            if not fetch_results:
                return

            results = await asyncio.to_thread(cursor.fetchall)
            # description = cursor.description
            # return results, description
            return results

    async def execute_async_query(
        self,
        query: str,
        parameters: dict | None = None,
        poll_interval: float | None = None,
        fetch_results: bool = True,
        timeout: float = 60 * 60,  # 1 hour
    ) -> list[Row] | None:
        """Execute a query asynchronously and poll for results.

        This is useful for long running queries as it means we don't need to maintain a network connection to the
        Databricks server, which could timeout or be interrupted.

        Executing the query and polling for results are done in separate threads in order to avoid blocking the event
        loop in the main thread.

        Args:
            query: The query to execute.
            parameters: The parameters to bind to the query.
            poll_interval: The interval (in seconds) to poll for results.
            fetch_results: Whether to fetch results.
            timeout: The timeout (in seconds) to wait for the query to complete.
                This is more of a safeguard than anything else, just to prevent us waiting forever.

        # TODO - decide what to return (if we need description or not)
        Returns:
            If `fetch_results` is `True`, a tuple containing:
            - The query results as a list of tuples or dicts
            # - The cursor description (containing list of fields in result)
            Else when `fetch_results` is `False` we return `None`.
        """
        # TODO - ensure errors are raised correctly
        poll_interval = poll_interval or self.DEFAULT_POLL_INTERVAL

        query_start_time = time.time()
        self.logger.debug("Executing async query: %s", query)

        with self.connection.cursor() as cursor:
            await asyncio.to_thread(cursor.execute_async, query, parameters)

            self.logger.debug("Waiting for async query to complete")

            while await asyncio.to_thread(cursor.is_query_pending):
                await asyncio.sleep(poll_interval)
                if time.time() - query_start_time > timeout:
                    raise TimeoutError(f"Timed out waiting for query to complete after {timeout} seconds")

            # this should return an exception if the query failed so ensure we log the query time
            try:
                await asyncio.to_thread(cursor.get_async_execution_result)
            finally:
                query_execution_time = time.time() - query_start_time
                self.logger.debug("Async query completed in %.2fs", query_execution_time)

            if fetch_results is False:
                return

            self.logger.debug("Fetching query results")

            results = await asyncio.to_thread(cursor.fetchall)
            # description = cursor.description

            self.logger.debug("Finished fetching query results")

            # return results, description
            return results

    async def use_catalog(self, catalog: str):
        await self.execute_query(f"USE CATALOG {catalog}", fetch_results=False)

    async def use_schema(self, schema: str):
        await self.execute_query(f"USE SCHEMA {schema}", fetch_results=False)

    @contextlib.asynccontextmanager
    async def managed_table(
        self,
        table_name: str,
        fields: list[DatabricksField],
        delete: bool = False,
    ):
        """Manage a table in Databricks by ensuring it exists while in context."""
        # log if we're creating a permanent table
        if delete is False:
            self.external_logger.info("Creating Databricks table %s", table_name)
        else:
            self.logger.info("Creating Databricks table %s", table_name)

        await self.acreate_table(table_name, fields)

        yield table_name

        if delete is True:
            self.logger.info("Deleting Databricks table %s", table_name)
            await self.adelete_table(table_name)

    async def acreate_table(self, table_name: str, fields: list[DatabricksField]):
        """Asynchronously create the Databricks delta table if it doesn't exist."""
        # TODO - add partition by timestamp if it exists?
        field_ddl = ", ".join(f'"{field[0]}" {field[1]}' for field in fields)
        await self.execute_query(
            f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                {field_ddl}
            )
            USING DELTA
            COMMENT = 'PostHog generated table'
            """,
            fetch_results=False,
        )

    async def adelete_table(self, table_name: str):
        """Asynchronously delete the Databricks delta table if it exists."""
        await self.execute_query(f"DROP TABLE IF EXISTS {table_name}", fetch_results=False)

    async def aput_file_stream_to_volume(self, file: io.BytesIO, volume_name: str, file_name: str):
        """Asynchronously put a local file stream to a Databricks volume."""
        results = await self.execute_query(
            f"PUT '__input_stream__' INTO '{volume_name}/{file_name}' OVERWRITE",
            query_kwargs={"input_stream": file},
        )
        # TODO - check results

    async def acopy_into_table_from_volume(self, table_name: str, volume_name: str):
        """Asynchronously copy data from a Databricks volume into a Databricks table."""
        results = await self.execute_async_query(
            f"COPY INTO {table_name} FROM '{volume_name}' FILEFORMAT = PARQUET",
        )

    @contextlib.asynccontextmanager
    async def managed_volume(self, volume: str):
        """Manage a volume in Databricks by ensuring it exists while in context."""
        self.logger.info("Creating Databricks volume %s", volume)
        await self.acreate_volume(volume)
        yield volume
        self.logger.info("Deleting Databricks volume %s", volume)
        await self.adelete_volume(volume)

    async def acreate_volume(self, volume: str):
        """Asynchronously create a Databricks volume."""
        await self.execute_query(
            f"CREATE VOLUME IF NOT EXISTS {volume} COMMENT 'PostHog generated volume'",
            fetch_results=False,
        )

    async def adelete_volume(self, volume: str):
        """Asynchronously delete a Databricks volume."""
        await self.execute_query(
            f"DROP VOLUME IF EXISTS {volume}",
            fetch_results=False,
        )

    async def aget_table_columns(self, table_name: str) -> list[str]:
        """Asynchronously get the columns of a Databricks table.

        The Databricks connector has dedicated methods for retrieving metadata.
        """
        with self.connection.cursor() as cursor:
            await asyncio.to_thread(cursor.columns, table_name=table_name)
            results = await asyncio.to_thread(cursor.fetchall)
            # TODO - check results
            return [row.name for row in results]

    async def amerge_mutable_tables(
        self,
        target_table: str,
        source_table: str,
        merge_key: collections.abc.Iterable[DatabricksField],
        update_key: collections.abc.Iterable[str],
        fields: collections.abc.Iterable[DatabricksField],
        with_schema_evolution: bool = True,
    ):
        """Merge data from source_table into target_table in Databricks.

        If `with_schema_evolution` is True, we will use `WITH SCHEMA EVOLUTION` to enable [automatic schema
        evolution](https://docs.databricks.com/aws/en/delta/update-schema#automatic-schema-evolution-for-delta-lake-merge).
        This means the target table will automatically be updated with the schema of the source table (however, no
        columns will be dropped from the target table).

        Otherwise, we use the more manual approach of getting the column names from the target table and then specifying
        the individual columns in the `MERGE` query to update the target table.
        """

        # TODO - add tests to test this SQL

        assert merge_key, "Merge key must be defined"
        assert update_key, "Update key must be defined"
        assert fields, "Fields must be defined"

        merge_condition = " AND ".join([f'target."{field[0]}" = source."{field[0]}"' for field in merge_key])

        update_condition = " OR ".join([f'target."{field[0]}" < source."{field[0]}"' for field in update_key])

        if with_schema_evolution is True:
            merge_query = f"""
            MERGE WITH SCHEMA EVOLUTION INTO {target_table} AS target
            USING {source_table} AS source
            ON {merge_condition}
            WHEN MATCHED AND ({update_condition}) THEN
                UPDATE SET *
            WHEN NOT MATCHED THEN
                INSERT *
            """
        else:
            # first we need to get the column names from the target table
            target_table_field_names = await self.aget_table_columns(target_table)

            update_clause = ", ".join(
                [
                    f'target."{field[0]}" = source."{field[0]}"'
                    for field in fields
                    if field[0] in target_table_field_names
                ]
            )
            field_names = ", ".join([f'"{field[0]}"' for field in fields if field[0] in target_table_field_names])
            values = ", ".join([f'source."{field[0]}"' for field in fields if field[0] in target_table_field_names])

            merge_query = f"""
            MERGE INTO {target_table} AS target
            USING {source_table} AS source
            ON {merge_condition}
            WHEN MATCHED AND ({update_condition}) THEN
                UPDATE SET
                    {update_clause}
            WHEN NOT MATCHED THEN
                INSERT ({field_names})
                VALUES ({values})
            """

        await self.execute_async_query(merge_query, fetch_results=False)


def databricks_default_fields() -> list[BatchExportField]:
    """Default fields for a Databricks batch export.

    NOTE: for Databricks, we are exporting a reduced set of fields compared to other destinations as we're not so
    concerned about supporting legacy fields for backwards compatibility.
    """
    batch_export_fields = events_model_default_fields()
    # add a metadata field for the ingested timestamp to aid with debugging
    # (this is not strictly the time the data is ingested into Databricks but rather the time we query it from ClickHouse)
    batch_export_fields.append({"expression": "NOW64()", "alias": "databricks_ingested_timestamp"})
    return batch_export_fields


def _get_databricks_fields_from_record_schema(
    record_schema: pa.Schema, known_variant_columns: list[str]
) -> list[DatabricksField]:
    """Maps a PyArrow schema to a list of Databricks fields.

    Arguments:
        record_schema: The schema of a PyArrow RecordBatch from which we'll attempt to
            derive Databricks-supported types.
        known_variant_columns: If a string type field is a known VARIANT column then use VARIANT
            as its Databricks type.
    """
    databricks_schema: list[DatabricksField] = []

    for name in record_schema.names:
        pa_field = record_schema.field(name)

        if pa.types.is_string(pa_field.type) or isinstance(pa_field.type, JsonType):
            if pa_field.name in known_variant_columns:
                databricks_type = "VARIANT"
            else:
                databricks_type = "STRING"

        elif pa.types.is_binary(pa_field.type):
            databricks_type = "BINARY"

        elif pa.types.is_signed_integer(pa_field.type) or pa.types.is_unsigned_integer(pa_field.type):
            databricks_type = "INTEGER"

        elif pa.types.is_floating(pa_field.type):
            databricks_type = "FLOAT"

        elif pa.types.is_boolean(pa_field.type):
            databricks_type = "BOOLEAN"

        elif pa.types.is_timestamp(pa_field.type):
            databricks_type = "TIMESTAMP"

        elif pa.types.is_list(pa_field.type):
            databricks_type = "ARRAY"

        else:
            raise TypeError(f"Unsupported type in field '{name}': '{databricks_type}'")

        databricks_schema.append((name, databricks_type))

    return databricks_schema


def _get_databricks_table_settings(
    model: BatchExportModel | BatchExportSchema | None, record_batch_schema: pa.Schema, use_variant_type: bool
) -> tuple[list[DatabricksField], pa.Schema, list[str]]:
    """Get the various table settings for this batch export.

    For the events model, we actually export a reduced set of fields compared to other destinations for a number of reasons:
    - we do not need to support legacy fields, such as `set` and `set_once`
    - some fields, such as `ip` and `site_url`, are also present in `properties` so we can ignore these for efficiency
    - `elements` is not particularly useful in its current form (it is in a custom serialized format)
    """
    # we don't export the _inserted_at field
    record_batch_schema = pa.schema(
        [field.with_nullable(True) for field in record_batch_schema if field.name != "_inserted_at"]
    )

    if use_variant_type is True:
        json_type = "VARIANT"
        known_variant_columns = ["properties", "person_properties"]
    else:
        json_type = "STRING"
        known_variant_columns = []

    if model is None or (isinstance(model, BatchExportModel) and model.name == "events"):
        table_fields = [
            ("uuid", "STRING"),
            ("event", "STRING"),
            ("properties", json_type),
            ("distinct_id", "STRING"),
            ("team_id", "INTEGER"),
            ("timestamp", "TIMESTAMP"),
            ("databricks_ingested_timestamp", "TIMESTAMP"),
        ]
    else:
        table_fields = _get_databricks_fields_from_record_schema(
            record_batch_schema,
            known_variant_columns=known_variant_columns,
        )

    return table_fields, record_batch_schema, known_variant_columns


def _get_databricks_merge_config(
    model: BatchExportModel | BatchExportSchema | None,
) -> tuple[bool, list[DatabricksField], list[str]]:
    requires_merge = False
    merge_key = []
    update_key = []
    if isinstance(model, BatchExportModel):
        if model.name == "persons":
            requires_merge = True
            merge_key = [("team_id", "INTEGER"), ("distinct_id", "STRING")]
            update_key = ["person_version", "person_distinct_id_version"]
        elif model.name == "sessions":
            requires_merge = True
            merge_key = [("team_id", "INTEGER"), ("session_id", "STRING")]
            update_key = ["end_timestamp"]
    return requires_merge, merge_key, update_key


class DatabricksConsumer(Consumer):
    """A consumer that uploads data to a Databricks managed volume."""

    def __init__(
        self,
        client: DatabricksClient,
        volume_name: str,
    ):
        super().__init__()

        self.client = client
        self.volume_name = volume_name

        self.logger.bind(
            volume=self.volume_name,
        )

        self.current_file_index = 0
        self.current_buffer = io.BytesIO()

    async def consume_chunk(self, data: bytes):
        """Consume a chunk of data by writing it to the current buffer."""
        self.current_buffer.write(data)
        await asyncio.sleep(0)

    async def finalize_file(self):
        """Finalize the current file and start a new one."""
        await self._upload_current_buffer()
        self._start_new_file()

    def _start_new_file(self):
        self.current_file_index += 1

    async def _upload_current_buffer(self):
        """Upload the current buffer to Databricks, then start a new one."""
        buffer_size = self.current_buffer.tell()
        if buffer_size == 0:
            return  # Nothing to upload

        self.logger.info(
            "Uploading file %d with %d bytes to Databricks volume '%s'",
            self.current_file_index,
            buffer_size,
            self.volume_name,
        )

        self.current_buffer.seek(0)

        await self.client.aput_file_stream_to_volume(
            file=self.current_buffer,
            volume_name=self.volume_name,
            file_name=f"{self.current_file_index}.parquet",
        )

        self.external_logger.info(
            "File %d with %d bytes uploaded to Databricks volume '%s'",
            self.current_file_index,
            buffer_size,
            self.volume_name,
        )
        self.current_buffer = io.BytesIO()

    async def finalize(self):
        """Finalize by uploading any remaining data."""
        await self._upload_current_buffer()


@contextlib.asynccontextmanager
async def manage_resources(
    client: DatabricksClient,
    volume_name: str,
    fields: list[DatabricksField],
    table_name: str,
    stage_table_name: str | None = None,
) -> t.AsyncGenerator[tuple[str, str, str | None], None]:
    """Manage resources in Databricks by ensuring they exist while in context."""
    async with client.managed_volume(volume_name) as volume:
        async with client.managed_table(table_name, fields, delete=False) as table:
            if stage_table_name is not None:
                async with client.managed_table(stage_table_name, fields, delete=True) as stage_table:
                    yield volume, table, stage_table
            else:
                yield volume, table, None


@activity.defn
@handle_non_retryable_errors(NON_RETRYABLE_ERROR_TYPES)
async def insert_into_databricks_activity_from_stage(inputs: DatabricksInsertInputs) -> BatchExportResult:
    """Activity to batch export data from internal S3 stage to Databricks."""
    bind_contextvars(
        team_id=inputs.team_id,
        destination="Databricks",
        data_interval_start=inputs.data_interval_start,
        data_interval_end=inputs.data_interval_end,
        batch_export_id=inputs.batch_export_id,
        catalog=inputs.catalog,
        schema=inputs.schema,
        table_name=inputs.table_name,
    )
    external_logger = EXTERNAL_LOGGER.bind()

    external_logger.info(
        "Batch exporting range %s - %s to Databricks: %s.%s.%s",
        inputs.data_interval_start or "START",
        inputs.data_interval_end or "END",
        inputs.catalog,
        inputs.schema,
        inputs.table_name,
    )

    async with Heartbeater():
        model: BatchExportModel | BatchExportSchema | None = None
        if inputs.batch_export_schema is None:
            model = inputs.batch_export_model
        else:
            model = inputs.batch_export_schema

        queue = RecordBatchQueue(max_size_bytes=settings.BATCH_EXPORT_DATABRICKS_RECORD_BATCH_QUEUE_MAX_SIZE_BYTES)
        producer = Producer()
        assert inputs.batch_export_id is not None
        producer_task = await producer.start(
            queue=queue,
            batch_export_id=inputs.batch_export_id,
            data_interval_start=inputs.data_interval_start,
            data_interval_end=inputs.data_interval_end,
            max_record_batch_size_bytes=1024 * 1024 * 10,  # 10MB
        )

        record_batch_schema = await wait_for_schema_or_producer(queue, producer_task)
        if record_batch_schema is None:
            external_logger.info(
                "Batch export will finish early as there is no data matching specified filters in range %s - %s",
                inputs.data_interval_start or "START",
                inputs.data_interval_end or "END",
            )

            return BatchExportResult(records_completed=0, bytes_exported=0)

        table_fields, record_batch_schema, known_variant_columns = _get_databricks_table_settings(
            model=model, record_batch_schema=record_batch_schema, use_variant_type=inputs.use_variant_type
        )

        requires_merge, merge_key, update_key = _get_databricks_merge_config(model=model)

        data_interval_end_str = dt.datetime.fromisoformat(inputs.data_interval_end).strftime("%Y-%m-%d_%H-%M-%S")
        stage_table_name: str | None = (
            f"stage_{inputs.table_name}_{data_interval_end_str}_{inputs.team_id}" if requires_merge else None
        )
        volume_name = f"stage_{inputs.table_name}_{data_interval_end_str}_{inputs.team_id}"

        async with DatabricksClient.from_inputs(inputs).connect() as databricks_client:
            async with manage_resources(
                client=databricks_client,
                volume_name=volume_name,
                fields=table_fields,
                table_name=inputs.table_name,
                stage_table_name=stage_table_name,
            ):
                consumer = DatabricksConsumer(
                    client=databricks_client,
                    volume_name=volume_name,
                )

                result = await run_consumer_from_stage(
                    queue=queue,
                    consumer=consumer,
                    producer_task=producer_task,
                    schema=record_batch_schema,
                    file_format="Parquet",
                    # TODO - add compression
                    # compression="zstd",
                    compression=None,
                    include_inserted_at=False,
                    max_file_size_bytes=settings.BATCH_EXPORT_DATABRICKS_UPLOAD_CHUNK_SIZE_BYTES,
                    json_columns=known_variant_columns,
                )

                # TODO - maybe move this into the consumer finalize method?
                # Copy all staged files to the table
                await databricks_client.acopy_into_table_from_volume(
                    table_name=stage_table_name if stage_table_name else inputs.table_name,
                    volume_name=volume_name,
                )

                if requires_merge and stage_table_name is not None:
                    await databricks_client.amerge_mutable_tables(
                        target_table=inputs.table_name,
                        source_table=stage_table_name,
                        fields=table_fields,
                        merge_key=merge_key,
                        update_key=update_key,
                        with_schema_evolution=inputs.use_automatic_schema_evolution,
                    )

                return result


@workflow.defn(name="databricks-export", failure_exception_types=[workflow.NondeterminismError])
class DatabricksBatchExportWorkflow(PostHogWorkflow):
    """A Temporal Workflow to export ClickHouse data into Databricks.

    This Workflow is intended to be executed both manually and by a Temporal
    Schedule. When ran by a schedule, `data_interval_end` should be set to
    `None` so that we will fetch the end of the interval from the Temporal
    search attribute `TemporalScheduledStartTime`.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> DatabricksBatchExportInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return DatabricksBatchExportInputs(**loaded)

    @workflow.run
    async def run(self, inputs: DatabricksBatchExportInputs):
        """Workflow implementation to export data to Databricks table."""
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

        insert_inputs = DatabricksInsertInputs(
            team_id=inputs.team_id,
            server_hostname=inputs.server_hostname,
            http_path=inputs.http_path,
            client_id=inputs.client_id,
            client_secret=inputs.client_secret,
            catalog=inputs.catalog,
            schema=inputs.schema,
            table_name=inputs.table_name,
            data_interval_start=data_interval_start.isoformat() if not should_backfill_from_beginning else None,
            data_interval_end=data_interval_end.isoformat(),
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            run_id=run_id,
            backfill_details=inputs.backfill_details,
            is_backfill=is_backfill,
            batch_export_model=inputs.batch_export_model,
            batch_export_schema=inputs.batch_export_schema,
            batch_export_id=inputs.batch_export_id,
            destination_default_fields=databricks_default_fields(),
        )

        await execute_batch_export_using_internal_stage(
            insert_into_databricks_activity_from_stage,
            insert_inputs,
            interval=inputs.interval,
        )
