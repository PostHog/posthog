import uuid
import asyncio
from uuid import UUID

import pytest
from unittest.mock import AsyncMock, patch

import temporalio.activity
import temporalio.workflow
from temporalio.client import WorkflowHistory
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, UnsandboxedWorkflowRunner, Worker

from posthog.temporal.ai_observability.eval_reports.activities import (
    ack_eval_report_cursors_activity,
    check_count_triggered_eval_reports_activity,
    deliver_report_activity,
    fetch_count_triggered_eval_report_candidates_activity,
    fetch_due_eval_reports_activity,
    update_next_delivery_date_activity,
)
from posthog.temporal.ai_observability.eval_reports.constants import (
    CHECK_COUNT_TRIGGERED_REPORTS_WORKFLOW_NAME,
    COUNT_TRIGGER_CHECK_ACTIVITY_TIMEOUT,
    COUNT_TRIGGER_MAX_CONCURRENT_CHECKS,
    FETCH_ACTIVITY_TIMEOUT,
    FETCH_RETRY_POLICY,
    GENERATE_EVAL_REPORT_WORKFLOW_NAME,
    UPDATE_SCHEDULE_ACTIVITY_TIMEOUT,
    UPDATE_SCHEDULE_RETRY_POLICY,
    WORKFLOW_EXECUTION_TIMEOUT,
)
from posthog.temporal.ai_observability.eval_reports.types import (
    AckEvalReportCursorsInput,
    CheckCountTriggeredEvalReportOutput,
    CheckCountTriggeredEvalReportsBatchInput,
    CheckCountTriggeredEvalReportsBatchOutput,
    CheckCountTriggeredReportsWorkflowInputs,
    FetchDueEvalReportsOutput,
    GenerateAndDeliverEvalReportWorkflowInput,
    PrepareReportContextOutput,
    RunEvalReportAgentInput,
    RunEvalReportAgentOutput,
    ScheduleAllEvalReportsWorkflowInputs,
    StoreReportRunOutput,
    UpdateNextDeliveryDateInput,
)
from posthog.temporal.ai_observability.eval_reports.workflow import (
    CheckCountTriggeredReportsWorkflow,
    GenerateAndDeliverEvalReportWorkflow,
    ScheduleAllEvalReportsWorkflow,
    _check_count_triggered_eval_report_candidates,
    _check_count_triggered_eval_report_candidates_batched,
    _DueReportCandidates,
    _report_workflow_id,
    _start_report_workflow,
    _start_report_workflows,
)


# Temporal rejects a workflow class defined inside a function, so the stubs that a real
# coordinator run needs are declared at module level.
@temporalio.workflow.defn(name=GENERATE_EVAL_REPORT_WORKFLOW_NAME)
class StubReportChildWorkflow:
    @temporalio.workflow.run
    async def run(self, _inputs: GenerateAndDeliverEvalReportWorkflowInput) -> None:
        return None


# Reproduces the command order a count coordinator recorded before the windowed dispatch:
# every check window first, then the combined child starts. A history recorded by the
# workflow under test would only ever agree with itself, so the order the current code has
# to stay replay-compatible with is written out here instead.
@temporalio.workflow.defn(name=CHECK_COUNT_TRIGGERED_REPORTS_WORKFLOW_NAME)
class PreWindowedDispatchCountCoordinator:
    @temporalio.workflow.run
    async def run(self, inputs: CheckCountTriggeredReportsWorkflowInputs) -> None:
        result = await temporalio.workflow.execute_activity(
            fetch_count_triggered_eval_report_candidates_activity,
            inputs,
            start_to_close_timeout=FETCH_ACTIVITY_TIMEOUT,
            retry_policy=FETCH_RETRY_POLICY,
        )
        groups = result.report_id_groups or []
        due_report_ids: list[str] = []
        for index in range(0, len(groups), COUNT_TRIGGER_MAX_CONCURRENT_CHECKS):
            window = groups[index : index + COUNT_TRIGGER_MAX_CONCURRENT_CHECKS]
            window_results = await asyncio.gather(
                *(
                    temporalio.workflow.execute_activity(
                        check_count_triggered_eval_reports_activity,
                        CheckCountTriggeredEvalReportsBatchInput(report_ids=group),
                        start_to_close_timeout=COUNT_TRIGGER_CHECK_ACTIVITY_TIMEOUT,
                        retry_policy=FETCH_RETRY_POLICY,
                    )
                    for group in window
                )
            )
            for group_result in window_results:
                due_report_ids.extend(output.report_id for output in group_result.results if output.due)

        await asyncio.gather(
            *(
                temporalio.workflow.execute_child_workflow(
                    GenerateAndDeliverEvalReportWorkflow.run,
                    GenerateAndDeliverEvalReportWorkflowInput(report_id=report_id),
                    id=f"eval-report-count-{report_id}",
                    execution_timeout=WORKFLOW_EXECUTION_TIMEOUT,
                )
                for report_id in due_report_ids
            )
        )
        await temporalio.workflow.execute_activity(
            ack_eval_report_cursors_activity,
            AckEvalReportCursorsInput(
                trigger_type="count_triggered",
                region=inputs.region,
                cursor_before=result.cursor_before or "",
                report_ids=result.report_ids,
            ),
            start_to_close_timeout=UPDATE_SCHEDULE_ACTIVITY_TIMEOUT,
            retry_policy=UPDATE_SCHEDULE_RETRY_POLICY,
        )


