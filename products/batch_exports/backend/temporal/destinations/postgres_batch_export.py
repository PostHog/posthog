import io
import re
import csv
import json
import random
import typing
import asyncio
import datetime as dt
import contextlib
import dataclasses
import collections.abc

from django.conf import settings

import psycopg
import pyarrow as pa
from psycopg import sql
from psycopg.errors import SerializationFailure
from structlog.contextvars import bind_contextvars
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.models import BatchExportRun
from posthog.batch_exports.service import (
    BatchExportField,
    BatchExportInsertInputs,
    BatchExportModel,
    BatchExportSchema,
    PostgresBatchExportInputs,
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
from products.batch_exports.backend.temporal.pipeline.transformer import CSVStreamTransformer
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
    make_retryable_with_exponential_backoff,
    set_status_to_running_task,
)

PostgreSQLField = tuple[str, typing.LiteralString]
Fields = collections.abc.Iterable[PostgreSQLField]

# Compiled regex patterns for PostgreSQL data cleaning
NULL_UNICODE_PATTERN = re.compile(rb"(?<!\\)\\u0000")
UNPAIRED_SURROGATE_PATTERN = re.compile(
    rb"(\\u[dD][89A-Fa-f][0-9A-Fa-f]{2}\\u[dD][c-fC-F][0-9A-Fa-f]{2})|(\\u[dD][89A-Fa-f][0-9A-Fa-f]{2})"
)
UNPAIRED_SURROGATE_PATTERN_2 = re.compile(
    rb"(\\u[dD][89A-Fa-f][0-9A-Fa-f]{2}\\u[dD][c-fC-F][0-9A-Fa-f]{2})|(\\u[dD][c-fC-F][0-9A-Fa-f]{2})"
)

LOGGER = get_write_only_logger(__name__)
EXTERNAL_LOGGER = get_logger("EXTERNAL")

NON_RETRYABLE_ERROR_TYPES = (
    # Raised on errors that are related to database operation.
    # For example: unexpected disconnect, database or other object not found.
    "OperationalError",
    # The schema name provided is invalid (usually because it doesn't exist).
    "InvalidSchemaName",
    # Missing permissions to, e.g., insert into table.
    "InsufficientPrivilege",
    # Issue with exported data compared to schema, retrying won't help.
    "NotNullViolation",
    # A user added a unique constraint on their table, but batch exports (particularly events)
    # can cause duplicates.
    "UniqueViolation",
    # Something changed in the target table's schema that we were not expecting.
    "UndefinedColumn",
    # A VARCHAR column is too small.
    "StringDataRightTruncation",
    # Raised by PostgreSQL client. Self explanatory.
    "DiskFull",
    # Raised by our PostgreSQL client when failing to connect after several attempts.
    "PostgreSQLConnectionError",
    # Raised when merging without a primary key.
    "MissingPrimaryKeyError",
    # Raised when the database doesn't support a particular feature we use.
    # Generally, we have seen this when the database is read-only.
    "FeatureNotSupported",
    # A check constraint has been violated.
    # We do not create any ourselves, so this generally is a user-managed check, so we
    # should not retry.
    "CheckViolation",
    # We do not create foreign keys, so this is a user managed check we have failed.
    "ForeignKeyViolation",
    # Data (usually event properties) contains garbage that we cannot clean.
    "UntranslatableCharacter",
    "InvalidTextRepresentation",
    # Can be raised when merging tables with an incompatible schema (eg if the destination table has been
    # created manually)
    "DatatypeMismatch",
    # Exceeded limits for indexes that we do not maintain.
    "ProgramLimitExceeded",
    # Raised when the destination table schema is incompatible with the schema of the data we are trying to export.
    "PostgreSQLIncompatibleSchemaError",
    # Raised when a transaction fails to complete after a certain number of retries.
    "PostgreSQLTransactionError",
)


class PostgreSQLConnectionError(Exception):
    pass


class MissingPrimaryKeyError(Exception):
    def __init__(self, table: sql.Identifier, primary_key: sql.Composed):
        super().__init__(f"An operation could not be completed as '{table}' is missing a primary key on {primary_key}")


class PostgreSQLIncompatibleSchemaError(Exception):
    """Raised when the destination table schema is incompatible with the schema of the data we are trying to export."""

    def __init__(self, err_msg: str):
        super().__init__(f"The data being exported is incompatible with the schema of the destination table: {err_msg}")


class PostgreSQLTransactionError(Exception):
    """Raised when a transaction fails to complete after a certain number of retries."""

    def __init__(self, max_attempts: int, err_msg: str):
        super().__init__(f"A transaction failed to complete after {max_attempts} attempts: {err_msg}")


@dataclasses.dataclass(kw_only=True)
class PostgresInsertInputs(BatchExportInsertInputs):
    """Inputs for Postgres."""

    user: str
    password: str
    host: str
    port: int = 5432
    database: str
    schema: str = "public"
    table_name: str
    has_self_signed_cert: bool = False


