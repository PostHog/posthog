import os
import re
import gzip
import json
import typing as t
import datetime as dt
import operator
from collections import deque
from uuid import uuid4

import pytest

import responses
import snowflake.connector
from requests.models import PreparedRequest

from posthog.batch_exports.service import BackfillDetails, BatchExportModel, BatchExportSchema
from posthog.temporal.common.clickhouse import ClickHouseClient

from products.batch_exports.backend.temporal.destinations.snowflake_batch_export import snowflake_default_fields
from products.batch_exports.backend.temporal.record_batch_model import SessionsRecordBatchModel
from products.batch_exports.backend.temporal.spmc import Producer, RecordBatchQueue
from products.batch_exports.backend.tests.temporal.utils.records import (
    get_record_batch_from_queue,
    remove_duplicates_from_records,
)

# Common test attributes
TEST_TIME = dt.datetime.now(dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0)

REQUIRED_ENV_VARS = (
    "SNOWFLAKE_WAREHOUSE",
    "SNOWFLAKE_ACCOUNT",
    "SNOWFLAKE_USERNAME",
)


def snowflake_env_vars_are_set():
    if not all(env_var in os.environ for env_var in REQUIRED_ENV_VARS):
        return False
    if "SNOWFLAKE_PASSWORD" not in os.environ and "SNOWFLAKE_PRIVATE_KEY" not in os.environ:
        return False
    return True


SKIP_IF_MISSING_REQUIRED_ENV_VARS = pytest.mark.skipif(
    not snowflake_env_vars_are_set(),
    reason="Snowflake required env vars are not set",
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


class FakeSnowflakeCursor:
    """A fake Snowflake cursor that can fail on PUT and COPY queries."""

    def __init__(self, *args, failure_mode: str | None = None, **kwargs):
        self._execute_calls: list[dict[str, t.Any]] = []
        self._execute_async_calls: list[dict[str, t.Any]] = []
        self._sfqid = 1
        self._fail = failure_mode

    @property
    def sfqid(self):
        current = self._sfqid
        self._sfqid += 1
        return current

    def execute(self, query, params=None, file_stream=None):
        self._execute_calls.append({"query": query, "params": params, "file_stream": file_stream})

    def execute_async(self, query, params=None, file_stream=None):
        self._execute_async_calls.append({"query": query, "params": params, "file_stream": file_stream})

    def get_results_from_sfqid(self, query_id):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args, **kwargs):
        pass

    def fetchone(self):
        if self._fail == "put":
            return (
                "test",
                "test.gz",
                456,
                0,
                "NONE",
                "GZIP",
                "FAILED",
                "Some error on put",
            )
        else:
            return (
                "test",
                "test.gz",
                456,
                0,
                "NONE",
                "GZIP",
                "UPLOADED",
                None,
            )

    def fetchall(self):
        if self._fail == "copy":
            return [("test", "LOAD FAILED", 100, 99, 1, 1, "Some error on copy", 3)]
        else:
            return [("test", "LOADED", 100, 99, 1, 1, "Some error on copy", 3)]

    def description(self):
        return []


class FakeSnowflakeConnection:
    def __init__(
        self,
        *args,
        failure_mode: str | None = None,
        **kwargs,
    ):
        self._cursors: list[FakeSnowflakeCursor] = []
        self._is_running = True
        self.failure_mode = failure_mode

    def cursor(self) -> FakeSnowflakeCursor:
        cursor = FakeSnowflakeCursor(failure_mode=self.failure_mode)
        self._cursors.append(cursor)
        return cursor

    def get_query_status_throw_if_error(self, query_id):
        return "SUCCESS"

    def is_still_running(self, status):
        current_status = self._is_running
        self._is_running = not current_status
        return current_status

    def close(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args, **kwargs):
        pass


def contains_queries_in_order(queries: list[str], *queries_to_find: str):
    """Check if a list of queries contains a list of queries in order."""
    # We use a deque to pop the queries we find off the list of queries to
    # find, so that we can check that they are in order.
    # Note that we use regexes to match the queries, so we can more specifically
    # target the queries we want to find.
    queries_to_find_deque = deque(queries_to_find)
    for query in queries:
        if not queries_to_find_deque:
            # We've found all the queries we need to find.
            return True
        if re.match(queries_to_find_deque[0], query):
            # We found the query we were looking for, so pop it off the deque.
            queries_to_find_deque.popleft()
    return not queries_to_find_deque


