from posthog.temporal.ai_observability.ai_observability_reports.activities import (
    fetch_enabled_ai_observability_report_configs_activity,
    run_ai_observability_report_agent_activity,
)
from posthog.temporal.ai_observability.ai_observability_reports.coordinator import (
    AIObservabilityReportCoordinatorWorkflow,
)
from posthog.temporal.ai_observability.ai_observability_reports.workflow import GenerateAIObservabilityReportWorkflow

WORKFLOWS = [
    AIObservabilityReportCoordinatorWorkflow,
    GenerateAIObservabilityReportWorkflow,
]

ACTIVITIES = [
    fetch_enabled_ai_observability_report_configs_activity,
    run_ai_observability_report_agent_activity,
]

__all__ = [
    "ACTIVITIES",
    "WORKFLOWS",
    "AIObservabilityReportCoordinatorWorkflow",
    "GenerateAIObservabilityReportWorkflow",
    "fetch_enabled_ai_observability_report_configs_activity",
    "run_ai_observability_report_agent_activity",
]
