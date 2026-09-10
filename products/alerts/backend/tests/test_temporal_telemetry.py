import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, Mock

from django.conf import settings

from opentelemetry import trace
from temporalio.api.common.v1 import Payload
from temporalio.exceptions import CancelledError
from temporalio.testing import ActivityEnvironment
from temporalio.worker import ActivityInboundInterceptor, ExecuteActivityInput

from posthog.temporal.common.interceptor import is_task_queue_supported
from posthog.temporal.common.worker import ALL_INTERCEPTOR_CLASSES

from products.alerts.backend.facade.temporal import AlertsProductTelemetryInterceptor
from products.alerts.backend.temporal import telemetry


@pytest.mark.parametrize(
    "error,outcome,level",
    [
        (None, "success", "info"),
        (ValueError("sensitive exception message"), "failure", "warning"),
        (asyncio.CancelledError("sensitive cancellation message"), "cancellation", "info"),
        (CancelledError("sensitive cancellation message"), "cancellation", "info"),
    ],
)
@pytest.mark.parametrize("tracing_enabled", [False, True])
async def test_activity_attempt_logs(error, outcome, level, tracing_enabled, activity_logs, span_exporter, monkeypatch):
    environment = ActivityEnvironment()
    downstream = Mock(spec=ActivityInboundInterceptor)
    result = object()
    downstream.execute_activity = AsyncMock(return_value=result, side_effect=error)
    interceptor = AlertsProductTelemetryInterceptor().intercept_activity(downstream)
    activity_input = ExecuteActivityInput(
        fn=downstream.execute_activity,
        args=["sensitive activity input"],
        executor=None,
        headers={"private": Payload(data=b"sensitive header")},
    )
    monkeypatch.setattr(telemetry, "time", SimpleNamespace(monotonic=Mock(side_effect=[1.0, 1.125, 2.0, 2.5])))
    span = (
        trace.get_tracer(__name__).start_span("test-activity")
        if tracing_enabled
        else trace.NonRecordingSpan(trace.INVALID_SPAN_CONTEXT)
    )
    with trace.use_span(span, end_on_exit=True):
        for attempt in (1, 2):
            environment.info = replace(environment.info, attempt=attempt)
            if error is None:
                assert await environment.run(interceptor.execute_activity, activity_input) is result
            else:
                with pytest.raises(type(error)) as caught:
                    await environment.run(interceptor.execute_activity, activity_input)
                assert caught.value is error

    assert len(activity_logs) == 4
    for attempt, duration_ms in ((1, 125.0), (2, 500.0)):
        start, finish = activity_logs[(attempt - 1) * 2 : attempt * 2]
        assert start["event"] == "alerts_product_activity_started"
        assert start["log_level"] == "info"
        assert "duration_ms" not in start
        assert "outcome" not in start
        assert finish["event"] == "alerts_product_activity_finished"
        assert finish["log_level"] == level
        assert finish["outcome"] == outcome
        assert finish["duration_ms"] == duration_ms
        if outcome == "failure":
            assert finish["exception_type"] == "ValueError"
        else:
            assert "exception_type" not in finish
        for entry in (start, finish):
            assert entry["attempt"] == attempt
            for field in (
                "activity_id",
                "activity_type",
                "task_queue",
                "workflow_id",
                "workflow_namespace",
                "workflow_run_id",
                "workflow_type",
            ):
                assert entry[field] == getattr(environment.info, field)
            if tracing_enabled:
                assert entry["trace_id"] == trace.format_trace_id(span.get_span_context().trace_id)
                assert entry["span_id"] == trace.format_span_id(span.get_span_context().span_id)
            else:
                assert "trace_id" not in entry
                assert "span_id" not in entry
            assert "exc_info" not in entry
            assert "exception" not in entry
    assert "sensitive" not in str(activity_logs)


@pytest.mark.parametrize("error", [None, ValueError("original error"), asyncio.CancelledError(), CancelledError()])
@pytest.mark.parametrize("failure_point", ["start", "finish", "trace", "clock"])
async def test_telemetry_failure_preserves_activity_outcome(error, failure_point, activity_logs, monkeypatch):
    environment = ActivityEnvironment()
    downstream = Mock(spec=ActivityInboundInterceptor)
    result = object()
    downstream.execute_activity = AsyncMock(return_value=result, side_effect=error)
    interceptor = AlertsProductTelemetryInterceptor().intercept_activity(downstream)
    activity_input = ExecuteActivityInput(fn=downstream.execute_activity, args=[], executor=None, headers={})
    telemetry_error = RuntimeError("telemetry unavailable")
    if failure_point in ("start", "finish"):
        calls = 0

        def failing_log(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == (1 if failure_point == "start" else 2):
                raise telemetry_error

        monkeypatch.setattr(telemetry, "LOGGER", SimpleNamespace(info=failing_log, warning=failing_log))
    elif failure_point == "trace":
        monkeypatch.setattr(telemetry, "trace", SimpleNamespace(get_current_span=Mock(side_effect=telemetry_error)))
    else:
        monkeypatch.setattr(telemetry, "time", SimpleNamespace(monotonic=Mock(side_effect=telemetry_error)))

    if error is None:
        assert await environment.run(interceptor.execute_activity, activity_input) is result
    else:
        with pytest.raises(type(error)) as caught:
            await environment.run(interceptor.execute_activity, activity_input)
        assert caught.value is error
    downstream.execute_activity.assert_awaited_once_with(activity_input)


@pytest.mark.parametrize(
    "task_queue,supported",
    [
        (settings.ALERTS_PRODUCT_EVALUATION_TASK_QUEUE, True),
        (settings.ALERTS_PRODUCT_DELIVERY_TASK_QUEUE, True),
        (settings.LOGS_ALERTING_TASK_QUEUE, False),
        ("unrelated-task-queue", False),
    ],
)
def test_telemetry_registration(task_queue, supported):
    registered = [
        interceptor
        for interceptor in ALL_INTERCEPTOR_CLASSES
        if interceptor is AlertsProductTelemetryInterceptor and is_task_queue_supported(task_queue, interceptor)
    ]
    assert registered == ([AlertsProductTelemetryInterceptor] if supported else [])
