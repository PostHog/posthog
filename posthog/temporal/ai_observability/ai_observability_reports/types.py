import dataclasses

from posthog.temporal.ai_observability.ai_observability_reports.constants import DEFAULT_MAX_CONCURRENT_CONFIGS


@dataclasses.dataclass
class AIObservabilityReportCoordinatorInputs:
    """Inputs for the daily coordinator. It fetches all enabled configs fresh each tick."""

    max_concurrent_configs: int = DEFAULT_MAX_CONCURRENT_CONFIGS


@dataclasses.dataclass
class FetchEnabledConfigsOutput:
    config_ids: list[str]


@dataclasses.dataclass
class GenerateAIObservabilityReportInput:
    config_id: str


@dataclasses.dataclass
class RunAIObservabilityReportAgentInput:
    config_id: str


@dataclasses.dataclass
class RunAIObservabilityReportAgentOutput:
    # Empty when the agent ran but produced no report (the expected path — this agent never
    # files a Signals report). `delivered` reflects whether a Slack message was posted.
    delivered: bool
    skill_name: str
