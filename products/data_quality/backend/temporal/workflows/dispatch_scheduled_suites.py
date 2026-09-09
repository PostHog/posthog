from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.workflow import ParentClosePolicy

from posthog.temporal.common.base import PostHogWorkflow

from ...facade.contracts import CHECK_SUITE_WORKFLOW_NAME, DISPATCH_SCHEDULED_SUITES_WORKFLOW_NAME
from ...facade.enums import SubjectType, SuiteRunTrigger
from ..activities.claim_due_schedules import acknowledge_schedule_activity, claim_due_schedules_activity
from ..contracts import AcknowledgeScheduleInputs, ClaimDueSchedulesInputs, RunCheckSuiteInputs, ScheduledSuitesOutcome

SCHEDULE_CLAIM_BATCH_SIZE = 100


@workflow.defn(name=DISPATCH_SCHEDULED_SUITES_WORKFLOW_NAME)
class DispatchScheduledSuitesWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> None:
        return None

    @workflow.run
    async def run(self) -> ScheduledSuitesOutcome:
        now = workflow.now()
        claimed = started = 0
        after = None
        while True:
            batch = await workflow.execute_activity(
                claim_due_schedules_activity,
                ClaimDueSchedulesInputs(now=now, limit=SCHEDULE_CLAIM_BATCH_SIZE, after=after),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            claimed += batch.claimed_count
            accepted = list(batch.skipped_schedules)
            for schedule in batch.schedules:
                if schedule.subject_type != SubjectType.METRIC:
                    continue
                try:
                    await workflow.start_child_workflow(
                        CHECK_SUITE_WORKFLOW_NAME,
                        RunCheckSuiteInputs(
                            team_id=schedule.team_id,
                            trigger=SuiteRunTrigger.SCHEDULED,
                            metric_ids=[str(schedule.subject_uuid)],
                            schedule_id=str(schedule.schedule_id),
                        ),
                        id=f"data-quality-scheduled-{schedule.schedule_id}-{schedule.fire_at.isoformat()}",
                        parent_close_policy=ParentClosePolicy.ABANDON,
                        id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                        execution_timeout=timedelta(hours=1),
                    )
                    started += 1
                except WorkflowAlreadyStartedError:
                    pass
                except Exception:
                    workflow.logger.exception("Failed to start scheduled data quality suite")
                    continue
                accepted.append(schedule)
            for schedule in accepted:
                await workflow.execute_activity(
                    acknowledge_schedule_activity,
                    AcknowledgeScheduleInputs(occurrence=schedule, now=now),
                    start_to_close_timeout=timedelta(minutes=2),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
            after = batch.next_cursor
            if batch.claimed_count < SCHEDULE_CLAIM_BATCH_SIZE:
                break
        workflow.logger.info("Dispatched scheduled data quality suites", extra={"claimed": claimed, "started": started})
        return ScheduledSuitesOutcome(claimed=claimed, started=started)