@pytest.mark.asyncio
async def test_scheduled_coordinator_only_waits_for_child_start_acceptance() -> None:
    report_ids = ["report-a", "report-b"]
    occurrence_keys = {
        "report-a": "2026-09-09T10:00:00+00:00",
        "report-b": "2026-09-09T11:00:00+00:00",
    }

    async def fake_execute_activity(*_args, **_kwargs):
        return FetchDueEvalReportsOutput(report_ids=report_ids, report_occurrence_keys=occurrence_keys)

    with (
        patch(
            "posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.execute_activity",
            new=fake_execute_activity,
        ),
        patch(
            "posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.start_child_workflow",
            new_callable=AsyncMock,
        ) as start_child_workflow,
        patch(
            "posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.execute_child_workflow"
        ) as execute_child_workflow,
        patch(
            "posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.patched",
            return_value=True,
        ),
    ):
        await ScheduleAllEvalReportsWorkflow().run(
            ScheduleAllEvalReportsWorkflowInputs(max_reports_per_run=300, region="eu")
        )

    assert start_child_workflow.await_count == 2
    assert [call.kwargs["id"] for call in start_child_workflow.await_args_list] == [
        _report_workflow_id("eval-report", "report-a", occurrence_keys["report-a"]),
        _report_workflow_id("eval-report", "report-b", occurrence_keys["report-b"]),
    ]
    for call in start_child_workflow.await_args_list:
        assert call.kwargs["parent_close_policy"] == temporalio.workflow.ParentClosePolicy.ABANDON
        assert call.kwargs["id_reuse_policy"] == WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY
    execute_child_workflow.assert_not_called()


@pytest.mark.asyncio
async def test_scheduled_coordinator_acknowledges_cursor_after_child_starts() -> None:
    events: list[str] = []
    acknowledged_inputs: list[AckEvalReportCursorsInput] = []

    async def fake_execute_activity(activity, inputs, **_kwargs):
        if activity is fetch_due_eval_reports_activity:
            return FetchDueEvalReportsOutput(report_ids=["report-a"], cursor_before="41")
        if activity is ack_eval_report_cursors_activity:
            events.append("ack")
            acknowledged_inputs.append(inputs)
            return True
        raise AssertionError(f"unexpected activity: {activity}")

    async def fake_start_child_workflow(*_args, **_kwargs):
        events.append("start")

    with (
        patch(
            "posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.execute_activity",
            new=fake_execute_activity,
        ),
        patch(
            "posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.start_child_workflow",
            side_effect=fake_start_child_workflow,
        ),
        patch(
            "posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.patched",
            return_value=True,
        ),
    ):
        await ScheduleAllEvalReportsWorkflow().run(ScheduleAllEvalReportsWorkflowInputs(region="eu"))

    assert events == ["start", "ack"]
    assert acknowledged_inputs[0].cursor_before == "41"
    assert acknowledged_inputs[0].report_ids == ["report-a"]


