import collections.abc
import datetime as dt
import os
import uuid
import warnings

import psycopg2
import pytest
from django.conf import settings
from django.test import override_settings
from psycopg2.extras import RealDictCursor

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
from posthog.warehouse.types import IncrementalFieldType

SKIP_IF_MISSING_POSTGRES_CREDENTIALS = pytest.mark.skipif(
    not (
        os.environ.get("POSTGRES_HOST")
        and os.environ.get("POSTGRES_USER")
        and os.environ.get("POSTGRES_PASSWORD")
        and os.environ.get("POSTGRES_DATABASE")
    ),
    reason="Postgres credentials not set in environment",
)


@pytest.fixture
def postgres_config() -> dict[str, str]:
    """Return a Postgres configuration dictionary to use in tests."""
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    user = os.environ.get("POSTGRES_USER", "postgres")
    password = os.environ.get("POSTGRES_PASSWORD", "")
    database = os.environ.get("POSTGRES_DATABASE", "postgres")
    schema = os.environ.get("POSTGRES_SCHEMA", "public")

    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "database": database,
        "schema": schema,
    }


@pytest.fixture
def postgres_client() -> collections.abc.Generator[psycopg2.extensions.connection, None, None]:
    """Manage a postgres client for testing."""
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    user = os.environ.get("POSTGRES_USER", "postgres")
    password = os.environ.get("POSTGRES_PASSWORD", "")
    database = os.environ.get("POSTGRES_DATABASE", "postgres")

    conn = psycopg2.connect(host=host, port=port, user=user, password=password, dbname=database)

    yield conn

    conn.close()


@pytest.fixture
def postgres_table_integer(postgres_client) -> collections.abc.Generator[str, None, None]:
    """Create a test Postgres table with integer ID field."""
    table_name = f"test_postgres_source_{str(uuid.uuid4()).replace('-', '')}"

    cursor = postgres_client.cursor()
    cursor.execute(
        f"""
        CREATE TABLE {table_name} (
            id INTEGER,
            value TEXT
        )
        """
    )
    cursor.execute(f"INSERT INTO {table_name} (id, value) VALUES (0, 'a'), (1, 'b')")
    postgres_client.commit()

    yield table_name

    try:
        cursor = postgres_client.cursor()
        cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
        postgres_client.commit()
    except Exception as exc:
        warnings.warn(
            f"Failed to clean up table: {table_name} due to '{exc.__class__.__name__}': {str(exc)}", stacklevel=1
        )


@pytest.fixture
def postgres_table_timestamp(postgres_client) -> collections.abc.Generator[str, None, None]:
    """Create a test Postgres table with timestamp ID field."""
    table_name = f"test_postgres_source_{str(uuid.uuid4()).replace('-', '')}"

    cursor = postgres_client.cursor()
    cursor.execute(
        f"""
        CREATE TABLE {table_name} (
            id TIMESTAMP WITH TIME ZONE,
            value TEXT
        )
        """
    )

    first, second = dt.datetime(2025, 1, 1, tzinfo=dt.UTC), dt.datetime(2025, 1, 2, tzinfo=dt.UTC)
    cursor.execute(f"INSERT INTO {table_name} (id, value) VALUES (%s, 'a'), (%s, 'b')", (first, second))
    postgres_client.commit()

    yield table_name

    try:
        cursor = postgres_client.cursor()
        cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
        postgres_client.commit()
    except Exception as exc:
        warnings.warn(
            f"Failed to clean up table: {table_name} due to '{exc.__class__.__name__}': {str(exc)}", stacklevel=1
        )


@pytest.fixture
def postgres_view_integer(postgres_client, postgres_table_integer) -> collections.abc.Generator[str, None, None]:
    """Create a test Postgres view based on the integer ID table."""
    view_name = f"test_postgres_source_view_{str(uuid.uuid4()).replace('-', '')}"

    cursor = postgres_client.cursor()
    cursor.execute(
        f"""
        CREATE VIEW {view_name} AS
        SELECT * FROM {postgres_table_integer}
        """
    )
    postgres_client.commit()

    yield view_name

    try:
        cursor = postgres_client.cursor()
        cursor.execute(f"DROP VIEW IF EXISTS {view_name}")
        postgres_client.commit()
    except Exception as exc:
        warnings.warn(
            f"Failed to clean up view: {view_name} due to '{exc.__class__.__name__}': {str(exc)}", stacklevel=1
        )


