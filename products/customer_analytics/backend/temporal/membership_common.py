import json
import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import field
from datetime import datetime, timedelta
from time import monotonic
from typing import Literal

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
from temporalio.exceptions import CancelledError

with workflow.unsafe.imports_passed_through():
    from django.conf import settings

    from posthog.dataclasses import frozen
    from posthog.scheduling.jitter import deterministic_offset
    from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists

HEARTBEAT_TIMEOUT = timedelta(minutes=1)
BATCH_RETRY_ATTEMPTS = 3
BATCH_RETRY_DELAY = timedelta(seconds=20)
MIN_TEAM_RUN_BUDGET = HEARTBEAT_TIMEOUT * (BATCH_RETRY_ATTEMPTS + 1) + BATCH_RETRY_DELAY * (BATCH_RETRY_ATTEMPTS - 1)
BATCH_RETRY_POLICY = RetryPolicy(
    maximum_attempts=BATCH_RETRY_ATTEMPTS,
    initial_interval=BATCH_RETRY_DELAY,
    backoff_coefficient=1,
)


@frozen(frozen=False)
class MembershipRunSummary:
    counts: dict[str, int] = field(default_factory=dict)
    stop_reason: Literal["completed", "time_budget", "batch_limit", "team_page_limit", "failure", "cancelled"] = (
        "completed"
    )

    def add_counts(self, **counts: int) -> None:
        for name, value in counts.items():
            self.counts[name] = self.counts.get(name, 0) + value


@contextmanager
def record_membership_run(
    job: Literal["discovery", "deletion"],
    scope: Literal["team", "coordinator"],
    *,
    team_id: int | None = None,
    dry_run: bool | None = None,
    deletion_enabled: bool | None = None,
) -> Iterator[MembershipRunSummary]:
    started = workflow.now()
    summary = MembershipRunSummary()
    outcome = "success"
    try:
        yield summary
    except (asyncio.CancelledError, CancelledError):
        outcome = "cancelled"
        summary.stop_reason = "cancelled"
        raise
    except BaseException:
        outcome = "failure"
        summary.stop_reason = "failure"
        raise
    finally:
        if outcome == "success" and (summary.counts.get("teams_failed", 0) or summary.counts.get("failed_batches", 0)):
            outcome = "partial_failure"
        fields: dict[str, object] = {
            "job": job,
            "scope": scope,
            "team_id": team_id,
            "dry_run": dry_run,
            "deletion_enabled": deletion_enabled,
            "duration_seconds": (workflow.now() - started).total_seconds(),
            "outcome": outcome,
            "stop_reason": summary.stop_reason,
            **summary.counts,
        }
        # The stdlib formatter drops extra fields, so keep the summary in the message too.
        workflow.logger.info(
            "membership_run_summary %s",
            json.dumps(fields, sort_keys=True),
            extra=fields,
        )


def get_membership_run_deadline(run_budget: timedelta) -> datetime:
    info = workflow.info()
    return info.start_time + min(run_budget, info.execution_timeout or run_budget)


def get_membership_activity_timeout(deadline: datetime) -> timedelta | None:
    remaining = deadline - workflow.now()
    timeout = (remaining - HEARTBEAT_TIMEOUT - BATCH_RETRY_DELAY * (BATCH_RETRY_ATTEMPTS - 1)) // BATCH_RETRY_ATTEMPTS
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
