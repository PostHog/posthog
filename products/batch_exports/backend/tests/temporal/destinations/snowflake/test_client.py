"""
Test SnowflakeClient behavior.

Note: This module uses a real Snowflake connection.
"""

import os
import asyncio
import datetime as dt

import pytest

import pyarrow as pa
import pytest_asyncio

from products.batch_exports.backend.temporal.destinations.snowflake_batch_export import (
    SnowflakeClient,
    SnowflakeField,
    SnowflakeIncompatibleSchemaError,
    SnowflakeInsertInputs,
    SnowflakeQueryClientTimeoutError,
    SnowflakeTable,
    SnowflakeType,
    SnowflakeWarehouseUsageError,
)
from products.batch_exports.backend.tests.temporal.destinations.snowflake.utils import SKIP_IF_MISSING_REQUIRED_ENV_VARS

pytestmark = [
    pytest.mark.asyncio,
    SKIP_IF_MISSING_REQUIRED_ENV_VARS,
]


@pytest_asyncio.fixture
async def snowflake_client(snowflake_config, database, schema):
    """Create a SnowflakeClient with a test database and schema set up and cleaned up after tests."""

    inputs = SnowflakeInsertInputs(
        team_id=1,  # not important for this test
        data_interval_start=(
            dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)
        ).isoformat(),  # not important for this test
        data_interval_end=(dt.datetime.now(dt.UTC)).isoformat(),  # not important for this test
        table_name="test_table",  # not important for this test
        **snowflake_config,
    )

    async with SnowflakeClient.from_inputs(inputs).connect(use_namespace=False) as client:
        # Set up: Create database and schema
        await client.execute_async_query(f'CREATE DATABASE IF NOT EXISTS "{database}"', fetch_results=False)
        await client.execute_async_query(f'CREATE SCHEMA IF NOT EXISTS "{database}"."{schema}"', fetch_results=False)
        await client.execute_async_query(f'USE SCHEMA "{database}"."{schema}"', fetch_results=False)

        yield client

        # Tear down: Clean up database
        await client.execute_async_query(f'DROP DATABASE IF EXISTS "{database}" CASCADE', fetch_results=False)


async def test_execute_async_query_with_timeout_raises_error(snowflake_client):
    """Test that execute_async_query raises SnowflakeQueryClientTimeoutError when timeout is exceeded.

    This test uses a real Snowflake connection and runs a query that will take longer than
    the specified timeout. We use a SYSTEM$WAIT() call to simulate a long-running query.
    """
    with pytest.raises(SnowflakeQueryClientTimeoutError) as exc_info:
        await snowflake_client.execute_async_query(
            "CALL SYSTEM$WAIT(10)",  # Sleep for 10 seconds
            timeout=1.0,
        )

    # Verify the exception has the correct information
    error = exc_info.value
    error_message = str(error)
    assert "Query timed out after 1 seconds" in error_message
    assert "query_id:" in error_message
    # The query status should be RUNNING since the sleep is still executing
    assert (
        "Query is still running but exceeded timeout" in error_message
        or "Warehouse is overloaded" in error_message
        or "Warehouse is resuming" in error_message
    )

    query_id = error.query_id
    assert query_id is not None, "Query ID should be available as exception attribute"

    # Check if the query was actually cancelled/aborted in Snowflake
    # Poll for the query to be aborted with a timeout
    max_wait_seconds = 10
    poll_interval = 0.5
    elapsed = 0.0

    while elapsed < max_wait_seconds:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

        query_status = await snowflake_client.get_query_status(query_id, throw_if_error=False)
        assert query_status is not None, "Query status should be available"

        if query_status.name in ["ABORTED", "FAILED_WITH_ERROR"]:
            # Query was successfully aborted
            break

    # The query should be aborted, not still running
    assert query_status.name in [
        "ABORTED",
        "FAILED_WITH_ERROR",  # for some odd reason this seems to be the status when the query is aborted
    ], f"Query was not successfully aborted after timeout, status: {query_status.name}"


