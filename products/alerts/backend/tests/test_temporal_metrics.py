import io
import urllib.request

import pytest

from django.conf import settings
from django.test import override_settings

import structlog
from parameterized import parameterized
from temporalio.runtime import PrometheusConfig, Runtime, TelemetryConfig
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.management.commands.start_temporal_worker import should_enable_otel
from posthog.temporal.common.interceptor import is_task_queue_supported
from posthog.temporal.common.logger import configure_logger
from posthog.temporal.common.worker import ALL_INTERCEPTOR_CLASSES, get_free_port

from products.alerts.backend.facade.temporal import (
    ALERTS_PRODUCT_LATENCY_HISTOGRAM_BUCKETS,
    ALERTS_PRODUCT_LATENCY_HISTOGRAM_METRICS,
    ALERTS_PRODUCT_TASK_QUEUES,
    EVALUATION_ACTIVITIES,
    AlertsProductMetricsInterceptor,
)
from products.alerts.backend.temporal.metrics import EXECUTION_LATENCY_HISTOGRAM
from products.alerts.backend.temporal.workflows import AlertsProductCheckDueWorkflow, AlertsProductInputs

# Both queue names are hardcoded, so a queue that `_set_temporal_task_queue` collapses under DEBUG
# is not a safe negative case.
UNRELATED_TASK_QUEUE = "some-other-task-queue"


class TestWorkerRegistration:
    @parameterized.expand([(queue,) for queue in ALERTS_PRODUCT_TASK_QUEUES])
    def test_interceptor_runs_on_queue(self, task_queue: str) -> None:
        assert AlertsProductMetricsInterceptor in ALL_INTERCEPTOR_CLASSES
        assert is_task_queue_supported(task_queue, AlertsProductMetricsInterceptor)

    def test_interceptor_stays_off_other_queues(self) -> None:
        assert not is_task_queue_supported(UNRELATED_TASK_QUEUE, AlertsProductMetricsInterceptor)


class TestOtelEnablement:
    @parameterized.expand([(queue,) for queue in ALERTS_PRODUCT_TASK_QUEUES])
    def test_traces_are_forced_on_queue(self, task_queue: str) -> None:
        with override_settings(OTEL_SERVICE_NAME="posthog-temporal-worker", TEMPORAL_OTEL_PLUGIN_ENABLED=False):
            assert should_enable_otel(task_queue) is True

    def test_other_queues_keep_the_setting(self) -> None:
        with override_settings(OTEL_SERVICE_NAME="posthog-temporal-worker", TEMPORAL_OTEL_PLUGIN_ENABLED=False):
            assert should_enable_otel(UNRELATED_TASK_QUEUE) is False


@pytest.mark.asyncio
class TestWorkerTelemetry:
    async def test_evaluation_queue_reports_its_activity(self) -> None:
        """Run the evaluation workflow, then read the worker's metrics endpoint and its logs.

        A mocked meter cannot show that the interceptor attaches, that the queue labels the series,
        or that a log record carries the Temporal context.
        """
        metrics_port = get_free_port()
        runtime = Runtime(
            telemetry=TelemetryConfig(
                metrics=PrometheusConfig(
                    bind_address=f"127.0.0.1:{metrics_port}",
                    durations_as_seconds=False,
                    histogram_bucket_overrides=dict.fromkeys(
                        ALERTS_PRODUCT_LATENCY_HISTOGRAM_METRICS, ALERTS_PRODUCT_LATENCY_HISTOGRAM_BUCKETS
                    ),
                )
            )
        )
        task_queue = settings.ALERTS_PRODUCT_EVALUATION_TASK_QUEUE
        logged = io.StringIO()

        try:
            configure_logger(cache_logger_on_first_use=False, file=logged)
            async with await WorkflowEnvironment.start_time_skipping(runtime=runtime) as env:
                async with Worker(
                    env.client,
                    task_queue=task_queue,
                    workflows=[AlertsProductCheckDueWorkflow],
                    activities=EVALUATION_ACTIVITIES,
                    workflow_runner=UnsandboxedWorkflowRunner(),
                    interceptors=[AlertsProductMetricsInterceptor()],
                ):
                    await env.client.execute_workflow(
                        AlertsProductCheckDueWorkflow.run,
                        AlertsProductInputs(),
                        id="test-alerts-product-worker-telemetry",
                        task_queue=task_queue,
                    )
                scraped = urllib.request.urlopen(f"http://127.0.0.1:{metrics_port}/metrics").read().decode()
        finally:
            structlog.reset_defaults()

        execution_series = [line for line in scraped.splitlines() if line.startswith(EXECUTION_LATENCY_HISTOGRAM)]
        assert execution_series
        assert all(f'task_queue="{task_queue}"' in line for line in execution_series)
        assert all('activity_type="alerts_product_check_due_activity"' in line for line in execution_series)
        assert any('status="COMPLETED"' in line for line in execution_series)
        widest_bucket = int(ALERTS_PRODUCT_LATENCY_HISTOGRAM_BUCKETS[-1])
        assert any(f'le="{widest_bucket}"' in line for line in execution_series)

        # Temporal reports queue wait itself, so the fleets retune it instead of emitting their own.
        assert "temporal_activity_schedule_to_start_latency_bucket" in scraped

        activity_logs = logged.getvalue()
        assert EXECUTION_LATENCY_HISTOGRAM in activity_logs
        assert "COMPLETED" in activity_logs
        for expected_field in ("task_queue", "activity_type", "workflow_id", "attempt"):
            assert expected_field in activity_logs
