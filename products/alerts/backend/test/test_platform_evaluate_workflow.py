import uuid
from collections.abc import AsyncIterator

from django.conf import settings

import pytest_asyncio
from temporalio import activity
from temporalio.api.enums.v1 import EventType
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.alerts.backend.temporal.platform_evaluate import (
    EVALUATION_BUDGET,
    InsightAlertPlatformEvaluateWorkflow,
    InsightBatchPlanInputs,
    InsightCheckInputs,
)
from products.alerts_platform.backend.facade.contracts import (
    RECORD_OUTCOMES_ACTIVITY,
    AlertBatchKey,
    AlertDeliveryRequest,
    AlertEventKind,
    GroupOutcome,
    PlatformAlertOutcome,
    SourceBatchEvaluation,
    SourceEvaluationInputs,
    SourceKind,
    SourceOutcomeInputs,
)
from products.alerts_platform.backend.facade.temporal import source_evaluation_timeout

QUEUE = "test-platform-insight-evaluation"
ADMITTED = ("00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002")


@pytest_asyncio.fixture
async def environment() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        yield env


async def test_a_check_that_fails_does_not_stop_the_batch_recording_the_rest(environment: WorkflowEnvironment) -> None:
    recorded: list[SourceOutcomeInputs] = []

    @activity.defn(name="plan_platform_insight_batch_activity")
    async def plan(inputs: InsightBatchPlanInputs) -> list[str]:
        return list(ADMITTED)

    @activity.defn(name="evaluate_platform_insight_check_activity")
    async def evaluate(inputs: InsightCheckInputs) -> SourceBatchEvaluation | None:
        if inputs.configuration_id == ADMITTED[0]:
            raise ApplicationError("query failed", non_retryable=True)
        outcome = PlatformAlertOutcome(
            configuration_id=uuid.UUID(inputs.configuration_id),
            evaluation_key="slot:2026-09-16T10:00:00+00:00",
            consecutive_failures=0,
            groups=(GroupOutcome(grouping_key="", kind=AlertEventKind.FIRING, new_state="firing", notified=True),),
        )
        delivery = AlertDeliveryRequest(
            source=SourceKind.INSIGHT,
            team_id=1,
            configuration_id=inputs.configuration_id,
            evaluation_key=outcome.evaluation_key,
            destination_alert_id="legacy-alert",
            event_ids_by_kind={"firing": "$insight_alert_firing"},
        )
        return SourceBatchEvaluation(outcomes=(outcome,), deliveries=(delivery,))

    @activity.defn(name=RECORD_OUTCOMES_ACTIVITY)
    async def record(inputs: SourceOutcomeInputs) -> int:
        recorded.append(inputs)
        return len(inputs.outcomes)

    async with Worker(
        environment.client,
        task_queue=QUEUE,
        workflows=[InsightAlertPlatformEvaluateWorkflow],
        activities=[plan, evaluate, record],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        handle = await environment.client.start_workflow(
            InsightAlertPlatformEvaluateWorkflow.run,
            SourceEvaluationInputs(
                source=SourceKind.INSIGHT,
                cutoff="2026-09-16T10:00:00+00:00",
                batch_key=AlertBatchKey(team_id=1, slot="2026-09-16T10:00:00+00:00"),
            ),
            id=f"test-{uuid.uuid4()}",
            task_queue=QUEUE,
        )

        result = await handle.result()
        history = await handle.fetch_history()

    assert result == 1
    assert [[str(o.configuration_id) for o in batch.outcomes] for batch in recorded] == [[ADMITTED[1]]]
    children = [
        event.child_workflow_execution_started_event_attributes
        for event in history.events
        if event.event_type == EventType.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_STARTED
    ]
    assert [child.workflow_execution.workflow_id for child in children] == [
        f"alerts-deliver-preview-{ADMITTED[1]}:slot:2026-09-16T10:00:00+00:00"
    ]
    child = await environment.client.get_workflow_handle(children[0].workflow_execution.workflow_id).describe()
    assert child.task_queue == settings.ALERTS_PLATFORM_DELIVERY_TASK_QUEUE


def test_the_binding_holds_the_whole_batch() -> None:
    assert source_evaluation_timeout(SourceKind.INSIGHT) > EVALUATION_BUDGET
