import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

from unittest.mock import AsyncMock, patch

from django.test import SimpleTestCase

from asgiref.sync import async_to_sync
from parameterized import parameterized
from temporalio import activity, workflow
from temporalio.client import ScheduleOverlapPolicy
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker
from temporalio.workflow import ParentClosePolicy

from products.data_quality.backend.logic.contracts import ClaimedScheduleBatch, DueSchedule
from products.data_quality.backend.temporal import schedule as schedules
from products.data_quality.backend.temporal.contracts import (
    AcknowledgeScheduleInputs,
    ClaimDueSchedulesInputs,
    RunCheckSuiteInputs,
)
from products.data_quality.backend.temporal.workflows.dispatch_scheduled_suites import DispatchScheduledSuitesWorkflow


class TestDispatchScheduledSuites(SimpleTestCase):
    @parameterized.expand([("already_started",), ("start_failed",)])
    def test_full_disabled_chunk_continues_and_children_survive_dispatcher(self, first_start: str) -> None:
        now = datetime(2026, 1, 1, 12, tzinfo=UTC)
        metric_id = UUID(int=10)
        first = DueSchedule(
            team_id=1, schedule_id=UUID(int=1), subject_type="metric", subject_uuid=metric_id, fire_at=now
        )
        second = DueSchedule(
            team_id=1, schedule_id=UUID(int=2), subject_type="metric", subject_uuid=metric_id, fire_at=now
        )
        execute = AsyncMock(
            side_effect=[
                ClaimedScheduleBatch(claimed_count=100, schedules=[], next_cursor=first),
                ClaimedScheduleBatch(claimed_count=2, schedules=[first, second], next_cursor=second),
                True,
                True,
            ]
        )
        first_error = (
            WorkflowAlreadyStartedError("existing", "data-quality-run-suite")
            if first_start == "already_started"
            else RuntimeError("Child start failed")
        )
        start = AsyncMock(side_effect=[first_error, None])
        with (
            patch.object(workflow, "execute_activity", execute),
            patch.object(workflow, "start_child_workflow", start),
            patch.object(workflow, "now", return_value=now),
            patch.object(workflow.logger, "info") as log,
            patch.object(workflow.logger, "exception"),
        ):
            result = async_to_sync(DispatchScheduledSuitesWorkflow().run)()
        assert (result.claimed, result.started) == (102, 1)
        assert execute.await_count == (4 if first_start == "already_started" else 3)
        assert execute.await_args_list[1].args[1].after == first
        acknowledged = [call.args[1].occurrence for call in execute.await_args_list[2:]]
        assert acknowledged == ([first, second] if first_start == "already_started" else [second])
        assert start.await_count == 2
        first_call, second_call = start.await_args_list
        assert (
            first_call.kwargs["id"]
            == "data-quality-scheduled-00000000-0000-0000-0000-000000000001-2026-01-01T12:00:00+00:00"
        )
        assert second_call.kwargs["parent_close_policy"] == ParentClosePolicy.ABANDON
        assert second_call.kwargs["id_reuse_policy"] == WorkflowIDReusePolicy.REJECT_DUPLICATE
        assert second_call.args[1].trigger == "scheduled"
        assert second_call.args[1].metric_ids == [str(metric_id)]
        assert second_call.args[1].schedule_id == str(second.schedule_id)
        assert log.call_args.kwargs["extra"] == {"claimed": 102, "started": 1}

    def test_global_dispatch_schedule_runs_every_fifteen_minutes_without_overlap(self) -> None:
        with (
            patch.object(schedules, "a_schedule_exists", AsyncMock(return_value=False)),
            patch.object(schedules, "a_create_schedule", AsyncMock()) as create,
        ):
            async_to_sync(schedules.create_dispatch_scheduled_data_quality_suites_schedule)(AsyncMock())
        schedule = create.call_args.args[2]
        assert schedule.spec.cron_expressions == ["*/15 * * * *"]
        assert schedule.policy.overlap == ScheduleOverlapPolicy.SKIP
        assert schedule.action.workflow == "data-quality-dispatch-scheduled-suites"


@workflow.defn(name="data-quality-run-suite")
class CompletedScheduledSuite:
    @workflow.run
    async def run(self, inputs: RunCheckSuiteInputs) -> None:
        await workflow.execute_activity("record_scheduled_execution", start_to_close_timeout=timedelta(seconds=10))


class TestDispatchRetryDelivery(SimpleTestCase):
    @parameterized.expand(
        [("before_start",), ("before_acknowledgement",), ("after_acknowledgement",), ("termination",)]
    )
    def test_occurrence_is_delivered_once_across_failures(self, failure: str) -> None:
        async_to_sync(self._exercise_delivery)(failure)

    async def _exercise_delivery(self, failure: str) -> None:
        now = datetime(2026, 1, 1, 12, tzinfo=UTC)
        occurrence = DueSchedule(
            team_id=1, schedule_id=UUID(int=1), subject_type="metric", subject_uuid=UUID(int=10), fire_at=now
        )
        acknowledged = False
        executions = 0
        acknowledgement_attempts = 0
        acknowledgement_entered = asyncio.Event()
        release_acknowledgement = asyncio.Event()

        @activity.defn(name="claim_due_schedules_activity")
        async def read_due(inputs: ClaimDueSchedulesInputs) -> ClaimedScheduleBatch:
            if failure == "before_start" and activity.info().attempt == 1:
                raise RuntimeError("Due batch response lost")
            if acknowledged:
                return ClaimedScheduleBatch(claimed_count=0, schedules=[])
            return ClaimedScheduleBatch(claimed_count=1, schedules=[occurrence], next_cursor=occurrence)

        @activity.defn(name="acknowledge_schedule_activity")
        async def acknowledge(inputs: AcknowledgeScheduleInputs) -> bool:
            nonlocal acknowledged, acknowledgement_attempts
            acknowledgement_attempts += 1
            if acknowledgement_attempts == 1:
                if failure == "before_acknowledgement":
                    raise RuntimeError("Acknowledgement not committed")
                if failure == "termination":
                    acknowledgement_entered.set()
                    await release_acknowledgement.wait()
                    return False
            previous = acknowledged
            acknowledged = True
            if failure == "after_acknowledgement" and acknowledgement_attempts == 1:
                raise RuntimeError("Acknowledgement response lost")
            return not previous

        @activity.defn(name="record_scheduled_execution")
        async def record_execution() -> None:
            nonlocal executions
            executions += 1

        async with await WorkflowEnvironment.start_time_skipping() as environment:
            async with Worker(
                environment.client,
                task_queue="test-scheduled-delivery",
                workflows=[DispatchScheduledSuitesWorkflow, CompletedScheduledSuite],
                activities=[read_due, acknowledge, record_execution],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                first = await environment.client.start_workflow(
                    DispatchScheduledSuitesWorkflow.run, id="first-dispatch", task_queue="test-scheduled-delivery"
                )
                child_id = f"data-quality-scheduled-{occurrence.schedule_id}-{occurrence.fire_at.isoformat()}"
                if failure == "termination":
                    await asyncio.wait_for(acknowledgement_entered.wait(), timeout=20)
                    await environment.client.get_workflow_handle(child_id).result()
                    await first.terminate()
                    release_acknowledgement.set()
                else:
                    await first.result()
                    await environment.client.get_workflow_handle(child_id).result()
                await environment.client.execute_workflow(
                    DispatchScheduledSuitesWorkflow.run, id="retry-dispatch", task_queue="test-scheduled-delivery"
                )
                assert acknowledged
                assert executions == 1
                if failure != "before_start":
                    assert acknowledgement_attempts >= 2