@pytest.fixture
def bucket_name(request) -> str:
    """Name for a test MinIO bucket."""
    try:
        return request.param
    except AttributeError:
        return f"test-import-data-{str(uuid.uuid4())}"


@pytest.fixture
def minio_client(bucket_name):
    """Manage a client to interact with a MinIO bucket."""
    import boto3

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


def setup_postgres(
    team: Team,
    postgres_config: dict[str, str],
    postgres_table: str,
    is_incremental: bool,
):
    """Setup PostgreSQL test environment with source, credentials, and table."""
    job_inputs = {
        "host": postgres_config["host"],
        "port": postgres_config["port"],
        "database": postgres_config["database"],
        "user": postgres_config["user"],
        "password": postgres_config["password"],
        "schema": postgres_config["schema"],
    }

    source = ExternalDataSource.objects.create(
        team=team,
        source_id="source_id",
        connection_id="connection_id",
        status=ExternalDataSource.Status.COMPLETED,
        source_type=ExternalDataSource.Type.POSTGRES,
        job_inputs=job_inputs,
    )
    credentials = DataWarehouseCredential.objects.create(
        access_key=str(settings.OBJECT_STORAGE_ACCESS_KEY_ID),
        access_secret=str(settings.OBJECT_STORAGE_SECRET_ACCESS_KEY),
        team=team,
    )

    conn = psycopg2.connect(
        host=postgres_config["host"],
        port=postgres_config["port"],
        user=postgres_config["user"],
        password=postgres_config["password"],
        dbname=postgres_config["database"],
    )
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    cursor.execute(f"""
    SELECT column_name, data_type
    FROM information_schema.columns
    WHERE table_name = '{postgres_table}'
    """)
    columns = cursor.fetchall()

    id_field = next(col for col in columns if col["column_name"] == "id")

    if "int" in id_field["data_type"].lower():
        # PostgreSQL INTEGER maps to Int32 in ClickHouse, not Int64
        clickhouse_type = "Nullable(Int32)"
        incremental_field_type = IncrementalFieldType.Integer
    elif "timestamp" in id_field["data_type"].lower():
        clickhouse_type = "Nullable(DateTime64(6))"
        incremental_field_type = IncrementalFieldType.Timestamp
    else:
        raise ValueError(f"Invalid id field: {id_field}")

    warehouse_table = DataWarehouseTable.objects.create(
        name=postgres_table,
        format="Parquet",
        team=team,
        external_data_source=source,
        external_data_source_id=source.id,
        credential=credentials,
        url_pattern="https://bucket.s3/data/*",
        columns={
            "id": {"hogql": "IntegerDatabaseField", "clickhouse": clickhouse_type, "schema_valid": True},
            "value": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True},
        },
    )
    schema = ExternalDataSchema.objects.create(
        team=team,
        name=postgres_table,
        source=source,
        table=warehouse_table,
        should_sync=True,
        status=ExternalDataSchema.Status.COMPLETED,
        last_synced_at="2024-01-01",
        sync_type=ExternalDataSchema.SyncType.INCREMENTAL
        if is_incremental
        else ExternalDataSchema.SyncType.FULL_REFRESH,
        sync_type_config={
            "incremental_field": "id",
            "incremental_field_type": incremental_field_type,
            "incremental_field_last_value": None,
        }
        if is_incremental
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


@SKIP_IF_MISSING_POSTGRES_CREDENTIALS
@pytest.mark.django_db(transaction=True)
def test_postgres_source_full_refresh_table(
    activity_environment,
    team,
    postgres_config,
    postgres_table_integer,
    bucket_name,
    minio_client,
):
    """Test a full-refresh sync job with Postgres source."""
    inputs = setup_postgres(team, postgres_config, postgres_table_integer, is_incremental=False)

    with override_settings(
        NEW_POSTGRES_SOURCE_TEAM_IDS=[str(team.pk)],
        AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        AIRBYTE_BUCKET_REGION="us-east-1",
        AIRBYTE_BUCKET_DOMAIN="objectstorage:19000",
        BUCKET_URL=f"s3://{bucket_name}",
        BUCKET=bucket_name,
    ):
        activity_environment.run(import_data_activity_sync, inputs)

    objects = minio_client.list_objects_v2(Bucket=bucket_name, Prefix="")
    assert objects.get("KeyCount", 0) > 0

    table = DataWarehouseTable.objects.get(name=postgres_table_integer)
    columns = table.get_columns()
    assert "id" in columns
    assert "value" in columns
    assert columns["id"]["clickhouse"] == "Nullable(Int32)"  # Updated to match the actual type
    assert columns["value"]["clickhouse"] == "Nullable(String)"  # type: ignore

    function_call, context = table.get_function_call()
    query = f"SELECT * FROM {function_call}"
    result = sync_execute(query, args=context.values)
    assert result is not None
    assert len(result) == 2

    ids = []
    values = []
    for row in result:
        ids.append(row[0])
        values.append(row[1])

    assert all(id in ids for id in [0, 1])
    assert all(value in values for value in ["a", "b"])


@SKIP_IF_MISSING_POSTGRES_CREDENTIALS
@pytest.mark.django_db(transaction=True)
def test_postgres_source_full_refresh_view(
    activity_environment,
    team,
    postgres_config,
    postgres_view_integer,
    bucket_name,
    minio_client,
):
    """Test a full-refresh sync job with Postgres view."""
    inputs = setup_postgres(team, postgres_config, postgres_view_integer, is_incremental=False)

    with override_settings(
        NEW_POSTGRES_SOURCE_TEAM_IDS=[str(team.pk)],
        AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        AIRBYTE_BUCKET_REGION="us-east-1",
        AIRBYTE_BUCKET_DOMAIN="objectstorage:19000",
        BUCKET_URL=f"s3://{bucket_name}",
        BUCKET=bucket_name,
    ):
        activity_environment.run(import_data_activity_sync, inputs)

    objects = minio_client.list_objects_v2(Bucket=bucket_name, Prefix="")
    assert objects.get("KeyCount", 0) > 0

    table = DataWarehouseTable.objects.get(name=postgres_view_integer)
    columns = table.get_columns()
    assert "id" in columns
    assert "value" in columns
    assert columns["id"]["clickhouse"] == "Nullable(Int32)"  # Updated to match the actual type
    assert columns["value"]["clickhouse"] == "Nullable(String)"  # type: ignore

    function_call, context = table.get_function_call()
    query = f"SELECT * FROM {function_call}"
    result = sync_execute(query, args=context.values)
    assert result is not None
    assert len(result) == 2

    ids = []
    values = []
    for row in result:
        ids.append(row[0])
        values.append(row[1])

    assert all(id in ids for id in [0, 1])
    assert all(value in values for value in ["a", "b"])


@SKIP_IF_MISSING_POSTGRES_CREDENTIALS
@pytest.mark.django_db(transaction=True)
def test_postgres_source_incremental_integer(
    activity_environment,
    team,
    postgres_client,
    postgres_config,
    postgres_table_integer,
    bucket_name,
    minio_client,
):
    """Test an incremental sync job with Postgres source using integer field."""
    inputs = setup_postgres(team, postgres_config, postgres_table_integer, is_incremental=True)

    with override_settings(
        AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        AIRBYTE_BUCKET_REGION="us-east-1",
        AIRBYTE_BUCKET_DOMAIN="objectstorage:19000",
        BUCKET_URL=f"s3://{bucket_name}",
        BUCKET=bucket_name,
    ):
        activity_environment.run(import_data_activity_sync, inputs)

    objects = minio_client.list_objects_v2(Bucket=bucket_name, Prefix="")
    assert objects.get("KeyCount", 0) > 0

    table = DataWarehouseTable.objects.get(name=postgres_table_integer)
    function_call, context = table.get_function_call()
    query = f"SELECT * FROM {function_call}"
    result = sync_execute(query, args=context.values)
    assert result is not None
    assert len(result) == 2

    schema = ExternalDataSchema.objects.get(name=postgres_table_integer)
    assert schema.sync_type_config["incremental_field_last_value"] == 1

    # Insert new data for incremental sync
    cursor = postgres_client.cursor()
    cursor.execute(f"INSERT INTO {postgres_table_integer} (id, value) VALUES (2, 'c')")
    postgres_client.commit()

    with override_settings(
        AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        AIRBYTE_BUCKET_REGION="us-east-1",
        AIRBYTE_BUCKET_DOMAIN="objectstorage:19000",
        BUCKET_URL=f"s3://{bucket_name}",
        BUCKET=bucket_name,
    ):
        activity_environment.run(import_data_activity_sync, inputs)

    table = DataWarehouseTable.objects.get(name=postgres_table_integer)
    function_call, context = table.get_function_call()
    query = f"SELECT * FROM {function_call}"
    result = sync_execute(query, args=context.values)
    assert result is not None
    assert len(result) == 3

    ids = []
    values = []
    for row in result:
        ids.append(row[0])
        values.append(row[1])

    assert all(id in ids for id in [0, 1, 2])
    assert all(value in values for value in ["a", "b", "c"])

    schema = ExternalDataSchema.objects.get(name=postgres_table_integer)
    assert schema.sync_type_config["incremental_field_last_value"] == 2


@SKIP_IF_MISSING_POSTGRES_CREDENTIALS
@pytest.mark.django_db(transaction=True)
def test_postgres_source_incremental_timestamp(
    activity_environment,
    team,
    postgres_client,
    postgres_config,
    postgres_table_timestamp,
    bucket_name,
    minio_client,
):
    """Test an incremental sync job with Postgres source using timestamp field."""
    inputs = setup_postgres(team, postgres_config, postgres_table_timestamp, is_incremental=True)

    with override_settings(
        AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        AIRBYTE_BUCKET_REGION="us-east-1",
        AIRBYTE_BUCKET_DOMAIN="objectstorage:19000",
        BUCKET_URL=f"s3://{bucket_name}",
        BUCKET=bucket_name,
    ):
        activity_environment.run(import_data_activity_sync, inputs)

    objects = minio_client.list_objects_v2(Bucket=bucket_name, Prefix="")
    assert objects.get("KeyCount", 0) > 0

    table = DataWarehouseTable.objects.get(name=postgres_table_timestamp)
    function_call, context = table.get_function_call()
    query = f"SELECT * FROM {function_call}"
    result = sync_execute(query, args=context.values)
    assert result is not None
    assert len(result) == 2

    schema = ExternalDataSchema.objects.get(name=postgres_table_timestamp)
    assert schema.sync_type_config["incremental_field_last_value"] == "2025-01-02T00:00:00"

    now = dt.datetime(2025, 1, 3, tzinfo=dt.UTC)
    cursor = postgres_client.cursor()
    cursor.execute(f"INSERT INTO {postgres_table_timestamp} (id, value) VALUES (%s, 'c')", (now,))
    postgres_client.commit()

    with override_settings(
        AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        AIRBYTE_BUCKET_REGION="us-east-1",
        AIRBYTE_BUCKET_DOMAIN="objectstorage:19000",
        BUCKET_URL=f"s3://{bucket_name}",
        BUCKET=bucket_name,
    ):
        activity_environment.run(import_data_activity_sync, inputs)

    table = DataWarehouseTable.objects.get(name=postgres_table_timestamp)
    function_call, context = table.get_function_call()
    query = f"SELECT * FROM {function_call}"
    result = sync_execute(query, args=context.values)
    assert result is not None
    assert len(result) == 3

    ids = []
    values = []
    for row in result:
        ids.append(row[0])
        values.append(row[1])

    assert all(
        id in ids
        for id in [dt.datetime(2025, 1, 1, 0, 0), dt.datetime(2025, 1, 2, 0, 0), dt.datetime(2025, 1, 3, 0, 0)]
    )
    assert all(value in values for value in ["a", "b", "c"])

    schema = ExternalDataSchema.objects.get(name=postgres_table_timestamp)
    assert schema.sync_type_config["incremental_field_last_value"] == "2025-01-03T00:00:00"
