import re
import json
import datetime as dt
import operator
import collections.abc

from psycopg import sql

from posthog.batch_exports.service import BackfillDetails, BatchExportModel, BatchExportSchema
from posthog.temporal.common.clickhouse import ClickHouseClient

from products.batch_exports.backend.temporal.destinations.postgres_batch_export import postgres_default_fields
from products.batch_exports.backend.temporal.record_batch_model import SessionsRecordBatchModel
from products.batch_exports.backend.temporal.spmc import Producer, RecordBatchQueue
from products.batch_exports.backend.tests.temporal.utils.records import (
    get_record_batch_from_queue,
    remove_duplicates_from_records,
)

EXPECTED_PERSONS_BATCH_EXPORT_FIELDS = [
    "team_id",
    "distinct_id",
    "person_id",
    "properties",
    "person_version",
    "person_distinct_id_version",
    "created_at",
    "_inserted_at",
    "is_deleted",
]


TEST_MODELS: list[BatchExportModel | BatchExportSchema | None] = [
    BatchExportModel(
        name="a-custom-model",
        schema={
            "fields": [
                {"expression": "event", "alias": "event"},
                {"expression": "nullIf(JSONExtractString(properties, %(hogql_val_0)s), '')", "alias": "browser"},
                {"expression": "nullIf(JSONExtractString(properties, %(hogql_val_1)s), '')", "alias": "os"},
                {"expression": "nullIf(properties, '')", "alias": "all_properties"},
            ],
            "values": {"hogql_val_0": "$browser", "hogql_val_1": "$os"},
        },
    ),
    BatchExportModel(name="events", schema=None),
    BatchExportModel(
        name="events",
        schema=None,
        filters=[
            {"key": "$browser", "operator": "exact", "type": "event", "value": ["Chrome"]},
            {"key": "$os", "operator": "exact", "type": "event", "value": ["Mac OS X"]},
        ],
    ),
    BatchExportModel(name="persons", schema=None),
    BatchExportModel(name="sessions", schema=None),
    {
        "fields": [
            {"expression": "event", "alias": "event"},
            {"expression": "nullIf(JSONExtractString(properties, %(hogql_val_0)s), '')", "alias": "browser"},
            {"expression": "nullIf(JSONExtractString(properties, %(hogql_val_1)s), '')", "alias": "os"},
            {"expression": "nullIf(properties, '')", "alias": "all_properties"},
        ],
        "values": {"hogql_val_0": "$browser", "hogql_val_1": "$os"},
    },
    None,
]


async def assert_clickhouse_records_in_postgres(
    postgres_connection,
    clickhouse_client: ClickHouseClient,
    schema_name: str,
    table_name: str,
    team_id: int,
    batch_export_model: BatchExportModel | BatchExportSchema | None,
    data_interval_start: dt.datetime,
    data_interval_end: dt.datetime,
    exclude_events: list[str] | None = None,
    include_events: list[str] | None = None,
    sort_key: str = "event",
    backfill_details: BackfillDetails | None = None,
    expected_fields: list[str] | None = None,
    expect_duplicates: bool = False,
    primary_key: collections.abc.Sequence[str] | None = None,
):
    """Assert expected records are written to a given PostgreSQL table.

    The steps this function takes to assert records are written are:
    1. Read all records inserted into given PostgreSQL table.
    2. Cast records read from PostgreSQL to a Python list of dicts.
    3. Assert records read from PostgreSQL have the expected column names.
    4. Read all records that were supposed to be inserted from ClickHouse.
    5. Cast records returned by ClickHouse to a Python list of dicts.
    6. Compare each record returned by ClickHouse to each record read from PostgreSQL.

    Arguments:
        postgres_connection: A PostgreSQL connection used to read inserted events.
        clickhouse_client: A ClickHouseClient used to read events that are expected to be inserted.
        schema_name: PostgreSQL schema name.
        table_name: PostgreSQL table name.
        team_id: The ID of the team that we are testing events for.
        batch_export_schema: Custom schema used in the batch export.
        expected_fields: The expected fields to be exported.
    """
    inserted_records = []

    async with postgres_connection.cursor() as cursor:
        await cursor.execute(sql.SQL("SELECT * FROM {}").format(sql.Identifier(schema_name, table_name)))
        columns = [column.name for column in cursor.description]

        for row in await cursor.fetchall():
            event = dict(zip(columns, row))
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

    producer_task = await producer.start(
        queue=queue,
        model_name=model_name,
        team_id=team_id,
        full_range=(data_interval_start, data_interval_end),
        done_ranges=[],
        fields=fields,
        filters=filters,
        destination_default_fields=postgres_default_fields(),
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

                # Remove \u0000 from strings and bytes (we perform the same operation in the COPY query)
                if isinstance(v, str):
                    v = re.sub(r"(?<!\\)\\u0000", "", v)
                elif isinstance(v, bytes):
                    v = re.sub(rb"(?<!\\)\\u0000", b"", v)
                # We remove unpaired surrogates in PostgreSQL, so we have to remove them here too so
                # that comparison doesn't fail. The problem is that at some point our unpaired surrogate gets
                # escaped (which is correct, as unpaired surrogates are not valid). But then the
                # comparison fails as in PostgreSQL we remove unpaired surrogates, not just escape them.
                # So, we hardcode replace the test properties. Not ideal, but this works as we get the
                # expected result in PostgreSQL and the comparison is still useful.
                if isinstance(v, str):
                    v = v.replace("\\ud83e\\udd23\\udd23", "\\ud83e\\udd23").replace(
                        "\\ud83e\\udd23\\ud83e", "\\ud83e\\udd23"
                    )

                if k in {"properties", "set", "set_once", "person_properties", "elements"} and v is not None:
                    expected_record[k] = json.loads(v)
                elif isinstance(v, dt.datetime):
                    expected_record[k] = v.replace(tzinfo=dt.UTC)
                else:
                    expected_record[k] = v

            expected_records.append(expected_record)

    if expect_duplicates:
        inserted_records = remove_duplicates_from_records(inserted_records, primary_key)

    inserted_column_names = list(inserted_records[0].keys())
    expected_column_names = list(expected_records[0].keys())
    inserted_column_names.sort()
    expected_column_names.sort()

    inserted_records.sort(key=operator.itemgetter(sort_key))
    expected_records.sort(key=operator.itemgetter(sort_key))

    assert inserted_column_names == expected_column_names
    assert len(inserted_records) == len(expected_records)
    assert inserted_records[0] == expected_records[0]
    assert inserted_records == expected_records
