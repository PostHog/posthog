import os
import json
import uuid
import datetime as dt
import warnings
import collections.abc

import pytest

from django.conf import settings
from django.test import override_settings

import boto3
from google.cloud import bigquery

from posthog.clickhouse.client import sync_execute
from posthog.models import Team
from posthog.temporal.data_imports.workflow_activities.import_data_sync import (
    ImportDataActivityInputs,
    import_data_activity_sync,
)
from posthog.warehouse.models.credential import DataWarehouseCredential
from posthog.warehouse.models.external_data_job import ExternalDataJob
from posthog.warehouse.models.external_data_schema import ExternalDataSchema
from posthog.warehouse.models.external_data_source import ExternalDataSource
from posthog.warehouse.models.table import DataWarehouseTable
from posthog.warehouse.types import ExternalDataSourceType, IncrementalFieldType

SKIP_IF_MISSING_GOOGLE_APPLICATION_CREDENTIALS = pytest.mark.skipif(
    "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ,
    reason="Google credentials not set in environment",
)


@pytest.fixture
def bigquery_config() -> dict[str, str]:
    """Return a BigQuery configuration dictionary to use in tests."""
    credentials_file_path = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
    with open(credentials_file_path) as f:
        credentials = json.load(f)

    return {
        "project_id": credentials["project_id"],
        "private_key": credentials["private_key"],
        "private_key_id": credentials["private_key_id"],
        "token_uri": credentials["token_uri"],
        "client_email": credentials["client_email"],
    }


@pytest.fixture
def bigquery_client() -> collections.abc.Generator[bigquery.Client, None, None]:
    """Manage a bigquery.Client for testing."""
    client = bigquery.Client()

    yield client

    client.close()


@pytest.fixture
def bigquery_dataset(bigquery_config, bigquery_client) -> collections.abc.Generator[bigquery.Dataset, None, None]:
    """Manage a bigquery dataset for testing.

    We clean up the dataset after every test. Could be quite time expensive, but guarantees a clean slate.
    """
    dataset_id = f"{bigquery_config['project_id']}.ImportDataTest_{str(uuid.uuid4()).replace('-', '')}"

    dataset = bigquery.Dataset(dataset_id)
    dataset = bigquery_client.create_dataset(dataset)

    yield dataset

    try:
        bigquery_client.delete_dataset(dataset_id, delete_contents=True, not_found_ok=True)
    except Exception as exc:
        warnings.warn(
            f"Failed to clean up dataset: {dataset_id} due to '{exc.__class__.__name__}': {str(exc)}", stacklevel=1
        )


@pytest.fixture
def bigquery_table_primary_key(request) -> str:
    """Optionally set a custom primary key on table."""
    try:
        return request.param
    except AttributeError:
        return "id"


@pytest.fixture
def bigquery_table_integer(
    bigquery_config, bigquery_client, bigquery_dataset, bigquery_table_primary_key
) -> collections.abc.Generator[bigquery.Table, None, None]:
    """Manage a bigquery table for testing.

    We clean up the table after every test. Could be quite time expensive, but guarantees a clean slate.
    """
    table_id = f"{bigquery_config['project_id']}.{bigquery_dataset.dataset_id}.test_bigquery_source"
    id_column = bigquery_table_primary_key

    table = bigquery.Table(
        table_id,
        schema=[
            bigquery.SchemaField(name=id_column, field_type="STRING"),
            bigquery.SchemaField(name="incremental", field_type="INT64"),
            bigquery.SchemaField("value", field_type="STRING"),
        ],
    )
    table = bigquery_client.create_table(table)

    job = bigquery_client.query(
        f"INSERT INTO {table.dataset_id}.{table.table_id} ({id_column}, incremental, value) VALUES ('first', 0, 'a'), ('second', 1, 'b')"
    )
    job.result()

    yield table

    try:
        bigquery_client.delete_table(table, not_found_ok=True)
    except Exception as exc:
        warnings.warn(
            f"Failed to clean up table: {table_id} due to '{exc.__class__.__name__}': {str(exc)}", stacklevel=1
        )


