import collections.abc
import contextlib
import datetime as dt
import itertools
import json
import typing
from dataclasses import dataclass

import psycopg
from psycopg import sql
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.service import RedshiftBatchExportInputs
from posthog.temporal.batch_exports.base import PostHogWorkflow
from posthog.temporal.batch_exports.batch_exports import (
    CreateBatchExportRunInputs,
    UpdateBatchExportRunStatusInputs,
    create_export_run,
    execute_batch_export_insert_activity,
    get_data_interval,
    get_results_iterator,
    get_rows_count,
)
from posthog.temporal.batch_exports.clickhouse import get_client
from posthog.temporal.common.logger import bind_temporal_worker_logger
from posthog.temporal.batch_exports.metrics import get_rows_exported_metric
from posthog.temporal.batch_exports.postgres_batch_export import (
    PostgresInsertInputs,
    create_table_in_postgres,
    postgres_connection,
)


def remove_escaped_whitespace_recursive(value):
    """Remove all escaped whitespace characters from given value.

    PostgreSQL supports constant escaped strings by appending an E' to each string that
    contains whitespace in them (amongst other characters). See:
    https://www.postgresql.org/docs/current/sql-syntax-lexical.html#SQL-SYNTAX-STRINGS-ESCAPE

    However, Redshift does not support this syntax. So, to avoid any escaping by
    underlying PostgreSQL library, we remove the whitespace ourselves as defined in the
    translation table WHITESPACE_TRANSLATE.

    This function is recursive just to be extremely careful and catch any whitespace that
    may be sneaked in a dictionary key or sequence.
    """
    match value:
        case str(s):
            return " ".join(s.replace("\b", " ").split())

        case bytes(b):
            return remove_escaped_whitespace_recursive(b.decode("utf-8"))

        case [*sequence]:
            # mypy could be bugged as it's raising a Statement unreachable error.
            # But we are definitely reaching this statement in tests; hence the ignore comment.
            # Maybe: https://github.com/python/mypy/issues/16272.
            return type(value)(remove_escaped_whitespace_recursive(sequence_value) for sequence_value in sequence)  # type: ignore

        case set(elements):
            return set(remove_escaped_whitespace_recursive(element) for element in elements)

        case {**mapping}:
            return {k: remove_escaped_whitespace_recursive(v) for k, v in mapping.items()}

        case value:
            return value


@contextlib.asynccontextmanager
async def redshift_connection(inputs) -> typing.AsyncIterator[psycopg.AsyncConnection]:
    """Manage a Redshift connection.

    This just yields a Postgres connection but we adjust a couple of things required for
    psycopg to work with Redshift:
    1. Set UNICODE encoding to utf-8 as Redshift reports back UNICODE.
    2. Set prepare_threshold to None on the connection as psycopg attempts to run DEALLOCATE ALL otherwise
        which is not supported on Redshift.
    """
    psycopg._encodings._py_codecs["UNICODE"] = "utf-8"
    psycopg._encodings.py_codecs.update((k.encode(), v) for k, v in psycopg._encodings._py_codecs.items())

    async with postgres_connection(inputs) as connection:
        connection.prepare_threshold = None
        yield connection


async def insert_records_to_redshift(
    records: collections.abc.Iterator[dict[str, typing.Any]],
    redshift_connection: psycopg.AsyncConnection,
    schema: str | None,
    table: str,
    batch_size: int = 100,
):
    """Execute an INSERT query with given Redshift connection.

    The recommended way to insert multiple values into Redshift is using a COPY statement (see:
    https://docs.aws.amazon.com/redshift/latest/dg/r_COPY.html). However, Redshift cannot COPY from local
    files like Postgres, but only from files in S3 or executing commands in SSH hosts. Setting that up would
    add complexity and require more configuration from the user compared to the old Redshift export plugin.
    For this reasons, we are going with basic INSERT statements for now, and we can migrate to COPY from S3
    later if the need arises.

    Arguments:
        record: A dictionary representing the record to insert. Each key should correspond to a column
            in the destination table.
        redshift_connection: A connection to Redshift setup by psycopg2.
        schema: The schema that contains the table where to insert the record.
        table: The name of the table where to insert the record.
        batch_size: Number of records to insert in batch. Setting this too high could
            make us go OOM or exceed Redshift's SQL statement size limit (16MB). Setting this too low
            can significantly affect performance due to Redshift's poor handling of INSERTs.
    """
    first_record = next(records)
    columns = first_record.keys()

    if schema:
        table_identifier = sql.Identifier(schema, table)
    else:
        table_identifier = sql.Identifier(table)

    pre_query = sql.SQL("INSERT INTO {table} ({fields}) VALUES").format(
        table=table_identifier,
        fields=sql.SQL(", ").join(map(sql.Identifier, columns)),
    )
    template = sql.SQL("({})").format(sql.SQL(", ").join(map(sql.Placeholder, columns)))
    rows_exported = get_rows_exported_metric()

    async with async_client_cursor_from_connection(redshift_connection) as cursor:
        batch = []
        pre_query_str = pre_query.as_string(cursor).encode("utf-8")

        async def flush_to_redshift(batch):
            values = b",".join(batch).replace(b" E'", b" '")

            await cursor.execute(pre_query_str + values)
            rows_exported.add(len(batch))
            # It would be nice to record BYTES_EXPORTED for Redshift, but it's not worth estimating
            # the byte size of each batch the way things are currently written. We can revisit this
            # in the future if we decide it's useful enough.

        for record in itertools.chain([first_record], records):
            batch.append(cursor.mogrify(template, record).encode("utf-8"))
            if len(batch) < batch_size:
                continue

            await flush_to_redshift(batch)
            batch = []

        if len(batch) > 0:
            await flush_to_redshift(batch)


