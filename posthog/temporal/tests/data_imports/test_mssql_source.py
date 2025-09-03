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

(From my testing on Azure, the connection often fails the first time, but waiting for a bit and retrying works.
This might be due to the fact that I am using a free tier of Azure SQL Database which might need a bit of time to wake up.)
"""

import os
import uuid
import datetime as dt
import operator
from collections.abc import Generator
from decimal import Decimal
from typing import Any

import pytest

import pytz
import pymssql
import structlog

from posthog.temporal.data_imports.sources.mssql.mssql import _get_table_average_row_size, _get_table_stats
from posthog.temporal.tests.data_imports.conftest import run_external_data_job_workflow
from posthog.warehouse.models import ExternalDataSchema, ExternalDataSource
from posthog.warehouse.types import IncrementalFieldType

pytestmark = pytest.mark.usefixtures("minio_client")

REQUIRED_ENV_VARS = (
    "MSSQL_HOST",
    "MSSQL_USER",
    "MSSQL_PASSWORD",
    "MSSQL_DATABASE",
)

MSSQL_TABLE_NAME = "test_table"

TEST_DATA = [
    (
        1,
        "John Doe",
        "john@example.com",
        dt.datetime(2025, 1, 1, tzinfo=pytz.UTC),
        100,
        '{"key":"value"}',
        True,
        Decimal("13.33"),
        Decimal("19.99"),
        17678785.785690,
    ),
    (
        2,
        "Jane Smith",
        "jane@example.com",
        dt.datetime(2025, 1, 2, tzinfo=pytz.UTC),
        2000000,
        '{"num":10.5}',
        False,
        Decimal("10.5"),
        Decimal("10.5"),
        478756.0,
    ),
    (
        3,
        "Bob Wilson",
        "bob@example.com",
        dt.datetime(2025, 1, 3, tzinfo=pytz.UTC),
        3409892966,
        '{"key":{"nested":"value"}}',
        True,
        Decimal("10.5"),
        Decimal("10.5"),
        -9579990.124,
    ),
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
    with pymssql.connect(
        server=mssql_config["host"],
        port=mssql_config["port"],
        database=mssql_config["database"],
        user=mssql_config["user"],
        password=mssql_config["password"],
        login_timeout=5,
    ) as connection:
        yield connection


def _insert_test_data(cursor: pymssql.Cursor, table_name: str, data: list[tuple[Any, ...]]) -> None:
    for row in data:
        cursor.execute(
            f"INSERT INTO {table_name} (uid, name, email, created_at, big_int, json_data, active, decimal_data, price, float_data) VALUES (%d, %s, %s, %s, %d, %s, %d, %s, %s, %s)",
            row,
        )
    cursor.connection.commit()


@pytest.fixture
def mssql_source_table(
    mssql_connection: pymssql.Connection, mssql_config: dict[str, Any]
) -> Generator[pymssql.Cursor, None, None]:
    """Create a MS SQL Server table with test data and clean it up after the test."""
    with mssql_connection.cursor() as cursor:
        full_table_name = f"[{mssql_config['schema']}].[{MSSQL_TABLE_NAME}]"

        try:
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
                        uid INTEGER PRIMARY KEY,
                        name NVARCHAR(255),
                        email NVARCHAR(255),
                        created_at DATETIME2 DEFAULT GETUTCDATE(),
                        big_int BIGINT,
                        json_data JSON,
                        active BIT,
                        decimal_data DECIMAL(10, 2),
                        price MONEY,
                        float_data FLOAT
                    )
                END
            """)
            mssql_connection.commit()

            # Insert test data
            _insert_test_data(cursor=cursor, table_name=full_table_name, data=TEST_DATA)

            yield cursor

        finally:
            # Cleanup
            cursor.execute(f"DROP TABLE IF EXISTS {full_table_name}")
            mssql_connection.commit()


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


@pytest.fixture
def external_data_schema_incremental(external_data_source: ExternalDataSource, team) -> ExternalDataSchema:
    schema = ExternalDataSchema.objects.create(
        name=MSSQL_TABLE_NAME,
        team_id=team.pk,
        source_id=external_data_source.pk,
        sync_type="incremental",
        sync_type_config={
            "incremental_field": "uid",
            "incremental_field_type": "integer",
            "incremental_field_last_value": None,
        },
    )
    return schema


