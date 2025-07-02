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
import math
import operator
import os
import random
import uuid

import pymysql
import pytest
import structlog
from asgiref.sync import sync_to_async

from posthog.temporal.data_imports.pipelines.mysql.mysql import (
    MySQLSourceConfig,
    _get_partition_settings,
    _get_table_chunk_size,
    _get_table_average_row_size,
    _get_rows_to_sync,
    _build_query,
)
from posthog.temporal.tests.data_imports.conftest import run_external_data_job_workflow
from posthog.warehouse.models import ExternalDataSchema, ExternalDataSource
from posthog.warehouse.types import IncrementalFieldType
from posthog.temporal.data_imports.pipelines.pipeline.consts import DEFAULT_CHUNK_SIZE, DEFAULT_TABLE_SIZE_BYTES

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


@pytest.fixture
def partition_table_name(request) -> str:
    """Return the name of a table to test partitioning."""
    try:
        return request.param
    except AttributeError:
        return "test_partition_table"


@pytest.fixture
def partition_table_rows(request) -> int:
    """Return the number of rows of a table to test partitioning."""
    try:
        return request.param
    except AttributeError:
        return 1_000


@pytest.fixture
def mysql_partition_table(mysql_connection, partition_table_name, partition_table_rows):
    """Create an empty MySQL table and clean it up after the test."""
    conn = mysql_connection
    with conn.cursor() as cursor:
        # Create test table
        cursor.execute(f"""
            CREATE TABLE {partition_table_name} (
                id SERIAL,
                value INT(4) UNSIGNED NOT NULL,
                PRIMARY KEY (id)
            )
        """)

        for _ in range(partition_table_rows):
            value = random.randint(0, 2**32 - 1)
            cursor.execute(
                f"INSERT INTO {partition_table_name} (value) VALUES ({value})",
            )

    conn.commit()

    yield partition_table_name

    with conn.cursor() as cursor:
        # Cleanup
        cursor.execute(f"DROP TABLE {partition_table_name}")
    conn.commit()


@SKIP_IF_MISSING_MYSQL_CREDENTIALS
@pytest.mark.parametrize("partition_table_rows", [0], indirect=True)
def test_get_partition_settings_with_empty_table(mysql_partition_table, mysql_connection):
    with mysql_connection.cursor() as cursor:
        partition_settings = _get_partition_settings(cursor, os.environ["MYSQL_DATABASE"], mysql_partition_table)

    assert partition_settings is None


@SKIP_IF_MISSING_MYSQL_CREDENTIALS
def test_get_partition_settings_with_one_size_partition(mysql_partition_table, mysql_connection, partition_table_rows):
    with mysql_connection.cursor() as cursor:
        partition_settings = _get_partition_settings(
            cursor, os.environ["MYSQL_DATABASE"], mysql_partition_table, partition_size_bytes=1
        )

    assert partition_settings is not None
    assert partition_settings.partition_count == partition_table_rows
    assert partition_settings.partition_size == 1


