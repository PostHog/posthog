import io
import json
import time
import typing
import asyncio
import logging
import datetime as dt
import functools
import contextlib
import dataclasses
import collections.abc

from django.conf import settings

import pyarrow as pa
import snowflake.connector
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from snowflake.connector.connection import SnowflakeConnection
from snowflake.connector.constants import FIELD_ID_TO_NAME, QueryStatus
from snowflake.connector.cursor import ResultMetadata
from snowflake.connector.errors import InterfaceError, OperationalError
from structlog.contextvars import bind_contextvars
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.service import (
    BatchExportField,
    BatchExportInsertInputs,
    BatchExportModel,
    BatchExportSchema,
    SnowflakeBatchExportInputs,
)
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger, get_write_only_logger

from products.batch_exports.backend.temporal.batch_exports import (
    OverBillingLimitError,
    StartBatchExportRunInputs,
    default_fields,
    get_data_interval,
    start_batch_export_run,
)
from products.batch_exports.backend.temporal.destinations.utils import get_query_timeout
from products.batch_exports.backend.temporal.pipeline.consumer import Consumer, run_consumer_from_stage
from products.batch_exports.backend.temporal.pipeline.entrypoint import execute_batch_export_using_internal_stage
from products.batch_exports.backend.temporal.pipeline.producer import Producer
from products.batch_exports.backend.temporal.pipeline.table import Field, Table
from products.batch_exports.backend.temporal.pipeline.transformer import (
    ParquetStreamTransformer,
    PipelineTransformer,
    SchemaTransformer,
)
from products.batch_exports.backend.temporal.pipeline.types import BatchExportResult
from products.batch_exports.backend.temporal.spmc import RecordBatchQueue, wait_for_schema_or_producer
from products.batch_exports.backend.temporal.temporary_file import BatchExportTemporaryFile
from products.batch_exports.backend.temporal.utils import (
    JsonType,
    handle_non_retryable_errors,
    make_retryable_with_exponential_backoff,
)

LOGGER = get_write_only_logger(__name__)
EXTERNAL_LOGGER = get_logger("EXTERNAL")


class NamedBytesIO(io.BytesIO):
    """BytesIO with a name attribute for Snowflake compatibility."""

    def __init__(self, data: bytes, name: str):
        super().__init__(data)
        self.name = name


# One batch export allowed to connect at a time (in theory) per worker.
CONNECTION_SEMAPHORE = asyncio.Semaphore(value=1)

