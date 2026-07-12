import pytest
from unittest.mock import patch

from posthog.temporal.ai_observability.eval_reports.types import CheckCountTriggeredEvalReportOutput
from posthog.temporal.ai_observability.eval_reports.workflow import _check_count_triggered_eval_report_candidates


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
