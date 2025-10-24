"""
Test SnowflakeClient behavior.

Note: This module uses a real Snowflake connection.
"""

import re
import asyncio
import datetime as dt

import pytest

from products.batch_exports.backend.temporal.destinations.snowflake_batch_export import (
    SnowflakeClient,
    SnowflakeInsertInputs,
    SnowflakeQueryTimeoutError,
)
from products.batch_exports.backend.tests.temporal.destinations.snowflake.utils import SKIP_IF_MISSING_REQUIRED_ENV_VARS

pytestmark = [
    pytest.mark.asyncio,
    SKIP_IF_MISSING_REQUIRED_ENV_VARS,
]


@pytest.fixture
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
    """Test that execute_async_query raises SnowflakeQueryTimeoutError when timeout is exceeded.

    This test uses a real Snowflake connection and runs a query that will take longer than
    the specified timeout. We use a SYSTEM$WAIT() call to simulate a long-running query.
    """
    # Execute a query that will sleep for 10 seconds but with a 1 second timeout
    # This should raise a SnowflakeQueryTimeoutError
    with pytest.raises(SnowflakeQueryTimeoutError) as exc_info:
        await snowflake_client.execute_async_query(
            "CALL SYSTEM$WAIT(10)",  # Sleep for 10 seconds
            timeout=1.0,  # Timeout after 1 second
        )

    # Verify the exception has the correct information
    error_message = str(exc_info.value)
    assert "Query operation timed out after 1 seconds" in error_message
    assert "query_id:" in error_message
    # The query status should be RUNNING since the sleep is still executing
    assert (
        "Query is still running but exceeded timeout" in error_message
        or "Warehouse is overloaded" in error_message
        or "Warehouse is resuming" in error_message
    )

    # Extract the query_id from the error message to check if it was cancelled
    query_id_match = re.search(r"query_id:\s*([a-f0-9-]+)", error_message)
    assert query_id_match is not None, f"Query ID should be present in error message: {error_message}"
    query_id = query_id_match.group(1)

    # Check if the query was actually cancelled/aborted in Snowflake
    # Wait a bit to allow cancellation to take effect
    await asyncio.sleep(1)

    query_status = await snowflake_client.get_query_status(query_id, throw_if_error=False)

    # The query should be aborted, not still running
    assert query_status is not None, "Query status should be available"
    assert query_status.name in [
        "ABORTED",
        "FAILED_WITH_ERROR",  # for some odd reason this seems to be the status when the query is aborted
    ], f"Query should be aborted after timeout, status: {query_status.name}"


async def test_execute_async_query_without_timeout_completes(snowflake_client):
    """Test that execute_async_query completes successfully when no timeout is specified."""
    # Execute a simple query without a timeout - should complete successfully
    result = await snowflake_client.execute_async_query("SELECT 1 AS test_column")

    # Verify the query completed successfully
    assert result is not None
    results, description = result
    assert len(results) == 1
    assert results[0][0] == 1
    assert description[0].name.upper() == "TEST_COLUMN"


async def test_execute_async_query_completes_within_timeout(snowflake_client):
    """Test that execute_async_query completes successfully when query finishes before timeout."""
    # Execute a quick query with a generous timeout - should complete successfully
    result = await snowflake_client.execute_async_query(
        "SELECT 1 AS test_column",
        timeout=60.0,  # 60 second timeout, query should complete in < 1 second
    )

    # Verify the query completed successfully
    assert result is not None
    results, _description = result
    assert len(results) == 1
    assert results[0][0] == 1
