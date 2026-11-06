from datetime import datetime, timedelta
from time import monotonic

from temporalio import activity, workflow
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
    ScheduleState,
)
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from django.conf import settings

    from posthog.scheduling.jitter import deterministic_offset
    from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists

HEARTBEAT_TIMEOUT = timedelta(minutes=1)
BATCH_RETRY_ATTEMPTS = 3
BATCH_RETRY_DELAY = timedelta(seconds=1)
MIN_TEAM_RUN_BUDGET = HEARTBEAT_TIMEOUT * (BATCH_RETRY_ATTEMPTS + 1) + BATCH_RETRY_DELAY * (BATCH_RETRY_ATTEMPTS - 1)
BATCH_RETRY_POLICY = RetryPolicy(
    maximum_attempts=BATCH_RETRY_ATTEMPTS,
    initial_interval=BATCH_RETRY_DELAY,
    backoff_coefficient=1,
)


def get_membership_run_deadline(run_budget: timedelta) -> datetime:
    info = workflow.info()
    return info.start_time + min(run_budget, info.execution_timeout or run_budget)


def get_membership_activity_timeout(deadline: datetime) -> timedelta | None:
    remaining = deadline - workflow.now()
    timeout = (remaining - HEARTBEAT_TIMEOUT - BATCH_RETRY_DELAY * (BATCH_RETRY_ATTEMPTS - 1)) / BATCH_RETRY_ATTEMPTS
    return timeout if timeout > HEARTBEAT_TIMEOUT else None


def get_membership_query_deadline() -> float:
    timeout = activity.info().start_to_close_timeout
    if timeout is None or timeout <= HEARTBEAT_TIMEOUT:
        raise ValueError("The membership activity needs time to finish after its query deadline. Increase its timeout.")
    return monotonic() + (timeout - HEARTBEAT_TIMEOUT).total_seconds()


async def create_membership_schedule(
    client: Client,
    schedule_id: str,
    execution_timeout: timedelta,
    note: str,
    input: object | None = None,
) -> None:
    if await a_schedule_exists(client, schedule_id):
        return
    await a_create_schedule(
        client,
        schedule_id,
        Schedule(
            action=ScheduleActionStartWorkflow(
                schedule_id,
                args=[] if input is None else [input],
                id=schedule_id,
                task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
                execution_timeout=execution_timeout,
                retry_policy=RetryPolicy(maximum_attempts=1),
            ),
            spec=ScheduleSpec(
                intervals=[
                    ScheduleIntervalSpec(
                        every=timedelta(hours=1), offset=deterministic_offset(schedule_id, timedelta(hours=1))
                    )
                ],
            ),
            policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
            state=ScheduleState(paused=True, note=note),
        ),
        trigger_immediately=False,
    )
