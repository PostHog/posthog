import asyncio
from uuid import UUID

import pytest
from unittest.mock import patch

from posthog.temporal.ai_observability.eval_reports.activities import (
    deliver_report_activity,
    update_next_delivery_date_activity,
)
from posthog.temporal.ai_observability.eval_reports.types import (
    CheckCountTriggeredEvalReportOutput,
    CheckCountTriggeredEvalReportsBatchOutput,
    GenerateAndDeliverEvalReportWorkflowInput,
    PrepareReportContextOutput,
    RunEvalReportAgentInput,
    RunEvalReportAgentOutput,
    StoreReportRunOutput,
    UpdateNextDeliveryDateInput,
)
from posthog.temporal.ai_observability.eval_reports.workflow import (
    GenerateAndDeliverEvalReportWorkflow,
    _check_count_triggered_eval_report_candidates,
    _check_count_triggered_eval_report_candidates_batched,
)


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
        )

    with (
        patch(
            "posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.execute_activity",
            new=fake_execute_activity,
        ),
        patch("posthog.temporal.ai_observability.eval_reports.workflow.record_coordinator_reports_found") as record,
        patch("posthog.temporal.ai_observability.eval_reports.workflow.temporalio.workflow.logger") as logger,
    ):
        report_ids = await _check_count_triggered_eval_report_candidates(
            ["due", "failed", "not_due", "cooldown", "daily_cap", "not_deliverable"]
        )

    assert report_ids == ["due"]
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
        report_ids = await _check_count_triggered_eval_report_candidates_batched([["due", "skip"], ["boom1", "boom2"]])

    assert report_ids == ["due"]
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
