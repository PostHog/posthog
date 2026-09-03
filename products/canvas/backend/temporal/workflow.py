"""Canvas build workflow: a single activity that runs the whole build.

Durable execution replaces the Celery-era recovery machinery: a lost dispatch or a
dead worker is retried by the Temporal server within the activity retry policy,
instead of waiting for the periodic sweeper to notice a stale ``enqueued_at``.
"""

from datetime import timedelta

import temporalio.workflow
from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

with temporalio.workflow.unsafe.imports_passed_through():
    from products.canvas.backend.temporal.activities import CanvasBuildInput, run_canvas_build_activity

# Mirrors the Celery task's time_limit=330: the build itself is bounded by a 45s
# sandbox execution timeout, the rest is object-storage reads and artifact uploads.
BUILD_ACTIVITY_TIMEOUT = timedelta(seconds=330)

# run_canvas_build handles build failures internally (terminal STATUS_FAILED rows) and
# only raises for infrastructure errors worth retrying, e.g. object-storage reads; it
# also caps total executions per build at MAX_BUILD_ATTEMPTS via attempt_count.
BUILD_ACTIVITY_RETRY_POLICY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=1),
)


@workflow.defn(name="canvas-build")
class CanvasBuildWorkflow(PostHogWorkflow):
    inputs_cls = CanvasBuildInput

    @workflow.run
    async def run(self, input: CanvasBuildInput) -> None:
        await workflow.execute_activity(
            run_canvas_build_activity,
            input,
            start_to_close_timeout=BUILD_ACTIVITY_TIMEOUT,
            retry_policy=BUILD_ACTIVITY_RETRY_POLICY,
        )
