"""Tests for the Postgres source.

These tests use the Postgres database running in the Docker Compose stack.
"""

import datetime as dt
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import psycopg
import pytest
import pytest_asyncio
from django.conf import settings
from psycopg import AsyncConnection, AsyncCursor, sql
from psycopg.rows import TupleRow

from posthog.temporal.tests.data_imports.conftest import run_external_data_job_workflow
from posthog.warehouse.models import ExternalDataSchema, ExternalDataSource

pytestmark = pytest.mark.usefixtures("minio_client")


POSTGRES_TABLE_NAME = "test_table"

TEST_DATA = [
    (1, "John Doe", "john@example.com", dt.datetime(2025, 1, 1, tzinfo=dt.UTC), 100),
    (2, "Jane Smith", "jane@example.com", dt.datetime(2025, 1, 2, tzinfo=dt.UTC), 2000000),
    (3, "Bob Wilson", "bob@example.com", dt.datetime(2025, 1, 3, tzinfo=dt.UTC), 3409892966),
]


@pytest.fixture
def postgres_config() -> dict[str, Any]:
    return {
        "user": settings.PG_USER,
        "password": settings.PG_PASSWORD,
        "database": "data_imports_test_database",
        "schema": "data_imports_test_schema",
        "host": settings.PG_HOST,
        "port": int(settings.PG_PORT),
    }


@pytest_asyncio.fixture
async def postgres_connection(
    postgres_config: dict[str, Any], setup_postgres_test_db: None
) -> AsyncGenerator[AsyncConnection, None]:
    connection = await psycopg.AsyncConnection.connect(
        host=postgres_config["host"],
        port=postgres_config["port"],
        dbname=postgres_config["database"],
        user=postgres_config["user"],
        password=postgres_config["password"],
        autocommit=True,
    )

    yield connection

    await connection.close()


@pytest_asyncio.fixture
async def postgres_source_table(
    postgres_connection: AsyncConnection, postgres_config: dict[str, Any]
) -> AsyncGenerator[AsyncCursor[TupleRow], None]:
    """Create a Postgres table with test data and clean it up after the test."""
    async with postgres_connection.cursor() as cursor:
        full_table_name = sql.Identifier(postgres_config["schema"], POSTGRES_TABLE_NAME)
        # Create test table
        await cursor.execute(
            sql.SQL("""
            CREATE TABLE IF NOT EXISTS {} (
                id INTEGER,
                name VARCHAR(255),
                email VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                big_int BIGINT
            )
        """).format(full_table_name)
        )

        # Insert test data
        await cursor.executemany(
            sql.SQL("INSERT INTO {} (id, name, email, created_at, big_int) VALUES (%s, %s, %s, %s, %s)").format(
                full_table_name
            ),
            TEST_DATA,
        )

    yield cursor

    # Cleanup
    async with postgres_connection.cursor() as cursor:
        await cursor.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(full_table_name))


@pytest.fixture
def external_data_source(postgres_config: dict[str, Any], team) -> ExternalDataSource:
    source = ExternalDataSource.objects.create(
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        destination_id=str(uuid.uuid4()),
        team=team,
        status="running",
        source_type="Postgres",
        job_inputs=postgres_config,
    )
    return source


@pytest.fixture
def external_data_schema_full_refresh(external_data_source: ExternalDataSource, team) -> ExternalDataSchema:
    schema = ExternalDataSchema.objects.create(
        name=POSTGRES_TABLE_NAME,
        team_id=team.pk,
        source_id=external_data_source.pk,
        sync_type="full_refresh",
        sync_type_config={},
    )
    return schema


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_postgres_source_full_refresh(
    team,
    postgres_source_table: AsyncCursor[TupleRow],
    external_data_source: ExternalDataSource,
    external_data_schema_full_refresh: ExternalDataSchema,
):
    """Test that a full refresh sync works as expected."""
    table_name = f"postgres_{POSTGRES_TABLE_NAME}"
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

    assert res.results == TEST_DATA