@pytest.fixture
def bigquery_table_timestamp(
    bigquery_config, bigquery_client, bigquery_dataset, bigquery_table_primary_key
) -> collections.abc.Generator[bigquery.Table, None, None]:
    """Manage a bigquery table for testing.

    We clean up the table after every test. Could be quite time expensive, but guarantees a clean slate.
    """
    table_id = f"{bigquery_config['project_id']}.{bigquery_dataset.dataset_id}.test_bigquery_source"
    id_column = bigquery_table_primary_key

    table = bigquery.Table(
        table_id,
        schema=[
            bigquery.SchemaField(name=id_column, field_type="STRING"),
            bigquery.SchemaField(name="incremental", field_type="TIMESTAMP"),
            bigquery.SchemaField("value", field_type="STRING"),
        ],
    )
    table = bigquery_client.create_table(table)

    first, second = dt.datetime(2025, 1, 1, tzinfo=dt.UTC), dt.datetime(2025, 1, 2, tzinfo=dt.UTC)
    job = bigquery_client.query(
        f"INSERT INTO {table.dataset_id}.{table.table_id} ({id_column}, incremental, value) VALUES ('first', '{first.isoformat()}', 'a'), ('second', '{second.isoformat()}', 'b')"
    )
    job.result()

    if bigquery_table_primary_key != "id":
        job = bigquery_client.query(
            f"ALTER TABLE {table.dataset_id}.{table.table_id} ADD PRIMARY KEY({id_column}) NOT ENFORCED"
        )
        job.result()

    yield table

    try:
        bigquery_client.delete_table(table, not_found_ok=True)
    except Exception as exc:
        warnings.warn(
            f"Failed to clean up table: {table_id} due to '{exc.__class__.__name__}': {str(exc)}", stacklevel=1
        )


@pytest.fixture
def bigquery_view_integer(
    bigquery_config, bigquery_client, bigquery_dataset, bigquery_table_integer
) -> collections.abc.Generator[bigquery.Table, None, None]:
    """Manage a BigQuery view for testing.

    We clean up the view after every test. Could be quite time expensive, but guarantees a clean slate.
    """
    view_id = f"{bigquery_config['project_id']}.{bigquery_dataset.dataset_id}.test_bigquery_source_view"
    source_id = f"{bigquery_config['project_id']}.{bigquery_table_integer.dataset_id}.{bigquery_table_integer.table_id}"

    table = bigquery.Table(view_id)
    table.view_query = f"SELECT * FROM `{source_id}`"
    table_that_is_actually_a_view = bigquery_client.create_table(table)

    # Just in case you don't believe me.
    assert table_that_is_actually_a_view.table_type == "VIEW"

    yield table_that_is_actually_a_view

    try:
        bigquery_client.delete_table(table_that_is_actually_a_view, not_found_ok=True)
    except Exception as exc:
        warnings.warn(f"Failed to clean up view: {view_id} due to '{exc.__class__.__name__}': {str(exc)}", stacklevel=1)


@pytest.fixture
def bucket_name(request) -> str:
    """Name for a test MinIO bucket."""
    try:
        return request.param
    except AttributeError:
        return f"test-import-data-{str(uuid.uuid4())}"


@pytest.fixture
def minio_client(bucket_name):
    """Manage a client to interact with a MinIO bucket.

    Yields the client after creating a bucket. Upon resuming, we delete
    the contents and the bucket itself.
    """
    session = boto3.Session()
    minio_client = session.client(
        "s3",
        aws_access_key_id="object_storage_root_user",
        aws_secret_access_key="object_storage_root_password",
        endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
    )
    _ = minio_client.create_bucket(Bucket=bucket_name)

    yield minio_client

    response = minio_client.list_objects_v2(Bucket=bucket_name, Prefix="")
    if "Contents" in response:
        for obj in response["Contents"]:
            if "Key" in obj:
                _ = minio_client.delete_object(Bucket=bucket_name, Key=obj["Key"])

    _ = minio_client.delete_bucket(Bucket=bucket_name)


