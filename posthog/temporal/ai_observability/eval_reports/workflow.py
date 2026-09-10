"""Temporal workflows for evaluation reports."""

import json
import asyncio
from datetime import timedelta
from itertools import batched

from django.conf import settings

import temporalio.workflow
from structlog import get_logger
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.temporal.ai_observability.eval_reports.activities import (
    ack_eval_report_cursors_activity,
    check_count_triggered_eval_report_activity,
    check_count_triggered_eval_reports_activity,
    deliver_report_activity,
    fetch_count_triggered_eval_report_candidates_activity,
    fetch_due_eval_reports_activity,
    prepare_report_context_activity,
    run_eval_report_agent_activity,
    store_report_run_activity,
    update_next_delivery_date_activity,
)
from posthog.temporal.ai_observability.eval_reports.constants import (
    AGENT_ACTIVITY_TIMEOUT,
    AGENT_HEARTBEAT_TIMEOUT,
    AGENT_RETRY_POLICY,
    CHECK_COUNT_TRIGGERED_REPORTS_WORKFLOW_NAME,
    COUNT_TRIGGER_CHECK_ACTIVITY_TIMEOUT,
    COUNT_TRIGGER_CHECK_BATCH_SIZE,
    COUNT_TRIGGER_MAX_CONCURRENT_CHECKS,
    DELIVER_ACTIVITY_TIMEOUT,
    DELIVER_HEARTBEAT_TIMEOUT,
    DELIVER_RETRY_POLICY,
    FETCH_ACTIVITY_TIMEOUT,
    FETCH_RETRY_POLICY,
    GENERATE_EVAL_REPORT_WORKFLOW_NAME,
    PREPARE_ACTIVITY_TIMEOUT,
    REPORT_START_BATCH_SIZE,
    SCHEDULE_ALL_EVAL_REPORTS_WORKFLOW_NAME,
    STORE_ACTIVITY_TIMEOUT,
    STORE_RETRY_POLICY,
    UPDATE_SCHEDULE_ACTIVITY_TIMEOUT,
    UPDATE_SCHEDULE_RETRY_POLICY,
    WORKFLOW_EXECUTION_TIMEOUT,
)
from posthog.temporal.ai_observability.eval_reports.emit_signal import (
    EmitEvalReportSignalInputs,
    EmitEvalReportSignalWorkflow,
)
from posthog.temporal.ai_observability.eval_reports.metrics import record_coordinator_reports_found
from posthog.temporal.ai_observability.eval_reports.types import (
    AckEvalReportCursorsInput,
    CheckCountTriggeredEvalReportInput,
    CheckCountTriggeredEvalReportsBatchInput,
    CheckCountTriggeredReportsWorkflowInputs,
    DeliverReportInput,
    FetchDueEvalReportsOutput,
    GenerateAndDeliverEvalReportWorkflowInput,
    PrepareReportContextInput,
    RunEvalReportAgentInput,
    ScheduleAllEvalReportsWorkflowInputs,
    StoreReportRunInput,
    UpdateNextDeliveryDateInput,
)
from posthog.temporal.common.base import PostHogWorkflow

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

        await _dispatch_report_workflows(
            "scheduled_eval_report",
            "eval-report",
            result.report_ids,
            patch_id="eval-report-scheduled-coordinator-fire-and-forget-2026-09",
        )
        await _ack_eval_report_cursors(result, "scheduled", inputs.region)


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
            fetch_count_triggered_eval_report_candidates_activity,
            inputs,
            start_to_close_timeout=FETCH_ACTIVITY_TIMEOUT,
            retry_policy=FETCH_RETRY_POLICY,
        )
        # Batched path: one check activity per team-group, each sharing one ClickHouse
        # count query, instead of one activity per report. Gated on the fetch output so
        # the decision is replay-deterministic: histories recorded before batching (and
        # fetch results produced by a pre-batching worker mid-deploy) decode
        # report_id_groups as None and keep their per-report command sequence.
        uses_batched_checks = result.report_id_groups is not None
        if uses_batched_checks:
            report_ids = await _check_count_triggered_eval_report_candidates_batched(
                result.report_id_groups or [],
                dispatch_due_reports=True,
            )
        else:
            report_ids = await _check_count_triggered_eval_report_candidates(result.report_ids)

        if report_ids and not uses_batched_checks:
            await _dispatch_report_workflows(
                "count_triggered_eval_report",
                "eval-report-count",
                report_ids,
                patch_id="eval-report-count-coordinator-fire-and-forget-2026-09",
            )

        await _ack_eval_report_cursors(result, "count_triggered", inputs.region)