@contextlib.asynccontextmanager
async def async_client_cursor_from_connection(
    psycopg_connection: psycopg.AsyncConnection,
) -> typing.AsyncIterator[psycopg.AsyncClientCursor]:
    """Yield a AsyncClientCursor from a psycopg.AsyncConnection.

    Keeps track of the current cursor_factory to set it after we are done.
    """
    current_factory = psycopg_connection.cursor_factory
    psycopg_connection.cursor_factory = psycopg.AsyncClientCursor

    try:
        async with psycopg_connection.cursor() as cursor:
            # Not a fan of typing.cast, but we know this is an psycopg.AsyncClientCursor
            # as we have just set cursor_factory.
            cursor = typing.cast(psycopg.AsyncClientCursor, cursor)
            yield cursor
    finally:
        psycopg_connection.cursor_factory = current_factory


@dataclass
class RedshiftInsertInputs(PostgresInsertInputs):
    """Inputs for Redshift insert activity.

    Inherit from PostgresInsertInputs as they are the same, but allow
    for setting property_data_type which is unique to Redshift.
    """

    properties_data_type: str = "varchar"


@activity.defn
async def insert_into_redshift_activity(inputs: RedshiftInsertInputs):
    """Activity to insert data from ClickHouse to Redshift.

    This activity executes the following steps:
    1. Check if anything is to be exported.
    2. Create destination table if not present.
    3. Query rows to export.
    4. Insert rows into Redshift.

    Args:
        inputs: The dataclass holding inputs for this activity. The inputs
            include: connection configuration (e.g. host, user, port), batch export
            query parameters (e.g. team_id, data_interval_start, include_events), and
            the Redshift-specific properties_data_type to indicate the type of JSON-like
            fields.
    """
    logger = await bind_temporal_worker_logger(team_id=inputs.team_id, destination="Redshift")
    logger.info(
        "Exporting batch %s - %s",
        inputs.data_interval_start,
        inputs.data_interval_end,
    )

    async with get_client() as client:
        if not await client.is_alive():
            raise ConnectionError("Cannot establish connection to ClickHouse")

        count = await get_rows_count(
            client=client,
            team_id=inputs.team_id,
            interval_start=inputs.data_interval_start,
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

        results_iterator = get_results_iterator(
            client=client,
            team_id=inputs.team_id,
            interval_start=inputs.data_interval_start,
            interval_end=inputs.data_interval_end,
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
        )
        properties_type = "VARCHAR(65535)" if inputs.properties_data_type == "varchar" else "SUPER"

        async with redshift_connection(inputs) as connection:
            await create_table_in_postgres(
                connection,
                schema=inputs.schema,
                table_name=inputs.table_name,
                fields=[
                    ("uuid", "VARCHAR(200)"),
                    ("event", "VARCHAR(200)"),
                    ("properties", properties_type),
                    ("elements", "VARCHAR(65535)"),
                    ("set", properties_type),
                    ("set_once", properties_type),
                    ("distinct_id", "VARCHAR(200)"),
                    ("team_id", "INTEGER"),
                    ("ip", "VARCHAR(200)"),
                    ("site_url", "VARCHAR(200)"),
                    ("timestamp", "TIMESTAMP WITH TIME ZONE"),
                ],
            )

        schema_columns = [
            "uuid",
            "event",
            "properties",
            "elements",
            "set",
            "set_once",
            "distinct_id",
            "team_id",
            "ip",
            "site_url",
            "timestamp",
        ]
        json_columns = ("properties", "set", "set_once")

        def map_to_record(row: dict) -> dict:
            """Map row to a record to insert to Redshift."""
            record = {
                key: json.dumps(remove_escaped_whitespace_recursive(row[key]), ensure_ascii=False)
                if key in json_columns and row[key] is not None
                else row[key]
                for key in schema_columns
            }
            record["elements"] = ""
            return record

        async with postgres_connection(inputs) as connection:
            await insert_records_to_redshift(
                (map_to_record(result) for result in results_iterator), connection, inputs.schema, inputs.table_name
            )


@workflow.defn(name="redshift-export")
class RedshiftBatchExportWorkflow(PostHogWorkflow):
    """A Temporal Workflow to export ClickHouse data into Postgres.

    This Workflow is intended to be executed both manually and by a Temporal
    Schedule. When ran by a schedule, `data_interval_end` should be set to
    `None` so that we will fetch the end of the interval from the Temporal
    search attribute `TemporalScheduledStartTime`.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> RedshiftBatchExportInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return RedshiftBatchExportInputs(**loaded)

    @workflow.run
    async def run(self, inputs: RedshiftBatchExportInputs):
        """Workflow implementation to export data to Redshift."""
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

        update_inputs = UpdateBatchExportRunStatusInputs(
            id=run_id,
            status="Completed",
            team_id=inputs.team_id,
        )

        insert_inputs = RedshiftInsertInputs(
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
            properties_data_type=inputs.properties_data_type,
        )

        await execute_batch_export_insert_activity(
            insert_into_redshift_activity,
            insert_inputs,
            non_retryable_error_types=[],
            update_inputs=update_inputs,
            # Disable heartbeat timeout until we add heartbeat support.
            heartbeat_timeout_seconds=None,
        )