def setup_bigquery(
    team: Team,
    bigquery_config: dict[str, str],
    bigquery_dataset: bigquery.Dataset,
    bigquery_table: bigquery.Table,
    is_incremental: bool,
):
    source = ExternalDataSource.objects.create(
        team=team,
        source_id="source_id",
        connection_id="connection_id",
        status=ExternalDataSource.Status.COMPLETED,
        source_type=ExternalDataSourceType.BIGQUERY,
        job_inputs={
            "dataset_id": bigquery_dataset.dataset_id,
            "temporary_dataset_id": None,
            "using_temporary_dataset": False,
            **bigquery_config,
        },
    )
    credentials = DataWarehouseCredential.objects.create(
        access_key=str(settings.OBJECT_STORAGE_ACCESS_KEY_ID),
        access_secret=str(settings.OBJECT_STORAGE_SECRET_ACCESS_KEY),
        team=team,
    )

    incremental_field = next(field for field in bigquery_table.schema if field.name == "incremental")

    if incremental_field.field_type == "INTEGER":
        clickhouse_type = "Nullable(Int64)"
        incremental_field_type = IncrementalFieldType.Integer
    elif incremental_field.field_type == "TIMESTAMP":
        clickhouse_type = "Nullable(DateTime64(6))"
        incremental_field_type = IncrementalFieldType.Timestamp
    else:
        raise ValueError(f"Invalid id field: {incremental_field}")

    warehouse_table = DataWarehouseTable.objects.create(
        name=bigquery_table.table_id,
        format="Parquet",
        team=team,
        external_data_source=source,
        external_data_source_id=source.id,
        credential=credentials,
        url_pattern="https://bucket.s3/data/*",
        columns={
            "id": {"hogql": "IntegerDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True},
            incremental_field.name: {
                "hogql": "IntegerDatabaseField",
                "clickhouse": clickhouse_type,
                "schema_valid": True,
            },
            "value": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True},
        },
    )
    schema = ExternalDataSchema.objects.create(
        team=team,
        name=bigquery_table.table_id,
        source=source,
        table=warehouse_table,
        should_sync=True,
        status=ExternalDataSchema.Status.COMPLETED,
        last_synced_at="2024-01-01",
        sync_type=ExternalDataSchema.SyncType.INCREMENTAL
        if is_incremental
        else ExternalDataSchema.SyncType.FULL_REFRESH,
        sync_type_config={
            "incremental_field": incremental_field.name,
            "incremental_field_type": incremental_field_type,
            "incremental_field_last_value": None,
        }
        if ExternalDataSchema.SyncType.INCREMENTAL
        else {},
    )

    job = ExternalDataJob.objects.create(
        team=team,
        pipeline=source,
        schema=schema,
        status=ExternalDataJob.Status.RUNNING,
        rows_synced=0,
        workflow_id="some_workflow_id",
        pipeline_version=ExternalDataJob.PipelineVersion.V1,
    )
    return ImportDataActivityInputs(team_id=team.pk, schema_id=schema.pk, source_id=source.pk, run_id=str(job.pk))


@SKIP_IF_MISSING_GOOGLE_APPLICATION_CREDENTIALS
@pytest.mark.django_db(transaction=True)
def test_bigquery_source_full_refresh_table(
    activity_environment,
    team,
    bigquery_client,
    bigquery_config,
    bigquery_dataset,
    bigquery_table_integer,
    bigquery_table_primary_key,
    bucket_name,
    minio_client,
):
    """Test a full-refresh sync job with BigQuery source.

    We generate some data and ensure that running `import_data_activity_sync`
    results in the data loaded in S3, and query-able using ClickHouse table
    function.

    Finally, we assert the values correspond to the ones we have inserted in
    BigQuery.
    """
    inputs = setup_bigquery(team, bigquery_config, bigquery_dataset, bigquery_table_integer, is_incremental=False)

    with override_settings(
        NEW_BIGQUERY_SOURCE_TEAM_IDS=[str(team.pk)],
        AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        AIRBYTE_BUCKET_REGION="us-east-1",
        AIRBYTE_BUCKET_DOMAIN="objectstorage:19000",
        BUCKET_URL=f"s3://{bucket_name}",
        BUCKET_PATH=bucket_name,
    ):
        activity_environment.run(import_data_activity_sync, inputs)

    objects = minio_client.list_objects_v2(Bucket=bucket_name, Prefix="")
    assert objects.get("KeyCount", 0) > 0

    table = DataWarehouseTable.objects.get(name=bigquery_table_integer.table_id)
    columns = table.get_columns()

    assert bigquery_table_primary_key in columns
    assert "incremental" in columns
    assert "value" in columns

    assert columns[bigquery_table_primary_key]["clickhouse"] == "Nullable(String)"  # type: ignore
    assert columns["incremental"]["clickhouse"] == "Nullable(Int64)"  # type: ignore
    assert columns["value"]["clickhouse"] == "Nullable(String)"  # type: ignore

    function_call, context = table.get_function_call()
    query = f"SELECT * FROM {function_call}"
    result = sync_execute(query, args=context.values)
    assert result is not None
    assert len(result) == 2

    incrementals = []
    values = []
    for row in result:
        incrementals.append(row[1])
        values.append(row[2])

    assert all(incremental in incrementals for incremental in [0, 1])
    assert all(value in values for value in ["a", "b"])