@pytest.mark.asyncio
async def test_count_coordinator_acknowledges_cursor_after_due_child_starts() -> None:
    events: list[str] = []

    async def fake_execute_activity(activity, _inputs, **_kwargs):
        if activity is fetch_count_triggered_eval_report_candidates_activity:
            return FetchDueEvalReportsOutput(
                report_ids=["report-a"],
                report_id_groups=[["report-a"]],
                cursor_before="41",
            )
        if activity is ack_eval_report_cursors_activity:
            events.append("ack")
            return True
        raise AssertionError(f"unexpected activity: {activity}")

    async def fake_check_candidates(_groups, *, dispatch_due_reports):
        events.append("check")
        assert dispatch_due_reports is True
        events.append("start")
        return _DueReportCandidates(["report-a"], {"report-a": "count-window"})

    with (
        patch(
            "posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.execute_activity",
            new=fake_execute_activity,
        ),
        patch(
            "posthog.temporal.ai_observability.eval_reports.workflow._check_count_triggered_eval_report_candidates_batched",
            new=fake_check_candidates,
        ),
        patch(
            "posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.patched",
            return_value=True,
        ),
    ):
        await CheckCountTriggeredReportsWorkflow().run(CheckCountTriggeredReportsWorkflowInputs(region="eu"))

    assert events == ["check", "start", "ack"]


@pytest.mark.asyncio
async def test_count_coordinator_replays_pre_windowed_dispatch_history() -> None:
    report_ids = [f"report-{index}" for index in range(6)]

    @temporalio.activity.defn(name="fetch_count_triggered_eval_report_candidates_activity")
    async def fetch_candidates(_inputs: CheckCountTriggeredReportsWorkflowInputs) -> FetchDueEvalReportsOutput:
        return FetchDueEvalReportsOutput(
            report_ids=report_ids,
            report_id_groups=[[report_id] for report_id in report_ids],
            cursor_before="",
        )

    @temporalio.activity.defn(name="check_count_triggered_eval_reports_activity")
    async def check_candidates(
        inputs: CheckCountTriggeredEvalReportsBatchInput,
    ) -> CheckCountTriggeredEvalReportsBatchOutput:
        return CheckCountTriggeredEvalReportsBatchOutput(
            results=[
                CheckCountTriggeredEvalReportOutput(report_id=report_id, due=True) for report_id in inputs.report_ids
            ]
        )

    @temporalio.activity.defn(name="ack_eval_report_cursors_activity")
    async def ack_cursor(_inputs: AckEvalReportCursorsInput) -> bool:
        return True

    task_queue = str(uuid.uuid4())
    pre_patch_history: WorkflowHistory
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[PreWindowedDispatchCountCoordinator, StubReportChildWorkflow],
            activities=[fetch_candidates, check_candidates, ack_cursor],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await env.client.start_workflow(
                PreWindowedDispatchCountCoordinator.run,
                CheckCountTriggeredReportsWorkflowInputs(region="test"),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )
            await handle.result()
            pre_patch_history = await handle.fetch_history()

    await Replayer(
        workflows=[CheckCountTriggeredReportsWorkflow],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ).replay_workflow(pre_patch_history)


@pytest.mark.asyncio
async def test_report_child_starts_are_emitted_in_bounded_batches() -> None:
    gather_batch_sizes: list[int] = []
    original_gather = asyncio.gather

    async def recording_gather(*tasks, **kwargs):
        gather_batch_sizes.append(len(tasks))
        return await original_gather(*tasks, **kwargs)

    with (
        patch("posthog.temporal.ai_observability.eval_reports.workflow.REPORT_START_BATCH_SIZE", 2),
        patch(
            "posthog.temporal.ai_observability.eval_reports.workflow._start_report_workflow",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "posthog.temporal.ai_observability.eval_reports.workflow.asyncio.gather",
            side_effect=recording_gather,
        ),
    ):
        await _start_report_workflows("scheduled", "report", ["a", "b", "c", "d", "e"])

    assert gather_batch_sizes == [2, 2, 1]


