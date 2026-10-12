"""Tests for `run_query_to_s3` — the per-query gather activity.

The dispatch path (period vs snapshot) and result persistence are
verified end-to-end against real MinIO via the `minio_workflow_ctx`
fixture; only the failure-propagation test mocks `object_storage.write`
so we can assert it was *never* called.
"""

import json
import asyncio
from datetime import datetime
from threading import Event

import pytest
from unittest.mock import patch

from asgiref.sync import sync_to_async
from temporalio.testing import ActivityEnvironment

from posthog.storage import object_storage
from posthog.temporal.tests.usage_report.test_aggregator import _ctx
from posthog.temporal.usage_report import storage
from posthog.temporal.usage_report.activities import run_query_to_s3
from posthog.temporal.usage_report.queries import QuerySpec
from posthog.temporal.usage_report.storage import queries_key
from posthog.temporal.usage_report.types import RunQueryToS3Inputs, WorkflowContext


@pytest.mark.asyncio
async def test_query_persists_while_thread_sensitive_executor_is_busy(
    activity_environment: ActivityEnvironment,
) -> None:
    started = asyncio.Event()
    release = Event()
    loop = asyncio.get_running_loop()

    def occupy_shared_thread() -> None:
        loop.call_soon_threadsafe(started.set)
        release.wait()

    def query(begin: datetime, end: datetime) -> list[tuple[int, int]]:
        return [(1, 17)]

    blocker = asyncio.create_task(sync_to_async(occupy_shared_thread)())
    try:
        await asyncio.wait_for(started.wait(), timeout=10)
        with (
            patch.dict(
                "posthog.temporal.usage_report.activities.QUERY_INDEX",
                {"test_query": QuerySpec(name="test_query", fn=query)},
            ),
            patch("posthog.storage.object_storage.write") as write,
        ):
            result = await asyncio.wait_for(
                activity_environment.run(run_query_to_s3, RunQueryToS3Inputs(ctx=_ctx(), query_name="test_query")),
                timeout=10,
            )
        assert result.query_name == "test_query"
        assert write.call_args.args[0] == result.s3_key
        assert json.loads(write.call_args.args[1]) == [[1, 17]]
    finally:
        release.set()
        await blocker


@pytest.mark.asyncio
async def test_run_query_to_s3_calls_fn_with_period_and_writes_to_s3(
    minio_workflow_ctx: WorkflowContext, activity_environment
) -> None:
    """Period specs receive (begin, end) and the result lands in MinIO."""
    seen_periods: list[tuple[datetime, datetime]] = []

    def fake_query(begin: datetime, end: datetime) -> list[tuple[int, int]]:
        seen_periods.append((begin, end))
        return [(1, 100), (2, 50)]

    fake_spec = QuerySpec(name="test_query_metric", fn=fake_query)

    with patch.dict(
        "posthog.temporal.usage_report.activities.QUERY_INDEX",
        {"test_query_metric": fake_spec},
        clear=False,
    ):
        result = await activity_environment.run(
            run_query_to_s3,
            RunQueryToS3Inputs(ctx=minio_workflow_ctx, query_name="test_query_metric"),
        )

    # Period passed through verbatim from WorkflowContext.
    assert seen_periods == [(minio_workflow_ctx.period_start, minio_workflow_ctx.period_end)]

    # Result advertises the right key + name; duration is non-negative.
    assert result.query_name == "test_query_metric"
    assert result.s3_key == queries_key(minio_workflow_ctx, "test_query_metric")
    assert result.duration_ms >= 0

    # And the returned key actually has the rows in MinIO.
    body = object_storage.read_bytes(result.s3_key, bucket=storage.bucket())
    assert body is not None
    # `default=str` coerces tuples to lists during JSON encoding.
    assert json.loads(body) == [[1, 100], [2, 50]]


@pytest.mark.asyncio
async def test_run_query_to_s3_snapshot_kind_calls_fn_without_period(
    minio_workflow_ctx: WorkflowContext, activity_environment
) -> None:
    """Snapshot specs declare zero-arg fns — the activity must dispatch
    them without the period, otherwise we'd get a TypeError.
    """
    fn_args: list[tuple] = []

    def fake_snapshot_query() -> list[dict[str, int]]:
        fn_args.append(())
        return [{"team_id": 1, "total": 7}]

    fake_spec = QuerySpec(
        name="test_snapshot_count",
        fn=fake_snapshot_query,
        kind="snapshot",
    )

    with patch.dict(
        "posthog.temporal.usage_report.activities.QUERY_INDEX",
        {"test_snapshot_count": fake_spec},
        clear=False,
    ):
        result = await activity_environment.run(
            run_query_to_s3,
            RunQueryToS3Inputs(ctx=minio_workflow_ctx, query_name="test_snapshot_count"),
        )

    assert fn_args == [()], "Snapshot fn should be invoked with no positional args"
    assert result.query_name == "test_snapshot_count"
    body = object_storage.read_bytes(result.s3_key, bucket=storage.bucket())
    assert body is not None
    assert json.loads(body) == [{"team_id": 1, "total": 7}]


@pytest.mark.asyncio
async def test_run_query_to_s3_propagates_query_failure(
    minio_workflow_ctx: WorkflowContext, activity_environment
) -> None:
    """If the underlying query raises, the activity must raise and not
    write a partial / stale object — otherwise re-runs would skip the
    gather. We mock `write` so we can assert it was *never* called.
    """

    def boom(begin: datetime, end: datetime) -> None:
        raise RuntimeError("boom")

    fake_spec = QuerySpec(name="test_failing_query", fn=boom)

    with (
        patch.dict(
            "posthog.temporal.usage_report.activities.QUERY_INDEX",
            {"test_failing_query": fake_spec},
            clear=False,
        ),
        patch("posthog.temporal.usage_report.storage.object_storage.write") as mock_write,
    ):
        with pytest.raises(Exception, match="boom"):
            await activity_environment.run(
                run_query_to_s3,
                RunQueryToS3Inputs(ctx=minio_workflow_ctx, query_name="test_failing_query"),
            )

    mock_write.assert_not_called()