@SKIP_IF_MISSING_GOOGLE_APPLICATION_CREDENTIALS
@pytest.mark.django_db(transaction=True)
def test_bigquery_source_full_refresh_view(
    activity_environment,
    team,
    bigquery_client,
    bigquery_config,
    bigquery_dataset,
    bigquery_view_integer,
    bigquery_table_primary_key,
    bucket_name,
    minio_client,
):
    """Test a full-refresh sync job with BigQuery source.

    We generate some data and ensure that running `import_data_activity_sync`
    results in the data loaded in S3, and query-able using ClickHouse table
    function.

    Finally, we assert the values correspond to the ones we have inserted in
    BigQuery.
    """
    inputs = setup_bigquery(team, bigquery_config, bigquery_dataset, bigquery_view_integer, is_incremental=False)

    with override_settings(
        NEW_BIGQUERY_SOURCE_TEAM_IDS=[str(team.pk)],
        AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        AIRBYTE_BUCKET_REGION="us-east-1",
        AIRBYTE_BUCKET_DOMAIN="objectstorage:19000",
        BUCKET_URL=f"s3://{bucket_name}",
        BUCKET_PATH=bucket_name,
    ):
        activity_environment.run(import_data_activity_sync, inputs)

    objects = minio_client.list_objects_v2(Bucket=bucket_name, Prefix="")
    assert objects.get("KeyCount", 0) > 0

    table = DataWarehouseTable.objects.get(name=bigquery_view_integer.table_id)
    columns = table.get_columns()

    assert bigquery_table_primary_key in columns
    assert "incremental" in columns
    assert "value" in columns

    assert columns[bigquery_table_primary_key]["clickhouse"] == "Nullable(String)"  # type: ignore
    assert columns["incremental"]["clickhouse"] == "Nullable(Int64)"  # type: ignore
    assert columns["value"]["clickhouse"] == "Nullable(String)"  # type: ignore

    function_call, context = table.get_function_call()
    query = f"SELECT * FROM {function_call}"
    result = sync_execute(query, args=context.values)
    assert result is not None
    assert len(result) == 2

    incrementals = []
    values = []
    for row in result:
        incrementals.append(row[1])
        values.append(row[2])

    assert all(incremental in incrementals for incremental in [0, 1])
    assert all(value in values for value in ["a", "b"])


