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

from products.alerts.backend.platform_chart_detail import (
    CHART_ASSET_ID_KEY,
    CHART_PENDING_KEY,
    CHART_RENDER_USER_ID_KEY,
    RenderedChart,
)
from products.alerts.backend.platform_source_cycle import PLATFORM_LLM_CHECKS
from products.alerts.backend.temporal.platform_evaluate import (
    EVALUATION_BUDGET,
    REAL_TIME_CHECK_HEARTBEAT_TIMEOUT,
    AdmittedInsightCheck,
    FailedInsightCheckInputs,
    InsightAlertPlatformEvaluateWorkflow,
    InsightBatchPlanInputs,
    InsightChartInputs,
    InsightCheckInputs,
    StopInsightQueriesInputs,
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


def _outcome(configuration_id: str, kind: AlertEventKind, state: str) -> PlatformAlertOutcome:
    return PlatformAlertOutcome(
        configuration_id=uuid.UUID(configuration_id),
        evaluation_key="slot:2026-09-16T10:00:00+00:00",
        consecutive_failures=0,
        groups=(GroupOutcome(grouping_key="", kind=kind, new_state=state, notified=kind != AlertEventKind.CHECK),),
    )


async def test_a_check_that_fails_does_not_stop_the_batch_recording_the_rest(environment: WorkflowEnvironment) -> None:
    recorded: list[SourceOutcomeInputs] = []
    failed: list[FailedInsightCheckInputs] = []
    stopped: list[StopInsightQueriesInputs] = []

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
        outcome = _outcome(inputs.configuration_id, AlertEventKind.FIRING, "firing")
        delivery = AlertDeliveryRequest(
            source=SourceKind.INSIGHT,
            team_id=1,
            configuration_id=inputs.configuration_id,
            evaluation_key=outcome.evaluation_key,
            destination_alert_id="legacy-alert",
            event_ids_by_kind={"firing": "$insight_alert_firing"},
        )
        return SourceBatchEvaluation(outcomes=(outcome,), deliveries=(delivery,))

    @activity.defn(name="fail_platform_insight_check_activity")
    async def fail(inputs: FailedInsightCheckInputs) -> SourceBatchEvaluation | None:
        failed.append(inputs)
        return SourceBatchEvaluation(
            outcomes=(_outcome(inputs.configuration_id, AlertEventKind.ERRORED, "errored"),), deliveries=()
        )

    @activity.defn(name="stop_platform_insight_queries_activity")
    async def stop(inputs: StopInsightQueriesInputs) -> None:
        stopped.append(inputs)

    @activity.defn(name=RECORD_OUTCOMES_ACTIVITY)
    async def record(inputs: SourceOutcomeInputs) -> int:
        recorded.append(inputs)
        return len(inputs.outcomes)

    async with (
        Worker(
            environment.client,
            task_queue=QUEUE,
            workflows=[InsightAlertPlatformEvaluateWorkflow],
            activities=[plan, evaluate, fail, stop, record],
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

    assert result == 3
    # The check with no retry left no outcome of its own, so it is recorded as errored, with the reason.
    assert [(inputs.configuration_id, inputs.error_message) for inputs in failed] == [(ADMITTED[0], "worker lost")]
    # Its one attempt's query may still run, which nothing else stops.
    assert [(inputs.configuration_id, len(inputs.query_ids)) for inputs in stopped] == [(ADMITTED[0], 1)]
    assert sorted(
        (str(o.configuration_id), o.groups[0].new_state) for batch in recorded for o in batch.outcomes
    ) == sorted([(ADMITTED[0], "errored"), (ADMITTED[1], "firing"), (AI_CHECK, "firing")])
    real_time_heartbeats = [
        event.activity_task_scheduled_event_attributes.heartbeat_timeout.ToTimedelta()
        for event in history.events
        if event.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED
        and event.activity_task_scheduled_event_attributes.activity_type.name
        == "evaluate_platform_insight_check_activity"
        and event.activity_task_scheduled_event_attributes.heartbeat_timeout.ToTimedelta()
    ]
    # Only the real-time check heartbeats, so a dead worker's check is retried inside its budget.
    assert real_time_heartbeats == [REAL_TIME_CHECK_HEARTBEAT_TIMEOUT]
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
        outcome = _outcome(inputs.configuration_id, AlertEventKind.FIRING, "firing")
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
    "fail_second_plan, pool_full_rounds, expected",
    [
        (
            False,
            0,
            [
                "00000000-0000-0000-0000-000000000001",
                "00000000-0000-0000-0000-000000000002",
                "00000000-0000-0000-0000-000000000003",
            ],
        ),
        # A later plan that fails stops admission, but the checks that already ran still record.
        (True, 0, ["00000000-0000-0000-0000-000000000001"]),
        # Other batches hold every slot at first. The batch waits for one rather than leave its checks to a later tick.
        (
            False,
            2,
            [
                "00000000-0000-0000-0000-000000000001",
                "00000000-0000-0000-0000-000000000002",
                "00000000-0000-0000-0000-000000000003",
            ],
        ),
    ],
)
async def test_a_batch_refills_the_slots_its_finished_checks_free(
    environment: WorkflowEnvironment, fail_second_plan: bool, pool_full_rounds: int, expected: list[str]
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
        if len(plans) <= pool_full_rounds:
            return []
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
        outcome = _outcome(inputs.configuration_id, AlertEventKind.CHECK, "not_firing")
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
    assert sorted(str(o.configuration_id) for batch in recorded for o in batch.outcomes) == expected


async def test_a_slow_check_does_not_hold_back_the_record_of_a_check_that_finished(
    environment: WorkflowEnvironment,
) -> None:
    fast, slow = ADMITTED
    recorded: list[str] = []
    fast_recorded = asyncio.Event()
    slow_saw_the_record: list[bool] = []

    @activity.defn(name="plan_platform_insight_checks_activity")
    async def plan(inputs: InsightBatchPlanInputs) -> list[AdmittedInsightCheck]:
        return [
            AdmittedInsightCheck(configuration_id=configuration_id, real_time=configuration_id == fast)
            for configuration_id in ADMITTED
            if configuration_id not in inputs.exclude
        ]

    @activity.defn(name="evaluate_platform_insight_check_activity")
    async def evaluate(inputs: InsightCheckInputs) -> SourceBatchEvaluation | None:
        if inputs.configuration_id == slow:
            # A batch that records only once every check ended would never set this.
            try:
                await asyncio.wait_for(fast_recorded.wait(), timeout=10)
                slow_saw_the_record.append(True)
            except TimeoutError:
                slow_saw_the_record.append(False)
        return SourceBatchEvaluation(
            outcomes=(_outcome(inputs.configuration_id, AlertEventKind.CHECK, "not_firing"),), deliveries=()
        )

    @activity.defn(name=RECORD_OUTCOMES_ACTIVITY)
    async def record(inputs: SourceOutcomeInputs) -> int:
        recorded.extend(str(outcome.configuration_id) for outcome in inputs.outcomes)
        if fast in recorded:
            fast_recorded.set()
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

    assert (result, recorded, slow_saw_the_record) == (2, [fast, slow], [True])


@pytest.mark.parametrize(
    "failed_attempts, expected_detail",
    [
        (0, {"alert_id": "legacy-alert", CHART_ASSET_ID_KEY: 7, CHART_RENDER_USER_ID_KEY: 3}),
        # The render pool was full at first, so the render waited for a slot.
        (1, {"alert_id": "legacy-alert", CHART_ASSET_ID_KEY: 7, CHART_RENDER_USER_ID_KEY: 3}),
        (None, {"alert_id": "legacy-alert"}),
    ],
)
async def test_a_firing_records_the_chart_rendered_after_its_check(
    environment: WorkflowEnvironment, failed_attempts: int | None, expected_detail: dict[str, object]
) -> None:
    events: list[str] = []
    recorded: list[SourceOutcomeInputs] = []

    @activity.defn(name="plan_platform_insight_checks_activity")
    async def plan(inputs: InsightBatchPlanInputs) -> list[AdmittedInsightCheck]:
        return [AdmittedInsightCheck(configuration_id=ADMITTED[0])] if not inputs.exclude else []

    @activity.defn(name="evaluate_platform_insight_check_activity")
    async def evaluate(inputs: InsightCheckInputs) -> SourceBatchEvaluation | None:
        events.append("check")
        outcome = PlatformAlertOutcome(
            configuration_id=uuid.UUID(inputs.configuration_id),
            evaluation_key="slot:2026-09-16T10:00:00+00:00",
            consecutive_failures=0,
            groups=(
                GroupOutcome(
                    grouping_key="",
                    kind=AlertEventKind.FIRING,
                    new_state="firing",
                    notified=True,
                    source_detail={"alert_id": "legacy-alert", CHART_PENDING_KEY: "legacy-alert"},
                ),
            ),
        )
        return SourceBatchEvaluation(outcomes=(outcome,), deliveries=())

    @activity.defn(name="render_platform_insight_chart_activity")
    async def render(inputs: InsightChartInputs) -> RenderedChart | None:
        if failed_attempts is None or activity.info().attempt <= failed_attempts:
            raise ApplicationError("render pool full")
        events.append(f"render:{inputs.alert_id}")
        return RenderedChart(asset_id=7, render_user_id=3)

    @activity.defn(name=RECORD_OUTCOMES_ACTIVITY)
    async def record(inputs: SourceOutcomeInputs) -> int:
        events.append("record")
        recorded.append(inputs)
        return len(inputs.outcomes)

    async with Worker(
        environment.client,
        task_queue=QUEUE,
        workflows=[InsightAlertPlatformEvaluateWorkflow],
        activities=[plan, evaluate, render, record],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        await environment.client.execute_workflow(
            InsightAlertPlatformEvaluateWorkflow.run,
            SourceEvaluationInputs(
                source=SourceKind.INSIGHT,
                cutoff="2026-09-16T10:00:00+00:00",
                batch_key=AlertBatchKey(team_id=1, slot="2026-09-16T10:00:00+00:00"),
            ),
            id=f"test-{uuid.uuid4()}",
            task_queue=QUEUE,
        )

    assert events == (["check", "record"] if failed_attempts is None else ["check", "render:legacy-alert", "record"])
    assert [group.source_detail for batch in recorded for o in batch.outcomes for group in o.groups] == [
        expected_detail
    ]


def test_the_binding_holds_the_whole_batch() -> None:
    assert source_evaluation_timeout(SourceKind.INSIGHT) > EVALUATION_BUDGET


async def test_a_cancelled_platform_ai_check_keeps_its_place_in_the_cap_until_its_thread_ends() -> None:
    release = threading.Event()
    started: list[str] = []

    def blocking(inputs: InsightCheckInputs, *_args: object, **_kwargs: object) -> None:
        started.append(inputs.configuration_id)
        if not inputs.owned_by_platform:
            release.wait(timeout=30)

    def check(configuration_id: str, *, owned: bool = False) -> InsightCheckInputs:
        return InsightCheckInputs(
            evaluation=SourceEvaluationInputs(
                source=SourceKind.INSIGHT,
                cutoff="2026-09-16T10:00:00+00:00",
                batch_key=AlertBatchKey(team_id=1, slot="2026-09-16T10:00:00+00:00"),
            ),
            configuration_id=configuration_id,
            held_until=0.0,
            uses_llm_detector=True,
            owned_by_platform=owned,
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
            # A check of an alert the platform owns is production's own, so the full cap does not hold it back.
            async with asyncio.timeout(10):
                await ActivityEnvironment().run(
                    evaluate_platform_insight_llm_check_activity, check("owned", owned=True)
                )
            assert "owned" in started

            release.set()
            await running
            async with asyncio.timeout(10):
                while PLATFORM_LLM_CHECKS.locked():
                    await asyncio.sleep(0.01)
    finally:
        release.set()


async def test_a_record_that_fails_while_a_check_still_runs_records_again_at_the_next_poll(
    environment: WorkflowEnvironment,
) -> None:
    fast, slow = ADMITTED
    attempts: list[list[str]] = []
    fast_attempted = asyncio.Event()

    @activity.defn(name="plan_platform_insight_checks_activity")
    async def plan(inputs: InsightBatchPlanInputs) -> list[AdmittedInsightCheck]:
        return [
            AdmittedInsightCheck(configuration_id=configuration_id)
            for configuration_id in ADMITTED
            if configuration_id not in inputs.exclude
        ]

    @activity.defn(name="evaluate_platform_insight_check_activity")
    async def evaluate(inputs: InsightCheckInputs) -> SourceBatchEvaluation | None:
        if inputs.configuration_id == slow:
            await asyncio.wait_for(fast_attempted.wait(), timeout=10)
        return SourceBatchEvaluation(
            outcomes=(_outcome(inputs.configuration_id, AlertEventKind.CHECK, "not_firing"),), deliveries=()
        )

    @activity.defn(name=RECORD_OUTCOMES_ACTIVITY)
    async def record(inputs: SourceOutcomeInputs) -> int:
        attempts.append(sorted(str(outcome.configuration_id) for outcome in inputs.outcomes))
        if len(attempts) == 1:
            fast_attempted.set()
            raise ApplicationError("database unavailable", non_retryable=True)
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

    # The failed record ended neither the batch nor the outcome it held.
    assert result == 2
    assert attempts[0] == [fast]
    assert sorted(configuration_id for attempt in attempts[1:] for configuration_id in attempt) == [fast, slow]
