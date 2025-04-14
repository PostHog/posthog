"""Tests for the Microsoft SQL Server source.

NOTE: These tests require a Microsoft SQL Server to be running somewhere (for example, on Azure).
Therefore these tests will only run if the required environment variables are set.

You can run these tests using:

```
OBJECT_STORAGE_ENDPOINT=http://localhost:19000 \
    MSSQL_HOST=localhost \
    MSSQL_USER=username \
    MSSQL_PASSWORD=password \
    MSSQL_DATABASE=database_name \
    pytest posthog/temporal/tests/data_imports/test_mssql_source.py
```
"""

import datetime as dt
import os
import uuid
from collections.abc import Generator
from typing import Any

import pymssql
import pytest

from posthog.temporal.tests.data_imports.conftest import run_external_data_job_workflow
from posthog.warehouse.models import ExternalDataSchema, ExternalDataSource

pytestmark = pytest.mark.usefixtures("minio_client")

REQUIRED_ENV_VARS = (
    "MSSQL_HOST",
    "MSSQL_USER",
    "MSSQL_PASSWORD",
    "MSSQL_DATABASE",
)

MSSQL_TABLE_NAME = "test_table"

TEST_DATA = [
    (1, "John Doe", "john@example.com", dt.datetime(2025, 1, 1, tzinfo=dt.UTC), 100),
    (2, "Jane Smith", "jane@example.com", dt.datetime(2025, 1, 2, tzinfo=dt.UTC), 2000000),
    (3, "Bob Wilson", "bob@example.com", dt.datetime(2025, 1, 3, tzinfo=dt.UTC), 3409892966),
]


def mssql_env_vars_are_set() -> bool:
    if not all(env_var in os.environ for env_var in REQUIRED_ENV_VARS):
        return False
    return True


SKIP_IF_MISSING_MSSQL_CREDENTIALS = pytest.mark.skipif(
    not mssql_env_vars_are_set(),
    reason="MSSQL required env vars are not set",
)


@pytest.fixture
def mssql_config() -> dict[str, Any]:
    return {
        "user": os.environ["MSSQL_USER"],
        "password": os.environ["MSSQL_PASSWORD"],
        "database": os.environ["MSSQL_DATABASE"],
        "schema": os.environ.get("MSSQL_SCHEMA", "dbo"),
        "host": os.environ["MSSQL_HOST"],
        "port": int(os.environ.get("MSSQL_PORT", 1433)),
    }


@pytest.fixture
def mssql_connection(mssql_config: dict[str, Any]) -> Generator[pymssql.Connection, None, None]:
    connection = pymssql.connect(
        server=mssql_config["host"],
        port=mssql_config["port"],
        database=mssql_config["database"],
        user=mssql_config["user"],
        password=mssql_config["password"],
    )

    yield connection
    connection.close()


@pytest.fixture
def mssql_source_table(
    mssql_connection: pymssql.Connection, mssql_config: dict[str, Any]
) -> Generator[pymssql.Cursor, None, None]:
    """Create a MS SQL Server table with test data and clean it up after the test."""
    cursor = mssql_connection.cursor()
    full_table_name = f"[{mssql_config['schema']}].[{MSSQL_TABLE_NAME}]"

    # Create test table
    cursor.execute(f"""
        IF NOT EXISTS (
            SELECT *
            FROM sys.tables t
            JOIN sys.schemas s ON t.schema_id = s.schema_id
            WHERE s.name = '{mssql_config['schema']}'
            AND t.name = '{MSSQL_TABLE_NAME}'
        )
        BEGIN
            CREATE TABLE {full_table_name} (
                id INTEGER,
                name NVARCHAR(255),
                email NVARCHAR(255),
                created_at DATETIME2 DEFAULT GETUTCDATE(),
                big_int BIGINT
            )
        END
    """)

    # Insert test data
    for row in TEST_DATA:
        cursor.execute(
            f"INSERT INTO {full_table_name} (id, name, email, created_at, big_int) VALUES (%d, %s, %s, %s, %d)", row
        )
    mssql_connection.commit()

    yield cursor

    # Cleanup
    cursor.execute(f"DROP TABLE IF EXISTS {full_table_name}")
    mssql_connection.commit()
    cursor.close()


@pytest.fixture
def external_data_source(mssql_config: dict[str, Any], team) -> ExternalDataSource:
    source = ExternalDataSource.objects.create(
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        destination_id=str(uuid.uuid4()),
        team=team,
        status="running",
        source_type="MSSQL",
        job_inputs=mssql_config,
    )
    return source


@pytest.fixture
def external_data_schema_full_refresh(external_data_source: ExternalDataSource, team) -> ExternalDataSchema:
    schema = ExternalDataSchema.objects.create(
        name=MSSQL_TABLE_NAME,
        team_id=team.pk,
        source_id=external_data_source.pk,
        sync_type="full_refresh",
        sync_type_config={},
    )
    return schema


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@SKIP_IF_MISSING_MSSQL_CREDENTIALS
async def test_mssql_source_full_refresh(
    team,
    mssql_source_table: pymssql.Cursor,
    external_data_source: ExternalDataSource,
    external_data_schema_full_refresh: ExternalDataSchema,
):
    """Test that a full refresh sync works as expected."""
    table_name = f"mssql_{MSSQL_TABLE_NAME}"
    expected_num_rows = len(TEST_DATA)

    res = await run_external_data_job_workflow(
        team=team,
        external_data_source=external_data_source,
        external_data_schema=external_data_schema_full_refresh,
        table_name=table_name,
        expected_rows_synced=expected_num_rows,
        expected_total_rows=expected_num_rows,
        expected_columns=["id", "name", "email", "created_at", "big_int"],
    )

    assert list(res.results) == TEST_DATA
