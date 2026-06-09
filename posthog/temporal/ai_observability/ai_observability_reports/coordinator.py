"""Daily coordinator: scan enabled AI observability report configs and fan out per config."""

import asyncio

import temporalio.workflow
from structlog import get_logger

from posthog.temporal.ai_observability.ai_observability_reports.constants import (
    COORDINATOR_WORKFLOW_NAME,
    FETCH_ACTIVITY_TIMEOUT,
    FETCH_RETRY_POLICY,
    GENERATE_WORKFLOW_EXECUTION_TIMEOUT,
)
from posthog.temporal.ai_observability.ai_observability_reports.types import (
    AIObservabilityReportCoordinatorInputs,
    GenerateAIObservabilityReportInput,
)
from posthog.temporal.ai_observability.ai_observability_reports.workflow import GenerateAIObservabilityReportWorkflow
from posthog.temporal.common.base import PostHogWorkflow

with temporalio.workflow.unsafe.imports_passed_through():
    from posthog.temporal.ai_observability.ai_observability_reports.activities import (
        fetch_enabled_ai_observability_report_configs_activity,
    )

logger = get_logger(__name__)


@temporalio.workflow.defn(name=COORDINATOR_WORKFLOW_NAME)
class AIObservabilityReportCoordinatorWorkflow(PostHogWorkflow):
    """Daily fan-out: one child `GenerateAIObservabilityReportWorkflow` per enabled config.

    Child failures are isolated (a broken skill or disconnected Slack on one team must not
    block the others) and logged for observability.
    """

    inputs_cls = AIObservabilityReportCoordinatorInputs
    inputs_optional = True

    @temporalio.workflow.run
    async def run(self, inputs: AIObservabilityReportCoordinatorInputs) -> None:
        result = await temporalio.workflow.execute_activity(
            fetch_enabled_ai_observability_report_configs_activity,
            start_to_close_timeout=FETCH_ACTIVITY_TIMEOUT,
            retry_policy=FETCH_RETRY_POLICY,
        )
        if not result.config_ids:
            return

        run_stamp = temporalio.workflow.now().isoformat()
        max_concurrent = max(1, inputs.max_concurrent_configs)
        for batch_start in range(0, len(result.config_ids), max_concurrent):
            batch = result.config_ids[batch_start : batch_start + max_concurrent]
            tasks = [
                temporalio.workflow.execute_child_workflow(
                    GenerateAIObservabilityReportWorkflow.run,
                    GenerateAIObservabilityReportInput(config_id=config_id),
                    id=f"ai-observability-report-{config_id}-{run_stamp}",
                    execution_timeout=GENERATE_WORKFLOW_EXECUTION_TIMEOUT,
                )
                for config_id in batch
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            _log_fan_out_failures(batch, results)


def _log_fan_out_failures(config_ids: list[str], results: list) -> None:
    failed = [
        (config_id, f"{type(result).__name__}: {result}")
        for config_id, result in zip(config_ids, results)
        if isinstance(result, BaseException)
    ]
    if failed:
        temporalio.workflow.logger.warning(
            "ai_observability_report_coordinator.child_workflow_errors",
            extra={"failed_count": len(failed), "failures": failed},
        )
