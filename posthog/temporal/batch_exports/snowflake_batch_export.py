import asyncio
import collections.abc
import contextlib
import dataclasses
import datetime as dt
import functools
import io
import json
import typing

import pyarrow as pa
import snowflake.connector
from django.conf import settings
from snowflake.connector.connection import SnowflakeConnection
from snowflake.connector.errors import OperationalError
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.models import BatchExportRun
from posthog.batch_exports.service import (
    BatchExportField,
    BatchExportModel,
    BatchExportSchema,
    SnowflakeBatchExportInputs,
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
    BatchExportTemporaryFile,
    JSONLBatchExportWriter,
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
    HeartbeatParseError,
    NotEnoughHeartbeatValuesError,
    should_resume_from_activity_heartbeat,
)


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


class SnowflakeConnectionError(Exception):
    """Raised when a connection to Snowflake is not established."""

    pass


class SnowflakeRetryableConnectionError(Exception):
    """Raised when a connection to Snowflake is not established."""

    pass


@dataclasses.dataclass
class SnowflakeHeartbeatDetails(BatchExportHeartbeatDetails):
    """The Snowflake batch export details included in every heartbeat.

    Attributes:
        file_no: The file number of the last file we managed to upload.
    """

    file_no: int

    @classmethod
    def from_activity(cls, activity):
        details = BatchExportHeartbeatDetails.from_activity(activity)

        if details.total_details < 2:
            raise NotEnoughHeartbeatValuesError(details.total_details, 2)

        try:
            file_no = int(details._remaining[0])
        except (TypeError, ValueError) as e:
            raise HeartbeatParseError("file_no") from e

        return cls(last_inserted_at=details.last_inserted_at, file_no=file_no, _remaining=details._remaining[2:])


@dataclasses.dataclass
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
    exclude_events: list[str] | None = None
    include_events: list[str] | None = None
    run_id: str | None = None
    is_backfill: bool = False
    batch_export_model: BatchExportModel | None = None
    batch_export_schema: BatchExportSchema | None = None


SnowflakeField = tuple[str, str]