@pytest.mark.asyncio
async def test_report_child_occurrence_cannot_restart_after_successful_completion() -> None:
    started_ids: set[str] = set()

    async def fake_start_child_workflow(*_args, **kwargs):
        workflow_id = kwargs["id"]
        if workflow_id in started_ids:
            raise WorkflowAlreadyStartedError(workflow_id, "eval-report")
        started_ids.add(workflow_id)

    with patch(
        "posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.start_child_workflow",
        side_effect=fake_start_child_workflow,
    ) as start_child_workflow:
        first_started = await _start_report_workflow("eval-report", "report-a", occurrence_key="scheduled:10:00")
        duplicate_started = await _start_report_workflow("eval-report", "report-a", occurrence_key="scheduled:10:00")
        next_occurrence_started = await _start_report_workflow(
            "eval-report", "report-a", occurrence_key="scheduled:11:00"
        )

    assert first_started is True
    assert duplicate_started is False
    assert next_occurrence_started is True
    assert len(started_ids) == 2
    for call in start_child_workflow.await_args_list:
        assert call.kwargs["id_reuse_policy"] == WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY


@pytest.mark.asyncio
async def test_report_child_preserves_legacy_command_without_occurrence_key() -> None:
    with patch(
        "posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.start_child_workflow"
    ) as start_child_workflow:
        assert await _start_report_workflow("eval-report", "report-a") is True

    await_args = start_child_workflow.await_args
    assert await_args is not None
    assert await_args.kwargs["id"] == "eval-report-report-a"
    assert await_args.kwargs["id_reuse_policy"] == WorkflowIDReusePolicy.ALLOW_DUPLICATE


@pytest.mark.parametrize(
    ("start_errors", "expected_warning_extra", "expected_info_extra"),
    [
        pytest.param(
            {"eval-report-report-b": WorkflowAlreadyStartedError("eval-report-report-b", "eval-report")},
            None,
            {"already_started_count": 1},
            id="overlap_only_stays_informational",
        ),
        pytest.param(
            {
                "eval-report-report-b": WorkflowAlreadyStartedError("eval-report-report-b", "eval-report"),
                "eval-report-report-c": RuntimeError("boom"),
            },
            {
                "already_started_count": 1,
                "failed_count": 1,
                "failure_samples": [("report-c", "RuntimeError: boom")],
            },
            None,
            id="real_failure_warns_and_keeps_both_counts",
        ),
    ],
)
@pytest.mark.asyncio
async def test_scheduled_coordinator_reports_child_start_outcomes(
    start_errors: dict[str, Exception],
    expected_warning_extra: dict | None,
    expected_info_extra: dict | None,
) -> None:
    report_ids = ["report-a", "report-b", "report-c"]

    async def fake_execute_activity(*_args, **_kwargs):
        return FetchDueEvalReportsOutput(report_ids=report_ids)

    async def fake_start_child_workflow(*_args, **kwargs):
        error = start_errors.get(kwargs["id"])
        if error is not None:
            raise error

    with (
        patch(
            "posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.execute_activity",
            new=fake_execute_activity,
        ),
        patch(
            "posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.start_child_workflow",
            new_callable=AsyncMock,
            side_effect=fake_start_child_workflow,
        ) as start_child_workflow,
        patch(
            "posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.patched",
            return_value=True,
        ),
        patch("posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.logger") as workflow_logger,
    ):
        await ScheduleAllEvalReportsWorkflow().run(ScheduleAllEvalReportsWorkflowInputs())

    assert [call.kwargs["id"] for call in start_child_workflow.await_args_list] == [
        "eval-report-report-a",
        "eval-report-report-b",
        "eval-report-report-c",
    ]
    warnings = [(call.args[0], call.kwargs["extra"]) for call in workflow_logger.warning.call_args_list]
    infos = [(call.args[0], call.kwargs["extra"]) for call in workflow_logger.info.call_args_list]
    if expected_warning_extra is None:
        assert warnings == []
    else:
        assert warnings == [("scheduled_eval_report.child_workflow_start_errors", expected_warning_extra)]
    if expected_info_extra is None:
        assert infos == []
    else:
        assert infos == [("scheduled_eval_report.child_workflow_already_running", expected_info_extra)]


