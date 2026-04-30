"""Temporal workflows for evaluation reports."""

import json
import asyncio
from datetime import timedelta

from django.conf import settings

import temporalio.workflow
from structlog import get_logger
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.llm_analytics.eval_reports.activities import (
    deliver_report_activity,
    fetch_count_triggered_eval_reports_activity,
    fetch_due_eval_reports_activity,
    prepare_report_context_activity,
    run_eval_report_agent_activity,
    store_report_run_activity,
    update_next_delivery_date_activity,
)
from posthog.temporal.llm_analytics.eval_reports.constants import (
    AGENT_ACTIVITY_TIMEOUT,
    AGENT_HEARTBEAT_TIMEOUT,
    AGENT_RETRY_POLICY,
    CHECK_COUNT_TRIGGERED_REPORTS_WORKFLOW_NAME,
    DELIVER_ACTIVITY_TIMEOUT,
    DELIVER_HEARTBEAT_TIMEOUT,
    DELIVER_RETRY_POLICY,
    FETCH_ACTIVITY_TIMEOUT,
    FETCH_RETRY_POLICY,
    GENERATE_EVAL_REPORT_WORKFLOW_NAME,
    PREPARE_ACTIVITY_TIMEOUT,
    SCHEDULE_ALL_EVAL_REPORTS_WORKFLOW_NAME,
    STORE_ACTIVITY_TIMEOUT,
    STORE_RETRY_POLICY,
    UPDATE_SCHEDULE_ACTIVITY_TIMEOUT,
    UPDATE_SCHEDULE_RETRY_POLICY,
    WORKFLOW_EXECUTION_TIMEOUT,
)
from posthog.temporal.llm_analytics.eval_reports.emit_signal import (
    EmitEvalReportSignalInputs,
    EmitEvalReportSignalWorkflow,
)
from posthog.temporal.llm_analytics.eval_reports.types import (
    CheckCountTriggeredReportsWorkflowInputs,
    DeliverReportInput,
    GenerateAndDeliverEvalReportWorkflowInput,
    PrepareReportContextInput,
    RunEvalReportAgentInput,
    ScheduleAllEvalReportsWorkflowInputs,
    StoreReportRunInput,
    UpdateNextDeliveryDateInput,
)

logger = get_logger(__name__)


@temporalio.workflow.defn(name=SCHEDULE_ALL_EVAL_REPORTS_WORKFLOW_NAME)
class ScheduleAllEvalReportsWorkflow(PostHogWorkflow):
    """Hourly workflow that finds due evaluation reports and fans out generation."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> ScheduleAllEvalReportsWorkflowInputs:
        if not inputs:
            return ScheduleAllEvalReportsWorkflowInputs()
        loaded = json.loads(inputs[0])
        return ScheduleAllEvalReportsWorkflowInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: ScheduleAllEvalReportsWorkflowInputs) -> None:
        result = await temporalio.workflow.execute_activity(
            fetch_due_eval_reports_activity,
            inputs,
            start_to_close_timeout=FETCH_ACTIVITY_TIMEOUT,
            retry_policy=FETCH_RETRY_POLICY,
        )

        if not result.report_ids:
            return

        # Fan-out: start child workflow per due report
        tasks = []
        for report_id in result.report_ids:
            task = temporalio.workflow.execute_child_workflow(
                GenerateAndDeliverEvalReportWorkflow.run,
                GenerateAndDeliverEvalReportWorkflowInput(report_id=report_id),
                id=f"eval-report-{report_id}",
                execution_timeout=WORKFLOW_EXECUTION_TIMEOUT,
            )
            tasks.append(task)

        # return_exceptions=True isolates individual report failures — one failing
        # report shouldn't block the others. Log the offenders so they're visible
        # in observability even though we don't re-raise.
        results = await asyncio.gather(*tasks, return_exceptions=True)
        _log_fan_out_failures("scheduled_eval_report", result.report_ids, results)


@temporalio.workflow.defn(name=CHECK_COUNT_TRIGGERED_REPORTS_WORKFLOW_NAME)
class CheckCountTriggeredReportsWorkflow(PostHogWorkflow):
    """5-minute workflow that checks count-based evaluation reports for threshold crossings."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> CheckCountTriggeredReportsWorkflowInputs:
        if not inputs:
            return CheckCountTriggeredReportsWorkflowInputs()
        loaded = json.loads(inputs[0])
        return CheckCountTriggeredReportsWorkflowInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: CheckCountTriggeredReportsWorkflowInputs) -> None:
        result = await temporalio.workflow.execute_activity(
            fetch_count_triggered_eval_reports_activity,
            inputs,
            start_to_close_timeout=FETCH_ACTIVITY_TIMEOUT,
            retry_policy=FETCH_RETRY_POLICY,
        )

        if not result.report_ids:
            return

        tasks = []
        for report_id in result.report_ids:
            task = temporalio.workflow.execute_child_workflow(
                GenerateAndDeliverEvalReportWorkflow.run,
                GenerateAndDeliverEvalReportWorkflowInput(report_id=report_id),
                id=f"eval-report-count-{report_id}",
                execution_timeout=WORKFLOW_EXECUTION_TIMEOUT,
            )
            tasks.append(task)

        results = await asyncio.gather(*tasks, return_exceptions=True)
        _log_fan_out_failures("count_triggered_eval_report", result.report_ids, results)