async def test_execute_async_query_without_timeout_completes(snowflake_client):
    """Test that execute_async_query completes successfully when no timeout is specified."""
    result = await snowflake_client.execute_async_query("SELECT 1 AS test_column")

    assert result is not None
    results, description = result
    assert len(results) == 1
    assert results[0][0] == 1
    assert description[0].name.upper() == "TEST_COLUMN"


async def test_execute_async_query_completes_within_timeout(snowflake_client):
    """Test that execute_async_query completes successfully when query finishes before timeout."""
    result = await snowflake_client.execute_async_query(
        "SELECT 1 AS test_column",
        timeout=60.0,
    )

    assert result is not None
    results, _description = result
    assert len(results) == 1
    assert results[0][0] == 1


async def test_use_namespace_raises_error_if_warehouse_not_found_or_missing_usage_permissions(snowflake_client):
    """Test that use_namespace raises an error if the warehouse is not found or we are missing 'USAGE' permissions on it."""
    snowflake_client.warehouse = "garbage"
    with pytest.raises(SnowflakeWarehouseUsageError):
        await snowflake_client.use_namespace()


@pytest.fixture
def table_name():
    return f"test_table_{os.urandom(5).hex()}"


@pytest_asyncio.fixture
async def test_table(snowflake_client, database, schema, table_name):
    """A table for testing."""
    table = SnowflakeTable(
        name=table_name,
        fields=(
            SnowflakeField("id", SnowflakeType("INTEGER", False), pa.int64(), True),
            SnowflakeField("text", SnowflakeType("TEXT", False), pa.string(), True),
        ),
        parents=(database, schema),
    )

    await snowflake_client.create_table(table)

    yield table

    await snowflake_client.delete_table(table)


async def test_get_table(snowflake_client, database, schema, test_table):
    """Test getting a table."""
    get_result = await snowflake_client.get_table(test_table)

    assert test_table.name == get_result.name
    assert test_table.fields == get_result.fields


async def test_get_table_does_not_fail_with_additional_fields(snowflake_client, database, schema, test_table):
    """Test getting a table when additional fields are present."""
    _ = await snowflake_client.execute_async_query(
        f'ALTER TABLE "{test_table.name}" ADD COLUMN "new" STRING;',
        timeout=60.0,
    )

    get_result = await snowflake_client.get_table(test_table)

    assert test_table.name == get_result.name
    # Still equals as we only include fields present in the table request
    assert test_table.fields == get_result.fields


async def test_get_table_does_not_fail_with_missing_fields(snowflake_client, database, schema, test_table):
    """Test getting a table when missing fields that are not part of the primary key."""
    _ = await snowflake_client.execute_async_query(
        f'ALTER TABLE "{test_table.name}" DROP COLUMN "text";',
        timeout=60.0,
    )

    get_result = await snowflake_client.get_table(test_table)

    assert test_table.name == get_result.name
    # This time the fields will differ as we don't include missing fields
    assert test_table.fields != get_result.fields
    assert "text" not in get_result


async def test_get_table_raises_incompatible_schema_on_missing_primary_key_fields(
    snowflake_client, database, schema, test_table
):
    """Test attempting to get a table with missing primary_key fields fails"""
    table = SnowflakeTable(
        name=test_table.name,
        fields=(
            *test_table.fields,
            SnowflakeField("missing_key_one", SnowflakeType("INTEGER", False), pa.int64(), True),
            SnowflakeField("missing_key_two", SnowflakeType("INTEGER", False), pa.int64(), True),
        ),
        parents=test_table.parents,
        primary_key=("missing_key_one", "missing_key_two"),
        version_key=("id"),
    )

    with pytest.raises(SnowflakeIncompatibleSchemaError) as excinfo:
        await snowflake_client.get_table(table)

    assert "'missing_key_one', 'missing_key_two'" in str(excinfo.value)