@pytest.fixture
def external_data_schema_incremental(external_data_source, team):
    schema = ExternalDataSchema.objects.create(
        name=MYSQL_TABLE_NAME,
        team_id=team.pk,
        source_id=external_data_source.pk,
        sync_type="incremental",
        sync_type_config={
            "incremental_field": "id",
            "incremental_field_type": IncrementalFieldType.Integer,
            "incremental_field_last_value": None,
        },
    )
    return schema


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@SKIP_IF_MISSING_MYSQL_CREDENTIALS
async def test_mysql_source_incremental(
    team, mysql_source_table, external_data_source, external_data_schema_incremental, mysql_connection
):
    """Test that an incremental sync works as expected."""
    table_name = f"mysql_{MYSQL_TABLE_NAME}"
    expected_num_rows = len(TEST_DATA)

    res = await run_external_data_job_workflow(
        team=team,
        external_data_source=external_data_source,
        external_data_schema=external_data_schema_incremental,
        table_name=table_name,
        expected_rows_synced=expected_num_rows,
        expected_total_rows=expected_num_rows,
        expected_columns=["id", "name", "email", "created_at", "unsigned_int"],
    )
    assert res.results == TEST_DATA

    NEW_TEST_DATA = [
        (4, "John Doe", "john@example.com", dt.datetime(2025, 1, 1, tzinfo=dt.UTC), 100),
        (5, "Jane Smith", "jane@example.com", dt.datetime(2025, 1, 2, tzinfo=dt.UTC), 2000000),
        (6, "Bob Wilson", "bob@example.com", dt.datetime(2025, 1, 3, tzinfo=dt.UTC), 3409892966),
    ]

    with mysql_connection.cursor() as cursor:
        cursor.executemany(
            f"INSERT INTO {MYSQL_TABLE_NAME} (id, name, email, created_at, unsigned_int) VALUES (%s, %s, %s, %s, %s)",
            NEW_TEST_DATA,
        )
    mysql_connection.commit()

    expected_total_num_rows = expected_num_rows + len(NEW_TEST_DATA)
    res = await run_external_data_job_workflow(
        team=team,
        external_data_source=external_data_source,
        external_data_schema=external_data_schema_incremental,
        table_name=table_name,
        # We use a GTE, so the last id will be re-synced.
        expected_rows_synced=expected_num_rows + 1,
        expected_total_rows=expected_total_num_rows,
        expected_columns=["id", "name", "email", "created_at", "unsigned_int"],
    )
    # Compare sorted results as rows may have been shuffled around, but we only care the data is there,
    # not in which order.
    assert sorted(res.results, key=operator.itemgetter(0)) == sorted(
        TEST_DATA + NEW_TEST_DATA, key=operator.itemgetter(0)
    )


def test_mysql_sql_source_config_loads():
    job_inputs = {
        "host": "host.com",
        "port": "1111",
        "user": "Username",
        "schema": "schema",
        "database": "database",
        "password": "password",
        "using_ssl": False,
    }
    config = MySQLSourceConfig.from_dict(job_inputs)

    assert config.host == "host.com"
    assert config.port == 1111
    assert config.user == "Username"
    assert config.password == "password"
    assert config.database == "database"
    assert config.ssh_tunnel is None
    assert config.using_ssl is False


def test_mysql_source_config_loads_int_port():
    job_inputs = {
        "host": "host.com",
        "port": 1111,
        "user": "Username",
        "schema": "schema",
        "database": "database",
        "password": "password",
    }
    config = MySQLSourceConfig.from_dict(job_inputs)

    assert config.host == "host.com"
    assert config.port == 1111
    assert config.user == "Username"
    assert config.password == "password"
    assert config.database == "database"
    assert config.ssh_tunnel is None
    assert config.using_ssl is True


def test_mysql_source_config_loads_with_ssh_tunnel():
    job_inputs = {
        "host": "host.com",
        "port": "1111",
        "user": "Username",
        "schema": "schema",
        "database": "database",
        "password": "password",
        "ssh_tunnel_host": "other-host.com",
        "ssh_tunnel_enabled": "True",
        "ssh_tunnel_port": "55550",
        "ssh_tunnel_auth_type": "password",
        "ssh_tunnel_auth_type_password": "password",
        "ssh_tunnel_auth_type_username": "username",
    }
    config = MySQLSourceConfig.from_dict(job_inputs)

    assert config.host == "host.com"
    assert config.port == 1111
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


def test_mysql_source_config_loads_with_nested_dict_enabled_tunnel():
    job_inputs = {
        "host": "host.com",
        "port": 1111,
        "database": "database",
        "user": "Username",
        "password": "password",
        "schema": "schema",
        "ssh_tunnel": {
            "host": "other-host.com",
            "port": "55550",
            "enabled": "True",
            "auth": {
                "type": "password",
                "username": "username",
                "password": "password",
            },
        },
    }

    config = MySQLSourceConfig.from_dict(job_inputs)

    assert config.host == "host.com"
    assert config.port == 1111
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