async def run_in_retryable_transaction(
    connection: psycopg.AsyncConnection,
    fn: collections.abc.Callable[[], collections.abc.Awaitable[typing.Any]],
    max_attempts: int = 3,
) -> typing.Any:
    """Run a callable inside a transaction with retry logic for serialization failures.

    Inspiration: https://github.com/cockroachdb/example-app-python-psycopg3/blob/main/example.py#L70-L105

    Args:
        connection: The PostgreSQL connection to use
        fn: An async callable to execute within the transaction
        max_attempts: Maximum number of retry attempts
    Returns:
        The return value of fn
    """
    for attempt in range(1, max_attempts + 1):
        try:
            async with connection.transaction():
                return await fn()

        except SerializationFailure as e:
            if attempt == max_attempts:
                raise PostgreSQLTransactionError(max_attempts, str(e)) from e

            LOGGER.debug("SerializationFailure caught in transaction (attempt %d/%d): %s", attempt, max_attempts, e)
            sleep_seconds = (2**attempt) * 0.1 * (random.random() + 0.5)
            LOGGER.debug("Sleeping %s seconds", sleep_seconds)
            await asyncio.sleep(sleep_seconds)


class _PostgreSQLClientInputsProtocol(typing.Protocol):
    user: str
    password: str
    host: str
    port: int
    database: str
    has_self_signed_cert: bool


