"""Deletes the platform's alerts on an insight after the insight is deleted, retrying each one."""

import asyncio
import datetime as dt
from itertools import batched

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

from posthog.dataclasses import frozen
from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from posthog.temporal.common.utils import close_db_connections

    from products.alerts.backend.platform_native_cleanup import (
        NATIVE_CLEANUP_WORKFLOW,
        NativeCleanupInputs,
        delete_native_alert,
        native_alert_ids,
    )

LIST_START_TO_CLOSE = dt.timedelta(seconds=30)
# A delete resolves the alert's open incidents first, which calls the providers.
DELETE_START_TO_CLOSE = dt.timedelta(minutes=2)
# Long enough to outlast a provider or database outage, after which the alert's next check switches it off.
DELETE_SCHEDULE_TO_CLOSE = dt.timedelta(days=1)
DELETE_RETRY_POLICY = RetryPolicy(
    initial_interval=dt.timedelta(seconds=30),
    backoff_coefficient=2.0,
    maximum_interval=dt.timedelta(minutes=10),
)
# Bounds the deletes in flight for one bulk delete of insights.
DELETES_AT_ONCE = 20


@frozen
class DeleteNativeAlertInputs:
    team_id: int
    configuration_id: str


@activity.defn
@close_db_connections
def list_native_insight_alerts_activity(inputs: NativeCleanupInputs) -> list[str]:
    return native_alert_ids(inputs)


@activity.defn
@close_db_connections
def delete_native_insight_alert_activity(inputs: DeleteNativeAlertInputs) -> None:
    delete_native_alert(inputs.team_id, inputs.configuration_id)


@workflow.defn(name=NATIVE_CLEANUP_WORKFLOW)
class InsightAlertNativeCleanupWorkflow(PostHogWorkflow):
    inputs_cls = NativeCleanupInputs

    @workflow.run
    async def run(self, inputs: NativeCleanupInputs) -> int:
        configuration_ids = await workflow.execute_activity(
            list_native_insight_alerts_activity,
            inputs,
            start_to_close_timeout=LIST_START_TO_CLOSE,
            retry_policy=DELETE_RETRY_POLICY,
            schedule_to_close_timeout=DELETE_SCHEDULE_TO_CLOSE,
        )
        failed = 0
        for chunk in batched(configuration_ids, DELETES_AT_ONCE, strict=False):
            results = await asyncio.gather(
                *(
                    workflow.execute_activity(
                        delete_native_insight_alert_activity,
                        DeleteNativeAlertInputs(team_id=inputs.team_id, configuration_id=configuration_id),
                        start_to_close_timeout=DELETE_START_TO_CLOSE,
                        schedule_to_close_timeout=DELETE_SCHEDULE_TO_CLOSE,
                        retry_policy=DELETE_RETRY_POLICY,
                    )
                    for configuration_id in chunk
                ),
                return_exceptions=True,
            )
            for result in results:
                # A cancellation stops the run. A delete that ran out of retries does not stop the
                # deletes after it, which would otherwise leave their alerts behind as well.
                if isinstance(result, BaseException) and not isinstance(result, ActivityError):
                    raise result
            failed += sum(isinstance(result, ActivityError) for result in results)
        if failed:
            raise ApplicationError(
                f"{failed} of {len(configuration_ids)} insight alerts with no insight row were not deleted",
                non_retryable=True,
            )
        return len(configuration_ids)


NATIVE_CLEANUP_WORKFLOWS = [InsightAlertNativeCleanupWorkflow]
NATIVE_CLEANUP_ACTIVITIES = [list_native_insight_alerts_activity, delete_native_insight_alert_activity]
