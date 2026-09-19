import io
import asyncio

import pytest
from unittest.mock import MagicMock

import requests
from google.api_core.exceptions import BadRequest, Forbidden, GatewayTimeout, InternalServerError, RetryError
from google.cloud import bigquery

from products.batch_exports.backend.temporal.destinations import bigquery_batch_export
from products.batch_exports.backend.temporal.destinations.bigquery_batch_export import (
    BigQueryClient,
    BigQueryTable,
    StartJobTimeoutError,
)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    clock = MagicMock()
    clock.monotonic.return_value = 0.0
    yield_to_loop = asyncio.sleep

    async def sleep(delay: float) -> None:
        clock.monotonic.return_value += delay
        await yield_to_loop(0)

    monkeypatch.setattr(bigquery_batch_export, "time", clock)
    monkeypatch.setattr(asyncio, "sleep", sleep)
    return clock


@pytest.mark.parametrize(
    "poll_error,cancel_error",
    [
        (None, None),
        (GatewayTimeout("status unavailable"), None),
        (
            RetryError("poll retries exhausted", GatewayTimeout("status unavailable")),
            GatewayTimeout("cancel unavailable"),
        ),
        (
            requests.exceptions.ReadTimeout("status unavailable"),
            RetryError("cancel retries exhausted", GatewayTimeout("cancel unavailable")),
        ),
    ],
)
@pytest.mark.asyncio
async def test_load_pending_timeout_survives_retries(
    clock: MagicMock, poll_error: Exception | None, cancel_error: Exception | None
) -> None:
    def reload(*, retry: object, timeout: float) -> None:
        assert retry is None
        assert 0 < timeout <= min(30, 2 - clock.monotonic.return_value)
        if poll_error is not None:
            raise poll_error

    job = MagicMock(spec=bigquery.LoadJob, state="PENDING", job_id="test-load", job_type="load")
    job.reload.side_effect = reload
    job.cancel.side_effect = cancel_error
    sdk = MagicMock(project="test-project")
    sdk.load_table_from_file.return_value = job
    client = BigQueryClient(sdk)
    table = BigQueryTable("events", (), parents=("test-project", "test_dataset"))

    with pytest.raises(StartJobTimeoutError, match="test-load"):
        await client.load_file(io.BytesIO(), "JSONLines", table, timeout=2)

    sdk.load_table_from_file.assert_called_once()
    job.cancel.assert_called_once_with(retry=None, timeout=5)
    job.result.assert_not_called()
    assert clock.monotonic.return_value <= 3


@pytest.mark.parametrize(
    "state,terminal_failure,error",
    [
        ("RUNNING", False, GatewayTimeout("status unavailable")),
        ("RUNNING", False, RetryError("poll retries exhausted", GatewayTimeout("status unavailable"))),
        ("DONE", False, GatewayTimeout("status unavailable")),
        ("DONE", True, InternalServerError("load failed")),
        ("DONE", True, Forbidden("reason: quotaExceeded")),
        ("DONE", True, BadRequest("matched no files")),
    ],
)
@pytest.mark.asyncio
async def test_load_replaces_only_failed_jobs(
    clock: MagicMock, state: str, terminal_failure: bool, error: Exception
) -> None:
    job = MagicMock(spec=bigquery.LoadJob, state=state)
    job.error_result = {"reason": "backendError"} if terminal_failure else None
    job.result.side_effect = [error, job]
    replacement = MagicMock(spec=bigquery.LoadJob, state="PENDING")
    replacement.result.return_value = replacement

    def start_replacement(**kwargs: object) -> None:
        replacement.state = "RUNNING"

    replacement.reload.side_effect = start_replacement
    sdk = MagicMock(project="test-project")
    sdk.load_table_from_file.side_effect = [job, replacement]
    client = BigQueryClient(sdk)
    table = BigQueryTable("events", (), parents=("test-project", "test_dataset"))

    result = await client.load_file(io.BytesIO(), "JSONLines", table, timeout=0.5)

    assert result is (replacement if terminal_failure else job)
    assert sdk.load_table_from_file.call_count == (2 if terminal_failure else 1)
    assert job.result.call_count == (1 if terminal_failure else 2)
    replacement.cancel.assert_not_called()


@pytest.mark.asyncio
async def test_load_does_not_retry_permanent_job_failure(clock: MagicMock) -> None:
    job = MagicMock(spec=bigquery.LoadJob, state="DONE", error_result={"reason": "invalid"})
    job.result.side_effect = BadRequest("invalid source data")
    sdk = MagicMock(project="test-project")
    sdk.load_table_from_file.return_value = job
    client = BigQueryClient(sdk)
    table = BigQueryTable("events", (), parents=("test-project", "test_dataset"))

    with pytest.raises(BadRequest, match="invalid source data"):
        await client.load_file(io.BytesIO(), "JSONLines", table)

    sdk.load_table_from_file.assert_called_once()