@pytest.fixture
def external_data_schema_incremental_using_created_at_column(
    external_data_source: ExternalDataSource, team
) -> ExternalDataSchema:
    schema = ExternalDataSchema.objects.create(
        name=MSSQL_TABLE_NAME,
        team_id=team.pk,
        source_id=external_data_source.pk,
        sync_type="incremental",
        sync_type_config={
            "incremental_field": "created_at",
            "incremental_field_type": "datetime",
            "incremental_field_last_value": None,
        },
    )
    return schema


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@SKIP_IF_MISSING_MSSQL_CREDENTIALS
class TestEndToEndWorkflow:
    async def test_full_refresh(
        self,
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
            expected_columns=[
                "uid",
                "name",
                "email",
                "created_at",
                "big_int",
                "json_data",
                "active",
                "decimal_data",
                "price",
                "float_data",
            ],
        )

        assert list(res.results) == TEST_DATA

    async def test_incremental(
        self,
        team,
        mssql_source_table: pymssql.Cursor,
        external_data_source: ExternalDataSource,
        external_data_schema_incremental: ExternalDataSchema,
    ):
        """Test that an incremental sync works as expected."""
        table_name = f"mssql_{MSSQL_TABLE_NAME}"
        expected_num_rows = len(TEST_DATA)

        res = await run_external_data_job_workflow(
            team=team,
            external_data_source=external_data_source,
            external_data_schema=external_data_schema_incremental,
            table_name=table_name,
            expected_rows_synced=expected_num_rows,
            expected_total_rows=expected_num_rows,
            expected_columns=[
                "uid",
                "name",
                "email",
                "created_at",
                "big_int",
                "json_data",
                "active",
                "decimal_data",
                "price",
                "float_data",
            ],
        )

        assert list(res.results) == TEST_DATA

        # insert new data to be synced on next incremental run
        NEW_TEST_DATA = [
            (
                4,
                "Mo Doe",
                "mo@example.com",
                dt.datetime(2025, 1, 4, tzinfo=pytz.UTC),
                999999999,
                '{"key":null}',
                True,
                Decimal("1300.33"),
                Decimal("199.99"),
                17678785.0,
            ),
        ]

        _insert_test_data(cursor=mssql_source_table, table_name=MSSQL_TABLE_NAME, data=NEW_TEST_DATA)
        expected_total_num_rows = expected_num_rows + len(NEW_TEST_DATA)

        res = await run_external_data_job_workflow(
            team=team,
            external_data_source=external_data_source,
            external_data_schema=external_data_schema_incremental,
            table_name=table_name,
            expected_rows_synced=len(NEW_TEST_DATA),
            expected_total_rows=expected_total_num_rows,
            expected_columns=[
                "uid",
                "name",
                "email",
                "created_at",
                "big_int",
                "json_data",
                "active",
                "decimal_data",
                "price",
                "float_data",
            ],
        )

        # Compare sorted results as rows may have been shuffled around, but we only care the data is there,
        # not in which order.
        assert sorted(res.results, key=operator.itemgetter(0)) == sorted(
            TEST_DATA + NEW_TEST_DATA, key=operator.itemgetter(0)
        )

    async def test_incremental_using_created_at_column(
        self,
        team,
        mssql_source_table: pymssql.Cursor,
        external_data_source: ExternalDataSource,
        external_data_schema_incremental_using_created_at_column: ExternalDataSchema,
    ):
        """Test that an incremental sync works as expected when using the `created_at` column as the incremental field."""
        table_name = f"mssql_{MSSQL_TABLE_NAME}"
        expected_num_rows = len(TEST_DATA)

        res = await run_external_data_job_workflow(
            team=team,
            external_data_source=external_data_source,
            external_data_schema=external_data_schema_incremental_using_created_at_column,
            table_name=table_name,
            expected_rows_synced=expected_num_rows,
            expected_total_rows=expected_num_rows,
            expected_columns=[
                "uid",
                "name",
                "email",
                "created_at",
                "big_int",
                "json_data",
                "active",
                "decimal_data",
                "price",
                "float_data",
            ],
        )

        assert list(res.results) == TEST_DATA

        # insert new data to be synced on next incremental run
        NEW_TEST_DATA = [
            (
                4,
                "Mo Doe",
                "mo@example.com",
                dt.datetime(2025, 1, 4, tzinfo=pytz.UTC),
                999999999,
                '{"key":null}',
                True,
                Decimal("1300.33"),
                Decimal("199.99"),
                17678785.0,
            ),
        ]

        _insert_test_data(cursor=mssql_source_table, table_name=MSSQL_TABLE_NAME, data=NEW_TEST_DATA)
        expected_total_num_rows = expected_num_rows + len(NEW_TEST_DATA)

        res = await run_external_data_job_workflow(
            team=team,
            external_data_source=external_data_source,
            external_data_schema=external_data_schema_incremental_using_created_at_column,
            table_name=table_name,
            expected_rows_synced=len(NEW_TEST_DATA),
            expected_total_rows=expected_total_num_rows,
            expected_columns=[
                "uid",
                "name",
                "email",
                "created_at",
                "big_int",
                "json_data",
                "active",
                "decimal_data",
                "price",
                "float_data",
            ],
        )

        # Compare sorted results as rows may have been shuffled around, but we only care the data is there,
        # not in which order.
        assert sorted(res.results, key=operator.itemgetter(0)) == sorted(
            TEST_DATA + NEW_TEST_DATA, key=operator.itemgetter(0)
        )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@SKIP_IF_MISSING_MSSQL_CREDENTIALS
