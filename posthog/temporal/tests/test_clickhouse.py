import uuid
import asyncio
import datetime as dt
import contextlib

import pytest
from unittest.mock import MagicMock, patch

from posthog.clickhouse.query_tagging import QueryTags
from posthog.temporal.common.clickhouse import (
    ClickHouseCheckQueryStatusError,
    ClickHouseClient,
    ClickHouseError,
    ClickHouseMemoryLimitExceededError,
    ClickHouseQueryNotFound,
    ClickHouseQueryStatus,
    add_log_comment_param,
    encode_clickhouse_data,
)


async def _wait_for_query_status(
    client: ClickHouseClient,
    query_id: str,
    expected_status: ClickHouseQueryStatus,
    raise_on_error: bool = True,
    max_wait_time: float = 5.0,
    poll_interval: float = 0.5,
) -> ClickHouseQueryStatus | None:
    """Wait for a query to reach the expected status in the query log.

    Returns:
        The query status if found, None if timeout.
    """
    elapsed_time = 0.0
    while elapsed_time < max_wait_time:
        try:
            status = await client.acheck_query_in_query_log(query_id, raise_on_error=raise_on_error)
            if status == expected_status:
                return status
        except ClickHouseQueryNotFound:
            pass
        except ClickHouseError:
            if raise_on_error:
                raise
            return ClickHouseQueryStatus.ERROR
        await asyncio.sleep(poll_interval)
        elapsed_time += poll_interval
    return None


async def _wait_for_query_in_process_list(
    client: ClickHouseClient,
    query_id: str,
    expected: bool,
    max_wait_time: float = 5.0,
    poll_interval: float = 0.5,
) -> bool:
    """Wait for a query to appear or disappear from the process list.

    Returns:
        True if query is in process list, False otherwise.
    """
    elapsed_time = 0.0
    while elapsed_time < max_wait_time:
        is_running = await client.acheck_query_in_process_list(query_id)
        if is_running == expected:
            return is_running
        await asyncio.sleep(poll_interval)
        elapsed_time += poll_interval
    return not expected


async def _run_and_cancel_query(
    client: ClickHouseClient,
    query: str,
    query_id: str,
    wait_before_cancel: float = 0.5,
) -> asyncio.Task:
    """Start a long-running query and cancel it after a short delay.

    Returns:
        The task running the query (which will raise ClickHouseError when awaited).
    """

    async def run_query():
        await client.execute_query(query, query_id=query_id)

    query_task = asyncio.create_task(run_query())
    await asyncio.sleep(wait_before_cancel)
    await client.acancel_query(query_id)
    return query_task


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


@pytest.mark.parametrize(
    "query,query_parameters,expected",
    [
        (
            "select * from events where event = {event}",
            {"event": "hello"},
            "select * from events where event = 'hello'",
        ),
        (
            "select * from events where event = %(event)s",
            {"event": "world"},
            "select * from events where event = 'world'",
        ),
        (
            "select * from events where event = %(event)s and event != {another}",
            {"event": "index_{1}", "another": "event"},
            "select * from events where event = 'index_{1}' and event != 'event'",
        ),
        (
            "select * from events where event = %(event)s and event != {another}",
            {"event": "index_{something}", "another": "event"},
            "select * from events where event = 'index_{something}' and event != 'event'",
        ),
    ],
)
def test_prepare_query(clickhouse_client, query, query_parameters, expected):
    """Test data is encoded as expected."""
    result = clickhouse_client.prepare_query(query, query_parameters)
    assert result == expected


async def test_acancel_query(clickhouse_client, django_db_setup):
    """Test that acancel_query successfully cancels a long-running query."""
    query_id = f"test-long-running-query-{uuid.uuid4()}"
    long_running_query = "SELECT sleep(3)"

    query_task = await _run_and_cancel_query(clickhouse_client, long_running_query, query_id)

    with pytest.raises(ClickHouseError):
        await query_task

    status = await _wait_for_query_status(
        clickhouse_client, query_id, ClickHouseQueryStatus.ERROR, raise_on_error=False
    )

    # ClickHouse treats cancelled queries as failed, so we expect an error status
    # Code: 394. DB::Exception: Query was cancelled. (QUERY_WAS_CANCELLED)
    assert status == ClickHouseQueryStatus.ERROR