class PostgreSQLClient:
    """PostgreSQL connection client used in batch exports."""

    def __init__(
        self,
        user: str,
        password: str,
        host: str,
        port: int,
        database: str,
        has_self_signed_cert: bool,
        connection_timeout: int = 30,
    ):
        self.user = user
        self.password = password
        self.database = database
        self.host = host
        self.port = port
        self.has_self_signed_cert = has_self_signed_cert
        self.connection_timeout = connection_timeout

        self.logger = LOGGER.bind(host=host, port=port, database=database, user=user)
        self.external_logger = EXTERNAL_LOGGER.bind(host=host, port=port, database=database, user=user)
        self._connection: None | psycopg.AsyncConnection = None

    @classmethod
    def from_inputs(cls, inputs: _PostgreSQLClientInputsProtocol) -> typing.Self:
        """Initialize `PostgreSQLClient` from `PostgresInsertInputs`."""
        return cls(
            user=inputs.user,
            password=inputs.password,
            database=inputs.database,
            host=inputs.host,
            port=inputs.port,
            has_self_signed_cert=inputs.has_self_signed_cert,
        )

    @property
    def connection(self) -> psycopg.AsyncConnection:
        """Raise if a `psycopg.AsyncConnection` hasn't been established, else return it."""
        if self._connection is None:
            raise PostgreSQLConnectionError("Not connected, open a connection by calling connect")
        return self._connection

    @contextlib.asynccontextmanager
    async def connect(
        self,
    ) -> typing.AsyncIterator[typing.Self]:
        """Manage a PostgreSQL connection.

        By using a context manager Pyscopg will take care of closing the connection.
        """
        kwargs: dict[str, typing.Any] = {}
        if self.has_self_signed_cert:
            # Disable certificate verification for self-signed certificates.
            kwargs["sslrootcert"] = None

        max_attempts = 5
        connect: typing.Callable[..., typing.Awaitable[psycopg.AsyncConnection]] = (
            make_retryable_with_exponential_backoff(
                psycopg.AsyncConnection.connect,
                max_attempts=max_attempts,
                retryable_exceptions=(psycopg.OperationalError, psycopg.errors.ConnectionTimeout),
            )
        )

        try:
            connection: psycopg.AsyncConnection = await connect(
                user=self.user,
                password=self.password,
                dbname=self.database,
                host=self.host,
                port=self.port,
                connect_timeout=self.connection_timeout,
                sslmode="prefer" if settings.TEST else "require",
                **kwargs,
            )
        except psycopg.errors.ConnectionTimeout as err:
            raise PostgreSQLConnectionError(
                f"Timed-out while trying to connect for {max_attempts} attempts. Is the "
                f"server running at '{self.host}', port '{self.port}' and accepting "
                "TCP/IP connections?"
            ) from err
        except psycopg.OperationalError as err:
            raise PostgreSQLConnectionError(
                f"Failed to connect after {max_attempts} attempts due to an unrecoverable error. "
                "Please review connection configuration. "
                f"Error message: {str(err)}"
            ) from err

        async with connection as connection:
            self._connection = connection
            yield self

    async def acreate_table(
        self,
        schema: str | None,
        table_name: str,
        fields: Fields,
        exists_ok: bool = True,
        primary_key: Fields | None = None,
        log_statements: bool = False,
    ) -> None:
        """Create a table in PostgreSQL.

        Args:
            schema: Name of the schema where the table is to be created.
            table_name: Name of the table to create.
            fields: An iterable of PostgreSQL fields for the table.
            exists_ok: Whether to ignore if the table already exists.
            primary_key: Optionally set a primary key on these fields, needed for merges.
            log_statements: If `True`, log the statements executed (useful for debugging)
        """
        if schema:
            table_identifier = sql.Identifier(schema, table_name)
        else:
            table_identifier = sql.Identifier(table_name)

        if exists_ok is True:
            base_query = "CREATE TABLE IF NOT EXISTS {table} ({fields}{pkey})"
        else:
            base_query = "CREATE TABLE {table} ({fields}{pkey})"

        if primary_key is not None:
            primary_key_clause = sql.SQL(", PRIMARY KEY ({fields})").format(
                fields=sql.SQL(",").join(sql.Identifier(field[0]) for field in primary_key)
            )

        async with self.connection.transaction():
            async with self.connection.cursor() as cursor:
                await cursor.execute("SET TRANSACTION READ WRITE")

                query = sql.SQL(base_query).format(
                    pkey=primary_key_clause if primary_key else sql.SQL(""),
                    table=table_identifier,
                    fields=sql.SQL(",").join(
                        sql.SQL("{field} {type}").format(
                            field=sql.Identifier(field),
                            type=sql.SQL(field_type),
                        )
                        for field, field_type in fields
                    ),
                )

                if log_statements:
                    LOGGER.info("Executing create table statement: %s", query.as_string(cursor))

                await cursor.execute(query)

    async def adelete_table(self, schema: str | None, table_name: str, not_found_ok: bool = True) -> None:
        """Delete a table in PostgreSQL.

        Args:
            schema: Name of the schema where the table to delete is located.
            table_name: Name of the table to delete.
            not_found_ok: Whether to ignore if the table doesn't exist.
        """
        if schema:
            table_identifier = sql.Identifier(schema, table_name)
        else:
            table_identifier = sql.Identifier(table_name)

        if not_found_ok is True:
            base_query = "DROP TABLE IF EXISTS {table}"
        else:
            base_query = "DROP TABLE {table}"

        async with self.connection.transaction():
            async with self.connection.cursor() as cursor:
                await cursor.execute("SET TRANSACTION READ WRITE")

                await cursor.execute(sql.SQL(base_query).format(table=table_identifier))

    async def aget_table_columns(self, schema: str | None, table_name: str) -> list[str]:
        """Get the column names for a table in PostgreSQL.

        Args:
            schema: Name of the schema where the table is located.
            table_name: Name of the table to get columns for.

        Returns:
            A list of column names in the table.
        """
        if schema:
            table_identifier = sql.Identifier(schema, table_name)
        else:
            table_identifier = sql.Identifier(table_name)

        async with self.connection.transaction():
            async with self.connection.cursor() as cursor:
                await cursor.execute(sql.SQL("SELECT * FROM {} WHERE 1=0").format(table_identifier))
                columns = [column.name for column in cursor.description or []]
                return columns

    @contextlib.asynccontextmanager
    async def managed_table(
        self,
        schema: str,
        table_name: str,
        fields: Fields,
        primary_key: Fields | None = None,
        exists_ok: bool = True,
        not_found_ok: bool = True,
        delete: bool = True,
        create: bool = True,
        log_statements: bool = False,
    ) -> collections.abc.AsyncGenerator[str, None]:
        """Manage a table in PostgreSQL by ensure it exists while in context.

        Managing a table implies two operations: creation of a table, which happens upon entering the
        context manager, and deletion of the table, which happens upon exiting.

        Args:
            schema: Schema where the managed table is.
            table_name: A name for the managed table.
            fields: An iterable of PostgreSQL fields for the table when it has to be created.
            primary_key: Optionally set a primary key on these fields on creation.
            exists_ok: Whether to ignore if the table already exists on creation.
            not_found_ok: Whether to ignore if the table doesn't exist.
            delete: If `False`, do not delete the table on exiting context manager.
            create: If `False`, do not attempt to create the table.
            log_statements: If `True`, log the statements executed (useful for debugging)
        """
        if create is True:
            await self.acreate_table(
                schema, table_name, fields, exists_ok, primary_key=primary_key, log_statements=log_statements
            )

        try:
            yield table_name
        finally:
            if delete is True:
                await self.adelete_table(schema, table_name, not_found_ok)

    async def amerge_mutable_tables(
        self,
        final_table_name: str,
        stage_table_name: str,
        schema: str,
        merge_key: Fields,
        update_key: Fields,
        update_when_matched: Fields,
    ) -> None:
        """Merge two identical person model tables in PostgreSQL.

        Merging utilizes PostgreSQL's `INSERT INTO ... ON CONFLICT` statement. PostgreSQL version
        15 and later supports a `MERGE` command, but to ensure support for older versions of PostgreSQL
        we do not use it. There are differences in the way concurrency is managed in `MERGE` but those
        are less relevant concerns for us than compatibility.
        """
        if schema:
            final_table_identifier = sql.Identifier(schema, final_table_name)
            stage_table_identifier = sql.Identifier(schema, stage_table_name)

        else:
            final_table_identifier = sql.Identifier(final_table_name)
            stage_table_identifier = sql.Identifier(stage_table_name)

        and_separator = sql.SQL(" AND ")
        merge_condition = and_separator.join(
            sql.SQL("{final_field} = {stage_field}").format(
                final_field=sql.Identifier("final", field[0]),
                stage_field=sql.Identifier(schema, stage_table_name, field[0]),
            )
            for field in merge_key
        )

        or_separator = sql.SQL(" OR ")
        update_condition = or_separator.join(
            sql.SQL("EXCLUDED.{stage_field} > final.{final_field}").format(
                final_field=sql.Identifier(field[0]),
                stage_field=sql.Identifier(field[0]),
            )
            for field in update_key
        )

        comma = sql.SQL(",")
        update_clause = comma.join(
            sql.SQL("{final_field} = EXCLUDED.{stage_field}").format(
                final_field=sql.Identifier(field[0]),
                stage_field=sql.Identifier(field[0]),
            )
            for field in update_when_matched
        )
        field_names = comma.join(sql.Identifier(field[0]) for field in update_when_matched)
        conflict_fields = comma.join(sql.Identifier(field[0]) for field in merge_key)

        merge_query = sql.SQL(
            """\
        INSERT INTO {final_table} AS final ({field_names})
        SELECT {field_names} FROM {stage_table}
        ON CONFLICT ({conflict_fields}) DO UPDATE SET
            {update_clause}
        WHERE ({update_condition})
        """
        ).format(
            final_table=final_table_identifier,
            conflict_fields=conflict_fields,
            stage_table=stage_table_identifier,
            merge_condition=merge_condition,
            update_condition=update_condition,
            update_clause=update_clause,
            field_names=field_names,
        )

        async with self.connection.transaction():
            async with self.connection.cursor() as cursor:
                if schema:
                    await cursor.execute(sql.SQL("SET search_path TO {schema}").format(schema=sql.Identifier(schema)))
                await cursor.execute("SET TRANSACTION READ WRITE")

                try:
                    await cursor.execute(merge_query)
                except psycopg.errors.InvalidColumnReference:
                    raise MissingPrimaryKeyError(final_table_identifier, conflict_fields)

    async def copy_tsv_to_postgres(
        self,
        tsv_file,
        schema: str,
        table_name: str,
        schema_columns: list[str],
    ) -> None:
        """Execute a COPY FROM query with given connection to copy contents of tsv_file.

        Arguments:
            tsv_file: A file-like object to interpret as TSV to copy its contents.
            schema: The schema where the table we are COPYing into exists.
            table_name: The name of the table we are COPYing into.
            schema_columns: The column names of the table we are COPYing into.
        """
        tsv_file.seek(0)

        async def _copy_tsv_in_transaction():
            async with self.connection.cursor() as cursor:
                if schema:
                    await cursor.execute(sql.SQL("SET search_path TO {schema}").format(schema=sql.Identifier(schema)))

                await cursor.execute("SET TRANSACTION READ WRITE")

                async with cursor.copy(
                    # TODO: Switch to binary encoding as CSV has a million edge cases.
                    sql.SQL("COPY {table_name} ({fields}) FROM STDIN WITH (FORMAT CSV, DELIMITER '\t')").format(
                        table_name=sql.Identifier(table_name),
                        fields=sql.SQL(",").join(sql.Identifier(column) for column in schema_columns),
                    )
                ) as copy:
                    while data := await asyncio.to_thread(tsv_file.read):
                        data = remove_invalid_json(data)
                        await copy.write(data)

        await run_in_retryable_transaction(self.connection, _copy_tsv_in_transaction)


