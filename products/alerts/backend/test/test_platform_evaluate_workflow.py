import uuid
from collections.abc import AsyncIterator

import pytest
from unittest.mock import patch

from django.conf import settings

import pytest_asyncio
from temporalio import activity, converter
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

    @activity.defn(name="plan_platform_insight_round_activity")
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


async def test_a_batch_over_the_payload_budget_records_in_chunks_and_starts_one_delivery_per_check(
    environment: WorkflowEnvironment,
) -> None:
    recorded: list[SourceOutcomeInputs] = []

    @activity.defn(name="plan_platform_insight_round_activity")
    async def plan(inputs: InsightBatchPlanInputs) -> list[str]:
        return list(ADMITTED)

    @activity.defn(name="evaluate_platform_insight_check_activity")
    async def evaluate(inputs: InsightCheckInputs) -> SourceBatchEvaluation | None:
        outcome = PlatformAlertOutcome(
            configuration_id=uuid.UUID(inputs.configuration_id),
            evaluation_key="slot:2026-09-16T10:00:00+00:00",
            consecutive_failures=0,
            groups=(GroupOutcome(grouping_key="", kind=AlertEventKind.FIRING, new_state="firing", notified=True),),
        )
        split = inputs.configuration_id == ADMITTED[0]
        delivery = AlertDeliveryRequest(
            source=SourceKind.INSIGHT,
            team_id=1,
            configuration_id=inputs.configuration_id,
            evaluation_key=outcome.evaluation_key,
            destination_alert_id="legacy-alert",
            event_ids_by_kind={"firing": "$insight_alert_firing"},
            overflowed=3 if split else 0,
            parts=2 if split else 1,
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
        # Room for one outcome per record, so two checks need two.
        with patch("products.alerts_platform.backend.facade.payload.MAX_BATCH_PAYLOAD_BYTES", 1):
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

    assert result == 2
    assert sorted(str(o.configuration_id) for batch in recorded for o in batch.outcomes) == list(ADMITTED)
    assert [len(batch.outcomes) for batch in recorded] == [1, 1]
    started = {}
    for event in history.events:
        if event.event_type == EventType.EVENT_TYPE_START_CHILD_WORKFLOW_EXECUTION_INITIATED:
            attributes = event.start_child_workflow_execution_initiated_event_attributes
            (request,) = converter.default().payload_converter.from_payloads(
                attributes.input.payloads, [AlertDeliveryRequest]
            )
            started[attributes.workflow_id] = (request.parts, request.overflowed)
    key = "slot:2026-09-16T10:00:00+00:00"
    assert started == {
        f"alerts-deliver-preview-{ADMITTED[0]}:{key}": (2, 3),
        f"alerts-deliver-preview-{ADMITTED[1]}:{key}": (1, 0),
    }


@pytest.mark.parametrize(
    "fail_second_plan, expected",
    [
        (
            False,
            [
                "00000000-0000-0000-0000-000000000001",
                "00000000-0000-0000-0000-000000000002",
                "00000000-0000-0000-0000-000000000003",
            ],
        ),
        # A later plan that fails stops admission, but the checks that already ran still record.
        (True, ["00000000-0000-0000-0000-000000000001"]),
    ],
)
async def test_a_batch_refills_the_slots_its_finished_checks_free(
    environment: WorkflowEnvironment, fail_second_plan: bool, expected: list[str]
) -> None:
    due = [f"00000000-0000-0000-0000-00000000000{n}" for n in range(1, 4)]
    plans: list[tuple[str, ...]] = []
    evaluated: list[str] = []
    recorded: list[SourceOutcomeInputs] = []

    # A pool of one slot: each round admits the first due check that this batch did not start.
    @activity.defn(name="plan_platform_insight_round_activity")
    async def plan(inputs: InsightBatchPlanInputs) -> list[str]:
        plans.append(inputs.exclude)
        if fail_second_plan and len(plans) == 2:
            raise ApplicationError("redis unavailable", non_retryable=True)
        if set(inputs.exclude) - set(evaluated):
            return []
        return [configuration_id for configuration_id in due if configuration_id not in inputs.exclude][:1]

    @activity.defn(name="evaluate_platform_insight_check_activity")
    async def evaluate(inputs: InsightCheckInputs) -> SourceBatchEvaluation | None:
        evaluated.append(inputs.configuration_id)
        outcome = PlatformAlertOutcome(
            configuration_id=uuid.UUID(inputs.configuration_id),
            evaluation_key="slot:2026-09-16T10:00:00+00:00",
            consecutive_failures=0,
            groups=(GroupOutcome(grouping_key="", kind=AlertEventKind.CHECK, new_state="not_firing", notified=False),),
        )
        return SourceBatchEvaluation(outcomes=(outcome,), deliveries=())

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
        result = await environment.client.execute_workflow(
            InsightAlertPlatformEvaluateWorkflow.run,
            SourceEvaluationInputs(
                source=SourceKind.INSIGHT,
                cutoff="2026-09-16T10:00:00+00:00",
                batch_key=AlertBatchKey(team_id=1, slot="2026-09-16T10:00:00+00:00"),
            ),
            id=f"test-{uuid.uuid4()}",
            task_queue=QUEUE,
        )

    assert result == len(expected)
    assert sorted(evaluated) == expected
    assert [sorted(str(o.configuration_id) for o in batch.outcomes) for batch in recorded] == [expected]


def test_the_binding_holds_the_whole_batch() -> None:
    assert source_evaluation_timeout(SourceKind.INSIGHT) > EVALUATION_BUDGET