@pytest.mark.asyncio
async def test_scheduled_coordinator_preserves_legacy_commands_for_open_histories() -> None:
    async def fake_execute_activity(*_args, **_kwargs):
        return FetchDueEvalReportsOutput(report_ids=["report-a"])

    with (
        patch(
            "posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.execute_activity",
            new=fake_execute_activity,
        ),
        patch(
            "posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.start_child_workflow",
            new_callable=AsyncMock,
        ) as start_child_workflow,
        patch(
            "posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.execute_child_workflow",
            new_callable=AsyncMock,
        ) as execute_child_workflow,
        patch(
            "posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.patched",
            return_value=False,
        ),
    ):
        await ScheduleAllEvalReportsWorkflow().run(ScheduleAllEvalReportsWorkflowInputs())

    execute_child_workflow.assert_awaited_once()
    start_child_workflow.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_workflow_forwards_sentiment_output_type() -> None:
    trace_uuid = UUID("11111111-1111-4111-8111-111111111111")
    session_uuid = UUID("22222222-2222-4222-8222-222222222222")
    activity_inputs: list[object] = []
    responses = iter(
        [
            PrepareReportContextOutput(
                report_id="report-id",
                team_id=1,
                evaluation_id="evaluation-id",
                evaluation_name="Sentiment",
                evaluation_description="",
                evaluation_prompt="",
                evaluation_type="sentiment",
                output_type="sentiment",
                period_start="2026-07-01T00:00:00+00:00",
                period_end="2026-07-02T00:00:00+00:00",
                previous_period_start="2026-06-30T00:00:00+00:00",
            ),
            RunEvalReportAgentOutput(
                report_id="report-id",
                content={},
                period_start="2026-07-01T00:00:00+00:00",
                period_end="2026-07-02T00:00:00+00:00",
            ),
            StoreReportRunOutput(report_run_id="run-id"),
            None,
        ]
    )

    async def fake_execute_activity(_activity, inputs, **_kwargs):
        activity_inputs.append(inputs)
        return next(responses)

    with (
        patch(
            "posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.execute_activity",
            new=fake_execute_activity,
        ),
        patch(
            "posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.patched",
            return_value=False,
        ),
        patch(
            "posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.uuid4",
            side_effect=[trace_uuid, session_uuid],
        ),
    ):
        await GenerateAndDeliverEvalReportWorkflow().run(
            GenerateAndDeliverEvalReportWorkflowInput(report_id="report-id", manual=True)
        )

    agent_input = activity_inputs[1]
    assert isinstance(agent_input, RunEvalReportAgentInput)
    assert agent_input.output_type == "sentiment"
    assert agent_input.trace_id == str(trace_uuid)
    assert agent_input.session_id == str(session_uuid)


