from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from ..activities.reconcile_schedules import ScheduleReconcileCursor, reconcile_metric_schedules_activity

RECONCILE_WORKFLOW_NAME = "data-quality-reconcile-metric-schedules"
PAGES_PER_WORKFLOW = 100


@workflow.defn(name=RECONCILE_WORKFLOW_NAME)
class ReconcileMetricSchedulesWorkflow(PostHogWorkflow):
    inputs_cls = ScheduleReconcileCursor

    @workflow.run
    async def run(self, cursor: ScheduleReconcileCursor) -> None:
        for _ in range(PAGES_PER_WORKFLOW):
            cursor = await workflow.execute_activity(
                reconcile_metric_schedules_activity,
                cursor,
                start_to_close_timeout=timedelta(minutes=5),
                heartbeat_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            if cursor.done:
                return
        workflow.continue_as_new(cursor)
