from __future__ import annotations

import structlog

from posthog.models import Team
from posthog.sync import database_sync_to_async

from products.ai_observability.backend.ai_observability_digest.delivery import deliver_overview_to_slack
from products.ai_observability.backend.ai_observability_digest.schema import AIObservabilityOverview
from products.signals.backend.custom_agent import CustomSignalAgent

logger = structlog.get_logger(__name__)

_OVERVIEW_DIRECTIVE = (
    "Now execute the skill instructions above against this team's AI observability data, using the "
    "available read-only PostHog MCP tools to gather the numbers (errors, costliest users, tool usage "
    "and errors, evaluation pass rates, cluster results, LLM latencies, and anything else the skill "
    "asks for). Summarize the current status into the structured overview below. Ground every section "
    "in data you actually retrieved and include concrete numbers; omit any section you have no data for."
)


class AIObservabilityDigestAgent(CustomSignalAgent):
    """Daily AI observability digest agent.

    Runs a team-authored skill (loaded into ``initial_prompt`` by the caller) against the
    team's AI observability data via read-only MCP, then posts the resulting structured
    overview to a Slack channel. It never files a Signals report — ``run`` returns ``False``
    so the base class skips report finalization entirely; Slack is the only output.
    """

    def __init__(
        self,
        *,
        team: Team,
        initial_prompt: str,
        repository: str | None,
        slack_integration_id: int | str | None,
        slack_channel: str,
        user_id: int | None = None,
        model: str | None = None,
    ) -> None:
        super().__init__(
            team=team,
            initial_prompt=initial_prompt,
            repository=repository,
            user_id=user_id,
            model=model,
        )
        self.slack_integration_id = slack_integration_id
        self.slack_channel = slack_channel

    @classmethod
    def identifier(cls) -> tuple[str, str]:
        return "llma", "ai_observability_digest"

    async def run(self) -> bool:
        overview = await self.send(
            _OVERVIEW_DIRECTIVE,
            AIObservabilityOverview,
            label="ai_observability_overview",
        )
        await database_sync_to_async(deliver_overview_to_slack, thread_sensitive=False)(
            team_id=self.team_id,
            integration_id=self.slack_integration_id,
            channel=self.slack_channel,
            overview=overview,
        )
        logger.info(
            "ai_observability_digest_completed",
            team_id=self.team_id,
            channel=self.slack_channel,
            section_count=len(overview.sections),
        )
        # Slack-only digest: never create a Signals report.
        return False