def add_mock_snowflake_api(rsps: responses.RequestsMock, fail: bool | str = False):
    # Create a crude mock of the Snowflake API that just stores the queries
    # in a list for us to inspect.
    #
    # We also mock the login request, as well as the PUT file transfer
    # request. For the latter we also store the data that was contained in
    # the file.
    queries = []
    staged_files = []

    def query_request_handler(request: PreparedRequest):
        assert isinstance(request.body, bytes)
        sql_text = json.loads(gzip.decompress(request.body))["sqlText"]
        queries.append(sql_text)

        rowset: list[tuple[t.Any, ...]] = [("test", "LOADED", 456, 192, "NONE", "GZIP", "UPLOADED", "")]

        # If the query is something that looks like `PUT file:///tmp/tmp50nod7v9
        # @%"events"` we extract the /tmp/tmp50nod7v9 and store the file
        # contents as a string in `staged_files`.
        if match := re.match(r"^PUT file://(?P<file_path>.*) @%(?P<table_name>.*)$", sql_text):
            file_path = match.group("file_path")
            with open(file_path) as f:
                staged_files.append(f.read())

            if fail == "put":
                rowset = [
                    (
                        "test",
                        "test.gz",
                        456,
                        0,
                        "NONE",
                        "GZIP",
                        "FAILED",
                        "Some error on put",
                    )
                ]

        else:
            if fail == "copy":
                rowset = [("test", "LOAD FAILED", 100, 99, 1, 1, "Some error on copy", 3)]

        return (
            200,
            {},
            json.dumps(
                {
                    "code": None,
                    "message": None,
                    "success": True,
                    "data": {
                        "parameters": [],
                        "rowtype": [
                            {
                                "name": "source",
                                "type": "TEXT",
                                "length": 0,
                                "precision": None,
                                "scale": None,
                                "nullable": True,
                            },
                            {
                                "name": "target",
                                "type": "TEXT",
                                "length": 0,
                                "precision": None,
                                "scale": None,
                                "nullable": True,
                            },
                            {
                                "name": "source_size",
                                "type": "fixed",
                                "length": 0,
                                "precision": None,
                                "scale": None,
                                "nullable": True,
                            },
                            {
                                "name": "target_size",
                                "type": "fixed",
                                "length": 0,
                                "precision": None,
                                "scale": None,
                                "nullable": True,
                            },
                            {
                                "name": "source_compression",
                                "type": "TEXT",
                                "length": 0,
                                "precision": None,
                                "scale": None,
                                "nullable": True,
                            },
                            {
                                "name": "target_compression",
                                "type": "TEXT",
                                "length": 0,
                                "precision": None,
                                "scale": None,
                                "nullable": True,
                            },
                            {
                                "name": "status",
                                "type": "TEXT",
                                "length": 0,
                                "precision": None,
                                "scale": None,
                                "nullable": True,
                            },
                            {
                                "name": "message",
                                "type": "TEXT",
                                "length": 0,
                                "precision": None,
                                "scale": None,
                                "nullable": True,
                            },
                        ],
                        "rowset": rowset,
                        "total": 1,
                        "returned": 1,
                        "queryId": str(uuid4()),
                        "queryResultFormat": "json",
                    },
                }
            ),
        )

    rsps.add(
        responses.POST,
        "https://account.snowflakecomputing.com:443/session/v1/login-request",
        json={
            "success": True,
            "data": {
                "token": "test-token",
                "masterToken": "test-token",
                "code": None,
                "message": None,
            },
        },
    )
    rsps.add_callback(
        responses.POST,
        "https://account.snowflakecomputing.com:443/queries/v1/query-request",
        callback=query_request_handler,
    )

    return queries, staged_files


async def assert_clickhouse_records_in_snowflake(
    snowflake_cursor: snowflake.connector.cursor.SnowflakeCursor,
    clickhouse_client: ClickHouseClient,
    table_name: str,
    team_id: int,
    data_interval_start: dt.datetime,
    data_interval_end: dt.datetime,
    exclude_events: list[str] | None = None,
    include_events: list[str] | None = None,
    batch_export_model: BatchExportModel | BatchExportSchema | None = None,
    backfill_details: BackfillDetails | None = None,
    sort_key: str = "event",
    expected_fields: list[str] | None = None,
    expect_duplicates: bool = False,
    primary_key: list[str] | None = None,
):
    """Assert ClickHouse records are written to Snowflake table.

    Arguments:
        snowflake_cursor: A SnowflakeCursor used to read records.
        clickhouse_client: A ClickHouseClient used to read records that are expected to be exported.
        team_id: The ID of the team that we are testing for.
        table_name: Snowflake table name where records are exported to.
        data_interval_start: Start of the batch period for exported records.
        data_interval_end: End of the batch period for exported records.
        exclude_events: Event names to be excluded from the export.
        include_events: Event names to be included in the export.
        batch_export_model: The model, or custom schema, used in the batch export.
        expected_fields: List of fields expected to be in the destination table.
        expect_duplicates: Whether duplicates are expected (e.g. when testing retrying logic).
    """
    snowflake_cursor.execute(f'SELECT * FROM "{table_name}"')

    rows = snowflake_cursor.fetchall()

    columns = {index: metadata.name for index, metadata in enumerate(snowflake_cursor.description)}
    json_columns = ("properties", "person_properties", "people_set", "people_set_once", "urls")

    # Rows are tuples, so we construct a dictionary using the metadata from cursor.description.
    # We rely on the order of the columns in each row matching the order set in cursor.description.
    # This seems to be the case, at least for now.
    inserted_records = [
        {
            columns[index]: json.loads(row[index])
            if columns[index] in json_columns and row[index] is not None
            else row[index]
            for index in columns.keys()
        }
        for row in rows
    ]

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
        destination_default_fields=snowflake_default_fields(),
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

                if k in json_columns and isinstance(v, str):
                    expected_record[k] = json.loads(v)
                elif isinstance(v, dt.datetime):
                    # By default, Snowflake's `TIMESTAMP` doesn't include a timezone component.
                    expected_record[k] = v.replace(tzinfo=None)
                elif k == "elements":
                    # Happens transparently when uploading elements as a variant field.
                    expected_record[k] = json.dumps(v)
                else:
                    expected_record[k] = v

            expected_records.append(expected_record)

    if expect_duplicates:
        inserted_records = remove_duplicates_from_records(inserted_records, primary_key)

    assert inserted_records, "No records were inserted into Snowflake"
    inserted_column_names = list(inserted_records[0].keys())
    expected_column_names = list(expected_records[0].keys())
    inserted_column_names.sort()
    expected_column_names.sort()

    # Ordering is not guaranteed, so we sort before comparing.
    inserted_records.sort(key=operator.itemgetter(sort_key))
    expected_records.sort(key=operator.itemgetter(sort_key))

    assert inserted_column_names == expected_column_names
    assert len(inserted_records) == len(expected_records)
    assert inserted_records[0] == expected_records[0]
    assert inserted_records == expected_records
    assert len(inserted_column_names) > 0
