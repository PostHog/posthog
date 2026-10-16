"""Tests for `run_query_to_s3` — the per-query gather activity.

The dispatch path (period vs snapshot) and result persistence are
verified end-to-end against real MinIO via the `minio_workflow_ctx`
fixture; only the failure-propagation test mocks `object_storage.write`
so we can assert it was *never* called.
"""

import json
import asyncio
import dataclasses
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from functools import partial
from threading import Event

import pytest
from unittest.mock import patch

from asgiref.sync import sync_to_async
from temporalio.testing import ActivityEnvironment

from posthog.storage import object_storage
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.tests.usage_report.test_aggregator import _ctx
from posthog.temporal.tests.usage_report.test_parity import _install_in_memory_object_storage
from posthog.temporal.usage_report import storage
from posthog.temporal.usage_report.activities import (
    fetch_usage_counter_report,
    plan_usage_counters,
    run_legacy_usage_counter,
    run_query_to_s3,
)
from posthog.temporal.usage_report.metrics import USAGE_REPORTS_QUERY_LATENCY
from posthog.temporal.usage_report.queries import QuerySpec
from posthog.temporal.usage_report.storage import queries_key
from posthog.temporal.usage_report.types import (
    RunLegacyCounterInputs,
    RunQueryToS3Inputs,
    RunQueryToS3Result,
    WorkflowContext,
)
from posthog.usage_counters import (
    UsageCounter,
    UsageCounterMode,
    UsageCounterPlan,
    UsageCounterReport,
    UsageRecordTotal,
    UsageRecordTotals,
)
from posthog.utils import DayRange

from products.tasks.backend.facade.billing import SandboxComputeUsageByTeam


async def _fetch_counter_report(environment: ActivityEnvironment, ctx: WorkflowContext) -> RunQueryToS3Result:
    if ctx.prepared_legacy_counters is not None:
        assert ctx.usage_counter_plan is not None
        prepared = []
        for counter in ctx.usage_counter_plan.legacy_counters:
            if await environment.run(run_legacy_usage_counter, RunLegacyCounterInputs(ctx=ctx, counter=counter)):
                prepared.append(counter)
        ctx = ctx.model_copy(update={"prepared_legacy_counters": prepared})
    return await environment.run(fetch_usage_counter_report, ctx)


