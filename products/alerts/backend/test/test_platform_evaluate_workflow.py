import uuid
import asyncio
import threading
from collections.abc import AsyncIterator

import pytest
from unittest.mock import patch

from django.conf import settings

import pytest_asyncio
from temporalio import activity, converter
from temporalio.api.enums.v1 import EventType
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment, WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.alerts.backend.platform_source_cycle import PLATFORM_LLM_CHECKS
from products.alerts.backend.temporal.platform_evaluate import (
    EVALUATION_BUDGET,
    AdmittedInsightCheck,
    InsightAlertPlatformEvaluateWorkflow,
    InsightBatchPlanInputs,
    InsightCheckInputs,
    evaluate_platform_insight_llm_check_activity,
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
AI_CHECK = "00000000-0000-0000-0000-000000000003"


@pytest_asyncio.fixture
async def environment() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        yield env


async def test_a_check_that_fails_does_not_stop_the_batch_recording_the_rest(environment: WorkflowEnvironment) -> None:
    recorded: list[SourceOutcomeInputs] = []

    # Only the real-time and AI checks have a retry, so the same first failure loses the other one.
    @activity.defn(name="plan_platform_insight_checks_activity")
    async def plan(inputs: InsightBatchPlanInputs) -> list[AdmittedInsightCheck]:
        admitted = [
            AdmittedInsightCheck(configuration_id=ADMITTED[0]),
            AdmittedInsightCheck(configuration_id=ADMITTED[1], real_time=True),
            AdmittedInsightCheck(configuration_id=AI_CHECK, uses_llm_detector=True),
        ]
        return [check for check in admitted if check.configuration_id not in inputs.exclude]

    @activity.defn(name="evaluate_platform_insight_check_activity")
    async def evaluate(inputs: InsightCheckInputs) -> SourceBatchEvaluation | None:
        if activity.info().attempt == 1:
            raise ApplicationError("worker lost")
        return _fired(inputs)

    # Registered only on the AI queue, so an AI check routed anywhere else never runs.
    @activity.defn(name="evaluate_platform_insight_llm_check_activity")
    async def evaluate_on_the_ai_queue(inputs: InsightCheckInputs) -> SourceBatchEvaluation | None:
        if not inputs.uses_llm_detector:
            raise ApplicationError("routed without the AI flag", non_retryable=True)
        if activity.info().attempt == 1:
            raise ApplicationError("model timed out")
        return _fired(inputs)

    def _fired(inputs: InsightCheckInputs) -> SourceBatchEvaluation:
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

    async with (
        Worker(
            environment.client,
            task_queue=QUEUE,
            workflows=[InsightAlertPlatformEvaluateWorkflow],
            activities=[plan, evaluate, record],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ),
        Worker(environment.client, task_queue=settings.MAX_AI_TASK_QUEUE, activities=[evaluate_on_the_ai_queue]),
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

    assert result == 2
    assert [sorted(str(o.configuration_id) for o in batch.outcomes) for batch in recorded] == [[ADMITTED[1], AI_CHECK]]
    children = [
        event.child_workflow_execution_started_event_attributes
        for event in history.events
        if event.event_type == EventType.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_STARTED
    ]
    assert sorted(child.workflow_execution.workflow_id for child in children) == [
        f"alerts-deliver-preview-{configuration_id}:slot:2026-09-16T10:00:00+00:00"
        for configuration_id in (ADMITTED[1], AI_CHECK)
    ]
    child = await environment.client.get_workflow_handle(children[0].workflow_execution.workflow_id).describe()
    assert child.task_queue == settings.ALERTS_PLATFORM_DELIVERY_TASK_QUEUE


async def test_a_batch_over_the_payload_budget_records_in_chunks_and_starts_one_delivery_per_check(
    environment: WorkflowEnvironment,
) -> None:
    recorded: list[SourceOutcomeInputs] = []

    @activity.defn(name="plan_platform_insight_checks_activity")
    async def plan(inputs: InsightBatchPlanInputs) -> list[AdmittedInsightCheck]:
        return [
            AdmittedInsightCheck(configuration_id=configuration_id)
            for configuration_id in ADMITTED
            if configuration_id not in inputs.exclude
        ]

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
    @activity.defn(name="plan_platform_insight_checks_activity")
    async def plan(inputs: InsightBatchPlanInputs) -> list[AdmittedInsightCheck]:
        plans.append(inputs.exclude)
        if fail_second_plan and len(plans) == 2:
            raise ApplicationError("redis unavailable", non_retryable=True)
        if set(inputs.exclude) - set(evaluated):
            return []
        return [
            AdmittedInsightCheck(configuration_id=configuration_id)
            for configuration_id in due
            if configuration_id not in inputs.exclude
        ][:1]

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


async def test_a_cancelled_platform_ai_check_keeps_its_place_in_the_cap_until_its_thread_ends() -> None:
    release = threading.Event()
    started: list[str] = []

    def blocking(inputs: InsightCheckInputs, *_args: object, **_kwargs: object) -> None:
        started.append(inputs.configuration_id)
        release.wait(timeout=30)

    def check(configuration_id: str) -> InsightCheckInputs:
        return InsightCheckInputs(
            evaluation=SourceEvaluationInputs(
                source=SourceKind.INSIGHT,
                cutoff="2026-09-16T10:00:00+00:00",
                batch_key=AlertBatchKey(team_id=1, slot="2026-09-16T10:00:00+00:00"),
            ),
            configuration_id=configuration_id,
            held_until=0.0,
            uses_llm_detector=True,
        )

    first, second = ActivityEnvironment(), ActivityEnvironment()
    try:
        with patch("products.alerts.backend.temporal.platform_evaluate._evaluate_check", blocking):
            cancelled = asyncio.ensure_future(
                first.run(evaluate_platform_insight_llm_check_activity, check(ADMITTED[0]))
            )
            running = asyncio.ensure_future(
                second.run(evaluate_platform_insight_llm_check_activity, check(ADMITTED[1]))
            )
            async with asyncio.timeout(10):
                while len(started) < 2:
                    await asyncio.sleep(0.01)

            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await cancelled
            # Its thread still runs, so the parallel run still holds both of its places.
            assert PLATFORM_LLM_CHECKS.locked()

            release.set()
            await running
            async with asyncio.timeout(10):
                while PLATFORM_LLM_CHECKS.locked():
                    await asyncio.sleep(0.01)
    finally:
        release.set()
