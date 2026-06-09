from __future__ import annotations

import dataclasses

import structlog
import temporalio.activity

from posthog.models import Team
from posthog.models.organization import OrganizationMembership
from posthog.sync import database_sync_to_async
from posthog.temporal.ai_observability.ai_observability_reports.types import (
    FetchEnabledConfigsOutput,
    RunAIObservabilityReportAgentInput,
    RunAIObservabilityReportAgentOutput,
)
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.scoped import scoped_temporal

logger = structlog.get_logger(__name__)


@dataclasses.dataclass
class _DigestContext:
    team: Team
    initial_prompt: str
    slack_integration_id: int | str | None
    slack_channel: str
    user_id: int
    skill_name: str


def _resolve_digest_user_id(team: Team, created_by_id: int | None) -> int:
    """Pick a PostHog user to attribute the sandbox run to.

    Unlike repo-backed agents, the digest does no GitHub work, so we don't require a GitHub
    integration: prefer the config's creator (if still an active org member), else any active
    member. Raises if the org has no active users.
    """
    if created_by_id is not None:
        is_active = OrganizationMembership.objects.filter(
            organization=team.organization,
            user_id=created_by_id,
            user__is_active=True,
        ).exists()
        if is_active:
            return created_by_id
    membership = (
        OrganizationMembership.objects.filter(organization=team.organization, user__is_active=True)
        .order_by("id")
        .first()
    )
    if not membership:
        raise RuntimeError(f"No active users in organization for team {team.id}; cannot run AI observability digest")
    return membership.user_id


def _build_initial_prompt(skill_body: str, additional_instructions: str) -> str:
    parts = [
        "You are running the daily AI observability digest for this team.",
        "## Skill instructions",
        skill_body.strip(),
    ]
    if additional_instructions.strip():
        parts.extend(["## Additional instructions", additional_instructions.strip()])
    return "\n\n".join(parts)


def _load_digest_context(config_id: str) -> _DigestContext | None:
    """Resolve everything the agent needs from a config row. Returns None to skip the run."""
    from products.ai_observability.backend.models import AIObservabilityReportConfig
    from products.signals.backend.scout_harness.skill_loader import SkillNotFoundError, load_skill_for_run

    config = (
        AIObservabilityReportConfig.all_teams.select_related("team", "team__organization").filter(id=config_id).first()
    )
    if config is None or not config.enabled:
        logger.info("ai_observability_digest_skip_disabled", config_id=config_id)
        return None
    if not config.slack_integration_id or not config.slack_channel:
        logger.warning("ai_observability_digest_skip_no_slack", config_id=config_id, team_id=config.team_id)
        return None

    team = config.team
    # Mirror the consent gate enforced by emit_signal / arun_agent — the digest sends team
    # data through an LLM + sandbox.
    if not team.organization.is_ai_data_processing_approved:
        logger.warning("ai_observability_digest_skip_no_consent", config_id=config_id, team_id=team.id)
        return None

    # A stale config pointing at a deleted/renamed skill should skip quietly, not fail the
    # child workflow — one team's bad config shouldn't generate noisy daily failures.
    try:
        skill = load_skill_for_run(team, config.skill_name)
    except SkillNotFoundError:
        logger.warning(
            "ai_observability_digest_skip_missing_skill",
            config_id=config_id,
            team_id=team.id,
            skill_name=config.skill_name,
        )
        return None
    user_id = _resolve_digest_user_id(team, config.created_by_id)
    return _DigestContext(
        team=team,
        initial_prompt=_build_initial_prompt(skill.body, config.additional_instructions),
        slack_integration_id=config.slack_integration_id,
        slack_channel=config.slack_channel,
        user_id=user_id,
        skill_name=skill.name,
    )


def _stamp_last_run_at(config_id: str) -> None:
    from django.utils import timezone

    from products.ai_observability.backend.models import AIObservabilityReportConfig

    AIObservabilityReportConfig.all_teams.filter(id=config_id).update(last_run_at=timezone.now())


@temporalio.activity.defn
@scoped_temporal()
async def fetch_enabled_ai_observability_report_configs_activity() -> FetchEnabledConfigsOutput:
    """Return the IDs of every enabled config wired to a Slack integration."""

    def _fetch() -> list[str]:
        from products.ai_observability.backend.models import AIObservabilityReportConfig

        ids = (
            AIObservabilityReportConfig.all_teams.filter(
                enabled=True,
                slack_integration__isnull=False,
                slack_integration__kind="slack",
            )
            .exclude(slack_channel="")
            .order_by("created_at", "id")
            .values_list("id", flat=True)
        )
        return [str(i) for i in ids]

    config_ids = await database_sync_to_async(_fetch, thread_sensitive=False)()
    logger.info("ai_observability_digest_configs_discovered", count=len(config_ids))
    return FetchEnabledConfigsOutput(config_ids=config_ids)


@temporalio.activity.defn
@scoped_temporal()
async def run_ai_observability_report_agent_activity(
    inputs: RunAIObservabilityReportAgentInput,
) -> RunAIObservabilityReportAgentOutput:
    """Run the digest agent for one config: load skill, execute in sandbox, post to Slack."""
    from posthog.temporal.ai_observability.ai_observability_reports.agent import AIObservabilityDigestAgent

    from products.signals.backend.custom_agent.base import NO_REPO

    log = logger.bind(config_id=inputs.config_id)
    async with Heartbeater():
        context = await database_sync_to_async(_load_digest_context, thread_sensitive=False)(inputs.config_id)
        if context is None:
            return RunAIObservabilityReportAgentOutput(delivered=False, skill_name="")

        agent = AIObservabilityDigestAgent(
            team=context.team,
            initial_prompt=context.initial_prompt,
            repository=NO_REPO,
            slack_integration_id=context.slack_integration_id,
            slack_channel=context.slack_channel,
            user_id=context.user_id,
        )
        await agent.start()
        # Stamp only after a successful run so `last_run_at` stays a reliable signal of the
        # last good digest (a failed run leaves it untouched).
        await database_sync_to_async(_stamp_last_run_at, thread_sensitive=False)(inputs.config_id)

        log.info("ai_observability_digest_agent_completed", skill_name=context.skill_name)
        return RunAIObservabilityReportAgentOutput(delivered=True, skill_name=context.skill_name)