def remove_invalid_json(data: bytes) -> bytes:
    """Remove invalid JSON from a byte string."""
    # \u0000 cannot be present in PostgreSQL's jsonb type, and will cause an error.
    # See: https://www.postgresql.org/docs/17/datatype-json.html
    # We use a regex to avoid replacing escaped \u0000 (for example, \\u0000, which we have seen in
    # some actual data)
    data = NULL_UNICODE_PATTERN.sub(b"", data)
    # Remove unpaired unicode surrogates
    data = UNPAIRED_SURROGATE_PATTERN.sub(rb"\1", data)
    data = UNPAIRED_SURROGATE_PATTERN_2.sub(rb"\1", data)
    return data


def postgres_default_fields() -> list[BatchExportField]:
    batch_export_fields = default_fields()
    batch_export_fields.append(
        {
            "expression": "nullIf(JSONExtractString(properties, '$ip'), '')",
            "alias": "ip",
        }
    )
    # Fields kept or removed for backwards compatibility with legacy apps schema.
    batch_export_fields.append({"expression": "toJSONString(toJSONString(elements_chain))", "alias": "elements"})
    batch_export_fields.append({"expression": "Null::Nullable(String)", "alias": "site_url"})
    batch_export_fields.pop(batch_export_fields.index({"expression": "created_at", "alias": "created_at"}))
    # Team ID is (for historical reasons) an INTEGER (4 bytes) in PostgreSQL, but in ClickHouse is stored as Int64.
    # We can't encode it as an Int64, as this includes 4 extra bytes, and PostgreSQL will reject the data with a
    # 'incorrect binary data format' error on the column, so we cast it to Int32.
    team_id_field = batch_export_fields.pop(
        batch_export_fields.index(BatchExportField(expression="team_id", alias="team_id"))
    )
    team_id_field["expression"] = "toInt32(team_id)"
    batch_export_fields.append(team_id_field)
    return batch_export_fields