def _log_fan_out_failures(kind: str, report_ids: list[str], results: list) -> None:
    """Log which child workflows failed in a fan-out, without re-raising."""
    failed: list[tuple[str, str]] = []
    for report_id, result in zip(report_ids, results):
        if isinstance(result, BaseException):
            failed.append((report_id, f"{type(result).__name__}: {result}"))
    if failed:
        temporalio.workflow.logger.warning(
            f"{kind}.child_workflow_errors",
            extra={"failed_count": len(failed), "failures": failed},
        )


@temporalio.workflow.defn(name=GENERATE_EVAL_REPORT_WORKFLOW_NAME)
class GenerateAndDeliverEvalReportWorkflow(PostHogWorkflow):
    """Per-report workflow: prepare context, run agent, store, deliver, update schedule."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> GenerateAndDeliverEvalReportWorkflowInput:
        loaded = json.loads(inputs[0])
        return GenerateAndDeliverEvalReportWorkflowInput(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: GenerateAndDeliverEvalReportWorkflowInput) -> None:
        # 1. Prepare context
        context = await temporalio.workflow.execute_activity(
            prepare_report_context_activity,
            PrepareReportContextInput(report_id=inputs.report_id, manual=inputs.manual),
            start_to_close_timeout=PREPARE_ACTIVITY_TIMEOUT,
            retry_policy=FETCH_RETRY_POLICY,
        )

        # 2. Run agent
        agent_result = await temporalio.workflow.execute_activity(
            run_eval_report_agent_activity,
            RunEvalReportAgentInput(
                report_id=context.report_id,
                team_id=context.team_id,
                evaluation_id=context.evaluation_id,
                evaluation_name=context.evaluation_name,
                evaluation_description=context.evaluation_description,
                evaluation_prompt=context.evaluation_prompt,
                evaluation_type=context.evaluation_type,
                period_start=context.period_start,
                period_end=context.period_end,
                previous_period_start=context.previous_period_start,
                report_prompt_guidance=context.report_prompt_guidance,
            ),
            start_to_close_timeout=AGENT_ACTIVITY_TIMEOUT,
            heartbeat_timeout=AGENT_HEARTBEAT_TIMEOUT,
            retry_policy=AGENT_RETRY_POLICY,
        )

        # 3. Store report run + emit event
        store_result = await temporalio.workflow.execute_activity(
            store_report_run_activity,
            StoreReportRunInput(
                report_id=agent_result.report_id,
                team_id=context.team_id,
                evaluation_id=context.evaluation_id,
                content=agent_result.content,
                period_start=agent_result.period_start,
                period_end=agent_result.period_end,
            ),
            start_to_close_timeout=STORE_ACTIVITY_TIMEOUT,
            retry_policy=STORE_RETRY_POLICY,
        )

        # 3b. Emit a signal for this report run (fire-and-forget).
        # Runs on the same LLMA worker as the parent via LLMA_TASK_QUEUE; ABANDON
        # parent-close lets the LLM summary call continue independently so it doesn't
        # block delivery. Gated by the same SignalSourceConfig(LLM_ANALYTICS, EVALUATION)
        # row that gates per-result emission — the activity bails out early for
        # teams/evaluations that haven't opted in.
        # Wrapped in workflow.patched so in-flight workflows started before this code
        # was deployed don't hit a nondeterminism error on replay — they'll skip the
        # child-workflow command entirely.
        if temporalio.workflow.patched("eval-report-emit-signal-2026-04"):
            try:
                await temporalio.workflow.start_child_workflow(
                    EmitEvalReportSignalWorkflow.run,
                    EmitEvalReportSignalInputs(
                        team_id=context.team_id,
                        evaluation_id=context.evaluation_id,
                        evaluation_name=context.evaluation_name,
                        evaluation_description=context.evaluation_description,
                        evaluation_prompt=context.evaluation_prompt,
                        report_id=agent_result.report_id,
                        report_run_id=store_result.report_run_id,
                        period_start=agent_result.period_start,
                        period_end=agent_result.period_end,
                    ),
                    id=f"emit-eval-report-signal-{context.team_id}-{context.evaluation_id}-{store_result.report_run_id}",
                    task_queue=settings.LLMA_TASK_QUEUE,
                    parent_close_policy=temporalio.workflow.ParentClosePolicy.ABANDON,
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                    execution_timeout=timedelta(minutes=5),
                )
            except WorkflowAlreadyStartedError:
                # Same parent workflow replayed/retried with the same report_run_id.
                # Safe to skip — the previous run is already handling emission.
                temporalio.workflow.logger.info(
                    "Eval report signal workflow already started for this run",
                    evaluation_id=context.evaluation_id,
                    team_id=context.team_id,
                    report_run_id=store_result.report_run_id,
                )

        # 4. Deliver
        await temporalio.workflow.execute_activity(
            deliver_report_activity,
            DeliverReportInput(
                report_id=inputs.report_id,
                report_run_id=store_result.report_run_id,
            ),
            start_to_close_timeout=DELIVER_ACTIVITY_TIMEOUT,
            heartbeat_timeout=DELIVER_HEARTBEAT_TIMEOUT,
            retry_policy=DELIVER_RETRY_POLICY,
        )

        # 5. Update next delivery date (skip for manual runs to avoid disrupting schedule)
        if not inputs.manual:
            await temporalio.workflow.execute_activity(
                update_next_delivery_date_activity,
                UpdateNextDeliveryDateInput(
                    report_id=inputs.report_id,
                    period_end=context.period_end,
                ),
                start_to_close_timeout=UPDATE_SCHEDULE_ACTIVITY_TIMEOUT,
                retry_policy=UPDATE_SCHEDULE_RETRY_POLICY,
            )