def test_mysql_source_config_loads_with_nested_dict_disabled_tunnel():
    job_inputs = {
        "host": "host.com",
        "port": 1111,
        "database": "database",
        "user": "Username",
        "password": "password",
        "schema": "schema",
        "ssh_tunnel": {
            "host": None,
            "port": None,
            "enabled": False,
            "auth": {
                "type": None,
                "username": None,
                "password": None,
                "private_key": None,
                "passphrase": None,
            },
        },
    }

    config = MySQLSourceConfig.from_dict(job_inputs)

    assert config.host == "host.com"
    assert config.port == 1111
    assert config.user == "Username"
    assert config.password == "password"
    assert config.database == "database"
    assert config.ssh_tunnel is not None
    assert config.ssh_tunnel.enabled is False
    assert config.ssh_tunnel.host is None
    assert config.ssh_tunnel.port is None
    assert config.ssh_tunnel.auth.type is None
    assert config.ssh_tunnel.auth.private_key is None
    assert config.ssh_tunnel.auth.passphrase is None
    assert config.ssh_tunnel.auth.username is None
    assert config.ssh_tunnel.auth.password is None


@pytest.fixture
def mysql_narrow_table(mysql_connection):
    """Create a MySQL table with very small rows (~50 bytes/row)."""
    conn = mysql_connection
    with conn.cursor() as cursor:
        table_name = "test_narrow_chunking"
        # Create test table with small rows
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                id INT,
                name VARCHAR(10),
                flag BOOLEAN
            )
        """)

        # Insert minimal test data
        cursor.executemany(
            f"INSERT INTO {table_name} (id, name, flag) VALUES (%s, %s, %s)",
            [(i, f"u{i}", i % 2 == 0) for i in range(5)],
        )
        conn.commit()

        yield cursor, table_name

        # Cleanup
        cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
        conn.commit()


@pytest.fixture
def mysql_wide_table(mysql_connection):
    """Create a MySQL table with very large rows (~25KB/row)."""
    conn = mysql_connection
    with conn.cursor() as cursor:
        table_name = "test_wide_chunking"
        # Create test table with large rows
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                id INT,
                large_text1 TEXT,
                large_text2 TEXT,
                large_text3 TEXT,
                metadata JSON
            )
        """)

        # Generate large text data (~25KB per row)
        large_text = "A" * 8000  # ~8KB per text field
        metadata = "{" + ", ".join([f'"key{i}": "value{i}"' for i in range(100)]) + "}"  # ~1KB JSON

        cursor.executemany(
            f"INSERT INTO {table_name} (id, large_text1, large_text2, large_text3, metadata) VALUES (%s, %s, %s, %s, %s)",
            [(i, large_text, large_text, large_text, metadata) for i in range(3)],
        )
        conn.commit()

        yield cursor, table_name

        # Cleanup
        cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
        conn.commit()


