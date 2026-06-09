"""Per-config workflow: run the digest agent for one team's AI observability report config."""

import temporalio.workflow
from structlog import get_logger

from posthog.temporal.ai_observability.ai_observability_reports.constants import (
    AGENT_ACTIVITY_TIMEOUT,
    AGENT_HEARTBEAT_TIMEOUT,
    AGENT_RETRY_POLICY,
    GENERATE_WORKFLOW_NAME,
)
from posthog.temporal.ai_observability.ai_observability_reports.types import (
    GenerateAIObservabilityReportInput,
    RunAIObservabilityReportAgentInput,
)
from posthog.temporal.common.base import PostHogWorkflow

with temporalio.workflow.unsafe.imports_passed_through():
    from posthog.temporal.ai_observability.ai_observability_reports.activities import (
        run_ai_observability_report_agent_activity,
    )

logger = get_logger(__name__)


@temporalio.workflow.defn(name=GENERATE_WORKFLOW_NAME)
class GenerateAIObservabilityReportWorkflow(PostHogWorkflow):
    """Runs the digest agent for a single config. The agent posts to Slack and files no report."""

    inputs_cls = GenerateAIObservabilityReportInput

    @temporalio.workflow.run
    async def run(self, inputs: GenerateAIObservabilityReportInput) -> None:
        await temporalio.workflow.execute_activity(
            run_ai_observability_report_agent_activity,
            RunAIObservabilityReportAgentInput(config_id=inputs.config_id),
            start_to_close_timeout=AGENT_ACTIVITY_TIMEOUT,
            heartbeat_timeout=AGENT_HEARTBEAT_TIMEOUT,
            retry_policy=AGENT_RETRY_POLICY,
        )