async def test_acheck_query_in_process_list(clickhouse_client, django_db_setup):
    """Test that acheck_query_in_process_list correctly identifies running queries."""
    query_id = f"test-process-list-query-{uuid.uuid4()}"
    long_running_query = "SELECT sleep(3)"

    query_task = asyncio.create_task(clickhouse_client.execute_query(long_running_query, query_id=query_id))
    await asyncio.sleep(0.5)

    # query should be running, and therefore in the process list
    is_running = await clickhouse_client.acheck_query_in_process_list(query_id)
    assert is_running is True

    # now try cancelling the query and asserting that it is no longer in the process list
    await clickhouse_client.acancel_query(query_id)

    with pytest.raises(ClickHouseError):
        await query_task

    is_running = await _wait_for_query_in_process_list(clickhouse_client, query_id, expected=False)
    assert is_running is False


async def test_acheck_query_in_query_log_successful(clickhouse_client, django_db_setup):
    """Test that acheck_query_in_query_log returns FINISHED for a successful query."""
    query_id = f"test-successful-query-{uuid.uuid4()}"
    await clickhouse_client.execute_query("SELECT 1", query_id=query_id)

    status = await _wait_for_query_status(clickhouse_client, query_id, ClickHouseQueryStatus.FINISHED)
    assert status == ClickHouseQueryStatus.FINISHED


async def test_acheck_query_in_query_log_cancelled(clickhouse_client, django_db_setup):
    """Test that acheck_query_in_query_log handles cancelled queries correctly based on raise_on_error."""
    query_id = f"test-cancelled-query-{uuid.uuid4()}"
    long_running_query = "SELECT sleep(3)"

    query_task = await _run_and_cancel_query(clickhouse_client, long_running_query, query_id)

    with pytest.raises(ClickHouseError):
        await query_task

    # using raise_on_error=False should return an error status
    status = await _wait_for_query_status(
        clickhouse_client, query_id, ClickHouseQueryStatus.ERROR, raise_on_error=False
    )
    assert status == ClickHouseQueryStatus.ERROR

    # using raise_on_error=True should raise an exception
    with pytest.raises(ClickHouseError):
        await _wait_for_query_status(clickhouse_client, query_id, ClickHouseQueryStatus.ERROR, raise_on_error=True)


async def test_acheck_query_in_query_log_not_found(clickhouse_client, django_db_setup):
    """Test that acheck_query_in_query_log raises ClickHouseQueryNotFound for non-existent queries."""
    non_existent_query_id = f"test-non-existent-query-{uuid.uuid4()}"
    with pytest.raises(ClickHouseQueryNotFound):
        await clickhouse_client.acheck_query_in_query_log(non_existent_query_id)


async def test_acheck_query_in_query_log_error(clickhouse_client, django_db_setup):
    """Test that acheck_query_in_query_log raises ClickHouseCheckQueryStatusError for errors."""
    # Simulate an exception from the ClickHouse client
    # (this is an example of a response we've seen in production, where a 200 is returned but it is actually an error)
    # because we use Format JSONEachRow we get the exception returned inside a JSON object
    mock_response = MagicMock()
    mock_response.status = 200

    async def mock_read():
        return b'{"exception": "Code: 202. DB::Exception: Received from dummy-ch-node.internal. DB::Exception: Too many simultaneous queries for all users. Current: 10, maximum: 10. (TOO_MANY_SIMULTANEOUS_QUERIES) (version x.x.x.x (official build))"}'

    mock_response.content.read = mock_read

    @contextlib.asynccontextmanager
    async def mock_get(*args, **kwargs):
        yield mock_response

    mock_session = MagicMock()
    mock_session.get = mock_get

    with patch.object(
        clickhouse_client,
        "session",
        mock_session,
    ):
        query_id = f"test-error-query-{uuid.uuid4()}"
        with pytest.raises(ClickHouseCheckQueryStatusError):
            await clickhouse_client.acheck_query_in_query_log(query_id)


