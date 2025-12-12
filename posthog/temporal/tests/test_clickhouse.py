import uuid
import asyncio
import datetime as dt

import pytest
from unittest.mock import MagicMock, patch

from posthog.clickhouse.query_tagging import QueryTags
from posthog.temporal.common.clickhouse import (
    ClickHouseError,
    ClickHouseMemoryLimitExceededError,
    ClickHouseQueryNotFound,
    ClickHouseQueryStatus,
    add_log_comment_param,
    encode_clickhouse_data,
)


@pytest.mark.parametrize(
    "data,expected",
    [
        (
            uuid.UUID("c4c5547d-8782-4017-8eca-3ea19f4d528e"),
            b"'c4c5547d-8782-4017-8eca-3ea19f4d528e'",
        ),
        ("", b"''"),
        ("'", b"'\\''"),
        ("\\", b"'\\\\'"),
        ("test-string", b"'test-string'"),
        ("a'\\b\\'c", b"'a\\'\\\\b\\\\\\'c'"),
        (("a", 1, ("b", 2)), b"('a',1,('b',2))"),
        (["a", 1, ["b", 2]], b"['a',1,['b',2]]"),
        (("; DROP TABLE events --",), b"('; DROP TABLE events --')"),
        (("'a'); DROP TABLE events --",), b"('\\'a\\'); DROP TABLE events --')"),
        (
            dt.datetime(2023, 7, 14, 0, 0, 0, tzinfo=dt.UTC),
            b"toDateTime('2023-07-14 00:00:00', 'UTC')",
        ),
        (dt.datetime(2023, 7, 14, 0, 0, 0), b"toDateTime('2023-07-14 00:00:00')"),
        (
            dt.datetime(2023, 7, 14, 0, 0, 0, 5555, tzinfo=dt.UTC),
            b"toDateTime64('2023-07-14 00:00:00.005555', 6, 'UTC')",
        ),
        ([1.1666, [0.132, -0.2390], 0.0], b"[1.1666,[0.132,-0.239],0]"),
    ],
)
def test_encode_clickhouse_data(data, expected):
    """Test data is encoded as expected."""
    result = encode_clickhouse_data(data)
    assert result == expected


@pytest.mark.parametrize(
    "params,qt,want",
    [
        ({}, QueryTags(), {"log_comment": "{}"}),
        ({"param_log_comment": ""}, QueryTags(), {"param_log_comment": "", "log_comment": "{}"}),
        ({"param_log_comment": "{}"}, QueryTags(), {"param_log_comment": "{}"}),
        ({"param_log_comment": '{"kind":"qt"}'}, QueryTags(), {"param_log_comment": '{"kind":"qt"}'}),
        ({"param_log_comment": '{"kind":"xyz"}'}, QueryTags(kind="abc"), {"param_log_comment": '{"kind":"xyz"}'}),
        ({}, QueryTags(kind="abc"), {"log_comment": '{"kind":"abc"}'}),
    ],
)
def test_add_log_comment_param(params, qt, want):
    add_log_comment_param(params, qt)
    assert params == want


def test_clickhouse_memory_limit_exceeded_error(clickhouse_client):
    """Simulate a ClickHouse memory limit exceeded error and verify that the correct error is raised."""
    with patch(
        "posthog.temporal.common.clickhouse.requests.Session.post",
        return_value=(
            MagicMock(
                status_code=500,
                text="Code: 241. DB::Exception: (total) memory limit exceeded: would use 99.97 GiB (attempt to allocate chunk of 12.26 MiB bytes), current RSS: 111.22 GiB, maximum: 111.19 GiB. OvercommitTracker decision: Query was selected to stop by OvercommitTracker: While executing MergeSortingTransform. (MEMORY_LIMIT_EXCEEDED) (version 25.8.12.129 (official build))",
            )
        ),
    ):
        with pytest.raises(ClickHouseMemoryLimitExceededError):
            with clickhouse_client.post_query("SELECT 1", query_parameters={}, query_id=None):
                pass


async def test_acancel_query(clickhouse_client, django_db_setup):
    """Test that acancel_query successfully cancels a long-running query."""
    long_running_query_id = f"test-long-running-query-{uuid.uuid4()}"
    long_running_query = "SELECT sleep(3)"

    async def run_query():
        await clickhouse_client.execute_query(
            long_running_query,
            query_id=long_running_query_id,
        )

    query_task = asyncio.create_task(run_query())

    await asyncio.sleep(0.5)

    await clickhouse_client.acancel_query(long_running_query_id)

    with pytest.raises(ClickHouseError):
        await query_task

    max_wait_time = 5.0
    poll_interval = 0.5
    elapsed_time = 0.0

    status = None
    while elapsed_time < max_wait_time:
        try:
            status = await clickhouse_client.acheck_query(long_running_query_id, raise_on_error=False)
            if status != ClickHouseQueryStatus.RUNNING:
                break
        except ClickHouseQueryNotFound:
            pass
        await asyncio.sleep(poll_interval)
        elapsed_time += poll_interval

    # ClickHouse treats cancelled queries as failed, so we expect an error status
    # Code: 394. DB::Exception: Query was cancelled. (QUERY_WAS_CANCELLED)
    assert status == ClickHouseQueryStatus.ERROR


async def test_acheck_query_in_process_list(clickhouse_client, django_db_setup):
    """Test that acheck_query_in_process_list correctly identifies running queries."""
    query_id = f"test-process-list-query-{uuid.uuid4()}"
    long_running_query = "SELECT sleep(3)"

    async def run_query():
        await clickhouse_client.execute_query(
            long_running_query,
            query_id=query_id,
        )

    query_task = asyncio.create_task(run_query())

    await asyncio.sleep(0.5)

    # query should be running, and therefore in the process list
    is_running = await clickhouse_client.acheck_query_in_process_list(query_id)
    assert is_running is True

    # now try cancelling the query and asserting that it is no longer in the process list
    await clickhouse_client.acancel_query(query_id)

    with pytest.raises(ClickHouseError):
        await query_task

    max_wait_time = 5.0
    poll_interval = 0.5
    elapsed_time = 0.0

    while elapsed_time < max_wait_time:
        is_running = await clickhouse_client.acheck_query_in_process_list(query_id)
        if not is_running:
            break
        await asyncio.sleep(poll_interval)
        elapsed_time += poll_interval

    assert is_running is False