@SKIP_IF_MISSING_GOOGLE_APPLICATION_CREDENTIALS
@pytest.mark.django_db(transaction=True)
def test_bigquery_source_incremental_integer(
    activity_environment,
    team,
    bigquery_client,
    bigquery_config,
    bigquery_dataset,
    bigquery_table_integer,
    bigquery_table_primary_key,
    bucket_name,
    minio_client,
):
    """Test an incremental sync job with BigQuery source.

    We generate some data and ensure that running `import_data_activity_sync`
    results in the data loaded in S3, and query-able using ClickHouse table
    function.

    Afterwards, we generate a new incremental value in BigQuery and run
    `import_data_activity_sync` again to ensure that is exported.

    After each activity run, we assert the values correspond to the ones we
    have inserted in BigQuery, and we verify the incremental configuration
    is updated accordingly.
    """
    inputs = setup_bigquery(team, bigquery_config, bigquery_dataset, bigquery_table_integer, is_incremental=True)

    with override_settings(
        AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        AIRBYTE_BUCKET_REGION="us-east-1",
        AIRBYTE_BUCKET_DOMAIN="objectstorage:19000",
        BUCKET_URL=f"s3://{bucket_name}",
        BUCKET_PATH=bucket_name,
    ):
        activity_environment.run(import_data_activity_sync, inputs)

    objects = minio_client.list_objects_v2(Bucket=bucket_name, Prefix="")
    assert objects.get("KeyCount", 0) > 0

    table = DataWarehouseTable.objects.get(name=bigquery_table_integer.table_id)
    columns = table.get_columns()

    assert bigquery_table_primary_key in columns
    assert "incremental" in columns
    assert "value" in columns

    assert columns[bigquery_table_primary_key]["clickhouse"] == "Nullable(String)"  # type: ignore
    assert columns["incremental"]["clickhouse"] == "Nullable(Int64)"  # type: ignore
    assert columns["value"]["clickhouse"] == "Nullable(String)"  # type: ignore

    function_call, context = table.get_function_call()
    query = f"SELECT * FROM {function_call}"
    result = sync_execute(query, args=context.values)
    assert result is not None
    assert len(result) == 2

    incrementals = []
    values = []
    for row in result:
        incrementals.append(row[1])
        values.append(row[2])

    assert all(incremental in incrementals for incremental in [0, 1])
    assert all(value in values for value in ["a", "b"])

    schema = ExternalDataSchema.objects.get(name=bigquery_table_integer.table_id)
    assert schema.sync_type_config["incremental_field_last_value"] == 1

    job = bigquery_client.query(
        f"INSERT INTO {bigquery_table_integer.dataset_id}.{bigquery_table_integer.table_id} ({bigquery_table_primary_key}, incremental, value) VALUES ('third', 2, 'c')"
    )
    _ = job.result()

    with override_settings(
        AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        AIRBYTE_BUCKET_REGION="us-east-1",
        AIRBYTE_BUCKET_DOMAIN="objectstorage:19000",
        BUCKET_URL=f"s3://{bucket_name}",
        BUCKET_PATH=bucket_name,
    ):
        activity_environment.run(import_data_activity_sync, inputs)

    objects = minio_client.list_objects_v2(Bucket=bucket_name, Prefix="")
    assert objects.get("KeyCount", 0) > 0

    table = DataWarehouseTable.objects.get(name=bigquery_table_integer.table_id)
    columns = table.get_columns()

    assert bigquery_table_primary_key in columns
    assert "incremental" in columns
    assert "value" in columns

    assert columns[bigquery_table_primary_key]["clickhouse"] == "Nullable(String)"  # type: ignore
    assert columns["incremental"]["clickhouse"] == "Nullable(Int64)"  # type: ignore
    assert columns["value"]["clickhouse"] == "Nullable(String)"  # type: ignore

    function_call, context = table.get_function_call()
    query = f"SELECT * FROM {function_call}"
    result = sync_execute(query, args=context.values)
    assert result is not None
    assert len(result) == 3

    incrementals = []
    values = []
    for row in result:
        incrementals.append(row[1])
        values.append(row[2])

    assert all(incremental in incrementals for incremental in [0, 1, 2])
    assert all(value in values for value in ["a", "b", "c"])

    schema = ExternalDataSchema.objects.get(name=bigquery_table_integer.table_id)
    assert schema.sync_type_config["incremental_field_last_value"] == 2


