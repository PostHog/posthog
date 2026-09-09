"""Prometheus metrics, structured logs, and traces for the alerts product workers.

The evaluation and delivery fleets run on dedicated queues, so this interceptor instruments every
activity on both of them instead of matching activity names. New activities become observable as
soon as they are registered.

Temporal adds `namespace`, `task_queue`, and `activity_type` to the activity meter, so one
histogram separates the two fleets without extra attributes.
"""

import typing

from django.conf import settings

from temporalio.worker import ActivityInboundInterceptor, ExecuteActivityInput, Interceptor

from posthog.temporal.common.metrics import ExecutionTimeRecorder

ALERTS_PRODUCT_TASK_QUEUES = (
    settings.ALERTS_PRODUCT_EVALUATION_TASK_QUEUE,
    settings.ALERTS_PRODUCT_DELIVERY_TASK_QUEUE,
)

EXECUTION_LATENCY_HISTOGRAM = "alerts_product_activity_execution_latency"

# `posthog/temporal/common/worker.py` registers these boundaries for the two queues above, and the
# names must match or the histograms keep Temporal's defaults. The second entry is Temporal's own
# per-attempt queue-wait histogram. It carries the queue but not the activity type, so a queue with
# more than one activity cannot separate their queue waits. Its default buckets stop at 10 seconds,
# which cannot separate a 30-second backlog from a 30-minute one, so the fleets retune it instead of
# emitting a second series that measures the same thing.
ALERTS_PRODUCT_LATENCY_HISTOGRAM_METRICS = (
    EXECUTION_LATENCY_HISTOGRAM,
    "temporal_activity_schedule_to_start_latency",
)

# One bucket set for both histograms. The low end resolves the noop activities, which finish in
# milliseconds. The high end reaches 30 minutes as headroom for the real activities that replace
# the noops. Until then the 30-second schedule-to-close timeout in `workflows.py` caps what queue
# wait can record, because the server fails a task that waits longer than that deadline and no
# worker receives it. A longer wait removes the sample instead of producing a large one.
ALERTS_PRODUCT_LATENCY_HISTOGRAM_BUCKETS = [
    50.0,  # 50ms
    100.0,  # 100ms
    250.0,  # 250ms
    500.0,  # 500ms
    1_000.0,  # 1s
    5_000.0,  # 5s
    10_000.0,  # 10s (activity start-to-close timeout)
    30_000.0,  # 30s (activity schedule-to-close timeout)
    60_000.0,  # 1m
    300_000.0,  # 5m
    1_800_000.0,  # 30m
]


class AlertsProductMetricsInterceptor(Interceptor):
    """Interceptor emitting telemetry for the alerts product evaluation and delivery workers."""

    # `is_task_queue_supported` in `posthog/temporal/common/interceptor.py` filters an interceptor
    # without this attribute out of every worker.
    task_queue = ALERTS_PRODUCT_TASK_QUEUES

    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        return _AlertsProductActivityInterceptor(super().intercept_activity(next))


class _AlertsProductActivityInterceptor(ActivityInboundInterceptor):
    async def execute_activity(self, input: ExecuteActivityInput) -> typing.Any:
        # Temporal's own `temporal_activity_execution_latency` has no outcome label and writes no
        # log. `ExecutionTimeRecorder` adds `status` and `exception` to the histogram, so outcome
        # rates read off its count, and `log=True` writes one structured record for each activity.
        with ExecutionTimeRecorder(
            EXECUTION_LATENCY_HISTOGRAM,
            description="Execution latency for alerts product activities.",
            log=True,
        ):
            return await super().execute_activity(input)
