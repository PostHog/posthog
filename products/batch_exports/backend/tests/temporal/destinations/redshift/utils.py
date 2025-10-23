import os
import ast
import json
import asyncio
import datetime as dt
import operator
import collections.abc

import aioboto3
import botocore.exceptions
from psycopg import sql

from posthog.batch_exports.service import BackfillDetails, BatchExportModel, BatchExportSchema
from posthog.temporal.common.clickhouse import ClickHouseClient

from products.batch_exports.backend.temporal.destinations.redshift_batch_export import redshift_default_fields
from products.batch_exports.backend.temporal.record_batch_model import SessionsRecordBatchModel
from products.batch_exports.backend.temporal.spmc import Producer, RecordBatchQueue
from products.batch_exports.backend.temporal.temporary_file import remove_escaped_whitespace_recursive
from products.batch_exports.backend.tests.temporal.utils.records import (
    get_record_batch_from_queue,
    remove_duplicates_from_records,
)

REQUIRED_ENV_VARS = (
    "REDSHIFT_USER",
    "REDSHIFT_PASSWORD",
    "REDSHIFT_HOST",
)

MISSING_REQUIRED_ENV_VARS = any(env_var not in os.environ for env_var in REQUIRED_ENV_VARS)


TEST_MODELS: list[BatchExportModel | BatchExportSchema | None] = [
    BatchExportModel(
        name="a-custom-model",
        schema={
            "fields": [
                {"expression": "event", "alias": "event"},
                {"expression": "nullIf(JSONExtractString(properties, %(hogql_val_0)s), '')", "alias": "browser"},
                {"expression": "nullIf(JSONExtractString(properties, %(hogql_val_1)s), '')", "alias": "os"},
            ],
            "values": {"hogql_val_0": "$browser", "hogql_val_1": "$os"},
        },
    ),
    BatchExportModel(name="events", schema=None),
    BatchExportModel(name="persons", schema=None),
    BatchExportModel(name="sessions", schema=None),
    {
        "fields": [
            {"expression": "event", "alias": "event"},
            {"expression": "nullIf(JSONExtractString(properties, %(hogql_val_0)s), '')", "alias": "browser"},
            {"expression": "nullIf(JSONExtractString(properties, %(hogql_val_1)s), '')", "alias": "os"},
        ],
        "values": {"hogql_val_0": "$browser", "hogql_val_1": "$os"},
    },
    None,
]