@SKIP_IF_MISSING_GOOGLE_APPLICATION_CREDENTIALS
@pytest.mark.django_db(transaction=True)
def test_bigquery_source_incremental_timestamp(
    activity_environment,
    team,
    bigquery_client,
    bigquery_config,
    bigquery_dataset,
    bigquery_table_timestamp,
    bigquery_table_primary_key,
    bucket_name,
    minio_client,
):
    """Test an incremental sync job with BigQuery source.

    We generate some data and ensure that running `import_data_activity_sync`
    results in the data loaded in S3, and query-able using ClickHouse table
    function.

    Afterwards, we generate a new incremental value in BigQuery and run
    `import_data_activity_sync` again to ensure that is exported.

    After each activity run, we assert the values correspond to the ones we
    have inserted in BigQuery, and we verify the incremental configuration
    is updated accordingly.
    """
    inputs = setup_bigquery(team, bigquery_config, bigquery_dataset, bigquery_table_timestamp, is_incremental=True)

    with override_settings(
        AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        AIRBYTE_BUCKET_REGION="us-east-1",
        AIRBYTE_BUCKET_DOMAIN="objectstorage:19000",
        BUCKET_URL=f"s3://{bucket_name}",
        BUCKET_PATH=bucket_name,
    ):
        activity_environment.run(import_data_activity_sync, inputs)

    objects = minio_client.list_objects_v2(Bucket=bucket_name, Prefix="")
    assert objects.get("KeyCount", 0) > 0

    table = DataWarehouseTable.objects.get(name=bigquery_table_timestamp.table_id)
    columns = table.get_columns()

    assert bigquery_table_primary_key in columns
    assert "incremental" in columns
    assert "value" in columns

    assert columns[bigquery_table_primary_key]["clickhouse"] == "Nullable(String)"  # type: ignore
    assert columns["incremental"]["clickhouse"] == "Nullable(DateTime64(6))"  # type: ignore
    assert columns["value"]["clickhouse"] == "Nullable(String)"  # type: ignore

    function_call, context = table.get_function_call()
    query = f"SELECT * FROM {function_call}"
    result = sync_execute(query, args=context.values)
    assert result is not None
    assert len(result) == 2

    timestamps = []
    values = []
    for row in result:
        timestamps.append(row[1])
        values.append(row[2])

    assert all(ts in timestamps for ts in [dt.datetime(2025, 1, 1, 0, 0), dt.datetime(2025, 1, 2, 0, 0)])
    assert all(value in values for value in ["a", "b"])

    schema = ExternalDataSchema.objects.get(name=bigquery_table_timestamp.table_id)
    assert schema.sync_type_config["incremental_field_last_value"] == "2025-01-02T00:00:00"

    now = dt.datetime(2025, 1, 3, tzinfo=dt.UTC)
    job = bigquery_client.query(
        f"INSERT INTO {bigquery_table_timestamp.dataset_id}.{bigquery_table_timestamp.table_id} ({bigquery_table_primary_key}, incremental, value) VALUES ('third', '{now.isoformat()}', 'c')"
    )
    _ = job.result()

    with override_settings(
        AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        AIRBYTE_BUCKET_REGION="us-east-1",
        AIRBYTE_BUCKET_DOMAIN="objectstorage:19000",
        BUCKET_URL=f"s3://{bucket_name}",
        BUCKET_PATH=bucket_name,
    ):
        activity_environment.run(import_data_activity_sync, inputs)

    objects = minio_client.list_objects_v2(Bucket=bucket_name, Prefix="")
    assert objects.get("KeyCount", 0) > 0

    table = DataWarehouseTable.objects.get(name=bigquery_table_timestamp.table_id)
    columns = table.get_columns()

    assert bigquery_table_primary_key in columns
    assert "incremental" in columns
    assert "value" in columns

    assert columns[bigquery_table_primary_key]["clickhouse"] == "Nullable(String)"  # type: ignore
    assert columns["incremental"]["clickhouse"] == "Nullable(DateTime64(6))"  # type: ignore
    assert columns["value"]["clickhouse"] == "Nullable(String)"  # type: ignore

    function_call, context = table.get_function_call()
    query = f"SELECT * FROM {function_call}"
    result = sync_execute(query, args=context.values)
    assert result is not None
    assert len(result) == 3

    timestamps = []
    values = []
    for row in result:
        timestamps.append(row[1])
        values.append(row[2])

    assert all(
        ts in timestamps
        for ts in [dt.datetime(2025, 1, 1, 0, 0), dt.datetime(2025, 1, 2, 0, 0), dt.datetime(2025, 1, 3, 0, 0)]
    )
    assert all(value in values for value in ["a", "b", "c"])

    schema = ExternalDataSchema.objects.get(name=bigquery_table_timestamp.table_id)
    assert schema.sync_type_config["incremental_field_last_value"] == "2025-01-03T00:00:00"