class SnowflakeClient:
    """Snowflake connection client used in batch exports."""

    def __init__(
        self, user: str, password: str, account: str, warehouse: str, database: str, schema: str, role: str | None
    ):
        self.user = user
        self.password = password
        self.account = account
        self.warehouse = warehouse
        self.database = database
        self.schema = schema
        self.role = role
        self._connection: SnowflakeConnection | None = None

    @classmethod
    def from_inputs(cls, inputs: SnowflakeInsertInputs) -> typing.Self:
        """Initialize `SnowflakeClient` from `SnowflakeInsertInputs`."""
        return cls(
            user=inputs.user,
            password=inputs.password,
            account=inputs.account,
            warehouse=inputs.warehouse,
            database=inputs.database,
            schema=inputs.schema,
            role=inputs.role,
        )

    @property
    def connection(self) -> SnowflakeConnection:
        """Raise if a `SnowflakeConnection` hasn't been established, else return it."""
        if self._connection is None:
            raise SnowflakeConnectionError("Not connected, open a connection by calling connect")
        return self._connection

    @contextlib.asynccontextmanager
    async def connect(self):
        """Manage a `SnowflakeConnection`.

        Methods that require a connection should be ran within this block.
        """
        try:
            connection = await asyncio.to_thread(
                snowflake.connector.connect,
                user=self.user,
                password=self.password,
                account=self.account,
                warehouse=self.warehouse,
                database=self.database,
                schema=self.schema,
                role=self.role,
            )

        except OperationalError as err:
            if err.errno == 251012:
                # 251012: Generic retryable error code
                raise SnowflakeRetryableConnectionError(
                    "Could not connect to Snowflake but this error may be retried"
                ) from err
            else:
                raise SnowflakeConnectionError(f"Could not connect to Snowflake - {err.errno}: {err.msg}") from err

        self._connection = connection

        await self.use_namespace()
        await self.execute_async_query("SET ABORT_DETACHED_QUERY = FALSE")

        try:
            yield self

        finally:
            self._connection = None
            await asyncio.to_thread(connection.close)

    async def use_namespace(self) -> None:
        """Switch to a namespace given by database and schema.

        This allows all queries that follow to ignore database and schema.
        """
        await self.execute_async_query(f'USE DATABASE "{self.database}"')
        await self.execute_async_query(f'USE SCHEMA "{self.schema}"')

    async def execute_async_query(
        self,
        query: str,
        parameters: dict | None = None,
        file_stream=None,
        poll_interval: float = 1.0,
    ) -> list[tuple] | list[dict]:
        """Wrap Snowflake connector's polling API in a coroutine.

        This enables asynchronous execution of queries to release the event loop to execute other tasks
        while we poll for a query to be done. For example, the event loop may use this time for heartbeating.

        Args:
            connection: A SnowflakeConnection object as produced by snowflake.connector.connect.
            query: A query string to run asynchronously.
            parameters: An optional dictionary of parameters to bind to the query.
            poll_interval: Specify how long to wait in between polls.
        """
        with self.connection.cursor() as cursor:
            # Snowflake docs incorrectly state that the 'params' argument is named 'parameters'.
            result = cursor.execute_async(query, params=parameters, file_stream=file_stream)
            query_id = cursor.sfqid or result["queryId"]

            # Snowflake does a blocking HTTP request, so we send it to a thread.
            query_status = await asyncio.to_thread(self.connection.get_query_status_throw_if_error, query_id)

        while self.connection.is_still_running(query_status):
            query_status = await asyncio.to_thread(self.connection.get_query_status_throw_if_error, query_id)
            await asyncio.sleep(poll_interval)

        with self.connection.cursor() as cursor:
            cursor.get_results_from_sfqid(query_id)
            results = cursor.fetchall()
        return results

    async def acreate_table(self, table_name: str, fields: list[SnowflakeField]) -> None:
        """Asynchronously create the table if it doesn't exist.

        Arguments:
            table_name: The name of the table to create.
            fields: An iterable of (name, type) tuples representing the fields of the table.
        """
        field_ddl = ", ".join(f'"{field[0]}" {field[1]}' for field in fields)

        await self.execute_async_query(
            f"""
            CREATE TABLE IF NOT EXISTS "{table_name}" (
                {field_ddl}
            )
            COMMENT = 'PostHog generated events table'
            """,
        )

    async def adelete_table(
        self,
        table_name: str,
        not_found_ok: bool = False,
    ) -> None:
        """Delete a table in BigQuery."""
        if not_found_ok is True:
            query = f'DROP TABLE IF EXISTS "{table_name}"'
        else:
            query = f'DROP TABLE "{table_name}"'

        await self.execute_async_query(query)
        return None

    @contextlib.asynccontextmanager
    async def managed_table(
        self,
        table_name: str,
        fields: list[SnowflakeField],
        not_found_ok: bool = True,
        delete: bool = True,
        create: bool = True,
    ) -> collections.abc.AsyncGenerator[str, None]:
        """Manage a table in Snowflake by ensure it exists while in context."""
        if create:
            await self.acreate_table(table_name, fields)

        try:
            yield table_name
        finally:
            if delete is True:
                await self.adelete_table(table_name, not_found_ok)

    async def put_file_to_snowflake_table(
        self,
        file: BatchExportTemporaryFile,
        table_name: str,
        file_no: int,
    ):
        """Executes a PUT query using the provided cursor to the provided table_name.

        Sadly, Snowflake's execute_async does not work with PUT statements. So, we pass the execute
        call to run_in_executor: Since execute ends up boiling down to blocking IO (HTTP request),
        the event loop should not be locked up.

        We add a file_no to the file_name when executing PUT as Snowflake will reject any files with the same
        name. Since batch exports re-use the same file, our name does not change, but we don't want Snowflake
        to reject or overwrite our new data.

        Args:
            file: The name of the local file to PUT.
            table_name: The name of the Snowflake table where to PUT the file.
            file_no: An int to identify which file number this is.

        Raises:
            TypeError: If we don't get a tuple back from Snowflake (should never happen).
            SnowflakeFileNotUploadedError: If the upload status is not 'UPLOADED'.
        """
        file.rewind()

        # We comply with the file-like interface of io.IOBase.
        # So we ask mypy to be nice with us.
        reader = io.BufferedReader(file)  # type: ignore
        query = f'PUT file://{file.name}_{file_no}.jsonl @%"{table_name}"'

        with self.connection.cursor() as cursor:
            cursor = self.connection.cursor()

            execute_put = functools.partial(cursor.execute, query, file_stream=reader)

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, func=execute_put)
            reader.detach()  # BufferedReader closes the file otherwise.

            result = cursor.fetchone()

            if not isinstance(result, tuple):
                # Mostly to appease mypy, as this query should always return a tuple.
                raise TypeError(f"Expected tuple from Snowflake PUT query but got: '{result.__class__.__name__}'")

        status, message = result[6:8]
        if status != "UPLOADED":
            raise SnowflakeFileNotUploadedError(table_name, status, message)

    async def copy_loaded_files_to_snowflake_table(
        self,
        table_name: str,
    ) -> None:
        """Execute a COPY query in Snowflake to load any files PUT into the table.

        The query is executed asynchronously using Snowflake's polling API.

        Args:
            connection: A SnowflakeConnection as returned by snowflake.connector.connect.
            table_name: The table we are COPY-ing files into.
        """
        query = f"""
        COPY INTO "{table_name}"
        FILE_FORMAT = (TYPE = 'JSON')
        MATCH_BY_COLUMN_NAME = CASE_SENSITIVE
        PURGE = TRUE
        """
        results = await self.execute_async_query(query)

        for query_result in results:
            if not isinstance(query_result, tuple):
                # Mostly to appease mypy, as this query should always return a tuple.
                raise TypeError(f"Expected tuple from Snowflake COPY INTO query but got: '{type(query_result)}'")

            if len(query_result) < 2:
                raise SnowflakeFileNotLoadedError(
                    table_name,
                    "NO STATUS",
                    0,
                    query_result[0] if len(query_result) == 1 else "NO ERROR MESSAGE",
                )

            _, status = query_result[0:2]

            if status != "LOADED":
                errors_seen, first_error = query_result[5:7]
                raise SnowflakeFileNotLoadedError(
                    table_name,
                    status or "NO STATUS",
                    errors_seen or 0,
                    first_error or "NO ERROR MESSAGE",
                )

    async def amerge_person_tables(
        self,
        final_table: str,
        stage_table: str,
        merge_key: collections.abc.Iterable[SnowflakeField],
        update_when_matched: collections.abc.Iterable[SnowflakeField],
        person_version_key: str = "person_version",
        person_distinct_id_version_key: str = "person_distinct_id_version",
    ):
        """Merge two identical person model tables in Snowflake."""
        merge_condition = "ON "

        for n, field in enumerate(merge_key):
            if n > 0:
                merge_condition += " AND "
            merge_condition += f'final."{field[0]}" = stage."{field[0]}"'

        update_clause = ""
        values = ""
        field_names = ""
        for n, field in enumerate(update_when_matched):
            if n > 0:
                update_clause += ", "
                values += ", "
                field_names += ", "

            update_clause += f'final."{field[0]}" = stage."{field[0]}"'
            field_names += f'"{field[0]}"'
            values += f'stage."{field[0]}"'

        merge_query = f"""
        MERGE INTO "{final_table}" AS final
        USING "{stage_table}" AS stage
        {merge_condition}

        WHEN MATCHED AND (stage."{person_version_key}" > final."{person_version_key}" OR stage."{person_distinct_id_version_key}" > final."{person_distinct_id_version_key}") THEN
            UPDATE SET
                {update_clause}
        WHEN NOT MATCHED THEN
            INSERT ({field_names})
            VALUES ({values});
        """

        await self.execute_async_query(merge_query)