def get_postgres_fields_from_record_schema(
    record_schema: pa.Schema, known_json_columns: list[str]
) -> list[PostgreSQLField]:
    """Generate a list of supported PostgreSQL fields from PyArrow schema.

    This function is used to map custom schemas to PostgreSQL-supported types. Some loss of precision is
    expected.
    """
    pg_schema: list[PostgreSQLField] = []

    for name in record_schema.names:
        pa_field = record_schema.field(name)

        if pa.types.is_string(pa_field.type) or isinstance(pa_field.type, JsonType):
            if pa_field.name in known_json_columns:
                pg_type = "JSONB"
            else:
                pg_type = "TEXT"

        elif pa.types.is_signed_integer(pa_field.type) or pa.types.is_unsigned_integer(pa_field.type):
            if pa.types.is_uint64(pa_field.type) or pa.types.is_int64(pa_field.type):
                pg_type = "BIGINT"
            else:
                pg_type = "INTEGER"

        elif pa.types.is_floating(pa_field.type):
            if pa.types.is_float64(pa_field.type):
                pg_type = "DOUBLE PRECISION"
            else:
                pg_type = "REAL"

        elif pa.types.is_boolean(pa_field.type):
            pg_type = "BOOLEAN"

        elif pa.types.is_timestamp(pa_field.type):
            if pa_field.type.tz is not None:
                pg_type = "TIMESTAMPTZ"
            else:
                pg_type = "TIMESTAMP"

        elif pa.types.is_list(pa_field.type) and pa.types.is_string(pa_field.type.value_type):
            pg_type = "TEXT[]"

        else:
            raise TypeError(f"Unsupported type in field '{name}': '{pa_field.type}'")

        pg_schema.append((name, pg_type))

    return pg_schema


@dataclasses.dataclass
class PostgreSQLHeartbeatDetails(BatchExportRangeHeartbeatDetails):
    """The PostgreSQL batch export details included in every heartbeat."""

    pass


class PostgreSQLConsumer(Consumer):
    def __init__(
        self,
        heartbeater: Heartbeater,
        heartbeat_details: PostgreSQLHeartbeatDetails,
        data_interval_start: dt.datetime | str | None,
        data_interval_end: dt.datetime | str,
        writer_format: WriterFormat,
        postgresql_client: PostgreSQLClient,
        postgresql_table: str,
        postgresql_table_schema: str,
        postgresql_table_fields: list[str],
    ):
        super().__init__(
            heartbeater=heartbeater,
            heartbeat_details=heartbeat_details,
            data_interval_start=data_interval_start,
            data_interval_end=data_interval_end,
            writer_format=writer_format,
        )
        self.heartbeat_details: PostgreSQLHeartbeatDetails = heartbeat_details
        self.postgresql_table = postgresql_table
        self.postgresql_table_schema = postgresql_table_schema
        self.postgresql_table_fields = postgresql_table_fields
        self.postgresql_client = postgresql_client

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
            "Copying %d records of size %d bytes to PostgreSQL table '%s.%s'",
            records_since_last_flush,
            bytes_since_last_flush,
            self.postgresql_table,
            self.postgresql_table_schema,
        )

        await self.postgresql_client.copy_tsv_to_postgres(
            batch_export_file,
            self.postgresql_table_schema,
            self.postgresql_table,
            self.postgresql_table_fields,
        )

        self.external_logger.info(
            "Copied %d records to PostgreSQL table '%s.%s'",
            records_since_last_flush,
            self.postgresql_table_schema,
            self.postgresql_table,
        )
        self.rows_exported_counter.add(records_since_last_flush)
        self.bytes_exported_counter.add(bytes_since_last_flush)

        self.heartbeat_details.records_completed += records_since_last_flush
        self.heartbeat_details.track_done_range(last_date_range, self.data_interval_start)