@SKIP_IF_MISSING_GOOGLE_APPLICATION_CREDENTIALS
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("bigquery_table_primary_key", ["test_pk"], indirect=True)
def test_bigquery_source_incremental_custom_primary_key(
    activity_environment,
    team,
    bigquery_client,
    bigquery_config,
    bigquery_dataset,
    bigquery_table_timestamp,
    bigquery_table_primary_key,
    bucket_name,
    minio_client,
):
    """Test an incremental sync job with BigQuery source.

    We generate some data and ensure that running `import_data_activity_sync`
    results in the data loaded in S3, and query-able using ClickHouse table
    function.

    Afterwards, we generate a new incremental value in BigQuery and run
    `import_data_activity_sync` again to ensure that is exported.

    After each activity run, we assert the values correspond to the ones we
    have inserted in BigQuery, and we verify the incremental configuration
    is updated accordingly.
    """
    inputs = setup_bigquery(team, bigquery_config, bigquery_dataset, bigquery_table_timestamp, is_incremental=True)

    with override_settings(
        AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        AIRBYTE_BUCKET_REGION="us-east-1",
        AIRBYTE_BUCKET_DOMAIN="objectstorage:19000",
        BUCKET_URL=f"s3://{bucket_name}",
        BUCKET_PATH=bucket_name,
    ):
        activity_environment.run(import_data_activity_sync, inputs)

    objects = minio_client.list_objects_v2(Bucket=bucket_name, Prefix="")
    assert objects.get("KeyCount", 0) > 0

    table = DataWarehouseTable.objects.get(name=bigquery_table_timestamp.table_id)
    columns = table.get_columns()

    assert bigquery_table_primary_key in columns
    assert "incremental" in columns
    assert "value" in columns

    assert columns[bigquery_table_primary_key]["clickhouse"] == "Nullable(String)"  # type: ignore
    assert columns["incremental"]["clickhouse"] == "Nullable(DateTime64(6))"  # type: ignore
    assert columns["value"]["clickhouse"] == "Nullable(String)"  # type: ignore

    function_call, context = table.get_function_call()
    query = f"SELECT * FROM {function_call}"
    result = sync_execute(query, args=context.values)
    assert result is not None
    assert len(result) == 2

    timestamps = []
    values = []
    for row in result:
        timestamps.append(row[1])
        values.append(row[2])

    assert all(ts in timestamps for ts in [dt.datetime(2025, 1, 1, 0, 0), dt.datetime(2025, 1, 2, 0, 0)])
    assert all(value in values for value in ["a", "b"])

    schema = ExternalDataSchema.objects.get(name=bigquery_table_timestamp.table_id)
    assert schema.sync_type_config["incremental_field_last_value"] == "2025-01-02T00:00:00"

    now = dt.datetime(2025, 1, 3, tzinfo=dt.UTC)
    job = bigquery_client.query(
        f"INSERT INTO {bigquery_table_timestamp.dataset_id}.{bigquery_table_timestamp.table_id} ({bigquery_table_primary_key}, incremental, value) VALUES ('third', '{now.isoformat()}', 'c')"
    )
    _ = job.result()

    with override_settings(
        AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        AIRBYTE_BUCKET_REGION="us-east-1",
        AIRBYTE_BUCKET_DOMAIN="objectstorage:19000",
        BUCKET_URL=f"s3://{bucket_name}",
        BUCKET_PATH=bucket_name,
    ):
        activity_environment.run(import_data_activity_sync, inputs)

    objects = minio_client.list_objects_v2(Bucket=bucket_name, Prefix="")
    assert objects.get("KeyCount", 0) > 0

    table = DataWarehouseTable.objects.get(name=bigquery_table_timestamp.table_id)
    columns = table.get_columns()

    assert bigquery_table_primary_key in columns
    assert "incremental" in columns
    assert "value" in columns

    assert columns[bigquery_table_primary_key]["clickhouse"] == "Nullable(String)"  # type: ignore
    assert columns["incremental"]["clickhouse"] == "Nullable(DateTime64(6))"  # type: ignore
    assert columns["value"]["clickhouse"] == "Nullable(String)"  # type: ignore

    function_call, context = table.get_function_call()
    query = f"SELECT * FROM {function_call}"
    result = sync_execute(query, args=context.values)
    assert result is not None
    assert len(result) == 3

    timestamps = []
    values = []
    for row in result:
        timestamps.append(row[1])
        values.append(row[2])

    assert all(
        ts in timestamps
        for ts in [dt.datetime(2025, 1, 1, 0, 0), dt.datetime(2025, 1, 2, 0, 0), dt.datetime(2025, 1, 3, 0, 0)]
    )
    assert all(value in values for value in ["a", "b", "c"])

    schema = ExternalDataSchema.objects.get(name=bigquery_table_timestamp.table_id)
    assert schema.sync_type_config["incremental_field_last_value"] == "2025-01-03T00:00:00"
