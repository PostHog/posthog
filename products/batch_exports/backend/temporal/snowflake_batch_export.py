import asyncio
import collections.abc
import contextlib
import dataclasses
import datetime as dt
import functools
import io
import json
import logging
import typing

import pyarrow as pa
import snowflake.connector
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from django.conf import settings
from snowflake.connector.connection import SnowflakeConnection
from snowflake.connector.cursor import ResultMetadata
from snowflake.connector.errors import InterfaceError, OperationalError
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.models import BatchExportRun
from posthog.batch_exports.service import (
    BatchExportField,
    BatchExportInsertInputs,
    BatchExportModel,
    SnowflakeBatchExportInputs,
)
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import (
    bind_contextvars,
    get_external_logger,
    get_logger,
)
from products.batch_exports.backend.temporal.batch_exports import (
    FinishBatchExportRunInputs,
    RecordsCompleted,
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
from products.batch_exports.backend.temporal.spmc import (
    Consumer,
    Producer,
    RecordBatchQueue,
    resolve_batch_exports_model,
    run_consumer,
    wait_for_schema_or_producer,
)
from products.batch_exports.backend.temporal.temporary_file import (
    BatchExportTemporaryFile,
    WriterFormat,
)
from products.batch_exports.backend.temporal.utils import (
    JsonType,
    set_status_to_running_task,
)

LOGGER = get_logger(__name__)
EXTERNAL_LOGGER = get_external_logger()

# One batch export allowed to connect at a time (in theory) per worker.
CONNECTION_SEMAPHORE = asyncio.Semaphore(value=1)

NON_RETRYABLE_ERROR_TYPES = [
    # Raised when we cannot connect to Snowflake.
    "DatabaseError",
    # Raised by Snowflake when a query cannot be compiled.
    # Usually this means we don't have table permissions or something doesn't exist (db, schema).
    "ProgrammingError",
    # Raised by Snowflake with an incorrect account name.
    "ForbiddenError",
    # Our own exception when we can't connect to Snowflake, usually due to invalid parameters.
    "SnowflakeConnectionError",
    # Raised when a table is not found in Snowflake.
    "SnowflakeTableNotFoundError",
    # Raised when a using key-pair auth and the private key or passphrase is not valid.
    "InvalidPrivateKeyError",
    # Raised when a valid authentication method is not provided.
    "SnowflakeAuthenticationError",
]


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


class SnowflakeTableNotFoundError(Exception):
    """Raised when a table is not found in Snowflake."""

    def __init__(self, table_name: str):
        super().__init__(f"Table '{table_name}' not found in Snowflake")


class SnowflakeAuthenticationError(Exception):
    """Raised when a valid authentication method is not provided."""

    def __init__(self, message: str):
        super().__init__(message)


class InvalidPrivateKeyError(Exception):
    """Raised when a private key is not valid."""

    def __init__(self, message: str):
        super().__init__(message)


@dataclasses.dataclass
class SnowflakeHeartbeatDetails(BatchExportRangeHeartbeatDetails):
    """The Snowflake batch export details included in every heartbeat."""

    pass


@dataclasses.dataclass(kw_only=True)
class SnowflakeInsertInputs(BatchExportInsertInputs):
    """Inputs for Snowflake."""

    # TODO: do _not_ store credentials in temporal inputs. It makes it very hard
    # to keep track of where credentials are being stored and increases the
    # attach surface for credential leaks.

    user: str
    account: str
    database: str
    warehouse: str
    schema: str
    table_name: str
    authentication_type: str = "password"
    password: str | None = None
    private_key: str | None = None
    private_key_passphrase: str | None = None
    role: str | None = None


SnowflakeField = tuple[str, str]


def load_private_key(private_key: str, passphrase: str | None) -> bytes:
    try:
        p_key = serialization.load_pem_private_key(
            private_key.encode("utf-8"),
            password=passphrase.encode() if passphrase is not None else None,
            backend=default_backend(),
        )
    except (ValueError, TypeError) as e:
        msg = "Invalid private key"

        if passphrase is not None and "Incorrect password?" in str(e):
            msg = "Could not load private key: incorrect passphrase?"
        elif "Password was not given but private key is encrypted" in str(e):
            msg = "Could not load private key: passphrase was not given but private key is encrypted"
        elif "Password was given but private key is not encrypted" in str(e):
            if passphrase == "":
                try:
                    loaded = load_private_key(private_key, None)
                except (ValueError, TypeError):
                    # Proceed with top level handling
                    pass
                else:
                    return loaded
            msg = "Could not load private key: passphrase was given but private key is not encrypted"

        raise InvalidPrivateKeyError(msg)

    return p_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


class SnowflakeClient:
    """Snowflake connection client used in batch exports."""

    def __init__(
        self,
        user: str,
        account: str,
        warehouse: str,
        database: str,
        schema: str,
        role: str | None = None,
        password: str | None = None,
        private_key: bytes | None = None,
    ):
        if password is None and private_key is None:
            raise SnowflakeAuthenticationError("Either password or private key must be provided")

        self.role = role
        self.user = user
        self.password = password
        self.private_key = private_key
        self.account = account
        self.warehouse = warehouse
        self.database = database
        self.schema = schema
        self._connection: SnowflakeConnection | None = None

        self.logger = LOGGER.bind(user=user, account=account, warehouse=warehouse, database=database)

    @classmethod
    def from_inputs(cls, inputs: SnowflakeInsertInputs) -> typing.Self:
        """Initialize `SnowflakeClient` from `SnowflakeInsertInputs`."""

        # User could have specified both password and private key in their batch export config.
        # (for example, if they've already created a batch export with password auth and are now switching to keypair auth)
        # Therefore we decide which one to use based on the authentication_type.
        password = None
        private_key = None
        if inputs.authentication_type == "password":
            password = inputs.password
            if password is None:
                raise SnowflakeAuthenticationError("Password is required for password authentication")
        elif inputs.authentication_type == "keypair":
            if inputs.private_key is None:
                raise SnowflakeAuthenticationError("Private key is required for keypair authentication")

            private_key = load_private_key(inputs.private_key, inputs.private_key_passphrase)

        else:
            raise SnowflakeAuthenticationError(f"Invalid authentication type: {inputs.authentication_type}")

        return cls(
            user=inputs.user,
            account=inputs.account,
            warehouse=inputs.warehouse,
            database=inputs.database,
            schema=inputs.schema,
            role=inputs.role,
            password=password,
            private_key=private_key,
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
        self.logger.debug("Initializing Snowflake connection")
        self.ensure_snowflake_logger_level("INFO")

        try:
            async with CONNECTION_SEMAPHORE:
                connection = await asyncio.to_thread(
                    snowflake.connector.connect,
                    user=self.user,
                    password=self.password,
                    account=self.account,
                    warehouse=self.warehouse,
                    database=self.database,
                    schema=self.schema,
                    role=self.role,
                    private_key=self.private_key,
                    login_timeout=5,
                )
            connection.telemetry_enabled = False

        except OperationalError as err:
            if err.errno == 251012:
                # 251012: Generic retryable error code
                raise SnowflakeRetryableConnectionError(
                    "Could not connect to Snowflake but this error may be retried"
                ) from err
            else:
                raise SnowflakeConnectionError(f"Could not connect to Snowflake - {err.errno}: {err.msg}") from err

        except InterfaceError as err:
            raise SnowflakeConnectionError(f"Could not connect to Snowflake - {err.errno}: {err.msg}") from err

        self.logger.debug("Connected to Snowflake")

        self._connection = connection

        # Call this again in case level was reset.
        self.ensure_snowflake_logger_level("DEBUG")

        await self.use_namespace()
        await self.execute_async_query("SET ABORT_DETACHED_QUERY = FALSE", fetch_results=False)

        try:
            yield self

        finally:
            self._connection = None
            await asyncio.to_thread(connection.close)

    def ensure_snowflake_logger_level(self, level: str):
        """Ensure the log level for logger used by inner `SnowflakeConnection`."""
        logger = logging.getLogger("snowflake.connector")
        logger.setLevel(level)

    async def use_namespace(self) -> None:
        """Switch to a namespace given by database and schema.

        This allows all queries that follow to ignore database and schema.
        """
        await self.execute_async_query(f'USE DATABASE "{self.database}"', fetch_results=False)
        await self.execute_async_query(f'USE SCHEMA "{self.schema}"', fetch_results=False)

    async def execute_async_query(
        self,
        query: str,
        parameters: dict | None = None,
        file_stream=None,
        poll_interval: float = 1.0,
        fetch_results: bool = True,
    ) -> tuple[list[tuple] | list[dict], list[ResultMetadata]] | None:
        """Wrap Snowflake connector's polling API in a coroutine.

        This enables asynchronous execution of queries to release the event loop to execute other tasks
        while we poll for a query to be done. For example, the event loop may use this time for heartbeating.

        Args:
            connection: A SnowflakeConnection object as produced by snowflake.connector.connect.
            query: A query string to run asynchronously.
            parameters: An optional dictionary of parameters to bind to the query.
            poll_interval: Specify how long to wait in between polls.
            fetch_results: Whether any result should be fetched from the query.

        Returns:
            If `fetch_results` is `True`, a tuple containing:
            - The query results as a list of tuples or dicts
            - The cursor description (containing list of fields in result)
            Else when `fetch_results` is `False` we return `None`.
        """
        self.logger.debug("Executing async query: %s", query)

        with self.connection.cursor() as cursor:
            # Snowflake docs incorrectly state that the 'params' argument is named 'parameters'.
            result = await asyncio.to_thread(cursor.execute_async, query, params=parameters, file_stream=file_stream)
            query_id = cursor.sfqid or result["queryId"]

        self.logger.debug("Waiting for results of query with ID '%s'", query_id)

        # Snowflake does a blocking HTTP request, so we send it to a thread.
        query_status = await asyncio.to_thread(self.connection.get_query_status_throw_if_error, query_id)

        while self.connection.is_still_running(query_status):
            query_status = await asyncio.to_thread(self.connection.get_query_status_throw_if_error, query_id)
            await asyncio.sleep(poll_interval)

        self.logger.debug("Async query '%s' finished with status '%s'", query_id, query_status)

        if fetch_results is False:
            return None

        self.logger.debug("Fetching query results for query '%s'", query_id)

        with self.connection.cursor() as cursor:
            await asyncio.to_thread(cursor.get_results_from_sfqid, query_id)
            results = await asyncio.to_thread(cursor.fetchall)
            description = cursor.description

        self.logger.debug("Finished fetching query results for %s", query)

        return results, description

    async def aremove_internal_stage_files(self, table_name: str, table_stage_prefix: str) -> None:
        """Asynchronously remove files from internal table stage.

        Arguments:
            table_name: The name of the table whose internal stage to clear.
            table_stage_prefix: Prefix to path of internal stage files.
        """
        await self.execute_async_query(f"""REMOVE '@%"{table_name}"/{table_stage_prefix}'""", fetch_results=False)

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
            COMMENT = 'PostHog generated table'
            """,
            fetch_results=False,
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

        await self.execute_async_query(query, fetch_results=False)

    async def aget_table_columns(self, table_name: str) -> list[str]:
        """Get the column names for a given table.

        Arguments:
            table_name: The name of the table to get columns for.

        Returns:
            A list of column names.
        """
        try:
            result = await self.execute_async_query(f"""
                SELECT * FROM "{table_name}" LIMIT 0
            """)
            assert result is not None
            _, metadata = result
        except snowflake.connector.errors.ProgrammingError as e:
            if "does not exist" in str(e):
                raise SnowflakeTableNotFoundError(table_name)
            else:
                raise

        return [row.name for row in metadata]

    @contextlib.asynccontextmanager
    async def managed_table(
        self,
        table_name: str,
        table_stage_prefix: str,
        fields: list[SnowflakeField],
        not_found_ok: bool = True,
        delete: bool = True,
        create: bool = True,
    ) -> collections.abc.AsyncGenerator[str, None]:
        """Manage a table in Snowflake by ensure it exists while in context."""
        if create is True:
            await self.acreate_table(table_name, fields)
        else:
            await self.aremove_internal_stage_files(table_name, table_stage_prefix)

        try:
            yield table_name
        finally:
            if delete is True:
                await self.adelete_table(table_name, not_found_ok)
            else:
                await self.aremove_internal_stage_files(table_name, table_stage_prefix)

    async def put_file_to_snowflake_table(
        self,
        file: BatchExportTemporaryFile,
        table_stage_prefix: str,
        table_name: str,
    ):
        """Executes a PUT query using the provided cursor to the provided table_name.

        Sadly, Snowflake's execute_async does not work with PUT statements. So, we pass the execute
        call to run_in_executor: Since execute ends up boiling down to blocking IO (HTTP request),
        the event loop should not be locked up.

        Args:
            file: The name of the local file to PUT.
            table_name: The name of the Snowflake table where to PUT the file.

        Raises:
            TypeError: If we don't get a tuple back from Snowflake (should never happen).
            SnowflakeFileNotUploadedError: If the upload status is not 'UPLOADED'.
        """
        file.rewind()

        # We comply with the file-like interface of io.IOBase.
        # So we ask mypy to be nice with us.
        reader = io.BufferedReader(file)  # type: ignore
        query = f"""
        PUT file://{file.name} '@%"{table_name}"/{table_stage_prefix}'
        """

        with self.connection.cursor() as cursor:
            cursor = self.connection.cursor()

            execute_put = functools.partial(cursor.execute, query, file_stream=reader)

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, func=execute_put)
            reader.detach()  # BufferedReader closes the file otherwise.

            result = await asyncio.to_thread(cursor.fetchone)

            if not isinstance(result, tuple):
                # Mostly to appease mypy, as this query should always return a tuple.
                raise TypeError(f"Expected tuple from Snowflake PUT query but got: '{result.__class__.__name__}'")

        status, message = result[6:8]
        if status != "UPLOADED":
            raise SnowflakeFileNotUploadedError(table_name, status, message)

    async def copy_loaded_files_to_snowflake_table(
        self,
        table_name: str,
        table_stage_prefix: str,
    ) -> None:
        """Execute a COPY query in Snowflake to load any files PUT into the table.

        The query is executed asynchronously using Snowflake's polling API.

        Args:
            connection: A SnowflakeConnection as returned by snowflake.connector.connect.
            table_name: The table we are COPY-ing files into.
        """
        query = f"""
        COPY INTO "{table_name}"
        FROM '@%"{table_name}"/{table_stage_prefix}'
        FILE_FORMAT = (TYPE = 'JSON')
        MATCH_BY_COLUMN_NAME = CASE_SENSITIVE
        PURGE = TRUE
        """
        result = await self.execute_async_query(query)
        assert result is not None
        results, _ = result

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

    async def amerge_mutable_tables(
        self,
        final_table: str,
        stage_table: str,
        merge_key: collections.abc.Iterable[SnowflakeField],
        update_key: collections.abc.Iterable[str],
        update_when_matched: collections.abc.Iterable[SnowflakeField],
    ):
        """Merge two identical person model tables in Snowflake."""

        # handle the case where the final table doesn't contain all the fields present in the stage table
        # (for example, if we've added new fields to the person model)
        final_table_column_names = await self.aget_table_columns(final_table)
        update_when_matched = [field for field in update_when_matched if field[0] in final_table_column_names]

        merge_condition = "ON "

        for n, field in enumerate(merge_key):
            if n > 0:
                merge_condition += " AND "
            merge_condition += f'final."{field[0]}" = stage."{field[0]}"'

        update_condition = "AND ("

        for index, field_name in enumerate(update_key):
            if index > 0:
                update_condition += " OR "
            update_condition += f'final."{field_name}" < stage."{field_name}"'
        update_condition += ")"

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

        WHEN MATCHED {update_condition} THEN
            UPDATE SET
                {update_clause}
        WHEN NOT MATCHED THEN
            INSERT ({field_names})
            VALUES ({values});
        """

        await self.execute_async_query(merge_query, fetch_results=False)


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


class SnowflakeConsumer(Consumer):
    def __init__(
        self,
        heartbeater: Heartbeater,
        heartbeat_details: SnowflakeHeartbeatDetails,
        data_interval_start: dt.datetime | str | None,
        data_interval_end: dt.datetime | str,
        writer_format: WriterFormat,
        snowflake_client: SnowflakeClient,
        snowflake_table: str,
        snowflake_table_stage_prefix: str,
    ):
        super().__init__(
            heartbeater=heartbeater,
            heartbeat_details=heartbeat_details,
            data_interval_start=data_interval_start,
            data_interval_end=data_interval_end,
            writer_format=writer_format,
        )
        self.heartbeat_details: SnowflakeHeartbeatDetails = heartbeat_details
        self.snowflake_table = snowflake_table
        self.snowflake_client = snowflake_client
        self.snowflake_table_stage_prefix = snowflake_table_stage_prefix

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
        self.external_logger.info(
            "Putting file %d containing %d records with size %d bytes to Snowflake table '%s' stage",
            flush_counter,
            records_since_last_flush,
            bytes_since_last_flush,
            self.snowflake_table,
        )

        await self.snowflake_client.put_file_to_snowflake_table(
            batch_export_file,
            self.snowflake_table_stage_prefix,
            self.snowflake_table,
        )

        self.external_logger.info(
            "File with %d records loaded to Snowflake table '%s' stage", records_since_last_flush, self.snowflake_table
        )
        self.rows_exported_counter.add(records_since_last_flush)
        self.bytes_exported_counter.add(bytes_since_last_flush)

        self.heartbeat_details.records_completed += records_since_last_flush
        self.heartbeat_details.track_done_range(last_date_range, self.data_interval_start)


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
            snowflake_type = "BOOLEAN"

        elif pa.types.is_timestamp(pa_field.type):
            snowflake_type = "TIMESTAMP"

        elif pa.types.is_list(pa_field.type):
            snowflake_type = "ARRAY"

        else:
            raise TypeError(f"Unsupported type in field '{name}': '{pa_field.type}'")

        snowflake_schema.append((name, snowflake_type))

    return snowflake_schema


@activity.defn
async def insert_into_snowflake_activity(inputs: SnowflakeInsertInputs) -> RecordsCompleted:
    """Activity streams data from ClickHouse to Snowflake.

    TODO: We're using JSON here, it's not the most efficient way to do this.
    """
    bind_contextvars(
        team_id=inputs.team_id,
        destination="Snowflake",
        data_interval_start=inputs.data_interval_start,
        data_interval_end=inputs.data_interval_end,
    )
    external_logger = EXTERNAL_LOGGER.bind()

    external_logger.info(
        "Batch exporting range %s - %s to Snowflake: %s.%s.%s",
        inputs.data_interval_start or "START",
        inputs.data_interval_end or "END",
        inputs.database,
        inputs.schema,
        inputs.table_name,
    )

    async with (
        Heartbeater() as heartbeater,
        set_status_to_running_task(run_id=inputs.run_id),
    ):
        _, details = await should_resume_from_activity_heartbeat(activity, SnowflakeHeartbeatDetails)
        if details is None or str(inputs.team_id) in settings.BATCH_EXPORT_ORDERLESS_TEAM_IDS:
            details = SnowflakeHeartbeatDetails()

        done_ranges: list[DateRange] = details.done_ranges

        model, record_batch_model, model_name, fields, filters, extra_query_parameters = resolve_batch_exports_model(
            inputs.team_id, inputs.batch_export_model, inputs.batch_export_schema
        )

        data_interval_start = (
            dt.datetime.fromisoformat(inputs.data_interval_start) if inputs.data_interval_start else None
        )
        data_interval_end = dt.datetime.fromisoformat(inputs.data_interval_end)
        full_range = (data_interval_start, data_interval_end)

        queue = RecordBatchQueue(max_size_bytes=settings.BATCH_EXPORT_SNOWFLAKE_RECORD_BATCH_QUEUE_MAX_SIZE_BYTES)
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
            destination_default_fields=snowflake_default_fields(),
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            extra_query_parameters=extra_query_parameters,
        )

        record_batch_schema = await wait_for_schema_or_producer(queue, producer_task)
        if record_batch_schema is None:
            external_logger.info(
                "Batch export finished as there is no data in range %s - %s matching specified filters",
                inputs.data_interval_start or "START",
                inputs.data_interval_end or "END",
            )

            return details.records_completed

        record_batch_schema = pa.schema(
            # NOTE: For some reason, some batches set non-nullable fields as non-nullable, whereas other
            # record batches have them as nullable.
            # Until we figure it out, we set all fields to nullable. There are some fields we know
            # are not nullable, but I'm opting for the more flexible option until we out why schemas differ
            # between batches.
            [field.with_nullable(True) for field in record_batch_schema if field.name != "_inserted_at"]
        )

        known_variant_columns = ["properties", "people_set", "people_set_once", "person_properties"]

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
            table_fields = get_snowflake_fields_from_record_schema(
                record_batch_schema,
                known_variant_columns=known_variant_columns,
            )

        requires_merge = False
        merge_key = []
        update_key = []
        if isinstance(inputs.batch_export_model, BatchExportModel):
            if inputs.batch_export_model.name == "persons":
                requires_merge = True
                merge_key = [
                    ("team_id", "INT64"),
                    ("distinct_id", "STRING"),
                ]
                update_key = ["person_version", "person_distinct_id_version"]

            elif inputs.batch_export_model.name == "sessions":
                requires_merge = True
                merge_key = [("team_id", "INT64"), ("session_id", "STRING")]
                update_key = [
                    "end_timestamp",
                ]

        data_interval_end_str = dt.datetime.fromisoformat(inputs.data_interval_end).strftime("%Y-%m-%d_%H-%M-%S")
        stagle_table_name = (
            f"stage_{inputs.table_name}_{data_interval_end_str}_{inputs.team_id}"
            if requires_merge
            else inputs.table_name
        )

        async with SnowflakeClient.from_inputs(inputs).connect() as snow_client:
            async with (
                snow_client.managed_table(
                    inputs.table_name, data_interval_end_str, table_fields, delete=False
                ) as snow_table,
                snow_client.managed_table(
                    stagle_table_name, data_interval_end_str, table_fields, create=requires_merge, delete=requires_merge
                ) as snow_stage_table,
            ):
                consumer = SnowflakeConsumer(
                    heartbeater=heartbeater,
                    heartbeat_details=details,
                    data_interval_end=data_interval_end,
                    data_interval_start=data_interval_start,
                    writer_format=WriterFormat.JSONL,
                    snowflake_client=snow_client,
                    snowflake_table=snow_stage_table if requires_merge else snow_table,
                    snowflake_table_stage_prefix=data_interval_end_str,
                )
                try:
                    await run_consumer(
                        consumer=consumer,
                        queue=queue,
                        producer_task=producer_task,
                        schema=record_batch_schema,
                        max_bytes=settings.BATCH_EXPORT_SNOWFLAKE_UPLOAD_CHUNK_SIZE_BYTES,
                        json_columns=known_variant_columns,
                        multiple_files=True,
                    )

                # ensure we always write data to final table, even if we fail halfway through, as if we resume from
                # a heartbeat, we can continue without losing data
                finally:
                    await snow_client.copy_loaded_files_to_snowflake_table(
                        snow_stage_table if requires_merge else snow_table, data_interval_end_str
                    )

                    if requires_merge:
                        await snow_client.amerge_mutable_tables(
                            final_table=snow_table,
                            stage_table=snow_stage_table,
                            update_when_matched=table_fields,
                            merge_key=merge_key,
                            update_key=update_key,
                        )

        external_logger.info(
            "Batch export for range %s - %s finished with %d records exported",
            inputs.data_interval_start or "START",
            inputs.data_interval_end or "END",
            details.records_completed,
        )

        return details.records_completed


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

        finish_inputs = FinishBatchExportRunInputs(
            id=run_id,
            batch_export_id=inputs.batch_export_id,
            status=BatchExportRun.Status.COMPLETED,
            team_id=inputs.team_id,
        )

        insert_inputs = SnowflakeInsertInputs(
            team_id=inputs.team_id,
            user=inputs.user,
            account=inputs.account,
            authentication_type=inputs.authentication_type,
            password=inputs.password,
            private_key=inputs.private_key,
            private_key_passphrase=inputs.private_key_passphrase,
            warehouse=inputs.warehouse,
            database=inputs.database,
            schema=inputs.schema,
            table_name=inputs.table_name,
            data_interval_start=data_interval_start.isoformat() if not should_backfill_from_beginning else None,
            data_interval_end=data_interval_end.isoformat(),
            role=inputs.role,
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            run_id=run_id,
            backfill_details=inputs.backfill_details,
            is_backfill=is_backfill,
            batch_export_model=inputs.batch_export_model,
            batch_export_schema=inputs.batch_export_schema,
        )

        await execute_batch_export_insert_activity(
            insert_into_snowflake_activity,
            insert_inputs,
            interval=inputs.interval,
            non_retryable_error_types=NON_RETRYABLE_ERROR_TYPES,
            finish_inputs=finish_inputs,
        )
