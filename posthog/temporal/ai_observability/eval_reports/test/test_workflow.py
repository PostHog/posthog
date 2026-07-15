import pytest
from unittest.mock import patch

from posthog.temporal.ai_observability.eval_reports.types import (
    CheckCountTriggeredEvalReportOutput,
    GenerateAndDeliverEvalReportWorkflowInput,
    PrepareReportContextOutput,
    RunEvalReportAgentInput,
    RunEvalReportAgentOutput,
    StoreReportRunOutput,
)
from posthog.temporal.ai_observability.eval_reports.workflow import (
    GenerateAndDeliverEvalReportWorkflow,
    _check_count_triggered_eval_report_candidates,
)


@pytest.mark.asyncio
async def test_generate_workflow_forwards_sentiment_output_type() -> None:
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
    ):
        await GenerateAndDeliverEvalReportWorkflow().run(
            GenerateAndDeliverEvalReportWorkflowInput(report_id="report-id", manual=True)
        )

    agent_input = activity_inputs[1]
    assert isinstance(agent_input, RunEvalReportAgentInput)
    assert agent_input.output_type == "sentiment"


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