NON_RETRYABLE_ERROR_TYPES = (
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
    # Raised when a Warehouse is suspended.
    "SnowflakeWarehouseSuspendedError",
    # Raised when the destination table schema is incompatible with the schema of the file we are trying to load.
    "SnowflakeIncompatibleSchemaError",
    # Raised when we hit our self-imposed query timeout.
    # We don't want to continually retry as it could consume a lot of compute resources in the user's account and can
    # lead to a lot of queries queuing up for a given warehouse.
    "SnowflakeQueryClientTimeoutError",
    # Raised when a Snowflake query exceeds the timeout set in the user's account. This is typically set by
    # STATEMENT_TIMEOUT_IN_SECONDS, which can be set at various levels (account, warehouse, user).
    "SnowflakeQueryServerTimeoutError",
    # Raised when either the warehouse does not exist or we are missing 'USAGE' permissions on it
    "SnowflakeWarehouseUsageError",
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


class SnowflakeWarehouseSuspendedError(Exception):
    """Raised when a Warehouse is suspended."""

    pass


class SnowflakeWarehouseUsageError(Exception):
    """Raised when either the warehouse does not exist or we are missing 'USAGE' permissions on it"""

    def __init__(self, warehouse: str):
        super().__init__(f"Warehouse '{warehouse}' does not exist or we are missing 'USAGE' permissions on it")


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


class SnowflakeIncompatibleSchemaError(Exception):
    """Raised when the destination table schema is incompatible with the schema of the file we are trying to load."""

    def __init__(self, err_msg: str):
        super().__init__(
            f"The data being loaded into the destination table is incompatible with the schema of the destination table: {err_msg}"
        )


class SnowflakeQueryClientTimeoutError(TimeoutError):
    """Raised when a Snowflake query times out."""

    def __init__(self, timeout: float, query_id: str, query_status: str):
        """Initialize the exception with context about the timeout.

        Args:
            timeout: The timeout duration in seconds
            query_id: The Snowflake query ID for debugging
            query_status: The status of the query when timeout occurred
        """
        self.timeout = timeout
        self.query_id = query_id
        self.query_status = query_status

        # Provide context-specific guidance based on query status
        status_guidance = {
            "QUEUED": "Warehouse is overloaded with queued queries. Consider scaling up warehouse or reducing concurrent queries.",
            "RESUMING_WAREHOUSE": "Warehouse is resuming from suspended state. Consider keeping warehouse running or using larger warehouse.",
            "QUEUED_REPARING_WAREHOUSE": "Warehouse is repairing. Retry later or contact Snowflake support.",
            "BLOCKED": "Query is blocked. Check for locks or resource contention.",
            "RUNNING": "Query is still running but exceeded timeout. Consider using a larger warehouse or reducing the number of concurrent queries.",
        }

        guidance = status_guidance.get(query_status, f"Query status: {query_status}")

        super().__init__(f"Query timed out after {timeout:.0f} seconds (query_id: {query_id}). {guidance}")


class SnowflakeQueryServerTimeoutError(TimeoutError):
    """Raised when a Snowflake query exceeds the timeout set in the user's account.

    This is typically set by STATEMENT_TIMEOUT_IN_SECONDS, which can be set at various
    levels (account, warehouse, user).
    """

    pass


SnowflakeTypeName = typing.Literal[
    "STRING",
    "TEXT",
    "BINARY",
    # Semi-structured type
    "VARIANT",
    # The following are all aliases representing the same integer type
    "INT",
    "INTEGER",
    "BIGINT",
    "SMALLINT",
    "TINYINT",
    "BYTEINT",
    "FIXED",
    # All aliases of the same 64 bit float type
    "FLOAT",
    "FLOAT4",
    "FLOAT8",
    "REAL",
    "DOUBLE",
    "DOUBLE PRECISION",
    "BOOLEAN",
    "TIMESTAMP",
    "TIMESTAMP_NTZ",
    "TIMESTAMP_LTZ",
    "ARRAY",
]


class SnowflakeType(typing.NamedTuple):
    name: SnowflakeTypeName
    repeated: bool


class SnowflakeDestinationField(typing.NamedTuple):
    name: str
    type: SnowflakeTypeName
    is_nullable: bool


def data_type_to_snowflake_type(data_type: pa.DataType) -> SnowflakeType:
    """Mapping of `pa.DataType` to corresponding `SnowflakeType`."""
    repeated = False

    if pa.types.is_string(data_type):
        snowflake_type_name: SnowflakeTypeName = "STRING"

    elif isinstance(data_type, JsonType):
        snowflake_type_name = "VARIANT"

    elif pa.types.is_binary(data_type):
        snowflake_type_name = "BINARY"

    elif pa.types.is_signed_integer(data_type) or pa.types.is_unsigned_integer(data_type):
        # Snowflake's integer is weird: It supports all signed numbers with 38 digits:
        # So the range is -10^38 + 1 to 10^38 - 1.
        # That's a lot of numbers, more than arrow can hold in 64 bits.
        # So, we don't really need to concern ourselves with overflows (or underflows).
        snowflake_type_name = "INTEGER"

    elif pa.types.is_floating(data_type):
        snowflake_type_name = "FLOAT"

    elif pa.types.is_boolean(data_type):
        snowflake_type_name = "BOOLEAN"

    elif pa.types.is_timestamp(data_type):
        snowflake_type_name = "TIMESTAMP"

    elif pa.types.is_list(data_type):
        repeated = True
        snowflake_type_name = data_type_to_snowflake_type(data_type.value_type).name  # type: ignore[attr-defined]

    else:
        raise TypeError(f"Unsupported type: '{data_type}'")

    return SnowflakeType(snowflake_type_name, repeated=repeated)


def snowflake_type_to_data_type(type: SnowflakeType) -> pa.DataType:
    """Mapping of `SnowflakeType` to corresponding `pa.DataType`."""
    match type.name:
        case "STRING" | "TEXT":
            base_type: pa.DataType = pa.string()
        case "BINARY":
            base_type = pa.binary()
        case "INT" | "INTEGER" | "BIGINT" | "SMALLINT" | "TINYINT" | "BYTEINT" | "FIXED":
            base_type = pa.int64()
        case "BOOLEAN":
            base_type = pa.bool_()
        case "VARIANT":
            base_type = JsonType()
        case "TIMESTAMP" | "TIMESTAMP_NTZ" | "TIMESTAMP_LTZ":
            base_type = pa.timestamp("ms", tz="UTC")
        case "FLOAT" | "FLOAT4" | "FLOAT8" | "DOUBLE PRECISION" | "REAL":
            base_type = pa.float64()
        case _:
            raise ValueError(f"Unsupported type: '{type.name}'")

    if type.repeated is True:
        return pa.list_(base_type)
    else:
        return base_type


class SnowflakeField(Field):
    """A field for a SnowflakeTable."""

    def __init__(self, name: str, type: SnowflakeType, data_type: pa.DataType, nullable: bool):
        self.name = name
        self.alias = name.lower()
        self.snowflake_type = type
        self.data_type = data_type
        self.nullable = nullable

    @classmethod
    def from_arrow_field(cls, field: pa.Field) -> typing.Self:
        snowflake_type = data_type_to_snowflake_type(field.type)
        return cls(field.name, snowflake_type, field.type, field.nullable)

    @classmethod
    def from_destination_field(cls, field: SnowflakeDestinationField) -> typing.Self:
        if field.type == "ARRAY":
            # Snowflake's 'ARRAY' can contain anything, so they don't tell us what's in
            # it. For now, only support arrays of string.
            # TODO: Maybe support more arrays?
            snowflake_type = SnowflakeType(name="STRING", repeated=True)
        elif field.type == "FIXED":
            # This isn't documented as a type. I know it is 'INTEGER', not sure why the
            # snowflake library invented 'FIXED'.
            snowflake_type = SnowflakeType(name="INTEGER", repeated=False)
        else:
            snowflake_type = SnowflakeType(name=field.type, repeated=False)

        return cls(field.name, snowflake_type, snowflake_type_to_data_type(snowflake_type), field.is_nullable)

    @property
    def snowflake_type_name(self) -> SnowflakeTypeName:
        if self.snowflake_type.repeated is True:
            return "ARRAY"
        else:
            return self.snowflake_type.name

    def to_destination_field(self) -> SnowflakeDestinationField:
        return SnowflakeDestinationField(name=self.name, type=self.snowflake_type_name, is_nullable=self.nullable)


class SnowflakeTable(Table):
    def __init__(
        self,
        name: str,
        fields: collections.abc.Iterable[SnowflakeField],
        parents: collections.abc.Iterable[str] = (),
        primary_key: collections.abc.Iterable[str] = (),
        version_key: collections.abc.Iterable[str] = (),
        stage_prefix: str = "",
    ):
        super().__init__(name, fields, parents, primary_key, version_key)
        self.stage_prefix = stage_prefix

    @classmethod
    def from_snowflake_table(
        cls,
        name: str,
        fields: collections.abc.Iterable[SnowflakeDestinationField],
        parents: collections.abc.Iterable[str] = (),
        primary_key: collections.abc.Iterable[str] = (),
        version_key: collections.abc.Iterable[str] = (),
        stage_prefix: str = "",
    ) -> typing.Self:
        snow_fields = [SnowflakeField.from_destination_field(field) for field in fields]

        return cls(
            name,
            snow_fields,
            parents=parents,
            primary_key=primary_key,
            version_key=version_key,
            stage_prefix=stage_prefix,
        )

    @classmethod
    def from_arrow_schema(
        cls,
        schema: pa.Schema,
        name: str,
        table_schema: str,
        database: str,
        primary_key: collections.abc.Iterable[str],
        version_key: collections.abc.Iterable[str],
        stage_prefix: str = "",
    ) -> typing.Self:
        self = cls.from_arrow_schema_with_field_type(
            schema,
            SnowflakeField,
            name,
            (database, table_schema),
            primary_key,
            version_key,
        )
        self.stage_prefix = stage_prefix

        return self


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

    # How often to poll for query status. This is a trade-off between responsiveness and number of
    # queries we make to Snowflake. 0.2 seemed a good compromise, based on local testing.
    DEFAULT_POLL_INTERVAL = 0.2

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
    async def connect(self, use_namespace: bool = True):
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
                    # wrap role in quotes in case it contains lowercase or special characters
                    role=f'"{self.role}"' if self.role is not None else None,
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
        self.ensure_snowflake_logger_level("INFO")

        await self.execute_async_query("ALTER SESSION SET QUOTED_IDENTIFIERS_IGNORE_CASE = FALSE", fetch_results=False)

        if use_namespace:
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
        """Switch to a namespace given by database, schema, and warehouse.

        This allows all queries that follow to ignore database and schema.
        It also ensures that we have permissions to use the warehouse.
        """
        await self.execute_async_query(f'USE DATABASE "{self.database}"', fetch_results=False)
        await self.execute_async_query(f'USE SCHEMA "{self.schema}"', fetch_results=False)
        try:
            await self.execute_async_query(f'USE WAREHOUSE "{self.warehouse}"', fetch_results=False)
        except snowflake.connector.errors.ProgrammingError as exc:
            if exc.msg is not None and "Object does not exist" in exc.msg:
                raise SnowflakeWarehouseUsageError(self.warehouse)
            raise

    async def get_query_status(self, query_id: str, throw_if_error: bool = True) -> QueryStatus:
        """Get the status of a query.

        Snowflake does a blocking HTTP request, so we send it to a thread to avoid blocking the event loop.
        """
        if throw_if_error:
            return await asyncio.to_thread(self.connection.get_query_status_throw_if_error, query_id)
        else:
            return await asyncio.to_thread(self.connection.get_query_status, query_id)

    async def abort_query(self, query_id: str, timeout: float = 30.0) -> None:
        """Abort a query with a timeout to prevent hanging."""
        try:
            with self.connection.cursor() as cursor:
                abort_success = await asyncio.wait_for(
                    asyncio.to_thread(cursor.abort_query, query_id),
                    timeout=timeout,
                )
                if not abort_success:
                    self.logger.warning("Failed to abort query", query_id=query_id)
        except TimeoutError:
            self.logger.warning("Timed out while aborting query after %.2fs", timeout, query_id=query_id)
        except Exception as e:
            self.logger.warning("Error while aborting query '%s'", e, query_id=query_id)

    async def execute_async_query(
        self,
        query: str,
        parameters: dict | None = None,
        file_stream=None,
        poll_interval: float | None = None,
        fetch_results: bool = True,
        timeout: float | None = None,
    ) -> tuple[list[tuple] | list[dict], list[ResultMetadata]] | None:
        """Wrap Snowflake connector's polling API in a coroutine.

        This enables asynchronous execution of queries to release the event loop to execute other tasks
        while we poll for a query to be done. For example, the event loop may use this time for heartbeating.

        The main advantage of using execute_async and polling for the result is that we don't need to maintain a network
        connection to the Snowflake server, which could timeout or be interrupted.

        Args:
            connection: A SnowflakeConnection object as produced by snowflake.connector.connect.
            query: A query string to run asynchronously.
            parameters: An optional dictionary of parameters to bind to the query.
            poll_interval: Specify how long to wait in between polls.
            fetch_results: Whether any result should be fetched from the query.
            timeout: The timeout (in seconds) to wait for the query to complete. If None, no timeout is applied.

        Returns:
            If `fetch_results` is `True`, a tuple containing:
            - The query results as a list of tuples or dicts
            - The cursor description (containing list of fields in result)
            Else when `fetch_results` is `False` we return `None`.

        Raises:
            SnowflakeQueryClientTimeoutError: If the query exceeds the specified timeout set by us.
        """
        query_start_time = time.monotonic()
        self.logger.debug("Executing async query: %s", query)

        poll_interval = poll_interval or self.DEFAULT_POLL_INTERVAL

        with self.connection.cursor() as cursor:
            # Snowflake docs incorrectly state that the 'params' argument is named 'parameters'.
            result = await asyncio.to_thread(cursor.execute_async, query, params=parameters, file_stream=file_stream)
            query_id = cursor.sfqid or result["queryId"]

        self.logger.debug("Waiting for results of query with ID '%s'", query_id)

        query_status: QueryStatus = await self.get_query_status(query_id, throw_if_error=True)

        while self.connection.is_still_running(query_status):
            # Check if we've exceeded the timeout
            if timeout is not None and (time.monotonic() - query_start_time) > timeout:
                # Get the final query status to provide context in the error message
                final_status = await self.get_query_status(query_id, throw_if_error=False)
                self.logger.warning(
                    "Query timed out after %.2fs with status '%s'",
                    timeout,
                    final_status.name if final_status else "UNKNOWN",
                    query_id=query_id,
                )

                # Cancel the query in Snowflake to prevent it from continuing to run
                await self.abort_query(query_id)

                raise SnowflakeQueryClientTimeoutError(
                    timeout=timeout,
                    query_id=query_id,
                    query_status=final_status.name if final_status else "UNKNOWN",
                )

            query_status = await self.get_query_status(query_id, throw_if_error=True)
            await asyncio.sleep(poll_interval)

        query_execution_time = time.monotonic() - query_start_time
        self.logger.debug(
            "Async query finished with status '%s' in %.2fs", query_status, query_execution_time, query_id=query_id
        )

        if fetch_results is False:
            return None

        self.logger.debug("Fetching query results", query_id=query_id)

        with self.connection.cursor() as cursor:
            await asyncio.to_thread(cursor.get_results_from_sfqid, query_id)
            results = await asyncio.to_thread(cursor.fetchall)
            description = cursor.description

        self.logger.debug("Finished fetching query results", query_id=query_id)

        return results, description

    async def get_or_create_table(self, table: SnowflakeTable) -> SnowflakeTable:
        """Get a table if it exists, else create it.

        Arguments:
            table: The table to get or create.

        Returns:
            A SnowflakeTable.
        """
        try:
            table = await self.get_table(table)
        except SnowflakeTableNotFoundError:
            await self.create_table(table)
            return await self.get_table(table)
        else:
            await self.remove_internal_stage_files(table)
            return table

    async def get_table(self, table: SnowflakeTable) -> SnowflakeTable:
        """Get a table in Snowflake.

        Arguments:
            table: The table to get. Can be a reference.

        Returns:
            A SnowflakeTable.
        """
        try:
            result = await self.execute_async_query(f"""
                SELECT * FROM "{table.name}" LIMIT 0
            """)
            assert result is not None
            _, metadata = result
        except snowflake.connector.errors.ProgrammingError as e:
            if "does not exist" in str(e):
                raise SnowflakeTableNotFoundError(table.name)
            else:
                raise

        record_batch_field_names = [field.name.lower() for field in table.fields]
        fields = (
            SnowflakeDestinationField(metadata.name, FIELD_ID_TO_NAME[metadata.type_code], metadata.is_nullable)  # type: ignore[arg-type]
            for metadata in metadata
            # Only include fields that are present in the record batch schema
            if metadata.name.lower() in record_batch_field_names
        )

        return SnowflakeTable.from_snowflake_table(
            table.name,
            fields=fields,
            parents=table.parents,
            primary_key=table.primary_key,
            version_key=table.version_key,
            stage_prefix=table.stage_prefix,
        )

    async def create_table(self, table: SnowflakeTable, exists_ok: bool = True) -> None:
        """Asynchronously create the table if it doesn't exist.

        Arguments:
            table: The table to create.
            exists_ok:
                Whether to include an 'IF NOT EXISTS' clause in the query such that it
                won't fail if the table already exists.
        """
        field_ddl = ", ".join(f'"{field.name}" {field.snowflake_type_name}' for field in table)

        if_not_exists = ""
        if exists_ok:
            if_not_exists = "IF NOT EXISTS"

        await self.execute_async_query(
            f"""
            CREATE TABLE {if_not_exists} "{table.name}" (
                {field_ddl}
            )
            COMMENT = 'PostHog generated table'
            """,
            fetch_results=False,
        )

    async def delete_table(
        self,
        table: SnowflakeTable,
        not_found_ok: bool = False,
    ) -> None:
        """Delete a table in BigQuery."""
        if not_found_ok is True:
            query = f'DROP TABLE IF EXISTS "{table.name}"'
        else:
            query = f'DROP TABLE "{table.name}"'

        await self.execute_async_query(query, fetch_results=False)

    @contextlib.asynccontextmanager
    async def managed_table(
        self,
        table: SnowflakeTable,
        create: bool = True,
        exists_ok: bool = True,
        delete: bool = True,
        not_found_ok: bool = True,
    ) -> collections.abc.AsyncGenerator[SnowflakeTable, None]:
        """Manage a table in Snowflake by ensure it exists while in context."""
        if create is True:
            await self.create_table(table)
            table = await self.get_table(table)
        else:
            await self.remove_internal_stage_files(table)

        try:
            yield table
        finally:
            if delete is True:
                await self.delete_table(table, not_found_ok)
            else:
                await self.remove_internal_stage_files(table)

    async def remove_internal_stage_files(self, table: SnowflakeTable) -> None:
        """Remove files from internal table stage.

        Arguments:
            table: The table whose internal stage to clear.
        """
        await self.execute_async_query(f"""REMOVE '@%"{table.name}"/{table.stage_prefix}'""", fetch_results=False)

    async def put_file_to_snowflake_table_stage(
        self,
        file: BatchExportTemporaryFile | NamedBytesIO,
        table: SnowflakeTable,
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
        file_stream: io.BufferedReader | io.BytesIO
        if isinstance(file, BatchExportTemporaryFile):
            file.rewind()
            file_stream = io.BufferedReader(file)
        else:
            file.seek(0)
            file_stream = file

        query = f"""
        PUT file://{file.name} '@%"{table.name}"/{table.stage_prefix}'
        """

        with self.connection.cursor() as cursor:
            cursor = self.connection.cursor()

            execute_put = functools.partial(cursor.execute, query, file_stream=file_stream)

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, func=execute_put)

            if isinstance(file, BatchExportTemporaryFile):
                file_stream.detach()  # BufferedReader closes the file otherwise.

            result = await asyncio.to_thread(cursor.fetchone)

            if not isinstance(result, tuple):
                # Mostly to appease mypy, as this query should always return a tuple.
                raise TypeError(f"Expected tuple from Snowflake PUT query but got: '{result.__class__.__name__}'")

        status, message = result[6:8]
        if status != "UPLOADED" and status != "SKIPPED":
            raise SnowflakeFileNotUploadedError(table.name, status, message)

    async def copy_loaded_files_to_snowflake_table(
        self,
        table: SnowflakeTable,
        timeout: float,
    ) -> None:
        """Execute a COPY query in Snowflake to load any files PUT into the table stage.

        The query is executed asynchronously using Snowflake's polling API.

        Args:
            table: The table we are COPY-ing files into.
            timeout: The timeout (in seconds) to wait for the COPY INTO query to complete.

        Raises:
            SnowflakeQueryClientTimeoutError: If the COPY INTO query exceeds the specified timeout set by us.
            SnowflakeQueryServerTimeoutError: If the COPY INTO query exceeds the timeout set in the user's account.
        """
        select_fields = ", ".join(
            f"PARSE_JSON($1:\"{field.name}\", 'd')"
            if field.data_type == JsonType() and field.name.lower() != "elements"
            else f'$1:"{field.name}"'
            for field in table
        )
        query = f"""
        COPY INTO "{table.name}" ({", ".join(f'"{field.name}"' for field in table)})

        FROM (
            SELECT {select_fields} FROM '@%"{table.name}"/{table.stage_prefix}'
        )
        FILE_FORMAT = (TYPE = 'PARQUET')
        PURGE = TRUE
        """

        self.logger.info("Copying files from table stage into table %s", table.name)

        # Handle cases where the Warehouse is suspended (sometimes we can recover from this)
        max_attempts = 3
        execute_copy_into = make_retryable_with_exponential_backoff(
            self.execute_async_query,
            max_attempts=max_attempts,
            retryable_exceptions=(snowflake.connector.errors.ProgrammingError,),
            # 608 = Warehouse suspended error
            is_exception_retryable=lambda e: isinstance(e, snowflake.connector.errors.ProgrammingError)
            and (e.errno == 608 or e.errno == 90073),
        )

        # We need to explicitly catch exceptions here because otherwise they seem to be swallowed
        try:
            result = await execute_copy_into(query, poll_interval=1.0, timeout=timeout)
        except SnowflakeQueryClientTimeoutError:
            # Re-raise as-is since it already has good context
            raise
        except snowflake.connector.errors.ProgrammingError as e:
            self.logger.exception(f"Error executing COPY INTO query: {e}")

            if e.errno == 608 or e.errno == 90073:
                err_msg = (
                    f"Failed to execute COPY INTO query after {max_attempts} attempts due to warehouse being suspended"
                )
                if e.msg is not None:
                    err_msg += f": {e.msg}"
                raise SnowflakeWarehouseSuspendedError(err_msg)
            elif e.errno in (630, 604) and e.msg is not None:
                raise SnowflakeQueryServerTimeoutError(e.msg)
            elif e.errno == 904 and e.msg is not None and "invalid identifier" in e.msg:
                raise SnowflakeIncompatibleSchemaError(e.msg)

            raise SnowflakeFileNotLoadedError(
                table.name,
                "NO STATUS",
                0,
                e.msg or "NO ERROR MESSAGE",
            )

        assert result is not None
        results, _ = result

        for query_result in results:
            if not isinstance(query_result, tuple):
                # Mostly to appease mypy, as this query should always return a tuple.
                raise TypeError(f"Expected tuple from Snowflake COPY INTO query but got: '{type(query_result)}'")

            if len(query_result) < 2:
                raise SnowflakeFileNotLoadedError(
                    table.name,
                    "NO STATUS",
                    0,
                    query_result[0] if len(query_result) == 1 else "NO ERROR MESSAGE",
                )

            _, status = query_result[0:2]

            if status != "LOADED":
                errors_seen, first_error = query_result[5:7]
                raise SnowflakeFileNotLoadedError(
                    table.name,
                    status or "NO STATUS",
                    errors_seen or 0,
                    first_error or "NO ERROR MESSAGE",
                )

        self.logger.info("Finished copying files into destination table")

    async def merge_into_final_from_stage(
        self,
        final: SnowflakeTable,
        stage: SnowflakeTable,
        timeout: float,
    ):
        """Merge two identical model tables in Snowflake.

        Args:
            final_table: The name of the final table to merge into.
            stage_table: The name of the stage table to merge from.
            merge_key: The fields to use as merge keys.
            update_key: The fields to check for updates.
            update_when_matched: The fields to update when matched.
            timeout: The timeout (in seconds) to wait for the MERGE query to complete.

        Raises:
            SnowflakeQueryClientTimeoutError: If the MERGE query exceeds the specified timeout set by us.
        """
        merge_condition = "ON "

        for n, primary_key_field_name in enumerate(final.primary_key):
            field = final[primary_key_field_name]
            if n > 0:
                merge_condition += " AND "
            merge_condition += f'final."{field.name}" = stage."{field.name}"'

        update_condition = "AND ("

        for index, version_key_field_name in enumerate(final.version_key):
            field = final[version_key_field_name]
            if index > 0:
                update_condition += " OR "
            update_condition += f'final."{field.name}" < stage."{field.name}"'
        update_condition += ")"

        update_clause = ""
        values = ""
        field_names = ""
        for n, field in enumerate(final):
            if n > 0:
                update_clause += ", "
                values += ", "
                field_names += ", "

            update_clause += f'final."{field.name}" = stage."{field.name}"'
            field_names += f'"{field.name}"'
            values += f'stage."{field.name}"'

        merge_query = f"""
        MERGE INTO "{final.name}" AS final
        USING "{stage.name}" AS stage
        {merge_condition}

        WHEN MATCHED {update_condition} THEN
            UPDATE SET
                {update_clause}
        WHEN NOT MATCHED THEN
            INSERT ({field_names})
            VALUES ({values});
        """

        self.logger.info("Starting merge", stage_table=stage.name, final_table=final.name)
        await self.execute_async_query(merge_query, fetch_results=False, poll_interval=1.0, timeout=timeout)
        self.logger.info("Finished merge")


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


class MergeSettings(typing.NamedTuple):
    primary_key: collections.abc.Sequence[str]
    version_key: collections.abc.Sequence[str]


def _get_merge_settings(
    model: BatchExportModel | BatchExportSchema | None,
) -> MergeSettings | None:
    if isinstance(model, BatchExportModel):
        if model.name == "persons":
            primary_key: collections.abc.Sequence[str] = ("team_id", "distinct_id")
            version_key: collections.abc.Sequence[str] = ("person_version", "person_distinct_id_version")

        elif model.name == "sessions":
            primary_key = ("team_id", "session_id")
            version_key = ("end_timestamp",)
        else:
            return None
    else:
        return None

    return MergeSettings(primary_key, version_key)


class SnowflakeConsumer(Consumer):
    """A consumer that uploads data to Snowflake from the internal stage.

    At the moment, it doesn't support concurrent uploads, but we can add that later to improve performance.
    """

    def __init__(
        self,
        snowflake_client: SnowflakeClient,
        snowflake_table: SnowflakeTable,
    ):
        super().__init__()

        self.snowflake_client = snowflake_client
        self.snowflake_table = snowflake_table

        # Simple file management - no concurrent uploads for now
        self.current_file_index = 0
        self.current_buffer = NamedBytesIO(
            b"", name=f"{self.snowflake_table.stage_prefix}/{self.current_file_index}.parquet.zst"
        )

    async def consume_chunk(self, data: bytes):
        """Consume a chunk of data by writing it to the current buffer."""
        self.current_buffer.write(data)

    async def finalize_file(self):
        """Finalize the current file and start a new one."""
        await self._upload_current_buffer()

    def _start_new_file(self):
        """Start a new file (reset state for file splitting)."""
        self.current_file_index += 1
        self.current_buffer = NamedBytesIO(
            b"", name=f"{self.snowflake_table.stage_prefix}/{self.current_file_index}.parquet.zst"
        )

    async def _upload_current_buffer(self):
        """Upload the current buffer to Snowflake, then start a new one."""
        buffer_size = self.current_buffer.tell()
        if buffer_size == 0:
            return  # Nothing to upload

        self.logger.info(
            "Uploading file %d with %d bytes to Snowflake table '%s'",
            self.current_file_index,
            buffer_size,
            self.snowflake_table,
        )

        self.current_buffer.seek(0)

        await self.snowflake_client.put_file_to_snowflake_table_stage(
            file=self.current_buffer,
            table=self.snowflake_table,
        )

        self.external_logger.info(
            "File %d with %d bytes uploaded to Snowflake table '%s'",
            self.current_file_index,
            buffer_size,
            self.snowflake_table,
        )

        self._start_new_file()

    async def finalize(self):
        """Finalize by uploading any remaining data."""
        await self._upload_current_buffer()


@activity.defn
@handle_non_retryable_errors(NON_RETRYABLE_ERROR_TYPES)
async def insert_into_snowflake_activity_from_stage(inputs: SnowflakeInsertInputs) -> BatchExportResult:
    """Activity to batch export data from internal S3 stage to Snowflake.

    This activity reads data from our internal S3 stage instead of ClickHouse directly, and uses concurrent uploads to
    improve performance.
    """
    bind_contextvars(
        team_id=inputs.team_id,
        destination="Snowflake",
        data_interval_start=inputs.data_interval_start,
        data_interval_end=inputs.data_interval_end,
        batch_export_id=inputs.batch_export_id,
        database=inputs.database,
        schema=inputs.schema,
        table_name=inputs.table_name,
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

    async with Heartbeater():
        model: BatchExportModel | BatchExportSchema | None = None
        if inputs.batch_export_schema is None:
            model = inputs.batch_export_model
        else:
            model = inputs.batch_export_schema

        queue = RecordBatchQueue(max_size_bytes=settings.BATCH_EXPORT_SNOWFLAKE_RECORD_BATCH_QUEUE_MAX_SIZE_BYTES)
        producer = Producer()
        assert inputs.batch_export_id is not None
        producer_task = await producer.start(
            queue=queue,
            batch_export_id=inputs.batch_export_id,
            data_interval_start=inputs.data_interval_start,
            data_interval_end=inputs.data_interval_end,
            max_record_batch_size_bytes=1024 * 1024 * 10,  # 10MB
            stage_folder=inputs.stage_folder,
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

        # TODO: Figure out which fields are JSON without hard-coding them here.
        json_fields = {"properties", "people_set", "people_set_once", "person_properties"}
        record_batch_schema = pa.schema(
            field.with_type(JsonType()) if field.name in json_fields else field for field in record_batch_schema
        )

        data_interval_end_str = dt.datetime.fromisoformat(inputs.data_interval_end).strftime("%Y-%m-%d_%H-%M-%S")
        attempt = activity.info().attempt
        stage_table_name = f"stage_{inputs.table_name}_{data_interval_end_str}_{inputs.team_id}_{attempt}"

        merge_settings = _get_merge_settings(model)
        target_table = SnowflakeTable.from_arrow_schema(
            record_batch_schema,
            name=inputs.table_name,
            table_schema=inputs.schema,
            database=inputs.database,
            primary_key=merge_settings.primary_key if merge_settings else (),
            version_key=merge_settings.version_key if merge_settings else (),
            stage_prefix=data_interval_end_str,
        )
        if "elements" in target_table:
            # `elements` is exported into a 'VARIANT' column, despite it being a
            # pa.string.
            # TODO: Export the JSON representation of elements, or drop it completely.
            field = target_table["elements"]
            field.snowflake_type = SnowflakeType("VARIANT", repeated=False)

        # Calculate timeout for long-running queries (COPY INTO and MERGE)
        long_running_query_timeout = get_query_timeout(
            dt.datetime.fromisoformat(inputs.data_interval_start) if inputs.data_interval_start else None,
            dt.datetime.fromisoformat(inputs.data_interval_end),
        )

        async with SnowflakeClient.from_inputs(inputs).connect() as snow_client:
            consumer_table = snow_target_table = await snow_client.get_or_create_table(target_table)
            # Exporting directly to target table
            should_delete = False
            should_exist = True

            if snow_target_table.is_mutable():
                consumer_table = SnowflakeTable(
                    stage_table_name,
                    snow_target_table.fields,
                    snow_target_table.parents,
                    primary_key=snow_target_table.primary_key,
                    version_key=snow_target_table.version_key,
                )
                # Using a stage table to later merge
                should_delete = True
                should_exist = False

            async with (
                snow_client.managed_table(
                    consumer_table,
                    create=True,
                    exists_ok=should_exist,
                    delete=should_delete,
                ) as snow_consumer_table,
            ):
                consumer = SnowflakeConsumer(
                    snowflake_client=snow_client,
                    snowflake_table=snow_consumer_table,
                )

                transformer = PipelineTransformer(
                    transformers=(
                        SchemaTransformer(table=snow_consumer_table),
                        ParquetStreamTransformer(
                            compression="zstd",
                            max_file_size_bytes=settings.BATCH_EXPORT_SNOWFLAKE_UPLOAD_CHUNK_SIZE_BYTES,
                        ),
                    )
                )
                result = await run_consumer_from_stage(
                    queue=queue,
                    consumer=consumer,
                    producer_task=producer_task,
                    transformer=transformer,
                    # TODO: Deprecate this argument once all other destinations are also migrated.
                    json_columns=(),
                )

                # TODO - maybe move this into the consumer finalize method?
                # Copy all staged files to the table
                await snow_client.copy_loaded_files_to_snowflake_table(
                    snow_consumer_table,
                    timeout=long_running_query_timeout,
                )

                if snow_target_table.is_mutable():
                    await snow_client.merge_into_final_from_stage(
                        final=snow_target_table,
                        stage=snow_consumer_table,
                        timeout=long_running_query_timeout,
                    )

                return result


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
            batch_export_id=inputs.batch_export_id,
            destination_default_fields=snowflake_default_fields(),
        )

        await execute_batch_export_using_internal_stage(
            insert_into_snowflake_activity_from_stage,
            insert_inputs,
            interval=inputs.interval,
        )