@activity.defn
@handle_non_retryable_errors(NON_RETRYABLE_ERROR_TYPES)
async def insert_into_postgres_activity(inputs: PostgresInsertInputs) -> BatchExportResult:
    """Activity streams data from ClickHouse to Postgres."""
    bind_contextvars(
        team_id=inputs.team_id,
        destination="PostgreSQL",
        data_interval_start=inputs.data_interval_start,
        data_interval_end=inputs.data_interval_end,
    )
    external_logger = EXTERNAL_LOGGER.bind()

    external_logger.info(
        "Batch exporting range %s - %s to PostgreSQL: %s.%s.%s",
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
        _, details = await should_resume_from_activity_heartbeat(activity, PostgreSQLHeartbeatDetails)
        if details is None:
            details = PostgreSQLHeartbeatDetails()

        done_ranges: list[DateRange] = details.done_ranges

        model, record_batch_model, model_name, fields, filters, extra_query_parameters = resolve_batch_exports_model(
            inputs.team_id, inputs.batch_export_model, inputs.batch_export_schema
        )

        data_interval_start = (
            dt.datetime.fromisoformat(inputs.data_interval_start) if inputs.data_interval_start else None
        )
        data_interval_end = dt.datetime.fromisoformat(inputs.data_interval_end)
        full_range = (data_interval_start, data_interval_end)

        queue = RecordBatchQueue(max_size_bytes=settings.BATCH_EXPORT_POSTGRES_RECORD_BATCH_QUEUE_MAX_SIZE_BYTES)
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
            destination_default_fields=postgres_default_fields(),
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
            [field.with_nullable(True) for field in record_batch_schema if field.name != "_inserted_at"]
        )

        if model is None or (isinstance(model, BatchExportModel) and model.name == "events"):
            table_fields: Fields = [
                ("uuid", "VARCHAR(200)"),
                ("event", "VARCHAR(200)"),
                ("properties", "JSONB"),
                ("elements", "JSONB"),
                ("set", "JSONB"),
                ("set_once", "JSONB"),
                ("distinct_id", "VARCHAR(200)"),
                ("team_id", "INTEGER"),
                ("ip", "VARCHAR(200)"),
                ("site_url", "VARCHAR(200)"),
                ("timestamp", "TIMESTAMP WITH TIME ZONE"),
            ]

        else:
            table_fields = get_postgres_fields_from_record_schema(
                record_batch_schema,
                known_json_columns=["properties", "set", "set_once", "person_properties"],
            )

        requires_merge = False
        merge_key: Fields = []
        update_key: Fields = []
        primary_key: Fields | None = None
        if isinstance(inputs.batch_export_model, BatchExportModel):
            if inputs.batch_export_model.name == "persons":
                requires_merge = True
                merge_key = [
                    ("team_id", "INT"),
                    ("distinct_id", "TEXT"),
                ]
                update_key = [
                    ("person_version", "INT"),
                    ("person_distinct_id_version", "INT"),
                ]
                primary_key = (("team_id", "INTEGER"), ("distinct_id", "VARCHAR(200)"))

            elif inputs.batch_export_model.name == "sessions":
                requires_merge = True
                merge_key = [
                    ("team_id", "INT"),
                    ("session_id", "TEXT"),
                ]
                update_key = [
                    ("end_timestamp", "TIMESTAMP"),
                ]
                primary_key = (("team_id", "INTEGER"), ("session_id", "TEXT"))

        data_interval_end_str = dt.datetime.fromisoformat(inputs.data_interval_end).strftime("%Y-%m-%d_%H-%M-%S")
        # NOTE: PostgreSQL has a 63 byte limit on identifiers.
        # With a 6 digit `team_id`, this leaves 30 bytes for a table name input.
        # TODO: That should be enough, but we should add a proper check and alert on larger inputs.
        stage_table_name = (
            f"stage_{inputs.table_name}_{data_interval_end_str}_{inputs.team_id}"
            if requires_merge
            else inputs.table_name
        )[:63]

        async with PostgreSQLClient.from_inputs(inputs).connect() as pg_client:
            table_exists = False
            # handle the case where the final table doesn't contain all the fields present in the record batch schema
            try:
                columns = await pg_client.aget_table_columns(inputs.schema, inputs.table_name)
                table_exists = True
                table_fields = [field for field in table_fields if field[0] in columns]
                if not table_fields:
                    raise PostgreSQLIncompatibleSchemaError(
                        f"No matching columns found in the destination table '{inputs.schema}.{inputs.table_name}'"
                    )
            except psycopg.errors.InsufficientPrivilege:
                external_logger.warning(
                    "Insufficient privileges to get table columns for table '%s.%s'; "
                    "will assume all columns are present. If this results in an error, please grant SELECT "
                    "permissions on this table or ensure the destination table is using the latest schema "
                    "as described in the docs: https://posthog.com/docs/cdp/batch-exports/postgres",
                    inputs.schema,
                    inputs.table_name,
                )
            except psycopg.errors.UndefinedTable:
                # this can happen if the table doesn't exist yet
                pass

            schema_columns = [field[0] for field in table_fields]

            async with (
                pg_client.managed_table(
                    inputs.schema,
                    inputs.table_name,
                    table_fields,
                    create=not table_exists,
                    delete=False,
                    primary_key=primary_key,
                    log_statements=True,
                ) as pg_table,
                pg_client.managed_table(
                    inputs.schema,
                    stage_table_name,
                    table_fields,
                    create=requires_merge,
                    delete=requires_merge,
                    primary_key=primary_key,
                ) as pg_stage_table,
            ):
                consumer = PostgreSQLConsumer(
                    heartbeater=heartbeater,
                    heartbeat_details=details,
                    data_interval_end=data_interval_end,
                    data_interval_start=data_interval_start,
                    writer_format=WriterFormat.CSV,
                    postgresql_client=pg_client,
                    postgresql_table=pg_stage_table if requires_merge else pg_table,
                    postgresql_table_schema=inputs.schema,
                    postgresql_table_fields=schema_columns,
                )
                try:
                    _ = await run_consumer(
                        consumer=consumer,
                        queue=queue,
                        producer_task=producer_task,
                        schema=record_batch_schema,
                        max_bytes=settings.BATCH_EXPORT_POSTGRES_UPLOAD_CHUNK_SIZE_BYTES,
                        json_columns=(),
                        writer_file_kwargs={
                            "delimiter": "\t",
                            "quoting": csv.QUOTE_MINIMAL,
                            "escape_char": None,
                            "field_names": schema_columns,
                        },
                        multiple_files=True,
                    )
                finally:
                    if requires_merge:
                        await pg_client.amerge_mutable_tables(
                            final_table_name=pg_table,
                            stage_table_name=pg_stage_table,
                            schema=inputs.schema,
                            update_when_matched=table_fields,
                            merge_key=merge_key,
                            update_key=update_key,
                        )

                return BatchExportResult(records_completed=details.records_completed)


