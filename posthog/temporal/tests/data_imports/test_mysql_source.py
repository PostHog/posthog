"""Tests for the MySQL source.

NOTE: These tests require a MySQL server to be running locally (or somewhere else).
Therefore these tests will only run if the required environment variables are set.

You can run a local MySQL server using Docker:

```
docker run -d --name mysql-test -e MYSQL_ROOT_PASSWORD=root -e MYSQL_DATABASE=test -p 3306:3306 mysql:9.2
```

Then you can run these tests using:

```
OBJECT_STORAGE_ENDPOINT=http://localhost:19000 \
    MYSQL_HOST=localhost \
    MYSQL_USER=root \
    MYSQL_PASSWORD=root \
    MYSQL_DATABASE=test \
    pytest posthog/temporal/tests/data_imports/test_mysql_source.py
```

"""

import datetime as dt
import os
import uuid

import pymysql
import pytest

from posthog.temporal.tests.data_imports.conftest import run_external_data_job_workflow
from posthog.warehouse.models import ExternalDataSchema, ExternalDataSource

pytestmark = pytest.mark.usefixtures("minio_client")

REQUIRED_ENV_VARS = (
    "MYSQL_HOST",
    "MYSQL_USER",
    "MYSQL_PASSWORD",
    "MYSQL_DATABASE",
)

MYSQL_TABLE_NAME = "test_table"

TEST_DATA = [
    (1, "John Doe", "john@example.com", dt.datetime(2025, 1, 1, tzinfo=dt.UTC), 100),
    (2, "Jane Smith", "jane@example.com", dt.datetime(2025, 1, 2, tzinfo=dt.UTC), 2000000),
    (3, "Bob Wilson", "bob@example.com", dt.datetime(2025, 1, 3, tzinfo=dt.UTC), 3409892966),
]


def mysql_env_vars_are_set():
    if not all(env_var in os.environ for env_var in REQUIRED_ENV_VARS):
        return False
    return True


SKIP_IF_MISSING_MYSQL_CREDENTIALS = pytest.mark.skipif(
    not mysql_env_vars_are_set(),
    reason="MySQL required env vars are not set",
)


@pytest.fixture
def mysql_config():
    return {
        "host": os.environ["MYSQL_HOST"],
        "port": os.environ.get("MYSQL_PORT", 3306),
        "user": os.environ["MYSQL_USER"],
        "password": os.environ["MYSQL_PASSWORD"],
        "database": os.environ["MYSQL_DATABASE"],
        # TODO: I don't think this is needed
        "schema": os.environ["MYSQL_DATABASE"],
        "using_ssl": False,
    }


@pytest.fixture
def mysql_connection(mysql_config):
    with pymysql.connect(
        host=mysql_config["host"],
        port=mysql_config["port"],
        database=mysql_config["database"],
        user=mysql_config["user"],
        password=mysql_config["password"],
        connect_timeout=5,
    ) as connection:
        yield connection


@pytest.fixture
def mysql_source_table(mysql_connection):
    """Create a MySQL table with test data and clean it up after the test."""
    conn = mysql_connection
    with conn.cursor() as cursor:
        # Create test table
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {MYSQL_TABLE_NAME} (
                id INT,
                name VARCHAR(255),
                email VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                unsigned_int INT UNSIGNED
            )
        """)

        # Insert test data
        cursor.executemany(
            f"INSERT INTO {MYSQL_TABLE_NAME} (id, name, email, created_at, unsigned_int) VALUES (%s, %s, %s, %s, %s)",
            TEST_DATA,
        )
        conn.commit()

        yield cursor

        # Cleanup
        cursor.execute(f"DROP TABLE IF EXISTS {MYSQL_TABLE_NAME}")
        conn.commit()


@pytest.fixture
def external_data_source(mysql_config, team):
    source = ExternalDataSource.objects.create(
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        destination_id=str(uuid.uuid4()),
        team=team,
        status="running",
        source_type="MySQL",
        job_inputs=mysql_config,
    )
    return source


@pytest.fixture
def external_data_schema_full_refresh(external_data_source, team):
    schema = ExternalDataSchema.objects.create(
        name=MYSQL_TABLE_NAME,
        team_id=team.pk,
        source_id=external_data_source.pk,
        sync_type="full_refresh",
        sync_type_config={},
    )
    return schema


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@SKIP_IF_MISSING_MYSQL_CREDENTIALS
async def test_mysql_source_full_refresh(
    team, mysql_source_table, external_data_source, external_data_schema_full_refresh
):
    """Test that a full refresh sync works as expected."""
    table_name = f"mysql_{MYSQL_TABLE_NAME}"
    expected_num_rows = len(TEST_DATA)

    res = await run_external_data_job_workflow(
        team=team,
        external_data_source=external_data_source,
        external_data_schema=external_data_schema_full_refresh,
        table_name=table_name,
        expected_rows_synced=expected_num_rows,
        expected_total_rows=expected_num_rows,
        expected_columns=["id", "name", "email", "created_at", "unsigned_int"],
    )

    assert res.results == TEST_DATA
