import datetime as dt
import json
import operator
import os
import tempfile
from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
import pytest_asyncio
import snowflake.connector

from posthog.batch_exports.models import BatchExport
from posthog.batch_exports.service import BackfillDetails, BatchExportModel, BatchExportSchema
from posthog.temporal.common.clickhouse import ClickHouseClient
from posthog.temporal.tests.utils.models import (
    acreate_batch_export,
    adelete_batch_export,
)
from products.batch_exports.backend.temporal.destinations.snowflake_batch_export import (
    load_private_key,
    snowflake_default_fields,
)
from products.batch_exports.backend.temporal.record_batch_model import SessionsRecordBatchModel
from products.batch_exports.backend.temporal.spmc import Producer, RecordBatchQueue
from products.batch_exports.backend.tests.temporal.utils import (
    get_record_batch_from_queue,
    remove_duplicates_from_records,
)


@pytest.fixture
def database():
    """Generate a unique database name for tests."""
    return f"test_batch_exports_{uuid4()}"


@pytest.fixture
def schema():
    """Generate a unique schema name for tests."""
    return f"test_batch_exports_{uuid4()}"


@pytest.fixture
def table_name(ateam, interval):
    return f"test_workflow_table_{ateam.pk}_{interval}"


@pytest.fixture
def snowflake_config(database, schema) -> dict[str, str]:
    """Return a Snowflake configuration dictionary to use in tests.

    We set default configuration values to support tests against the Snowflake API
    and tests that mock it.
    """
    warehouse = os.getenv("SNOWFLAKE_WAREHOUSE", "warehouse")
    account = os.getenv("SNOWFLAKE_ACCOUNT", "account")
    role = os.getenv("SNOWFLAKE_ROLE", "role")
    username = os.getenv("SNOWFLAKE_USERNAME", "username")
    password = os.getenv("SNOWFLAKE_PASSWORD", "password")
    private_key = os.getenv("SNOWFLAKE_PRIVATE_KEY")
    private_key_passphrase = os.getenv("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE")

    config = {
        "user": username,
        "warehouse": warehouse,
        "account": account,
        "database": database,
        "schema": schema,
        "role": role,
    }
    if private_key:
        config["private_key"] = private_key
        config["private_key_passphrase"] = private_key_passphrase
        config["authentication_type"] = "keypair"
    elif password:
        config["password"] = password
        config["authentication_type"] = "password"
    else:
        raise ValueError("Either password or private key must be set")
    return config


@pytest_asyncio.fixture
async def snowflake_batch_export(
    ateam, table_name, snowflake_config, interval, exclude_events, temporal_client
) -> AsyncGenerator[BatchExport, None]:
    """Manage BatchExport model (and associated Temporal Schedule) for tests"""
    destination_data = {
        "type": "Snowflake",
        "config": {**snowflake_config, "table_name": table_name, "exclude_events": exclude_events},
    }
    batch_export_data = {
        "name": "my-production-snowflake-export",
        "destination": destination_data,
        "interval": interval,
    }

    batch_export = await acreate_batch_export(
        team_id=ateam.pk,
        name=batch_export_data["name"],
        destination_data=batch_export_data["destination"],
        interval=batch_export_data["interval"],
    )

    yield batch_export

    await adelete_batch_export(batch_export, temporal_client)


@pytest.fixture
def snowflake_cursor(snowflake_config: dict[str, str]):
    """Manage a snowflake cursor that cleans up after we are done."""
    password = None
    private_key = None
    if snowflake_config["authentication_type"] == "keypair":
        if snowflake_config.get("private_key") is None:
            raise ValueError("Private key is required for keypair authentication")

        private_key = load_private_key(snowflake_config["private_key"], snowflake_config["private_key_passphrase"])
    else:
        password = snowflake_config["password"]

    with snowflake.connector.connect(
        user=snowflake_config["user"],
        password=password,
        role=snowflake_config["role"],
        account=snowflake_config["account"],
        warehouse=snowflake_config["warehouse"],
        private_key=private_key,
    ) as connection:
        connection.telemetry_enabled = False
        cursor = connection.cursor()
        cursor.execute(f'CREATE DATABASE "{snowflake_config["database"]}"')
        cursor.execute(f'CREATE SCHEMA "{snowflake_config["database"]}"."{snowflake_config["schema"]}"')
        cursor.execute(f'USE SCHEMA "{snowflake_config["database"]}"."{snowflake_config["schema"]}"')

        yield cursor

        cursor.execute(f'DROP DATABASE IF EXISTS "{snowflake_config["database"]}" CASCADE')


@pytest.fixture
def garbage_jsonl_file():
    """Manage a JSON file with garbage data."""
    with tempfile.NamedTemporaryFile("w+b", suffix=".jsonl", prefix="garbage_") as garbage_jsonl_file:
        garbage_jsonl_file.write(b'{"team_id": totally not an integer}\n')
        garbage_jsonl_file.seek(0)

        yield garbage_jsonl_file.name


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