@pytest.mark.parametrize(
    (
        "agent_generation_status",
        "generation_status_patch_enabled",
        "attempt_patch_enabled",
        "expected_generation_status",
        "expected_schedule_updates",
    ),
    [
        ("metrics_unavailable", True, True, "metrics_unavailable", [(True, False)]),
        ("metrics_unavailable", False, False, "completed", [(True, True)]),
        ("completed", True, True, "completed", [(True, False), (False, True)]),
    ],
)
@pytest.mark.asyncio
async def test_generate_workflow_forwards_generation_status_to_schedule(
    agent_generation_status: str,
    generation_status_patch_enabled: bool,
    attempt_patch_enabled: bool,
    expected_generation_status: str,
    expected_schedule_updates: list[tuple[bool, bool]],
) -> None:
    activity_calls: list[object] = []
    activity_inputs: list[object] = []
    responses = iter(
        [
            PrepareReportContextOutput(
                report_id="report-id",
                team_id=1,
                evaluation_id="evaluation-id",
                evaluation_name="Evaluation",
                evaluation_description="",
                evaluation_prompt="",
                evaluation_type="llm_judge",
                period_start="2026-07-01T00:00:00+00:00",
                period_end="2026-07-02T00:00:00+00:00",
                previous_period_start="2026-06-30T00:00:00+00:00",
            ),
            RunEvalReportAgentOutput(
                report_id="report-id",
                content={
                    "generation_status": agent_generation_status,
                    "metrics": None if agent_generation_status == "metrics_unavailable" else {},
                },
                period_start="2026-07-01T00:00:00+00:00",
                period_end="2026-07-02T00:00:00+00:00",
                generation_status=agent_generation_status,
            ),
            StoreReportRunOutput(report_run_id="run-id"),
            None,
            None,
            None,
        ]
    )

    async def fake_execute_activity(activity, inputs, **_kwargs):
        activity_calls.append(activity)
        activity_inputs.append(inputs)
        return next(responses)

    def is_patch_enabled(patch_id: str) -> bool:
        if patch_id == "eval-report-generation-status-2026-07":
            return generation_status_patch_enabled
        if patch_id == "eval-report-attempt-before-delivery-2026-07":
            return attempt_patch_enabled
        return False

    with (
        patch(
            "posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.execute_activity",
            new=fake_execute_activity,
        ),
        patch(
            "posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.patched",
            side_effect=is_patch_enabled,
        ),
        patch(
            "posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.uuid4",
            return_value=UUID(int=0),
        ),
    ):
        await GenerateAndDeliverEvalReportWorkflow().run(
            GenerateAndDeliverEvalReportWorkflowInput(report_id="report-id")
        )

    schedule_inputs = [inputs for inputs in activity_inputs if isinstance(inputs, UpdateNextDeliveryDateInput)]
    assert [schedule_input.generation_status for schedule_input in schedule_inputs] == [
        expected_generation_status
    ] * len(expected_schedule_updates)
    assert [
        (schedule_input.record_attempt, schedule_input.advance_data_cursor) for schedule_input in schedule_inputs
    ] == expected_schedule_updates

    schedule_indexes = [
        index for index, activity in enumerate(activity_calls) if activity is update_next_delivery_date_activity
    ]
    delivery_index = activity_calls.index(deliver_report_activity)
    if attempt_patch_enabled:
        assert schedule_indexes[0] < delivery_index
        if expected_generation_status == "completed":
            assert schedule_indexes[-1] > delivery_index
    else:
        assert schedule_indexes == [delivery_index + 1]


@pytest.mark.parametrize("generation_status", ["completed", "metrics_unavailable"])
@pytest.mark.asyncio
async def test_automatic_run_records_attempt_before_delivery_failure(generation_status: str) -> None:
    activity_calls: list[object] = []
    activity_inputs: list[object] = []
    responses = iter(
        [
            PrepareReportContextOutput(
                report_id="report-id",
                team_id=1,
                evaluation_id="evaluation-id",
                evaluation_name="Evaluation",
                evaluation_description="",
                evaluation_prompt="",
                evaluation_type="llm_judge",
                period_start="2026-07-01T00:00:00+00:00",
                period_end="2026-07-02T00:00:00+00:00",
                previous_period_start="2026-06-30T00:00:00+00:00",
            ),
            RunEvalReportAgentOutput(
                report_id="report-id",
                content={
                    "generation_status": generation_status,
                    "metrics": None if generation_status == "metrics_unavailable" else {},
                },
                period_start="2026-07-01T00:00:00+00:00",
                period_end="2026-07-02T00:00:00+00:00",
                generation_status=generation_status,
            ),
            StoreReportRunOutput(report_run_id="run-id"),
            None,
        ]
    )

    async def fake_execute_activity(activity, inputs, **_kwargs):
        activity_calls.append(activity)
        activity_inputs.append(inputs)
        if activity is deliver_report_activity:
            raise RuntimeError("delivery unavailable")
        return next(responses)

    with (
        patch(
            "posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.execute_activity",
            new=fake_execute_activity,
        ),
        patch(
            "posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.patched",
            side_effect=lambda patch_id: (
                patch_id
                in {
                    "eval-report-generation-status-2026-07",
                    "eval-report-attempt-before-delivery-2026-07",
                }
            ),
        ),
        patch(
            "posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.uuid4",
            return_value=UUID(int=0),
        ),
        pytest.raises(RuntimeError, match="delivery unavailable"),
    ):
        await GenerateAndDeliverEvalReportWorkflow().run(
            GenerateAndDeliverEvalReportWorkflowInput(report_id="report-id")
        )

    schedule_inputs = [inputs for inputs in activity_inputs if isinstance(inputs, UpdateNextDeliveryDateInput)]
    assert len(schedule_inputs) == 1
    schedule_input = schedule_inputs[0]
    assert schedule_input.generation_status == generation_status
    assert schedule_input.record_attempt is True
    assert schedule_input.advance_data_cursor is False
    assert activity_calls.count(update_next_delivery_date_activity) == 1
    assert activity_calls.index(update_next_delivery_date_activity) < activity_calls.index(deliver_report_activity)


