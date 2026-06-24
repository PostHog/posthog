from __future__ import annotations

import structlog

from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team

from products.tasks.backend.facade import api as tasks_facade

logger = structlog.get_logger(__name__)

CONVERSATIONS_SUPPORT_REPLY_ENV_NAME = "CONVERSATIONS_SUPPORT_REPLY"


def get_or_create_support_sandbox_env(team_id: int) -> str:
    """Get or create the sandbox environment for conversations support reply drafting.

    Returns the env ID as a string. Reasserts policy on every call; the facade dedupes if a
    concurrent call raced past the SELECT and produced multiple rows.

    Ticket content is attacker-controlled (public widget/email), so this sandbox processes
    untrusted input with read MCP scopes. Lock egress to CUSTOM with an empty allowlist: the
    agent can still reach the always-on INFRASTRUCTURE_DOMAINS (*.posthog.com for MCP, the LLM
    gateways, api.anthropic.com), but NOT github/pypi/npm/etc. — closing the prompt-injection
    exfiltration channel that TRUSTED's broad allowlist would otherwise leave open. This agent
    only drafts text + calls read-only MCP tools; it has no reason to fetch from the internet.
    """
    return str(
        tasks_facade.upsert_internal_sandbox_env(
            team_id,
            CONVERSATIONS_SUPPORT_REPLY_ENV_NAME,
            tasks_facade.SandboxNetworkAccessLevel.CUSTOM,
            private=False,
            internal=True,
            allowed_domains=[],
            include_default_domains=False,
        )
    )


def resolve_user_id_for_support(team_id: int) -> int:
    """Resolve a user for autonomous sandbox runs — picks the oldest active org member.

    Unlike the Signals resolver, this does NOT require a GitHub integration. The support
    reply pipeline is autonomous with no human trigger and no repo context.
    """
    team = Team.objects.select_related("organization").get(id=team_id)
    membership = (
        OrganizationMembership.objects.select_related("user")
        .filter(organization=team.organization, user__is_active=True)
        .order_by("id")
        .first()
    )
    if not membership:
        raise RuntimeError(f"No active users in organization '{team.organization.name}' (team {team.id})")
    return membership.user_id