class PostgreSQLConsumerFromStage(ConsumerFromStage):
    """Consumer for PostgreSQL batch exports using internal stage."""

    def __init__(
        self,
        client: PostgreSQLClient,
        schema: str,
        table_name: str,
        schema_columns: list[str],
    ):
        super().__init__()

        self.client = client
        self.schema = schema
        self.table_name = table_name
        self.schema_columns = schema_columns

        self.logger = self.logger.bind(schema=schema, table=table_name)

        self.current_file_index = 0
        self.current_buffer = io.BytesIO()

    async def consume_chunk(self, data: bytes):
        """Buffer data chunks in memory."""
        self.current_buffer.write(data)
        await asyncio.sleep(0)

    async def finalize_file(self):
        """Upload the current buffer and start a new file."""
        await self._upload_current_buffer()
        self._start_new_file()

    def _start_new_file(self):
        """Start a new file (reset state for file splitting)."""
        self.current_file_index += 1

    async def finalize(self):
        """Finalize by uploading any remaining data."""
        await self._upload_current_buffer()

    async def _upload_current_buffer(self):
        """Upload the current buffer to PostgreSQL using COPY."""
        buffer_size = self.current_buffer.tell()
        if buffer_size == 0:
            return

        self.logger.debug(
            "Starting COPY to PostgreSQL",
            current_file_index=self.current_file_index,
            buffer_size=buffer_size,
        )

        self.current_buffer.seek(0)

        await self.client.copy_tsv_to_postgres(
            self.current_buffer,
            self.schema,
            self.table_name,
            self.schema_columns,
        )

        self.current_buffer = io.BytesIO()


def _get_table_fields(
    model: BatchExportModel | BatchExportSchema | None,
    record_batch_schema: pa.Schema,
) -> Fields:
    """Extract table field definitions from model and schema."""
    if model is None or (isinstance(model, BatchExportModel) and model.name == "events"):
        return [
            ("uuid", "VARCHAR(200)"),
            ("event", "VARCHAR(200)"),
            ("properties", "JSONB"),
            ("elements", "JSONB"),
            ("set", "JSONB"),
            ("set_once", "JSONB"),
            ("distinct_id", "VARCHAR(200)"),
            ("team_id", "INTEGER"),
            ("ip", "VARCHAR(200)"),
            ("site_url", "VARCHAR(200)"),
            ("timestamp", "TIMESTAMP WITH TIME ZONE"),
        ]
    else:
        return get_postgres_fields_from_record_schema(
            record_batch_schema,
            known_json_columns=["properties", "set", "set_once", "person_properties"],
        )


class MergeSettings(typing.NamedTuple):
    requires_merge: bool
    merge_key: Fields
    update_key: Fields
    primary_key: Fields | None


def _get_merge_settings(
    model: BatchExportModel | BatchExportSchema | None,
) -> MergeSettings:
    requires_merge = False
    merge_key: Fields = []
    update_key: Fields = []
    primary_key: Fields | None = None

    if isinstance(model, BatchExportModel):
        if model.name == "persons":
            requires_merge = True
            merge_key = [
                ("team_id", "INT"),
                ("distinct_id", "TEXT"),
            ]
            update_key = [
                ("person_version", "INT"),
                ("person_distinct_id_version", "INT"),
            ]
            primary_key = (("team_id", "INTEGER"), ("distinct_id", "VARCHAR(200)"))

        elif model.name == "sessions":
            requires_merge = True
            merge_key = [
                ("team_id", "INT"),
                ("session_id", "TEXT"),
            ]
            update_key = [
                ("end_timestamp", "TIMESTAMP"),
            ]
            primary_key = (("team_id", "INTEGER"), ("session_id", "TEXT"))

    return MergeSettings(requires_merge, merge_key, update_key, primary_key)