@pytest.mark.asyncio
async def test_generate_workflow_does_not_emit_signal_without_metrics() -> None:
    responses = iter(
        [
            PrepareReportContextOutput(
                report_id="report-id",
                team_id=1,
                evaluation_id="evaluation-id",
                evaluation_name="Evaluation",
                evaluation_description="",
                evaluation_prompt="",
                evaluation_type="llm_judge",
                period_start="2026-07-01T00:00:00+00:00",
                period_end="2026-07-02T00:00:00+00:00",
                previous_period_start="2026-06-30T00:00:00+00:00",
            ),
            RunEvalReportAgentOutput(
                report_id="report-id",
                content={"generation_status": "metrics_unavailable", "metrics": None},
                period_start="2026-07-01T00:00:00+00:00",
                period_end="2026-07-02T00:00:00+00:00",
                generation_status="metrics_unavailable",
            ),
            StoreReportRunOutput(report_run_id="run-id"),
            None,
        ]
    )

    async def fake_execute_activity(_activity, _inputs, **_kwargs):
        return next(responses)

    with (
        patch(
            "posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.execute_activity",
            new=fake_execute_activity,
        ),
        patch(
            "posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.patched",
            return_value=True,
        ),
        patch(
            "posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.start_child_workflow"
        ) as start_child_workflow,
        patch(
            "posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.uuid4",
            return_value=UUID(int=0),
        ),
    ):
        await GenerateAndDeliverEvalReportWorkflow().run(
            GenerateAndDeliverEvalReportWorkflowInput(report_id="report-id", manual=True)
        )

    start_child_workflow.assert_not_called()


@pytest.mark.asyncio
async def test_count_triggered_report_check_continues_after_activity_failure() -> None:
    checked_report_ids: list[str] = []
    skipped_reasons = {
        "cooldown": "cooldown",
        "daily_cap": "daily_cap",
        "not_deliverable": "not_deliverable",
    }

    async def fake_execute_activity(_activity, inputs, **_kwargs):
        checked_report_ids.append(inputs.report_id)
        if inputs.report_id == "failed":
            raise RuntimeError("clickhouse at capacity")
        return CheckCountTriggeredEvalReportOutput(
            report_id=inputs.report_id,
            due=inputs.report_id == "due",
            skipped_reason=skipped_reasons.get(inputs.report_id),
            occurrence_key="window-due" if inputs.report_id == "due" else None,
        )

    with (
        patch(
            "posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.execute_activity",
            new=fake_execute_activity,
        ),
        patch("posthog.temporal.ai_observability.eval_reports.workflow.record_coordinator_reports_found") as record,
        patch("posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.logger") as logger,
    ):
        due_reports = await _check_count_triggered_eval_report_candidates(
            ["due", "failed", "not_due", "cooldown", "daily_cap", "not_deliverable"]
        )

    assert due_reports.report_ids == ["due"]
    assert due_reports.occurrence_keys == {"due": "window-due"}
    assert checked_report_ids == ["due", "failed", "not_due", "cooldown", "daily_cap", "not_deliverable"]
    record.assert_called_once_with(1, "count_triggered")
    logger.warning.assert_called_once()
    assert logger.warning.call_args.args == ("count_triggered_eval_report_check.activity_errors",)
    assert logger.warning.call_args.kwargs["extra"]["failed_count"] == 1
    logger.info.assert_called_once_with(
        "llma_eval_reports_coordinator_count_triggered_poll",
        extra={
            "reports_found": 1,
            "total_checked": 6,
            "skipped_cooldown": 1,
            "skipped_daily_cap": 1,
            "skipped_not_deliverable": 1,
        },
    )


