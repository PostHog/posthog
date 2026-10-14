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
from posthog.temporal.tests.usage_report.test_parity import _install_in_memory_object_storage
from posthog.temporal.usage_report import storage
from posthog.temporal.usage_report.activities import fetch_usage_counter_report, run_query_to_s3
from posthog.temporal.usage_report.metrics import USAGE_REPORTS_QUERY_LATENCY
from posthog.temporal.usage_report.queries import QuerySpec
from posthog.temporal.usage_report.storage import queries_key
from posthog.temporal.usage_report.types import RunQueryToS3Inputs, WorkflowContext
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
@pytest.mark.parametrize(
    "mode,failure",
    [
        (UsageCounterMode.LEGACY, None),
        (UsageCounterMode.BOTH, None),
        (UsageCounterMode.BOTH, "legacy"),
        (UsageCounterMode.BOTH, "scan"),
        (UsageCounterMode.REALTIME, "scan"),
        (UsageCounterMode.REALTIME, "legacy"),
        (UsageCounterMode.BOTH, "write"),
    ],
)
async def test_counter_report_records_query_metrics(
    activity_environment, mode: UsageCounterMode, failure: str | None
) -> None:
    period = DayRange(start=datetime(2026, 5, 4, tzinfo=UTC), end=datetime(2026, 5, 5, tzinfo=UTC))
    ctx = WorkflowContext(
        run_id="counter-metrics-test",
        workflow_started_at=period.end,
        period_start=period.start,
        period_end=period.end,
        date_str="2026-05-04",
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
        or (failure == "legacy" and mode != UsageCounterMode.REALTIME)
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
        patch("posthog.temporal.usage_report.storage.object_storage.write") as write,
        patch("posthog.temporal.usage_report.storage.object_storage.read_bytes", return_value=None),
        patch("posthog.temporal.common.metrics.get_metric_meter") as meter,
    ):
        if failure == "write":

            def fail_report_write(key: str, *args: object, **kwargs: object) -> None:
                if key == queries_key(ctx, "usage_counters"):
                    raise RuntimeError("unavailable")

            write.side_effect = fail_report_write
        elif failure is not None:
            {"legacy": legacy, "scan": records}[failure].side_effect = RuntimeError("unavailable")
        if fails_report:
            with pytest.raises(RuntimeError, match="unavailable"):
                await activity_environment.run(fetch_usage_counter_report, ctx)
        else:
            await activity_environment.run(fetch_usage_counter_report, ctx)
            assert json.loads(write.call_args.args[1])["counts"][UsageCounter.CDP_INVOCATIONS.value] == [
                [1, 9 if mode == UsageCounterMode.REALTIME else 7]
            ]

    expected = [
        (UsageCounter.CDP_INVOCATIONS.value, "FAILED" if failure == "legacy" else "COMPLETED"),
    ]
    if not (failure == "legacy" and fails_report):
        expected.extend(
            (name, "COMPLETED") for name in ("exceptions_captured", "logs_retention_bytes", "sandbox_compute_usage")
        )
    if mode != UsageCounterMode.LEGACY and not (failure == "legacy" and fails_report):
        expected.append(("usage_records", "FAILED" if failure == "scan" else "COMPLETED"))
    expected.append(("usage_counters", "FAILED" if fails_report else "COMPLETED"))
    assert [(call.args[0]["query_name"], call.args[0]["status"]) for call in meter.call_args_list] == expected
    assert [call.args[0]["exception"] for call in meter.call_args_list] == [
        "RuntimeError" if status == "FAILED" else "" for _, status in expected
    ]
    histograms = meter.return_value.create_histogram_timedelta
    assert [call.kwargs["name"] for call in histograms.call_args_list] == [USAGE_REPORTS_QUERY_LATENCY] * len(expected)
    assert histograms.return_value.record.call_count == len(expected)


@pytest.mark.asyncio
async def test_counter_activity_reuses_successful_queries_on_retry(activity_environment, monkeypatch) -> None:
    s3 = _install_in_memory_object_storage(monkeypatch)
    period = DayRange(start=datetime(2026, 5, 4, tzinfo=UTC), end=datetime(2026, 5, 5, tzinfo=UTC))
    ctx = WorkflowContext(
        run_id="counter-retry-test",
        workflow_started_at=period.end,
        period_start=period.start,
        period_end=period.end,
        date_str="2026-05-04",
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
            await activity_environment.run(fetch_usage_counter_report, ctx)
        assert queries_key(ctx, "usage_counters") not in s3
        result = await activity_environment.run(fetch_usage_counter_report, ctx)
    events.assert_called_once()
    assert exceptions.call_count == 2
    assert json.loads(s3[result.s3_key])["counts"] == {
        UsageCounter.EVENTS.value: [[1, 7]],
        UsageCounter.EXCEPTIONS.value: [[1, 3]],
        "teams_with_web_exceptions_captured_in_period": [[1, 3]],
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