@pytest.mark.asyncio
@pytest.mark.parametrize("activity_name", ["plan", "fetch"])
async def test_counter_activities_complete_while_shared_executor_is_busy(
    activity_environment, activity_name: str
) -> None:
    period = DayRange(start=datetime(2026, 5, 4, tzinfo=UTC), end=datetime(2026, 5, 5, tzinfo=UTC))
    plan = UsageCounterPlan(
        period=period,
        caller="usage_reports_v2",
        modes={UsageCounter.EVENTS: UsageCounterMode.LEGACY},
        complete=True,
    )
    ctx = WorkflowContext(
        run_id="counter-executor-test",
        workflow_started_at=period.end,
        period_start=period.start,
        period_end=period.end,
        date_str="2026-05-04",
        usage_counter_plan=plan,
    )
    started = asyncio.Event()
    release = Event()
    loop = asyncio.get_running_loop()

    def occupy_shared_thread() -> None:
        loop.call_soon_threadsafe(started.set)
        release.wait()

    blocker = asyncio.create_task(sync_to_async(occupy_shared_thread)())
    try:
        await asyncio.wait_for(started.wait(), timeout=10)
        with (
            patch("posthog.temporal.usage_report.activities.UsageCounterService.resolve_plan", return_value=plan),
            patch(
                "posthog.temporal.usage_report.activities.UsageCounterService.fetch_report",
                return_value=UsageCounterReport(counts={UsageCounter.EVENTS: [(1, 17)]}),
            ),
            patch("posthog.storage.object_storage.write") as write,
        ):
            if activity_name == "plan":
                assert await asyncio.wait_for(activity_environment.run(plan_usage_counters, ctx), timeout=10) == plan
                write.assert_not_called()
            else:
                result = await asyncio.wait_for(activity_environment.run(fetch_usage_counter_report, ctx), timeout=10)
                assert write.call_args.args[0] == result.s3_key
                assert json.loads(write.call_args.args[1])["counts"] == {UsageCounter.EVENTS.value: [[1, 17]]}
    finally:
        release.set()
        await blocker


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
@pytest.mark.parametrize("prepared", [False, True])
@pytest.mark.parametrize(
    "mode,failure",
    [
        (UsageCounterMode.LEGACY, None),
        (UsageCounterMode.BOTH, None),
        (UsageCounterMode.BOTH, "legacy"),
        (UsageCounterMode.BOTH, "scan"),
        (UsageCounterMode.REALTIME, "scan"),
        (UsageCounterMode.REALTIME, "legacy"),
        (UsageCounterMode.BOTH, "checkpoint"),
        (UsageCounterMode.REALTIME, "checkpoint"),
        (UsageCounterMode.BOTH, "write"),
    ],
)
async def test_counter_report_records_query_metrics(
    activity_environment, monkeypatch, mode: UsageCounterMode, failure: str | None, prepared: bool
) -> None:
    _install_in_memory_object_storage(monkeypatch)
    write_to_storage = object_storage.write
    period = DayRange(start=datetime(2026, 5, 4, tzinfo=UTC), end=datetime(2026, 5, 5, tzinfo=UTC))
    ctx = WorkflowContext(
        run_id="counter-metrics-test",
        workflow_started_at=period.end,
        period_start=period.start,
        period_end=period.end,
        date_str="2026-05-04",
        prepared_legacy_counters=[] if prepared else None,
        usage_counter_plan=UsageCounterPlan(
            period=period,
            caller="usage_reports_v2",
            modes={
                UsageCounter.CDP_INVOCATIONS: mode,
                UsageCounter.EXCEPTIONS: UsageCounterMode.LEGACY,
                UsageCounter.LOGS_RETENTION_30D_BYTES: UsageCounterMode.LEGACY,
                UsageCounter.SANDBOX_COMPUTE_CREDITS: UsageCounterMode.LEGACY,
            },
            complete=True,
        ),
    )
    fails_report = (
        failure == "write"
        or (failure in {"legacy", "checkpoint"} and mode != UsageCounterMode.REALTIME)
        or (failure == "scan" and mode == UsageCounterMode.REALTIME)
    )
    with (
        patch(
            "posthog.tasks.usage_report.get_teams_with_cdp_billable_invocations_in_period", return_value=[(1, 7)]
        ) as legacy,
        patch(
            "posthog.tasks.usage_report.get_usage_records_in_period",
            return_value=UsageRecordTotals(
                totals=[
                    UsageRecordTotal(
                        team_id=1, organization_id="org-a", usage_key="cdp_billable_invocations", quantity=9
                    )
                ]
            ),
        ) as records,
        patch("posthog.tasks.usage_report.get_teams_with_exceptions_captured_in_period", return_value=({}, [])),
        patch("posthog.tasks.usage_report.get_teams_with_logs_retention_bytes_in_period", return_value={"30d": []}),
        patch(
            "posthog.tasks.usage_report.get_teams_with_billable_sandbox_compute_usage_in_period",
            return_value=SandboxComputeUsageByTeam(credits=[], cpu_millicore_seconds=[], memory_mib_seconds=[]),
        ),
        patch("posthog.temporal.usage_report.storage.object_storage.write", wraps=object_storage.write) as write,
        patch("posthog.temporal.common.metrics.get_metric_meter") as meter,
    ):
        if failure in {"write", "checkpoint"}:

            def fail_write(
                key: str, content: str | bytes, extras: dict | None = None, bucket: str | None = None
            ) -> None:
                failed_query = (
                    "usage_counters" if failure == "write" else f"legacy_{UsageCounter.CDP_INVOCATIONS.value}"
                )
                if key == queries_key(ctx, failed_query):
                    raise RuntimeError("unavailable")
                write_to_storage(key, content, extras=extras, bucket=bucket)

            write.side_effect = fail_write
        elif failure is not None:
            {"legacy": legacy, "scan": records}[failure].side_effect = RuntimeError("unavailable")
        if fails_report:
            with pytest.raises(RuntimeError, match="unavailable"):
                await _fetch_counter_report(activity_environment, ctx)
        else:
            await _fetch_counter_report(activity_environment, ctx)
            assert json.loads(write.call_args.args[1])["counts"][UsageCounter.CDP_INVOCATIONS.value] == [
                [1, 9 if mode == UsageCounterMode.REALTIME else 7]
            ]
        legacy.assert_called_once()

    expected = [
        (UsageCounter.CDP_INVOCATIONS.value, "FAILED" if failure in {"legacy", "checkpoint"} else "COMPLETED"),
    ]
    if not (failure in {"legacy", "checkpoint"} and fails_report):
        expected.extend(
            (name, "COMPLETED") for name in ("exceptions_captured", "logs_retention_bytes", "sandbox_compute_usage")
        )
    if mode != UsageCounterMode.LEGACY and not (failure in {"legacy", "checkpoint"} and fails_report):
        expected.append(("usage_records", "FAILED" if failure == "scan" else "COMPLETED"))
    if not (prepared and failure in {"legacy", "checkpoint"} and fails_report):
        expected.append(("usage_counters", "FAILED" if fails_report else "COMPLETED"))
    assert [(call.args[0]["query_name"], call.args[0]["status"]) for call in meter.call_args_list] == expected
    assert [call.args[0]["exception"] for call in meter.call_args_list] == [
        "RuntimeError" if status == "FAILED" else "" for _, status in expected
    ]
    histograms = meter.return_value.create_histogram_timedelta
    assert [call.kwargs["name"] for call in histograms.call_args_list] == [USAGE_REPORTS_QUERY_LATENCY] * len(expected)
    assert histograms.return_value.record.call_count == len(expected)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_during", ["cache_read", "legacy", "checkpoint", "last_checkpoint", "scan"])
