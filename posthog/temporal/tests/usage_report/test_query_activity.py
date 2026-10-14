"""Tests for `run_query_to_s3` — the per-query gather activity.

The dispatch path (period vs snapshot) and result persistence are
verified end-to-end against real MinIO via the `minio_workflow_ctx`
fixture; only the failure-propagation test mocks `object_storage.write`
so we can assert it was *never* called.
"""

import json
import asyncio
import dataclasses
from datetime import UTC, datetime

import pytest
from unittest.mock import patch

from posthog.storage import object_storage
from posthog.temporal.usage_report import storage
from posthog.temporal.usage_report.activities import fetch_usage_counter_report, run_query_to_s3
from posthog.temporal.usage_report.queries import QuerySpec
from posthog.temporal.usage_report.storage import queries_key
from posthog.temporal.usage_report.types import RunQueryToS3Inputs, WorkflowContext
from posthog.usage_counters import UsageCounter, UsageCounterMode, UsageCounterPlan, UsageCounterReport
from posthog.utils import DayRange


@pytest.mark.asyncio
async def test_fetch_usage_counter_report_converts_off_the_event_loop(activity_environment) -> None:
    period = DayRange(start=datetime(2026, 5, 4, tzinfo=UTC), end=datetime(2026, 5, 5, tzinfo=UTC))
    ctx = WorkflowContext(
        run_id="counter-report-test",
        workflow_started_at=period.end,
        period_start=period.start,
        period_end=period.end,
        date_str="2026-05-04",
        usage_counter_plan=UsageCounterPlan(
            period=period,
            caller="usage_reports_v2",
            modes={UsageCounter.EVENTS: UsageCounterMode.LEGACY},
            complete=True,
        ),
    )
    report = UsageCounterReport(counts={UsageCounter.EVENTS: [(1, 7)]})
    asdict = dataclasses.asdict

    def convert_report(value: UsageCounterReport) -> dict[str, object]:
        with pytest.raises(RuntimeError, match="no running event loop"):
            asyncio.get_running_loop()
        return asdict(value)

    with (
        patch("posthog.temporal.usage_report.activities.UsageCounterService.fetch_report", return_value=report),
        patch("posthog.temporal.usage_report.activities.dataclasses.asdict", side_effect=convert_report),
        patch("posthog.temporal.usage_report.storage.object_storage.write") as write,
    ):
        result = await activity_environment.run(fetch_usage_counter_report, ctx)

    assert result.query_name == "usage_counters"
    assert result.s3_key == queries_key(ctx, "usage_counters")
    write.assert_called_once()
    assert write.call_args.args[0] == result.s3_key
    assert json.loads(write.call_args.args[1]) == {
        "counts": {UsageCounter.EVENTS.value: [[1, 7]]},
        "usage_sources": None,
        "counter_comparisons": None,
    }


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