async def _check_count_triggered_eval_report_candidates(report_ids: list[str]) -> list[str]:
    due_report_ids: list[str] = []
    failed: list[tuple[str, str]] = []
    skipped_counts = {
        "cooldown": 0,
        "daily_cap": 0,
        "not_deliverable": 0,
    }

    for batch in batched(report_ids, COUNT_TRIGGER_CHECK_BATCH_SIZE, strict=False):
        tasks = [
            temporalio.workflow.execute_activity(
                check_count_triggered_eval_report_activity,
                CheckCountTriggeredEvalReportInput(report_id=report_id),
                start_to_close_timeout=COUNT_TRIGGER_CHECK_ACTIVITY_TIMEOUT,
                retry_policy=FETCH_RETRY_POLICY,
            )
            for report_id in batch
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for report_id, result in zip(batch, results):
            if isinstance(result, BaseException):
                failed.append((report_id, f"{type(result).__name__}: {result}"))
            elif result.due:
                due_report_ids.append(result.report_id)
            elif result.skipped_reason is not None:
                skipped_counts[result.skipped_reason] = skipped_counts.get(result.skipped_reason, 0) + 1

    if failed:
        temporalio.workflow.logger.warning(
            "count_triggered_eval_report_check.activity_errors",
            extra={"failed_count": len(failed), "failures": failed},
        )

    temporalio.workflow.logger.info(
        "llma_eval_reports_coordinator_count_triggered_poll",
        extra={
            "reports_found": len(due_report_ids),
            "total_checked": len(report_ids),
            "skipped_cooldown": skipped_counts["cooldown"],
            "skipped_daily_cap": skipped_counts["daily_cap"],
            "skipped_not_deliverable": skipped_counts["not_deliverable"],
        },
    )
    record_coordinator_reports_found(len(due_report_ids), "count_triggered")
    return due_report_ids


async def _check_count_triggered_eval_report_candidates_batched(
    report_id_groups: list[list[str]],
    *,
    dispatch_due_reports: bool = False,
) -> list[str]:
    due_report_ids: list[str] = []
    failed: list[tuple[str, str]] = []
    skipped_counts = {
        "cooldown": 0,
        "daily_cap": 0,
        "not_deliverable": 0,
    }

    # Each group holds one team's reports capped at COUNT_TRIGGER_QUERY_WIDTH, so one
    # activity runs one count query under its own timeout and Temporal retry policy, and
    # a ClickHouse failure is contained to that group. The window keeps at most
    # COUNT_TRIGGER_MAX_CONCURRENT_CHECKS count queries in flight — the legacy path's ceiling.
    for index in range(0, len(report_id_groups), COUNT_TRIGGER_MAX_CONCURRENT_CHECKS):
        window = report_id_groups[index : index + COUNT_TRIGGER_MAX_CONCURRENT_CHECKS]
        window_due_report_ids: list[str] = []
        tasks = [
            temporalio.workflow.execute_activity(
                check_count_triggered_eval_reports_activity,
                CheckCountTriggeredEvalReportsBatchInput(report_ids=group),
                start_to_close_timeout=COUNT_TRIGGER_CHECK_ACTIVITY_TIMEOUT,
                retry_policy=FETCH_RETRY_POLICY,
            )
            for group in window
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for group, group_result in zip(window, results):
            if isinstance(group_result, BaseException):
                # A group's activity exhausted its retries — attribute every report in it so
                # the failure is visible, while other groups still contribute their results.
                for report_id in group:
                    failed.append((report_id, f"{type(group_result).__name__}: {group_result}"))
                continue
            for output in group_result.results:
                if output.due:
                    due_report_ids.append(output.report_id)
                    window_due_report_ids.append(output.report_id)
                elif output.skipped_reason is not None:
                    skipped_counts[output.skipped_reason] = skipped_counts.get(output.skipped_reason, 0) + 1

        # Start reports as each bounded check window completes. If the coordinator later
        # reaches its execution timeout, results from earlier windows are still delivered;
        # the unacknowledged discovery cursor makes the unfinished page safe to retry.
        if dispatch_due_reports and window_due_report_ids:
            await _dispatch_report_workflows(
                "count_triggered_eval_report",
                "eval-report-count",
                window_due_report_ids,
                patch_id="eval-report-count-coordinator-fire-and-forget-2026-09",
            )

    if failed:
        temporalio.workflow.logger.warning(
            "count_triggered_eval_report_check.activity_errors",
            extra={"failed_count": len(failed), "failures": failed},
        )

    temporalio.workflow.logger.info(
        "llma_eval_reports_coordinator_count_triggered_poll",
        extra={
            "reports_found": len(due_report_ids),
            "total_checked": sum(len(group) for group in report_id_groups),
            "skipped_cooldown": skipped_counts["cooldown"],
            "skipped_daily_cap": skipped_counts["daily_cap"],
            "skipped_not_deliverable": skipped_counts["not_deliverable"],
        },
    )
    record_coordinator_reports_found(len(due_report_ids), "count_triggered")
    return due_report_ids


async def _dispatch_report_workflows(
    kind: str,
    workflow_id_prefix: str,
    report_ids: list[str],
    *,
    patch_id: str,
) -> None:
    if temporalio.workflow.patched(patch_id):
        await _start_report_workflows(kind, workflow_id_prefix, report_ids)
        return

    # When the patch marker is absent, preserve the command sequence required for replay.
    tasks = [
        temporalio.workflow.execute_child_workflow(
            GenerateAndDeliverEvalReportWorkflow.run,
            GenerateAndDeliverEvalReportWorkflowInput(report_id=report_id),
            id=f"{workflow_id_prefix}-{report_id}",
            execution_timeout=WORKFLOW_EXECUTION_TIMEOUT,
        )
        for report_id in report_ids
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    _log_legacy_fan_out_failures(kind, report_ids, results)


async def _start_report_workflows(kind: str, workflow_id_prefix: str, report_ids: list[str]) -> None:
    """Start bounded report children and return after Temporal accepts each command.

    The coordinator must not live for the full report-generation duration: doing so turns
    every report into coordinator history and makes an hourly/5-minute poll vulnerable to
    one slow child. ABANDON keeps accepted children running after this coordinator closes.
    """

    # An awaited start resolves only after the server records the child. Emit bounded groups so
    # dispatch does not spend one workflow task per report or put the whole page into one command
    # activation.
    results: list[bool | BaseException] = []
    for report_id_batch in batched(report_ids, REPORT_START_BATCH_SIZE, strict=False):
        results.extend(
            await asyncio.gather(
                *(_start_report_workflow(workflow_id_prefix, report_id) for report_id in report_id_batch),
                return_exceptions=True,
            )
        )

    already_started = 0
    failed_count = 0
    failure_samples: list[tuple[str, str]] = []
    for report_id, result in zip(report_ids, results):
        if isinstance(result, BaseException):
            failed_count += 1
            if len(failure_samples) < 20:
                failure_samples.append((report_id, f"{type(result).__name__}: {result}"))
        elif result is False:
            already_started += 1

    # A report child can outlive the poll interval, and its id carries no timestamp, so the
    # next poll reaching a still-open run is deduplication rather than a start failure. Only
    # a real failure warns, so an operator who mutes the overlap doesn't mute that too.
    if failed_count:
        temporalio.workflow.logger.warning(
            f"{kind}.child_workflow_start_errors",
            extra={
                "already_started_count": already_started,
                "failed_count": failed_count,
                "failure_samples": failure_samples,
            },
        )
    elif already_started:
        temporalio.workflow.logger.info(
            f"{kind}.child_workflow_already_running",
            extra={"already_started_count": already_started},
        )


async def _start_report_workflow(workflow_id_prefix: str, report_id: str) -> bool:
    """Start one report child. False means a previous coordinator's run is still open."""

    try:
        await temporalio.workflow.start_child_workflow(
            GenerateAndDeliverEvalReportWorkflow.run,
            GenerateAndDeliverEvalReportWorkflowInput(report_id=report_id),
            id=f"{workflow_id_prefix}-{report_id}",
            task_queue=settings.LLMA_TASK_QUEUE,
            parent_close_policy=temporalio.workflow.ParentClosePolicy.ABANDON,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            execution_timeout=WORKFLOW_EXECUTION_TIMEOUT,
        )
        return True
    except WorkflowAlreadyStartedError:
        return False


async def _ack_eval_report_cursors(
    result: FetchDueEvalReportsOutput,
    trigger_type: str,
    region: str,
) -> None:
    if result.cursor_before is None or not result.report_ids:
        return

    advanced = await temporalio.workflow.execute_activity(
        ack_eval_report_cursors_activity,
        AckEvalReportCursorsInput(
            trigger_type=trigger_type,
            region=region,
            cursor_before=result.cursor_before,
            report_ids=result.report_ids,
        ),
        start_to_close_timeout=UPDATE_SCHEDULE_ACTIVITY_TIMEOUT,
        retry_policy=UPDATE_SCHEDULE_RETRY_POLICY,
    )
    if not advanced:
        temporalio.workflow.logger.warning(
            "eval_report_coordinator.cursor_acknowledgement_conflict",
            extra={"trigger_type": trigger_type, "reports_count": len(result.report_ids)},
        )


def _log_legacy_fan_out_failures(kind: str, report_ids: list[str], results: list) -> None:
    failed = [
        (report_id, f"{type(result).__name__}: {result}")
        for report_id, result in zip(report_ids, results)
        if isinstance(result, BaseException)
    ]
    if failed:
        temporalio.workflow.logger.warning(
            f"{kind}.child_workflow_errors",
            extra={"failed_count": len(failed), "failures": failed[:20]},
        )


async def _update_report_schedule(inputs: UpdateNextDeliveryDateInput) -> None:
    await temporalio.workflow.execute_activity(
        update_next_delivery_date_activity,
        inputs,
        start_to_close_timeout=UPDATE_SCHEDULE_ACTIVITY_TIMEOUT,
        retry_policy=UPDATE_SCHEDULE_RETRY_POLICY,
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
        trace_id = str(temporalio.workflow.uuid4())
        session_id = str(temporalio.workflow.uuid4())

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
                output_type=context.output_type,
                true_is_failure=context.true_is_failure,
                period_start=context.period_start,
                period_end=context.period_end,
                previous_period_start=context.previous_period_start,
                report_prompt_guidance=context.report_prompt_guidance,
                trace_id=trace_id,
                session_id=session_id,
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

        generation_status = (
            agent_result.generation_status
            if temporalio.workflow.patched("eval-report-generation-status-2026-07")
            else "completed"
        )
        generation_completed = generation_status == "completed"
        attempt_before_delivery = temporalio.workflow.patched("eval-report-attempt-before-delivery-2026-07")

        if not inputs.manual and (attempt_before_delivery or not generation_completed):
            await _update_report_schedule(
                UpdateNextDeliveryDateInput(
                    report_id=inputs.report_id,
                    period_end=context.period_end,
                    generation_status=generation_status,
                    advance_data_cursor=False if attempt_before_delivery else None,
                )
            )

        # 3b. Emit a signal for this report run (fire-and-forget).
        # Runs on the same LLMA worker as the parent via LLMA_TASK_QUEUE; ABANDON
        # parent-close lets the LLM summary call continue independently so it doesn't
        # block delivery. Gated by the team-level SignalSourceConfig(LLM_ANALYTICS,
        # EVALUATION_REPORT) row — the activity bails out early for teams that
        # haven't opted in.
        # Wrapped in workflow.patched so in-flight workflows started before this code
        # was deployed don't hit a nondeterminism error on replay — they'll skip the
        # child-workflow command entirely.
        if generation_completed and temporalio.workflow.patched("eval-report-emit-signal-2026-04"):
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
                logger.info(
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

        # 5. Advance the successful data cursor (skip for manual runs to avoid disrupting schedule)
        if not inputs.manual and generation_completed:
            await _update_report_schedule(
                UpdateNextDeliveryDateInput(
                    report_id=inputs.report_id,
                    period_end=context.period_end,
                    generation_status=generation_status,
                    record_attempt=not attempt_before_delivery,
                    advance_data_cursor=True,
                )
            )
