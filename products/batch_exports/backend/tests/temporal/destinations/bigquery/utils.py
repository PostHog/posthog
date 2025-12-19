import os
import json
import datetime as dt
import operator
import collections.abc

import pytest

from google.cloud import bigquery

from posthog.batch_exports.service import BackfillDetails, BatchExportModel, BatchExportSchema
from posthog.temporal.common.clickhouse import ClickHouseClient

from products.batch_exports.backend.temporal.destinations.bigquery_batch_export import bigquery_default_fields
from products.batch_exports.backend.temporal.record_batch_model import SessionsRecordBatchModel
from products.batch_exports.backend.temporal.spmc import Producer, RecordBatchQueue
from products.batch_exports.backend.tests.temporal.utils.records import get_record_batch_from_queue

SKIP_IF_MISSING_GOOGLE_APPLICATION_CREDENTIALS = pytest.mark.skipif(
    "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ,
    reason="Google credentials not set in environment",
)

TEST_TIME = dt.datetime.now(dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0)

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
    BatchExportModel(name="persons", schema=None),
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


async def assert_clickhouse_records_in_bigquery(
    bigquery_client: bigquery.Client,
    clickhouse_client: ClickHouseClient,
    team_id: int,
    table_id: str,
    dataset_id: str,
    date_ranges: list[tuple[dt.datetime, dt.datetime]],
    min_ingested_timestamp: dt.datetime | None = None,
    exclude_events: list[str] | None = None,
    include_events: list[str] | None = None,
    batch_export_model: BatchExportModel | BatchExportSchema | None = None,
    use_json_type: bool = False,
    sort_key: str = "event",
    backfill_details: BackfillDetails | None = None,
    expect_duplicates: bool = False,
    expected_fields: list[str] | None = None,
    timestamp_columns: collections.abc.Sequence[str] = (),
) -> None:
    """Assert ClickHouse records are written to a given BigQuery table.

    Arguments:
        bigquery_client: A BigQuery client used to read inserted records.
        clickhouse_client: A ClickHouseClient used to read records that are expected to
            be exported.
        team_id: The ID of the team that we are testing for.
        table_id: BigQuery table id where records are exported to.
        dataset_id: BigQuery dataset containing the table where records are exported to.
        date_ranges: Ranges of records we should expect to have been exported.
        min_ingested_timestamp: A datetime used to assert a minimum bound for
            'bq_ingested_timestamp'.
        exclude_events: Event names to be excluded from the export.
        include_events: Event names to be included in the export.
        batch_export_model: Model used in the batch export.
        use_json_type: Whether to use JSON type for known fields.
        expect_duplicates: Whether duplicates are expected (e.g. when testing retrying logic).
        expected_fields: The expected fields to be exported.
        timestamp_columns: Columns that are exported as UNIX timestamp, and should be
            interpreted as datetime
    """
    if use_json_type is True:
        json_columns = ["properties", "set", "set_once", "person_properties"]
    else:
        json_columns = []

    query_job = bigquery_client.query(f"SELECT * FROM {dataset_id}.{table_id}")
    result = query_job.result()

    inserted_records = []
    inserted_bq_ingested_timestamp = []

    for row in result:
        inserted_record = {}

        for k, v in row.items():
            if k == "bq_ingested_timestamp":
                inserted_bq_ingested_timestamp.append(v)
                continue

            elif isinstance(v, int) and k in timestamp_columns:
                inserted_record[k] = dt.datetime.fromtimestamp(v, tz=dt.UTC)
                continue

            elif k in json_columns:
                assert (
                    isinstance(v, dict) or v is None
                ), f"Expected '{k}' to be JSON, but it was not deserialized to dict"

            inserted_record[k] = v

        inserted_records.append(inserted_record)

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
            destination_default_fields=bigquery_default_fields(),
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
                    if k == "_inserted_at" or k == "bq_ingested_timestamp":
                        # _inserted_at is not exported, only used for tracking progress.
                        # bq_ingested_timestamp cannot be compared as it comes from an unstable function.
                        continue

                    if k in json_columns and v is not None:
                        # We remove unpaired surrogates in BigQuery, so we have to remove them here to so
                        # that comparison doesn't fail. The problem is that at some point our unpaired surrogate gets
                        # escaped (which is correct, as unpaired surrogates are not valid). But then the
                        # comparison fails as in BigQuery we remove unpaired surrogates, not just escape them.
                        # So, we hardcode replace the test properties. Not ideal, but this works as we get the
                        # expected result in BigQuery and the comparison is still useful.
                        v = v.replace("\\ud83e\\udd23\\udd23", "\\ud83e\\udd23").replace(
                            "\\ud83e\\udd23\\ud83e", "\\ud83e\\udd23"
                        )
                        expected_record[k] = json.loads(v)
                    elif isinstance(v, dt.datetime):
                        expected_record[k] = v.replace(tzinfo=dt.UTC)
                    else:
                        expected_record[k] = v

                expected_records.append(expected_record)

    if expect_duplicates:
        seen = set()

        def is_record_seen(record) -> bool:
            nonlocal seen

            if record["uuid"] in seen:
                return True

            seen.add(record["uuid"])
            return False

        inserted_records = [record for record in inserted_records if not is_record_seen(record)]

    assert len(inserted_records) == len(expected_records)

    # Ordering is not guaranteed, so we sort before comparing.
    inserted_records.sort(key=operator.itemgetter(sort_key))
    expected_records.sort(key=operator.itemgetter(sort_key))

    if len(inserted_records) >= 1 and "team_id" in inserted_records[0]:
        assert all(record["team_id"] == team_id for record in inserted_records)

    assert inserted_records[0] == expected_records[0]
    assert inserted_records == expected_records

    if len(inserted_bq_ingested_timestamp) > 0:
        assert (
            min_ingested_timestamp is not None
        ), "Must set `min_ingested_timestamp` for comparison with exported value"
        assert all(ts >= min_ingested_timestamp for ts in inserted_bq_ingested_timestamp)
