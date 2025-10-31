"""Tests for the Postgres source.

These tests use the Postgres database running in the Docker Compose stack.
"""

import uuid
import datetime as dt
from collections.abc import AsyncGenerator
from typing import Any

import pytest

from django.conf import settings

import psycopg
import pytest_asyncio
from psycopg import AsyncConnection, AsyncCursor, sql
from psycopg.rows import TupleRow

from posthog.temporal.data_imports.sources.generated_configs import PostgresSourceConfig
from posthog.temporal.tests.data_imports.conftest import run_external_data_job_workflow

from products.data_warehouse.backend.models import ExternalDataSchema, ExternalDataSource

pytestmark = pytest.mark.usefixtures("minio_client")


POSTGRES_TABLE_NAME = "test_table"

TEST_DATA = [
    (
        1,
        "John Doe",
        "john@example.com",
        dt.datetime(2025, 1, 1, tzinfo=dt.UTC),
        100,
        "[0,2)",
        "[0.1,2.222)",
        '["2025-05-20 00:00:00+00","2025-05-20 01:00:00+00")',
    ),
    (
        2,
        "Jane Smith",
        "jane@example.com",
        dt.datetime(2025, 1, 2, tzinfo=dt.UTC),
        2000000,
        "[-4,-2)",
        "[-4.4,-2.222)",
        '["2025-05-20 00:00:00+00","2025-05-20 01:00:00+00")',
    ),
    (
        3,
        "Bob Wilson",
        "bob@example.com",
        dt.datetime(2025, 1, 3, tzinfo=dt.UTC),
        3409892966,
        "[-6,-4)",
        "[-6.66,-4.44)",
        '["2025-05-20 00:00:00+00","2025-05-20 01:00:00+00")',
    ),
    (
        4,
        "Wob Bilson",
        "wob@example.com",
        dt.datetime(2025, 1, 3, tzinfo=dt.UTC),
        4,
        "[5,7)",
        "[5.5,7.777)",
        None,
    ),
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
                big_int BIGINT,
                int_range INT4RANGE,
                num_range NUMRANGE,
                tstz_range TSTZRANGE NULL
            )
        """).format(full_table_name)
        )

        # Insert test data
        await cursor.executemany(
            sql.SQL(
                "INSERT INTO {} (id, name, email, created_at, big_int, int_range, num_range, tstz_range) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
            ).format(full_table_name),
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
        expected_columns=["id", "name", "email", "created_at", "big_int", "int_range", "num_range", "tstz_range"],
    )

    assert res.results == TEST_DATA


def test_postgresql__source_config_loads():
    job_inputs = {
        "host": "host.com",
        "port": "5432",
        "user": "Username",
        "schema": "schema",
        "database": "database",
        "password": "password",
        "ssh_tunnel": {
            "enabled": False,
            "host": "",
            "port": "",
            "auth_type": {
                "selection": "",
                "username": "",
                "password": "",
                "private_key": "",
                "passphrase": "",
            },
        },
    }
    config = PostgresSourceConfig.from_dict(job_inputs)

    assert config.host == "host.com"
    assert config.port == 5432
    assert config.user == "Username"
    assert config.password == "password"
    assert config.database == "database"
    assert config.ssh_tunnel is not None
    assert config.ssh_tunnel.enabled is False


def test_postgresql_source_config_loads_int_port():
    job_inputs = {
        "host": "host.com",
        "port": 5432,
        "user": "Username",
        "schema": "schema",
        "database": "database",
        "password": "password",
        "ssh_tunnel": {
            "enabled": False,
            "host": "",
            "port": "",
            "auth_type": {
                "selection": "",
                "username": "",
                "password": "",
                "private_key": "",
                "passphrase": "",
            },
        },
    }
    config = PostgresSourceConfig.from_dict(job_inputs)

    assert config.host == "host.com"
    assert config.port == 5432
    assert config.user == "Username"
    assert config.password == "password"
    assert config.database == "database"
    assert config.ssh_tunnel is not None
    assert config.ssh_tunnel.enabled is False


def test_postgresql_source_config_loads_with_ssh_tunnel():
    job_inputs = {
        "host": "host.com",
        "port": "5432",
        "user": "Username",
        "schema": "schema",
        "database": "database",
        "password": "password",
        "ssh_tunnel": {
            "enabled": True,
            "host": "other-host.com",
            "port": "55550",
            "auth_type": {
                "selection": "password",
                "username": "username",
                "password": "password",
                "private_key": "",
                "passphrase": "",
            },
        },
    }
    config = PostgresSourceConfig.from_dict(job_inputs)

    assert config.host == "host.com"
    assert config.port == 5432
    assert config.user == "Username"
    assert config.password == "password"
    assert config.database == "database"
    assert config.ssh_tunnel is not None
    assert config.ssh_tunnel.enabled is True
    assert config.ssh_tunnel.port == 55550
    assert config.ssh_tunnel.auth.type == "password"
    assert config.ssh_tunnel.auth.username == "username"
    assert config.ssh_tunnel.auth.password == "password"
    assert config.ssh_tunnel.host == "other-host.com"


def test_postgresql_source_config_loads_with_nested_dict_enabled_tunnel():
    job_inputs = {
        "host": "host.com",
        "port": 5432,
        "database": "database",
        "user": "Username",
        "password": "password",
        "schema": "schema",
        "ssh_tunnel": {
            "host": "other-host.com",
            "port": "55550",
            "enabled": "True",
            "auth_type": {
                "type": "password",
                "username": "username",
                "password": "password",
            },
        },
    }

    config = PostgresSourceConfig.from_dict(job_inputs)

    assert config.host == "host.com"
    assert config.port == 5432
    assert config.user == "Username"
    assert config.password == "password"
    assert config.database == "database"
    assert config.ssh_tunnel is not None
    assert config.ssh_tunnel.enabled is True
    assert config.ssh_tunnel.host == "other-host.com"
    assert config.ssh_tunnel.port == 55550
    assert config.ssh_tunnel.auth.type == "password"
    assert config.ssh_tunnel.auth.username == "username"
    assert config.ssh_tunnel.auth.password == "password"


def test_postgresql_source_config_loads_with_nested_dict_disabled_tunnel():
    job_inputs = {
        "host": "host.com",
        "port": 5432,
        "database": "database",
        "user": "Username",
        "password": "password",
        "schema": "schema",
        "ssh_tunnel": {
            "host": "",
            "port": "",
            "enabled": False,
            "auth_type": {
                "type": "",
                "username": "",
                "password": "",
                "private_key": "",
                "passphrase": "",
            },
        },
    }

    config = PostgresSourceConfig.from_dict(job_inputs)

    assert config.host == "host.com"
    assert config.port == 5432
    assert config.user == "Username"
    assert config.password == "password"
    assert config.database == "database"
    assert config.ssh_tunnel is not None
    assert config.ssh_tunnel.enabled is False
