import collections.abc
import contextlib
import csv
import dataclasses
import datetime as dt
import json
import typing
import uuid
import psycopg
import pyarrow as pa
from django.conf import settings
from psycopg import sql
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.models import BatchExportRun
from posthog.batch_exports.service import (
    BatchExportField,
    BatchExportModel,
    BatchExportSchema,
    PostgresBatchExportInputs,
    aupdate_batch_export_run,
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
from posthog.temporal.batch_exports.temporary_file import CSVBatchExportWriter
from posthog.temporal.batch_exports.utils import (
    JsonType,
    apeek_first_and_rewind,
    cast_record_batch_json_columns,
    make_retryable_with_exponential_backoff,
    set_status_to_running_task,
)
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import bind_temporal_worker_logger

PostgreSQLField = tuple[str, typing.LiteralString]
Fields = collections.abc.Iterable[PostgreSQLField]


class PostgreSQLConnectionError(Exception):
    pass


@dataclasses.dataclass
class PostgresInsertInputs:
    """Inputs for Postgres insert activity."""

    team_id: int
    user: str
    password: str
    host: str
    database: str
    table_name: str
    data_interval_start: str
    data_interval_end: str
    has_self_signed_cert: bool = False
    schema: str = "public"
    port: int = 5432
    exclude_events: list[str] | None = None
    include_events: list[str] | None = None
    run_id: str | None = None
    is_backfill: bool = False
    batch_export_model: BatchExportModel | None = None
    batch_export_schema: BatchExportSchema | None = None
    inserted_at_interval_start: str | None = None


class PostgreSQLClient:
    """PostgreSQL connection client used in batch exports."""

    def __init__(self, user: str, password: str, host: str, port: int, database: str, has_self_signed_cert: bool):
        self.user = user
        self.password = password
        self.database = database
        self.host = host
        self.port = port
        self.has_self_signed_cert = has_self_signed_cert

        self._connection: None | psycopg.AsyncConnection = None

    @classmethod
    def from_inputs(cls, inputs: PostgresInsertInputs) -> typing.Self:
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

        connect = make_retryable_with_exponential_backoff(
            psycopg.AsyncConnection.connect,
            retryable_exceptions=(psycopg.OperationalError,),
        )

        connection: psycopg.AsyncConnection = await connect(
            user=self.user,
            password=self.password,
            dbname=self.database,
            host=self.host,
            port=self.port,
            sslmode="prefer" if settings.TEST else "require",
            **kwargs,
        )

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
    ) -> None:
        """Create a table in PostgreSQL.

        Args:
            schema: Name of the schema where the table is to be created.
            table_name: Name of the table to create.
            fields: An iterable of PostgreSQL fields for the table.
            exists_ok: Whether to ignore if the table already exists.
            primary_key: Optionally set a primary key on these fields, needed for merges.
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

                await cursor.execute(
                    sql.SQL(base_query).format(
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
                )

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
        """
        if create is True:
            await self.acreate_table(schema, table_name, fields, exists_ok, primary_key=primary_key)

        try:
            yield table_name
        finally:
            if delete is True:
                await self.adelete_table(schema, table_name, not_found_ok)

    async def amerge_person_tables(
        self,
        final_table_name: str,
        stage_table_name: str,
        schema: str,
        merge_key: Fields,
        update_when_matched: Fields,
        person_version_key: str = "person_version",
        person_distinct_id_version_key: str = "person_distinct_id_version",
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

        and_separator = sql.SQL("AND")
        merge_condition = and_separator.join(
            sql.SQL("{final_field} = {stage_field}").format(
                final_field=sql.Identifier("final", field[0]),
                stage_field=sql.Identifier(schema, stage_table_name, field[0]),
            )
            for field in merge_key
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
        WHERE (EXCLUDED.{person_version_key} > final.{person_version_key} OR EXCLUDED.{person_distinct_id_version_key} > final.{person_distinct_id_version_key})
        """
        ).format(
            final_table=final_table_identifier,
            conflict_fields=conflict_fields,
            stage_table=stage_table_identifier,
            merge_condition=merge_condition,
            person_version_key=sql.Identifier(person_version_key),
            person_distinct_id_version_key=sql.Identifier(person_distinct_id_version_key),
            update_clause=update_clause,
            field_names=field_names,
        )

        async with self.connection.transaction():
            async with self.connection.cursor() as cursor:
                if schema:
                    await cursor.execute(sql.SQL("SET search_path TO {schema}").format(schema=sql.Identifier(schema)))
                await cursor.execute("SET TRANSACTION READ WRITE")

                await cursor.execute(merge_query)

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

        async with self.connection.transaction():
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
                    while data := tsv_file.read():
                        await copy.write(data)


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

        else:
            raise TypeError(f"Unsupported type: {pa_field.type}")

        pg_schema.append((name, pg_type))

    return pg_schema


@activity.defn
async def insert_into_postgres_activity(inputs: PostgresInsertInputs) -> RecordsCompleted:
    """Activity streams data from ClickHouse to Postgres."""
    logger = await bind_temporal_worker_logger(team_id=inputs.team_id, destination="PostgreSQL")
    await logger.ainfo(
        "Batch exporting range %s - %s to PostgreSQL: %s.%s.%s",
        inputs.data_interval_start,
        inputs.data_interval_end,
        inputs.database,
        inputs.schema,
        inputs.table_name,
    )

    async with (
        Heartbeater(),
        set_status_to_running_task(run_id=inputs.run_id, logger=logger),
        get_client(team_id=inputs.team_id) as client,
    ):
        if not await client.is_alive():
            raise ConnectionError("Cannot establish connection to ClickHouse")

        model: BatchExportModel | BatchExportSchema | None = None
        if inputs.batch_export_schema is None and "batch_export_model" in {
            field.name for field in dataclasses.fields(inputs)
        }:
            model = inputs.batch_export_model
        else:
            model = inputs.batch_export_schema

        record_batch_iterator = iter_model_records(
            client=client,
            model=model,
            team_id=inputs.team_id,
            interval_start=inputs.data_interval_start,
            interval_end=inputs.data_interval_end,
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            destination_default_fields=postgres_default_fields(),
            is_backfill=inputs.is_backfill,
            last_inserted_at=inputs.last_inserted_at,
        )
        first_record_batch, record_batch_iterator = await apeek_first_and_rewind(record_batch_iterator)
        if first_record_batch is None:
            return 0

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
            column_names = [column for column in first_record_batch.schema.names if column != "_inserted_at"]
            record_schema = first_record_batch.select(column_names).schema
            table_fields = get_postgres_fields_from_record_schema(
                record_schema, known_json_columns=["properties", "set", "set_once", "person_properties"]
            )

        schema_columns = [field[0] for field in table_fields]

        rows_exported = get_rows_exported_metric()
        bytes_exported = get_bytes_exported_metric()

        requires_merge = (
            isinstance(inputs.batch_export_model, BatchExportModel) and inputs.batch_export_model.name == "persons"
        )
        data_interval_end_str = dt.datetime.fromisoformat(inputs.data_interval_end).strftime("%Y-%m-%d_%H-%M-%S")
        stagle_table_name = (
            f"stage_{inputs.table_name}_{data_interval_end_str}" if requires_merge else inputs.table_name
        )

        if requires_merge:
            primary_key: Fields | None = (("team_id", "INTEGER"), ("distinct_id", "VARCHAR(200)"))
        else:
            primary_key = None

        async with PostgreSQLClient.from_inputs(inputs).connect() as pg_client:
            async with (
                pg_client.managed_table(
                    inputs.schema, inputs.table_name, table_fields, delete=False, primary_key=primary_key
                ) as pg_table,
                pg_client.managed_table(
                    inputs.schema,
                    stagle_table_name,
                    table_fields,
                    create=requires_merge,
                    delete=requires_merge,
                    primary_key=primary_key,
                ) as pg_stage_table,
            ):

                async def flush_to_postgres(
                    local_results_file,
                    records_since_last_flush,
                    bytes_since_last_flush,
                    flush_counter: int,
                    last_inserted_at,
                    last: bool,
                    error: Exception | None,
                ):
                    await logger.adebug(
                        "Copying %s records of size %s bytes",
                        records_since_last_flush,
                        bytes_since_last_flush,
                    )

                    table = pg_stage_table if requires_merge else pg_table
                    await pg_client.copy_tsv_to_postgres(
                        local_results_file,
                        inputs.schema,
                        table,
                        schema_columns,
                    )
                    rows_exported.add(records_since_last_flush)
                    bytes_exported.add(bytes_since_last_flush)

                writer = CSVBatchExportWriter(
                    max_bytes=settings.BATCH_EXPORT_POSTGRES_UPLOAD_CHUNK_SIZE_BYTES,
                    flush_callable=flush_to_postgres,
                    field_names=schema_columns,
                    delimiter="\t",
                    quoting=csv.QUOTE_MINIMAL,
                    escape_char=None,
                )

                last_inserted_at_interval_end = None
                async with writer.open_temporary_file():
                    async for record_batch in record_batch_iterator:
                        record_batch = cast_record_batch_json_columns(record_batch, json_columns=())

                        await writer.write_record_batch(record_batch)

                        if model is None or (isinstance(model, BatchExportModel) and model.name == "events"):
                            last_inserted_at_interval_end = record_batch.column("_inserted_at")[-1].as_py()

                if requires_merge:
                    merge_key: Fields = (
                        ("team_id", "INT"),
                        ("distinct_id", "TEXT"),
                    )
                    await pg_client.amerge_person_tables(
                        final_table_name=pg_table,
                        stage_table_name=pg_stage_table,
                        schema=inputs.schema,
                        update_when_matched=table_fields,
                        merge_key=merge_key,
                    )

                await aupdate_batch_export_run(
                    run_id=uuid.UUID(inputs.run_id),
                    inserted_at_interval_end=last_inserted_at_interval_end,
                )

                return writer.records_total


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
        data_interval_start, data_interval_end = get_data_interval(inputs.interval, inputs.data_interval_end)

        start_batch_export_run_inputs = StartBatchExportRunInputs(
            team_id=inputs.team_id,
            batch_export_id=inputs.batch_export_id,
            data_interval_start=data_interval_start.isoformat(),
            data_interval_end=data_interval_end.isoformat(),
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            is_backfill=inputs.is_backfill,
            inserted_at_interval_start=inputs.inserted_at_interval_start,
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
            data_interval_start=data_interval_start.isoformat(),
            data_interval_end=data_interval_end.isoformat(),
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            run_id=run_id,
            batch_export_model=inputs.batch_export_model,
            batch_export_schema=inputs.batch_export_schema,
            inserted_at_interval_start=inputs.inserted_at_interval_start,
        )

        await execute_batch_export_insert_activity(
            insert_into_postgres_activity,
            insert_inputs,
            interval=inputs.interval,
            non_retryable_error_types=[
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
            ],
            finish_inputs=finish_inputs,
        )