def snowflake_default_fields() -> list[BatchExportField]:
    """Default fields for a Snowflake batch export.

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
    # Fields kept for backwards compatibility with legacy apps schema.
    batch_export_fields.append({"expression": "elements_chain", "alias": "elements"})
    batch_export_fields.append({"expression": "''", "alias": "site_url"})
    batch_export_fields.pop(batch_export_fields.index({"expression": "created_at", "alias": "created_at"}))

    # For historical reasons, 'set' and 'set_once' are prefixed with 'people_'.
    set_field = batch_export_fields.pop(batch_export_fields.index(BatchExportField(expression="set", alias="set")))
    set_field["alias"] = "people_set"

    set_once_field = batch_export_fields.pop(
        batch_export_fields.index(BatchExportField(expression="set_once", alias="set_once"))
    )
    set_once_field["alias"] = "people_set_once"

    batch_export_fields.append(set_field)
    batch_export_fields.append(set_once_field)

    return batch_export_fields


def get_snowflake_fields_from_record_schema(
    record_schema: pa.Schema, known_variant_columns: list[str]
) -> list[SnowflakeField]:
    """Generate a list of supported Snowflake fields from PyArrow schema.
    This function is used to map custom schemas to Snowflake-supported types. Some loss
    of precision is expected.

    Arguments:
        record_schema: The schema of a PyArrow RecordBatch from which we'll attempt to
            derive Snowflake-supported types.
        known_variant_columns: If a string type field is a known VARIANT column then use VARIANT
            as its Snowflake type.
    """
    snowflake_schema: list[SnowflakeField] = []

    for name in record_schema.names:
        pa_field = record_schema.field(name)

        if pa.types.is_string(pa_field.type) or isinstance(pa_field.type, JsonType):
            if pa_field.name in known_variant_columns:
                snowflake_type = "VARIANT"
            else:
                snowflake_type = "STRING"

        elif pa.types.is_binary(pa_field.type):
            snowflake_type = "BYNARY"

        elif pa.types.is_signed_integer(pa_field.type) or pa.types.is_unsigned_integer(pa_field.type):
            snowflake_type = "INTEGER"

        elif pa.types.is_floating(pa_field.type):
            snowflake_type = "FLOAT"

        elif pa.types.is_boolean(pa_field.type):
            snowflake_type = "BOOL"

        elif pa.types.is_timestamp(pa_field.type):
            snowflake_type = "TIMESTAMP"

        else:
            raise TypeError(f"Unsupported type: {pa_field.type}")

        snowflake_schema.append((name, snowflake_type))

    return snowflake_schema


@activity.defn
async def insert_into_snowflake_activity(inputs: SnowflakeInsertInputs) -> RecordsCompleted:
    """Activity streams data from ClickHouse to Snowflake.

    TODO: We're using JSON here, it's not the most efficient way to do this.
    """
    logger = await bind_temporal_worker_logger(team_id=inputs.team_id, destination="Snowflake")
    logger.info(
        "Batch exporting range %s - %s to Snowflake: %s.%s.%s",
        inputs.data_interval_start,
        inputs.data_interval_end,
        inputs.database,
        inputs.schema,
        inputs.table_name,
    )

    async with (
        Heartbeater() as heartbeater,
        set_status_to_running_task(run_id=inputs.run_id, logger=logger),
        get_client(team_id=inputs.team_id) as client,
    ):
        if not await client.is_alive():
            raise ConnectionError("Cannot establish connection to ClickHouse")

        should_resume, details = await should_resume_from_activity_heartbeat(
            activity, SnowflakeHeartbeatDetails, logger
        )

        if should_resume is True and details is not None:
            data_interval_start = details.last_inserted_at.isoformat()
            current_flush_counter = details.file_no
        else:
            data_interval_start = inputs.data_interval_start
            current_flush_counter = 0

        rows_exported = get_rows_exported_metric()
        bytes_exported = get_bytes_exported_metric()

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
            destination_default_fields=snowflake_default_fields(),
            is_backfill=inputs.is_backfill,
        )
        first_record_batch, records_iterator = await apeek_first_and_rewind(records_iterator)

        if first_record_batch is None:
            return 0

        known_variant_columns = ["properties", "people_set", "people_set_once", "person_properties"]
        first_record_batch = cast_record_batch_json_columns(first_record_batch, json_columns=known_variant_columns)

        if model is None or (isinstance(model, BatchExportModel) and model.name == "events"):
            table_fields = [
                ("uuid", "STRING"),
                ("event", "STRING"),
                ("properties", "VARIANT"),
                ("elements", "VARIANT"),
                ("people_set", "VARIANT"),
                ("people_set_once", "VARIANT"),
                ("distinct_id", "STRING"),
                ("team_id", "INTEGER"),
                ("ip", "STRING"),
                ("site_url", "STRING"),
                ("timestamp", "TIMESTAMP"),
            ]

        else:
            column_names = [column for column in first_record_batch.schema.names if column != "_inserted_at"]
            record_schema = first_record_batch.select(column_names).schema
            table_fields = get_snowflake_fields_from_record_schema(
                record_schema,
                known_variant_columns=known_variant_columns,
            )

        requires_merge = (
            isinstance(inputs.batch_export_model, BatchExportModel) and inputs.batch_export_model.name == "persons"
        )
        data_interval_end_str = dt.datetime.fromisoformat(inputs.data_interval_end).strftime("%Y-%m-%d_%H-%M-%S")
        stagle_table_name = (
            f"stage_{inputs.table_name}_{data_interval_end_str}" if requires_merge else inputs.table_name
        )

        async with SnowflakeClient.from_inputs(inputs).connect() as snow_client:
            async with (
                snow_client.managed_table(inputs.table_name, table_fields, delete=False) as snow_table,
                snow_client.managed_table(
                    stagle_table_name, table_fields, create=requires_merge, delete=requires_merge
                ) as snow_stage_table,
            ):
                record_columns = [field[0] for field in table_fields]
                record_schema = pa.schema(
                    [field.with_nullable(True) for field in first_record_batch.select(record_columns).schema]
                )

                async def flush_to_snowflake(
                    local_results_file,
                    records_since_last_flush,
                    bytes_since_last_flush,
                    flush_counter: int,
                    last_inserted_at,
                    last: bool,
                    error: Exception | None,
                ):
                    logger.info(
                        "Putting %sfile %s containing %s records with size %s bytes",
                        "last " if last else "",
                        flush_counter,
                        records_since_last_flush,
                        bytes_since_last_flush,
                    )

                    table = snow_stage_table if requires_merge else snow_table

                    await snow_client.put_file_to_snowflake_table(local_results_file, table, flush_counter)
                    rows_exported.add(records_since_last_flush)
                    bytes_exported.add(bytes_since_last_flush)

                    heartbeater.details = (str(last_inserted_at), flush_counter)

                writer = JSONLBatchExportWriter(
                    max_bytes=settings.BATCH_EXPORT_SNOWFLAKE_UPLOAD_CHUNK_SIZE_BYTES,
                    flush_callable=flush_to_snowflake,
                )

                async with writer.open_temporary_file(current_flush_counter):
                    async for record_batch in records_iterator:
                        record_batch = cast_record_batch_json_columns(record_batch, json_columns=known_variant_columns)

                        await writer.write_record_batch(record_batch)

                await snow_client.copy_loaded_files_to_snowflake_table(
                    snow_stage_table if requires_merge else snow_table
                )
                if requires_merge:
                    merge_key = (
                        ("team_id", "INT64"),
                        ("distinct_id", "STRING"),
                    )
                    await snow_client.amerge_person_tables(
                        final_table=snow_table,
                        stage_table=snow_stage_table,
                        update_when_matched=table_fields,
                        merge_key=merge_key,
                    )

                return writer.records_total


@workflow.defn(name="snowflake-export", failure_exception_types=[workflow.NondeterminismError])
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
        """Workflow implementation to export data to Snowflake table."""
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
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            run_id=run_id,
            is_backfill=inputs.is_backfill,
            batch_export_model=inputs.batch_export_model,
            batch_export_schema=inputs.batch_export_schema,
        )

        await execute_batch_export_insert_activity(
            insert_into_snowflake_activity,
            insert_inputs,
            interval=inputs.interval,
            non_retryable_error_types=[
                # Raised when we cannot connect to Snowflake.
                "DatabaseError",
                # Raised by Snowflake when a query cannot be compiled.
                # Usually this means we don't have table permissions or something doesn't exist (db, schema).
                "ProgrammingError",
                # Raised by Snowflake with an incorrect account name.
                "ForbiddenError",
                # Our own exception when we can't connect to Snowflake, usually due to invalid parameters.
                "SnowflakeConnectionError",
            ],
            finish_inputs=finish_inputs,
        )