@pytest.fixture
def mysql_medium_table(mysql_connection):
    """Create a MySQL table with medium-sized rows (~15KB/row)."""
    conn = mysql_connection
    with conn.cursor() as cursor:
        table_name = "test_medium_chunking"
        # Create test table with medium rows
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                id INT,
                data1 TEXT,
                data2 TEXT,
                description VARCHAR(5000)
            )
        """)

        # Generate medium text data (~15KB per row)
        data1 = "B" * 5000  # ~5KB
        data2 = "C" * 5000  # ~5KB
        description = "D" * 4500  # ~4.5KB

        cursor.executemany(
            f"INSERT INTO {table_name} (id, data1, data2, description) VALUES (%s, %s, %s, %s)",
            [(i, data1, data2, description) for i in range(4)],
        )
        conn.commit()

        yield cursor, table_name

        # Cleanup
        cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
        conn.commit()


@pytest.fixture
def mysql_very_big_table(mysql_connection):
    """Create a MySQL table with large rows AND many rows for multi-chunk testing."""
    conn = mysql_connection
    with conn.cursor() as cursor:
        table_name = "test_very_big_chunking"
        # Create test table with large rows
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                id INT,
                huge_data TEXT,
                more_data TEXT
            )
        """)

        # Generate huge text data (~30KB per row)
        huge_data = "X" * 15000  # ~15KB
        more_data = "Y" * 15000  # ~15KB

        # Insert many rows to force multiple chunks
        # With ~30KB/row, chunk size should be ~5000 rows (150MB/30KB)
        # So we'll insert 12000 rows to get ~2.4 chunks
        rows_to_insert = []
        for i in range(12000):
            rows_to_insert.append((i, huge_data, more_data))

            # Insert in batches to avoid memory issues
            if len(rows_to_insert) >= 1000:
                cursor.executemany(
                    f"INSERT INTO {table_name} (id, huge_data, more_data) VALUES (%s, %s, %s)", rows_to_insert
                )
                conn.commit()
                rows_to_insert = []

        # Insert remaining rows
        if rows_to_insert:
            cursor.executemany(
                f"INSERT INTO {table_name} (id, huge_data, more_data) VALUES (%s, %s, %s)", rows_to_insert
            )
            conn.commit()

        yield cursor, table_name

        # Cleanup
        cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
        conn.commit()


@SKIP_IF_MISSING_MYSQL_CREDENTIALS
def test_mysql_narrow_table_chunking(mysql_narrow_table, mysql_config):
    """Test that narrow tables use the full chunk size (20,000 rows)."""

    cursor, table_name = mysql_narrow_table
    logger = structlog.get_logger()

    # Test average row size calculation
    avg_row_size = _get_table_average_row_size(
        cursor, mysql_config["database"], table_name, False, None, None, None, logger
    )

    assert avg_row_size is not None
    assert avg_row_size < 200

    # Test chunk size calculation
    chunk_size = _get_table_chunk_size(cursor, mysql_config["database"], table_name, False, None, None, None, logger)

    # For narrow tables, should use full DEFAULT_CHUNK_SIZE
    assert chunk_size == DEFAULT_CHUNK_SIZE


@SKIP_IF_MISSING_MYSQL_CREDENTIALS
def test_mysql_wide_table_chunking(mysql_wide_table, mysql_config):
    """Test that wide tables use reduced chunk size via dynamic chunking."""

    cursor, table_name = mysql_wide_table
    logger = structlog.get_logger()

    # Test average row size calculation
    avg_row_size = _get_table_average_row_size(
        cursor, mysql_config["database"], table_name, False, None, None, None, logger
    )

    assert avg_row_size is not None
    assert avg_row_size > 20000

    # Test chunk size calculation
    chunk_size = _get_table_chunk_size(cursor, mysql_config["database"], table_name, False, None, None, None, logger)

    # For wide tables, should use reduced chunk size, which is less than DEFAULT_CHUNK_SIZE
    expected_chunk_size = min(int(DEFAULT_TABLE_SIZE_BYTES / avg_row_size), DEFAULT_CHUNK_SIZE)
    assert chunk_size == expected_chunk_size  # make sure the chunk size is the same as the expected chunk size
    assert chunk_size < DEFAULT_CHUNK_SIZE