async def test_acheck_query_found(clickhouse_client, django_db_setup):
    query_id = f"test-acheck-query-{uuid.uuid4()}"
    await clickhouse_client.execute_query("SELECT 1", query_id=query_id)

    status = await _wait_for_query_status(clickhouse_client, query_id, ClickHouseQueryStatus.FINISHED)
    assert status == ClickHouseQueryStatus.FINISHED

    # acheck_query should return the same status
    result = await clickhouse_client.acheck_query(query_id)
    assert result == ClickHouseQueryStatus.FINISHED


async def test_acheck_query_not_found_anywhere(clickhouse_client, django_db_setup):
    """Test that acheck_query raises ClickHouseQueryNotFound when query is not in query log or process list."""
    non_existent_query_id = f"test-acheck-query-not-found-{uuid.uuid4()}"
    with pytest.raises(ClickHouseQueryNotFound):
        await clickhouse_client.acheck_query(non_existent_query_id)


async def test_stream_query_as_jsonl_handles_split_chunks(clickhouse_client):
    """Test that stream_query_as_jsonl correctly handles chunks that split mid-JSON."""

    mock_response = MagicMock()
    mock_response.status = 200

    chunks = [
        b'{"status": "ent',
        b'ered", "id": 1}\n{"status": "co',
        b'mpleted", "id": 2}\n',
    ]

    async def mock_iter_any():
        for chunk in chunks:
            yield chunk

    mock_response.content.iter_any = mock_iter_any

    @contextlib.asynccontextmanager
    async def mock_post(*args, **kwargs):
        yield mock_response

    with patch.object(clickhouse_client, "apost_query", mock_post):
        results = []
        async for result in clickhouse_client.stream_query_as_jsonl("SELECT 1"):
            results.append(result)

    assert len(results) == 2
    assert results[0] == {"status": "entered", "id": 1}
    assert results[1] == {"status": "completed", "id": 2}


async def test_stream_query_as_jsonl_handles_final_line_without_separator(clickhouse_client):
    """Test that stream_query_as_jsonl correctly handles the final line without a trailing separator."""

    mock_response = MagicMock()
    mock_response.status = 200

    chunks = [
        b'{"id": 1}\n{"id": 2}\n{"id": 3}',
    ]

    async def mock_iter_any():
        for chunk in chunks:
            yield chunk

    mock_response.content.iter_any = mock_iter_any

    @contextlib.asynccontextmanager
    async def mock_post(*args, **kwargs):
        yield mock_response

    with patch.object(clickhouse_client, "apost_query", mock_post):
        results = []
        async for result in clickhouse_client.stream_query_as_jsonl("SELECT 1"):
            results.append(result)

    assert len(results) == 3
    assert results[0] == {"id": 1}
    assert results[1] == {"id": 2}
    assert results[2] == {"id": 3}


async def test_stream_query_as_jsonl_handles_whitespace_only_lines(clickhouse_client):
    """Test that stream_query_as_jsonl correctly handles whitespace-only lines between valid JSON."""

    mock_response = MagicMock()
    mock_response.status = 200

    chunks = [
        b'{"id": 1}\n  \n{"id": 2}\n\t\n{"id": 3}\n',
    ]

    async def mock_iter_any():
        for chunk in chunks:
            yield chunk

    mock_response.content.iter_any = mock_iter_any

    @contextlib.asynccontextmanager
    async def mock_post(*args, **kwargs):
        yield mock_response

    with patch.object(clickhouse_client, "apost_query", mock_post):
        results = []
        async for result in clickhouse_client.stream_query_as_jsonl("SELECT 1"):
            results.append(result)

    assert len(results) == 3
    assert results[0] == {"id": 1}
    assert results[1] == {"id": 2}
    assert results[2] == {"id": 3}