@pytest.mark.parametrize("cancel_source", ["temporal", "task"])
@pytest.mark.parametrize("prepared", [False, True])
async def test_cancelled_counter_activity_stops_background_work(
    activity_environment, monkeypatch, cancel_during: str, cancel_source: str, prepared: bool
) -> None:
    _install_in_memory_object_storage(monkeypatch)
    read_from_storage = object_storage.read_bytes
    write_to_storage = object_storage.write
    period = DayRange(start=datetime(2026, 5, 4, tzinfo=UTC), end=datetime(2026, 5, 5, tzinfo=UTC))
    modes = {UsageCounter.CDP_INVOCATIONS: UsageCounterMode.BOTH}
    if cancel_during != "last_checkpoint":
        modes[UsageCounter.EVENTS] = UsageCounterMode.LEGACY
    ctx = WorkflowContext(
        run_id="counter-cancellation-test",
        workflow_started_at=period.end,
        period_start=period.start,
        period_end=period.end,
        date_str="2026-05-04",
        prepared_legacy_counters=[] if prepared else None,
        usage_counter_plan=UsageCounterPlan(period=period, caller="usage_reports_v2", modes=modes, complete=True),
    )
    started = asyncio.Event()
    release = Event()
    loop = asyncio.get_running_loop()

    def block(stage: str) -> None:
        if cancel_during == stage:
            loop.call_soon_threadsafe(started.set)
            assert release.wait(timeout=10)

    def read_checkpoint(*args, **kwargs):
        block("cache_read")
        return read_from_storage(*args, **kwargs)

    def legacy_query(*args, **kwargs):
        block("legacy")
        return [(1, 7)]

    def write_checkpoint(key, *args, **kwargs):
        if key == queries_key(ctx, f"legacy_{UsageCounter.CDP_INVOCATIONS.value}"):
            block("checkpoint")
            block("last_checkpoint")
        write_to_storage(key, *args, **kwargs)

    def scan_records(*args, **kwargs):
        block("scan")
        return UsageRecordTotals(totals=[])

    with (
        patch(
            "posthog.tasks.usage_report.get_teams_with_cdp_billable_invocations_in_period",
            side_effect=legacy_query,
        ) as legacy,
        patch("posthog.tasks.usage_report.get_teams_with_billable_event_count_in_period", return_value=[]) as events,
        patch("posthog.tasks.usage_report.get_usage_records_in_period", side_effect=scan_records) as records,
        patch("posthog.temporal.usage_report.storage.object_storage.read_bytes", side_effect=read_checkpoint) as read,
        patch("posthog.temporal.usage_report.storage.object_storage.write", side_effect=write_checkpoint) as write,
    ):
        with ThreadPoolExecutor(max_workers=1) as executor:
            with patch(
                "posthog.temporal.usage_report.activities.database_sync_to_async_pool",
                partial(database_sync_to_async_pool, executor=executor),
            ):
                task = asyncio.create_task(_fetch_counter_report(activity_environment, ctx))
                try:
                    await asyncio.wait_for(started.wait(), timeout=10)
                    calls_at_cancellation = [mock.call_count for mock in (read, legacy, events, records, write)]
                    if cancel_source == "temporal":
                        activity_environment.cancel()
                    else:
                        task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
                finally:
                    release.set()
                    if not task.done():
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)

        assert [mock.call_count for mock in (read, legacy, events, records, write)] == calls_at_cancellation
        assert all(call.args[0] != queries_key(ctx, "usage_counters") for call in write.call_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize("prepared", [False, True])
async def test_counter_activity_reuses_successful_queries_on_retry(
    activity_environment, monkeypatch, prepared: bool
) -> None:
    s3 = _install_in_memory_object_storage(monkeypatch)
    period = DayRange(start=datetime(2026, 5, 4, tzinfo=UTC), end=datetime(2026, 5, 5, tzinfo=UTC))
    ctx = WorkflowContext(
        run_id="counter-retry-test",
        workflow_started_at=period.end,
        period_start=period.start,
        period_end=period.end,
        date_str="2026-05-04",
        prepared_legacy_counters=[] if prepared else None,
        usage_counter_plan=UsageCounterPlan(
            period=period,
            caller="usage_reports_v2",
            complete=True,
            modes={UsageCounter.EVENTS: UsageCounterMode.LEGACY, UsageCounter.EXCEPTIONS: UsageCounterMode.LEGACY},
        ),
    )
    with (
        patch(
            "posthog.tasks.usage_report.get_teams_with_billable_event_count_in_period", return_value=[(1, 7)]
        ) as events,
        patch(
            "posthog.tasks.usage_report.get_teams_with_exceptions_captured_in_period",
            side_effect=[RuntimeError("unavailable"), ({"web": [(1, 3)]}, [(1, 3)])],
        ) as exceptions,
    ):
        with pytest.raises(RuntimeError, match="unavailable"):
            await _fetch_counter_report(activity_environment, ctx)
        assert queries_key(ctx, "usage_counters") not in s3
        result = await _fetch_counter_report(activity_environment, ctx)
    events.assert_called_once()
    assert exceptions.call_count == 2
    assert json.loads(s3[result.s3_key])["counts"] == {
        UsageCounter.EVENTS.value: [[1, 7]],
        UsageCounter.EXCEPTIONS.value: [[1, 3]],
        "teams_with_web_exceptions_captured_in_period": [[1, 3]],
    }


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