@SKIP_IF_MISSING_MYSQL_CREDENTIALS
def test_mysql_medium_table_chunking(mysql_medium_table, mysql_config):
    """Test that medium tables use moderately reduced chunk size."""

    cursor, table_name = mysql_medium_table
    logger = structlog.get_logger()

    # Test average row size calculation
    avg_row_size = _get_table_average_row_size(
        cursor, mysql_config["database"], table_name, False, None, None, None, logger
    )

    assert avg_row_size is not None
    assert (
        10000 < avg_row_size < 20000
    )  # little bit more complicated here, but make sure the avg row size is between 10000 and 20000 because the data is generated randomly

    # Test chunk size calculation
    chunk_size = _get_table_chunk_size(cursor, mysql_config["database"], table_name, False, None, None, None, logger)

    # For medium tables, should use moderately reduced chunk size
    expected_chunk_size = min(int(DEFAULT_TABLE_SIZE_BYTES / avg_row_size), DEFAULT_CHUNK_SIZE)
    assert chunk_size == expected_chunk_size
    assert chunk_size < DEFAULT_CHUNK_SIZE
    assert chunk_size > 5000  # make sure its not _too_ small


@SKIP_IF_MISSING_MYSQL_CREDENTIALS
def test_mysql_very_big_table_chunking(mysql_very_big_table, mysql_config):
    """Test that very big tables with many rows use dynamic chunking and process multiple chunks."""

    cursor, table_name = mysql_very_big_table
    logger = structlog.get_logger()

    # Test average row size calculation
    avg_row_size = _get_table_average_row_size(
        cursor, mysql_config["database"], table_name, False, None, None, None, logger
    )

    assert avg_row_size is not None
    assert avg_row_size > 25000  # want them big

    # Test chunk size calculation
    chunk_size = _get_table_chunk_size(cursor, mysql_config["database"], table_name, False, None, None, None, logger)

    # Should use significantly reduced chunk size, which is less than DEFAULT_CHUNK_SIZE
    expected_chunk_size = min(int(DEFAULT_TABLE_SIZE_BYTES / avg_row_size), DEFAULT_CHUNK_SIZE)
    assert chunk_size == expected_chunk_size  # make sure the chunk size is the same as the expected chunk size
    assert chunk_size < 6000  # make sure its smaller

    # Test that we'd process multiple chunks
    inner_query, inner_query_args = _build_query(mysql_config["database"], table_name, False, None, None, None)
    rows_to_sync = _get_rows_to_sync(cursor, inner_query, inner_query_args, logger)

    assert rows_to_sync == 12000  # make sure we inserted 12,000 rows
    expected_chunks = math.ceil(rows_to_sync / chunk_size)
    assert expected_chunks >= 2  # make sure we require multiple chunks

    # Verify memory usage would be reasonable
    memory_per_chunk = chunk_size * avg_row_size
    assert (
        memory_per_chunk <= DEFAULT_TABLE_SIZE_BYTES * 1.1
    )  # make sure the memory per chunk is less than 10% of the table size


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@SKIP_IF_MISSING_MYSQL_CREDENTIALS
async def test_mysql_chunking_end_to_end_wide_table(team, mysql_wide_table, mysql_config):
    """End-to-end test that wide tables are processed with correct chunking."""
    cursor, table_name = mysql_wide_table

    # Create external data source and schema
    source = await sync_to_async(ExternalDataSource.objects.create)(
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        destination_id=str(uuid.uuid4()),
        team=team,
        status="running",
        source_type="MySQL",
        job_inputs=mysql_config,
    )

    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        name=table_name,
        team_id=team.pk,
        source_id=source.pk,
        sync_type="full_refresh",
        sync_type_config={},
    )

    # Run the workflow
    table_name_postgres = f"mysql_{table_name}"
    expected_num_rows = 3  # We inserted 3 rows

    res = await run_external_data_job_workflow(
        team=team,
        external_data_source=source,
        external_data_schema=schema,
        table_name=table_name_postgres,
        expected_rows_synced=expected_num_rows,
        expected_total_rows=expected_num_rows,
        expected_columns=["id", "large_text1", "large_text2", "large_text3", "metadata"],
    )

    # Verify data was processed correctly despite chunking
    assert len(res.results) == expected_num_rows
    # Verify large data was preserved
    for row in res.results:
        assert len(row[1]) == 8000  # large_text1
        assert len(row[2]) == 8000  # large_text2
        assert len(row[3]) == 8000  # large_text3