@activity.defn
@handle_non_retryable_errors(NON_RETRYABLE_ERROR_TYPES)
async def insert_into_postgres_activity_from_stage(inputs: PostgresInsertInputs) -> BatchExportResult:
    """Activity streams data from internal S3 stage to Postgres."""
    bind_contextvars(
        team_id=inputs.team_id,
        destination="PostgreSQL",
        data_interval_start=inputs.data_interval_start,
        data_interval_end=inputs.data_interval_end,
        batch_export_id=inputs.batch_export_id,
    )
    external_logger = EXTERNAL_LOGGER.bind()

    external_logger.info(
        "Batch exporting range %s - %s to PostgreSQL (using internal stage): %s.%s.%s",
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

        queue = RecordBatchQueue(max_size_bytes=settings.BATCH_EXPORT_POSTGRES_RECORD_BATCH_QUEUE_MAX_SIZE_BYTES)
        producer = ProducerFromInternalStage()
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

        record_batch_schema = pa.schema(
            [field.with_nullable(True) for field in record_batch_schema if field.name != "_inserted_at"]
        )

        table_fields = _get_table_fields(model, record_batch_schema)
        merge_settings = _get_merge_settings(model)

        data_interval_end_str = dt.datetime.fromisoformat(inputs.data_interval_end).strftime("%Y-%m-%d_%H-%M-%S")

        attempt = activity.info().attempt
        # NOTE: PostgreSQL has a 63 byte limit on identifiers.
        # With a 6 digit `team_id`, this leaves 30 bytes for a table name input.
        # TODO: That should be enough, but we should add a proper check and alert on larger inputs.
        stage_table_name = (
            f"stage_{inputs.table_name}_{data_interval_end_str}_{inputs.team_id}_{attempt}"
            if merge_settings.requires_merge
            else inputs.table_name
        )[:63]

        async with PostgreSQLClient.from_inputs(inputs).connect() as pg_client:
            table_exists = False
            try:
                columns = await pg_client.aget_table_columns(inputs.schema, inputs.table_name)
                table_exists = True
                table_fields = [field for field in table_fields if field[0] in columns]
                if not table_fields:
                    raise PostgreSQLIncompatibleSchemaError(
                        f"No matching columns found in the destination table '{inputs.schema}.{inputs.table_name}'"
                    )
            except psycopg.errors.InsufficientPrivilege:
                external_logger.warning(
                    "Insufficient privileges to get table columns for table '%s.%s'; "
                    "will assume all columns are present. If this results in an error, please grant SELECT "
                    "permissions on this table or ensure the destination table is using the latest schema "
                    "as described in the docs: https://posthog.com/docs/cdp/batch-exports/postgres",
                    inputs.schema,
                    inputs.table_name,
                )
            except psycopg.errors.UndefinedTable:
                pass

            schema_columns = [field[0] for field in table_fields]

            async with (
                pg_client.managed_table(
                    inputs.schema,
                    inputs.table_name,
                    table_fields,
                    create=not table_exists,
                    delete=False,
                    primary_key=merge_settings.primary_key,
                    log_statements=True,
                ) as pg_table,
                pg_client.managed_table(
                    inputs.schema,
                    stage_table_name,
                    table_fields,
                    create=merge_settings.requires_merge,
                    delete=merge_settings.requires_merge,
                    primary_key=merge_settings.primary_key,
                ) as pg_stage_table,
            ):
                consumer = PostgreSQLConsumerFromStage(
                    client=pg_client,
                    schema=inputs.schema,
                    table_name=pg_stage_table if merge_settings.requires_merge else pg_table,
                    schema_columns=schema_columns,
                )

                transformer = CSVStreamTransformer(
                    field_names=schema_columns,
                    delimiter="\t",
                    quote_char='"',
                    escape_char=None,
                    line_terminator="\n",
                    quoting=csv.QUOTE_MINIMAL,
                    include_inserted_at=False,
                    max_file_size_bytes=settings.BATCH_EXPORT_POSTGRES_UPLOAD_CHUNK_SIZE_BYTES,
                )

                try:
                    result = await run_consumer_from_stage(
                        queue=queue,
                        consumer=consumer,
                        producer_task=producer_task,
                        transformer=transformer,
                    )
                finally:
                    if merge_settings.requires_merge:
                        await pg_client.amerge_mutable_tables(
                            final_table_name=pg_table,
                            stage_table_name=pg_stage_table,
                            schema=inputs.schema,
                            update_when_matched=table_fields,
                            merge_key=merge_settings.merge_key,
                            update_key=merge_settings.update_key,
                        )

                return result


@workflow.defn(name="postgres-export", failure_exception_types=[workflow.NondeterminismError])
class PostgresBatchExportWorkflow(PostHogWorkflow):
    """A Temporal Workflow to export ClickHouse data into Postgres.

    This Workflow is intended to be executed both manually and by a Temporal
    Schedule. When ran by a schedule, `data_interval_end` should be set to
    `None` so that we will fetch the end of the interval from the Temporal
    search attribute `TemporalScheduledStartTime`.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> PostgresBatchExportInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return PostgresBatchExportInputs(**loaded)

    @workflow.run
    async def run(self, inputs: PostgresBatchExportInputs):
        """Workflow implementation to export data to Postgres."""
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

        insert_inputs = PostgresInsertInputs(
            team_id=inputs.team_id,
            user=inputs.user,
            password=inputs.password,
            host=inputs.host,
            port=inputs.port,
            database=inputs.database,
            schema=inputs.schema,
            table_name=inputs.table_name,
            has_self_signed_cert=inputs.has_self_signed_cert,
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
            destination_default_fields=postgres_default_fields(),
        )

        if (
            str(inputs.team_id) in settings.BATCH_EXPORT_POSTGRES_USE_STAGE_TEAM_IDS
            or inputs.team_id % 100 < settings.BATCH_EXPORT_POSTGRES_USE_INTERNAL_STAGE_ROLLOUT_PERCENTAGE
        ):
            await execute_batch_export_using_internal_stage(
                insert_into_postgres_activity_from_stage,
                insert_inputs,
                interval=inputs.interval,
            )
        else:
            await execute_batch_export_insert_activity(
                insert_into_postgres_activity,
                insert_inputs,
                interval=inputs.interval,
                finish_inputs=finish_inputs,
            )