async def assert_clickhouse_records_in_redshift(
    redshift_connection,
    clickhouse_client: ClickHouseClient,
    schema_name: str,
    table_name: str,
    team_id: int,
    batch_export_model: BatchExportModel | BatchExportSchema | None,
    date_ranges: list[tuple[dt.datetime, dt.datetime]],
    exclude_events: list[str] | None = None,
    include_events: list[str] | None = None,
    properties_data_type: str = "varchar",
    sort_key: str = "event",
    backfill_details: BackfillDetails | None = None,
    expected_duplicates_threshold: float = 0.0,
    expected_fields: list[str] | None = None,
    primary_key: collections.abc.Sequence[str] | None = None,
    copy: bool = False,
):
    """Assert expected records are written to a given Redshift table.

    The steps this function takes to assert records are written are:
    1. Read all records inserted into given Redshift table.
    2. Cast records read from Redshift to a Python list of dicts.
    3. Assert records read from Redshift have the expected column names.
    4. Read all records that were supposed to be inserted from ClickHouse.
    5. Cast records returned by ClickHouse to a Python list of dicts.
    6. Compare each record returned by ClickHouse to each record read from Redshift.

    Caveats:
    * Casting records to a Python list of dicts means losing some type precision.

    Arguments:
        redshift_connection: A Redshift connection used to read inserted events.
        clickhouse_client: A ClickHouseClient used to read events that are expected to be inserted.
        schema_name: Redshift schema name.
        table_name: Redshift table name.
        team_id: The ID of the team that we are testing events for.
        batch_export_schema: Custom schema used in the batch export.
        date_ranges: Ranges of records we should expect to have been exported.
        expected_duplicates_threshold: Threshold of duplicates we should expect relative to
            number of unique events, fail if we exceed it.
        expected_fields: The expected fields to be exported.
        copy: Whether using Redshift's COPY or not. This impacts handling of special
            characters as Parquet+COPY can handle a lot more than JSON.
    """
    super_columns = ["properties", "set", "set_once", "person_properties"]
    array_super_columns = ["urls"]

    inserted_records = []
    async with redshift_connection.cursor() as cursor:
        await cursor.execute(sql.SQL("SELECT * FROM {}").format(sql.Identifier(schema_name, table_name)))
        columns = [column.name for column in cursor.description]

        for row in await cursor.fetchall():
            event = dict(zip(columns, row))

            for column in super_columns:
                # When reading a SUPER type field we read it as a str.
                # But Redshift will remove all unquoted whitespace, so
                # '{"prop": 1, "prop": 2}' in CH becomes '{"prop":1,"prop":2}' in Redshift.
                # To make comparison easier we load them as JSON even if we don't have
                # properties_data_type set to SUPER, thus they are both dicts.
                if column in event and event.get(column, None) is not None:
                    event[column] = json.loads(event[column])

            for column in array_super_columns:
                # Arrays stored in SUPER are dumped like Python sets: '{"value", "value1"}'
                # But we expect these to come as lists from ClickHouse.
                # So, since they are read as strings, we first `json.loads` them and
                # then pass the resulting string to `literal_eval`, which will produce
                # either a dict or a set (depending if it's empty or not). Either way
                # we can cast them to list.
                if column in event and event.get(column, None) is not None:
                    load_result = json.loads(event[column])

                    if not isinstance(load_result, list):
                        value = ast.literal_eval(load_result)
                        event[column] = list(value)
                    else:
                        event[column] = load_result

            inserted_records.append(event)

    if batch_export_model is not None:
        if isinstance(batch_export_model, BatchExportModel):
            model_name = batch_export_model.name
            fields = batch_export_model.schema["fields"] if batch_export_model.schema is not None else None
            filters = batch_export_model.filters
            extra_query_parameters = (
                batch_export_model.schema["values"] if batch_export_model.schema is not None else None
            )
        else:
            model_name = "custom"
            fields = batch_export_model["fields"]
            filters = None
            extra_query_parameters = batch_export_model["values"]
    else:
        model_name = "events"
        extra_query_parameters = None
        fields = None
        filters = None

    expected_records = []
    queue = RecordBatchQueue()
    if model_name == "sessions":
        producer = Producer(model=SessionsRecordBatchModel(team_id))
    else:
        producer = Producer()

    for data_interval_start, data_interval_end in date_ranges:
        producer_task = await producer.start(
            queue=queue,
            model_name=model_name,
            team_id=team_id,
            full_range=(data_interval_start, data_interval_end),
            done_ranges=[],
            fields=fields,
            filters=filters,
            destination_default_fields=redshift_default_fields(),
            exclude_events=exclude_events,
            include_events=include_events,
            is_backfill=backfill_details is not None,
            backfill_details=backfill_details,
            extra_query_parameters=extra_query_parameters,
        )
        while True:
            record_batch = await get_record_batch_from_queue(queue, producer_task)

            if record_batch is None:
                break

            select = record_batch.column_names
            if expected_fields:
                select = expected_fields

            for record in record_batch.select(select).to_pylist():
                expected_record = {}

                for k, v in record.items():
                    if k == "_inserted_at":
                        # _inserted_at is not exported, only used for tracking progress.
                        continue

                    elif k in super_columns and v is not None:
                        if copy is False:
                            expected_record[k] = remove_escaped_whitespace_recursive(json.loads(v))
                        else:
                            expected_record[k] = json.loads(v)
                    elif isinstance(v, dt.datetime):
                        expected_record[k] = v.replace(tzinfo=dt.UTC)
                    else:
                        expected_record[k] = v

                expected_records.append(expected_record)

    if expected_duplicates_threshold > 0.0:
        unduplicated_len = len(inserted_records)
        inserted_records = remove_duplicates_from_records(inserted_records, primary_key)
        assert (unduplicated_len - len(inserted_records)) / len(inserted_records) < expected_duplicates_threshold

    inserted_column_names = list(inserted_records[0].keys())
    expected_column_names = list(expected_records[0].keys())
    inserted_column_names.sort()
    expected_column_names.sort()

    inserted_records.sort(key=operator.itemgetter(sort_key))
    expected_records.sort(key=operator.itemgetter(sort_key))

    assert (
        inserted_column_names == expected_column_names
    ), f"Expected column names to be '{expected_column_names}', got '{inserted_column_names}'"
    assert inserted_records[0] == expected_records[0]
    assert inserted_records == expected_records
    assert len(inserted_records) == len(expected_records)


async def check_valid_credentials() -> bool:
    """Check if there are valid AWS credentials in the environment."""
    session = aioboto3.Session()
    async with session.client("sts") as sts:
        try:
            await sts.get_caller_identity()
        except botocore.exceptions.ClientError:
            return False
        else:
            return True


def has_valid_credentials() -> bool:
    """Synchronous wrapper around check_valid_credentials."""
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(check_valid_credentials())


async def delete_all_from_s3_prefix(s3_client, bucket_name: str, key_prefix: str):
    """Delete all objects in bucket_name under key_prefix."""
    response = await s3_client.list_objects_v2(Bucket=bucket_name, Prefix=key_prefix)

    if "Contents" in response:
        for obj in response["Contents"]:
            if "Key" in obj:
                await s3_client.delete_object(Bucket=bucket_name, Key=obj["Key"])
