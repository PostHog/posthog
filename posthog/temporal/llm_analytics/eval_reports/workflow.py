"""Temporal workflows for evaluation reports."""

import json
import asyncio

import temporalio.workflow
from structlog import get_logger

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.llm_analytics.eval_reports.activities import (
    deliver_report_activity,
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
from posthog.temporal.llm_analytics.eval_reports.types import (
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

        await asyncio.gather(*tasks, return_exceptions=True)


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
            PrepareReportContextInput(report_id=inputs.report_id),
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
                metadata=agent_result.metadata,
                period_start=agent_result.period_start,
                period_end=agent_result.period_end,
            ),
            start_to_close_timeout=STORE_ACTIVITY_TIMEOUT,
            retry_policy=STORE_RETRY_POLICY,
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

        # 5. Update next delivery date
        await temporalio.workflow.execute_activity(
            update_next_delivery_date_activity,
            UpdateNextDeliveryDateInput(report_id=inputs.report_id),
            start_to_close_timeout=UPDATE_SCHEDULE_ACTIVITY_TIMEOUT,
            retry_policy=UPDATE_SCHEDULE_RETRY_POLICY,
        )