@pytest.mark.asyncio
async def test_batched_count_check_aggregates_across_groups_and_isolates_group_failure() -> None:
    # One failing group activity must not sink the others: every report in it is recorded as
    # failed, while due/skipped reports from the surviving groups still aggregate correctly.
    async def fake_execute_activity(_activity, inputs, **_kwargs):
        if any(report_id.startswith("boom") for report_id in inputs.report_ids):
            raise RuntimeError("clickhouse at capacity")
        return CheckCountTriggeredEvalReportsBatchOutput(
            results=[
                CheckCountTriggeredEvalReportOutput(
                    report_id=report_id,
                    due=report_id == "due",
                    skipped_reason="cooldown" if report_id == "skip" else None,
                )
                for report_id in inputs.report_ids
            ]
        )

    with (
        patch(
            "posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.execute_activity",
            new=fake_execute_activity,
        ),
        patch("posthog.temporal.ai_observability.eval_reports.workflow.record_coordinator_reports_found") as record,
        patch("posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.logger") as logger,
    ):
        due_reports = await _check_count_triggered_eval_report_candidates_batched([["due", "skip"], ["boom1", "boom2"]])

    assert due_reports.report_ids == ["due"]
    record.assert_called_once_with(1, "count_triggered")
    logger.warning.assert_called_once()
    assert logger.warning.call_args.kwargs["extra"]["failed_count"] == 2
    logger.info.assert_called_once_with(
        "llma_eval_reports_coordinator_count_triggered_poll",
        extra={
            "reports_found": 1,
            "total_checked": 4,
            "skipped_cooldown": 1,
            "skipped_daily_cap": 0,
            "skipped_not_deliverable": 0,
        },
    )


@pytest.mark.asyncio
async def test_batched_count_check_caps_concurrent_group_activities() -> None:
    # The window must keep at most COUNT_TRIGGER_MAX_CONCURRENT_CHECKS count queries in
    # flight; losing it would fire every team's query at once — the exact ClickHouse
    # capacity pressure this path exists to avoid.
    active = 0
    max_active = 0

    async def fake_execute_activity(_activity, inputs, **_kwargs):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0)
        active -= 1
        return CheckCountTriggeredEvalReportsBatchOutput(
            results=[
                CheckCountTriggeredEvalReportOutput(report_id=report_id, due=False) for report_id in inputs.report_ids
            ]
        )

    with (
        patch(
            "posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.execute_activity",
            new=fake_execute_activity,
        ),
        patch("posthog.temporal.ai_observability.eval_reports.workflow.COUNT_TRIGGER_MAX_CONCURRENT_CHECKS", 2),
        patch("posthog.temporal.ai_observability.eval_reports.workflow.record_coordinator_reports_found"),
        patch("posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.logger"),
    ):
        await _check_count_triggered_eval_report_candidates_batched([[f"report-{index}"] for index in range(5)])

    assert max_active == 2


@pytest.mark.asyncio
async def test_batched_count_check_dispatches_each_completed_window() -> None:
    async def fake_execute_activity(_activity, inputs, **_kwargs):
        return CheckCountTriggeredEvalReportsBatchOutput(
            results=[
                CheckCountTriggeredEvalReportOutput(
                    report_id=report_id,
                    due=True,
                    occurrence_key=f"window-{report_id}",
                )
                for report_id in inputs.report_ids
            ]
        )

    with (
        patch(
            "posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.execute_activity",
            new=fake_execute_activity,
        ),
        patch("posthog.temporal.ai_observability.eval_reports.workflow.COUNT_TRIGGER_MAX_CONCURRENT_CHECKS", 1),
        patch(
            "posthog.temporal.ai_observability.eval_reports.workflow._dispatch_report_workflows",
            new_callable=AsyncMock,
        ) as dispatch,
        patch("posthog.temporal.ai_observability.eval_reports.workflow.record_coordinator_reports_found"),
        patch("posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.logger"),
    ):
        due_reports = await _check_count_triggered_eval_report_candidates_batched(
            [["due-a"], ["due-b"]],
            dispatch_due_reports=True,
        )

    assert due_reports.report_ids == ["due-a", "due-b"]
    assert due_reports.occurrence_keys == {"due-a": "window-due-a", "due-b": "window-due-b"}
    assert [call.args[2] for call in dispatch.await_args_list] == [["due-a"], ["due-b"]]
    assert [call.kwargs["occurrence_keys"] for call in dispatch.await_args_list] == [
        {"due-a": "window-due-a"},
        {"due-b": "window-due-b"},
    ]