class TestGetTableAverageRowSize:
    async def test_get_table_average_row_size(
        self,
        mssql_source_table: pymssql.Cursor,
        mssql_config: dict[str, Any],
    ):
        """Test that the average row size is calculated correctly.

        Here we use a table with a variety of column types and data to ensure the queries to calculate the average row size
        are correct.
        We don't assert the average row size here as it's hard to determine and is likely to be flaky.  We do this instead
        in another test below.
        """
        average_row_size = _get_table_average_row_size(
            cursor=mssql_source_table,
            schema=mssql_config["schema"],
            table_name=MSSQL_TABLE_NAME,
            should_use_incremental_field=False,
            incremental_field=None,
            incremental_field_type=None,
            db_incremental_field_last_value=None,
            logger=structlog.get_logger(),
        )

        # Just assert that we do calculate a value and don't return None
        assert isinstance(average_row_size, int)
        # sanity check that the average row size is not too big or too small
        assert average_row_size > 0
        assert average_row_size < 1000

    async def test_get_table_average_row_size_with_incremental_field(
        self,
        mssql_source_table: pymssql.Cursor,
        mssql_config: dict[str, Any],
    ):
        """Test that the average row size is calculated correctly for an incremental sync.

        Here we use a table with a variety of column types and data to ensure the queries to calculate the average row size
        are correct.
        We don't assert the average row size here as it's hard to determine and is likely to be flaky.  We do this instead
        in another test below.
        """
        average_row_size = _get_table_average_row_size(
            cursor=mssql_source_table,
            schema=mssql_config["schema"],
            table_name=MSSQL_TABLE_NAME,
            should_use_incremental_field=True,
            incremental_field="created_at",
            incremental_field_type=IncrementalFieldType.DateTime,
            db_incremental_field_last_value=None,
            logger=structlog.get_logger(),
        )

        # Just assert that we do calculate a value and don't return None
        assert isinstance(average_row_size, int)
        # sanity check that the average row size is not too big or too small
        assert average_row_size > 0
        assert average_row_size < 1000

    @pytest.fixture
    def mssql_source_table_known_row_size(
        self,
        mssql_connection: pymssql.Connection,
        mssql_config: dict[str, Any],
    ) -> Generator[pymssql.Cursor, None, None]:
        """Create a MS SQL Server table with deterministic row size and clean it up after the test."""
        with mssql_connection.cursor() as cursor:
            full_table_name = f"[{mssql_config['schema']}].[{MSSQL_TABLE_NAME}]"

            try:
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
                            name NVARCHAR(255)
                        )
                    END
                """)
                mssql_connection.commit()

                # Insert test data
                data = [
                    ("0123456789",),
                    ("acbcdefghi",),
                    ("9876543210",),
                ]
                for row in data:
                    cursor.execute(
                        f"INSERT INTO {full_table_name} (name) VALUES (%s)",
                        row,
                    )
                cursor.connection.commit()

                yield cursor

            finally:
                # Cleanup
                cursor.execute(f"DROP TABLE IF EXISTS {full_table_name}")
                mssql_connection.commit()

    async def test_get_table_average_row_size_calculates_correct_average_row_size(
        self,
        mssql_source_table_known_row_size: pymssql.Cursor,
        mssql_config: dict[str, Any],
    ):
        """Test that the average row size is calculated correctly.

        To do this, we test using a table with a known row size so we can assert the average row size is correct.
        """
        average_row_size = _get_table_average_row_size(
            cursor=mssql_source_table_known_row_size,
            schema=mssql_config["schema"],
            table_name=MSSQL_TABLE_NAME,
            should_use_incremental_field=False,
            incremental_field=None,
            incremental_field_type=None,
            db_incremental_field_last_value=None,
            logger=structlog.get_logger(),
        )

        # each character in column uses 2 bytes
        assert average_row_size == 20


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@SKIP_IF_MISSING_MSSQL_CREDENTIALS
class TestGetTableStats:
    @pytest.fixture
    def mssql_small_table(
        self,
        mssql_connection: pymssql.Connection,
        mssql_config: dict[str, Any],
    ) -> Generator[pymssql.Cursor, None, None]:
        """Create a small test table with known size and row count."""
        with mssql_connection.cursor() as cursor:
            full_table_name = f"[{mssql_config['schema']}].[test_small]"

            try:
                # Create test table
                cursor.execute(f"""
                    IF NOT EXISTS (
                        SELECT *
                        FROM sys.tables t
                        JOIN sys.schemas s ON t.schema_id = s.schema_id
                        WHERE s.name = '{mssql_config['schema']}'
                        AND t.name = 'test_small'
                    )
                    BEGIN
                        CREATE TABLE {full_table_name} (
                            id INT IDENTITY(1,1) PRIMARY KEY,
                            value INT
                        )
                    END
                """)
                mssql_connection.commit()

                # Insert exactly 1000 rows with small integers
                cursor.execute(f"""
                    WITH numbers AS (
                        SELECT 1 as n
                        UNION ALL
                        SELECT n + 1
                        FROM numbers
                        WHERE n < 1000
                    )
                    INSERT INTO {full_table_name} (value)
                    SELECT n FROM numbers
                    OPTION (MAXRECURSION 1000)
                """)
                mssql_connection.commit()

                yield cursor

            finally:
                # Cleanup
                cursor.execute(f"DROP TABLE IF EXISTS {full_table_name}")
                mssql_connection.commit()

    @pytest.fixture
    def mssql_empty_table(
        self,
        mssql_connection: pymssql.Connection,
        mssql_config: dict[str, Any],
    ) -> Generator[pymssql.Cursor, None, None]:
        """Create an empty test table."""
        with mssql_connection.cursor() as cursor:
            full_table_name = f"[{mssql_config['schema']}].[test_empty]"

            try:
                # Create test table but don't insert any rows
                cursor.execute(f"""
                    IF NOT EXISTS (
                        SELECT *
                        FROM sys.tables t
                        JOIN sys.schemas s ON t.schema_id = s.schema_id
                        WHERE s.name = '{mssql_config['schema']}'
                        AND t.name = 'test_empty'
                    )
                    BEGIN
                        CREATE TABLE {full_table_name} (
                            id INT IDENTITY(1,1) PRIMARY KEY,
                            value INT
                        )
                    END
                """)
                mssql_connection.commit()

                yield cursor

            finally:
                # Cleanup
                cursor.execute(f"DROP TABLE IF EXISTS {full_table_name}")
                mssql_connection.commit()

    async def test_get_table_stats(
        self,
        mssql_small_table: pymssql.Cursor,
        mssql_config: dict[str, Any],
    ):
        """Test that table stats are calculated correctly.

        We test using a table with exactly 1000 rows of small integers,
        so we can make some assertions about the size and row count.
        """
        total_rows, total_bytes = _get_table_stats(
            cursor=mssql_small_table,
            schema=mssql_config["schema"],
            table_name="test_small",
        )

        assert total_rows == 1000  # We inserted exactly 1000 rows
        # Size should be around 32KB
        assert total_bytes > 30 * 1024
        assert total_bytes < 34 * 1024

    async def test_get_table_stats_empty_table(
        self,
        mssql_empty_table: pymssql.Cursor,
        mssql_config: dict[str, Any],
    ):
        """Test that table stats work correctly with an empty table.

        An empty table should return 0 rows and 0 bytes.
        """
        total_rows, total_bytes = _get_table_stats(
            cursor=mssql_empty_table,
            schema=mssql_config["schema"],
            table_name="test_empty",
        )

        assert total_rows == 0
        assert total_bytes == 0
