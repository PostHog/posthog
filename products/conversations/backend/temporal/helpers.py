from __future__ import annotations

from django.db import transaction

import structlog

from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team

from products.tasks.backend.models import SandboxEnvironment

logger = structlog.get_logger(__name__)

CONVERSATIONS_SUPPORT_REPLY_ENV_NAME = "CONVERSATIONS_SUPPORT_REPLY"

# Ticket content is attacker-controlled (public widget/email), so this sandbox processes
# untrusted input with read MCP scopes. Lock egress to CUSTOM with an empty allowlist: the
# agent can still reach the always-on INFRASTRUCTURE_DOMAINS (*.posthog.com for MCP, the LLM
# gateways, api.anthropic.com), but NOT github/pypi/npm/etc. — closing the prompt-injection
# exfiltration channel that TRUSTED's broad allowlist would otherwise leave open. This agent
# only drafts text + calls read-only MCP tools; it has no reason to fetch from the internet.
_SANDBOX_DEFAULTS = {
    "network_access_level": SandboxEnvironment.NetworkAccessLevel.CUSTOM,
    "allowed_domains": [],
    "include_default_domains": False,
    "private": False,
    "internal": True,
}


def get_or_create_support_sandbox_env(team_id: int) -> str:
    """Get or create the sandbox environment for conversations support reply drafting.

    Returns the env ID as a string. Uses update_or_create to reassert policy on every call.

    SandboxEnvironment has no unique constraint on (team_id, name), so concurrent calls
    can race past the SELECT and both INSERT. We catch MultipleObjectsReturned, keep the
    oldest row, delete the rest, and retry.
    """
    try:
        env, _ = SandboxEnvironment.objects.update_or_create(
            team_id=team_id,
            name=CONVERSATIONS_SUPPORT_REPLY_ENV_NAME,
            defaults=_SANDBOX_DEFAULTS,
        )
        return str(env.id)
    except SandboxEnvironment.MultipleObjectsReturned:
        logger.warning(
            "support_sandbox_env_duplicate_detected",
            team_id=team_id,
            name=CONVERSATIONS_SUPPORT_REPLY_ENV_NAME,
        )
        with transaction.atomic():
            dupes = list(
                SandboxEnvironment.objects.filter(team_id=team_id, name=CONVERSATIONS_SUPPORT_REPLY_ENV_NAME).order_by(
                    "created_at"
                )
            )
            keeper = dupes[0]
            SandboxEnvironment.objects.filter(id__in=[d.id for d in dupes[1:]]).delete()
        for key, value in _SANDBOX_DEFAULTS.items():
            setattr(keeper, key, value)
        keeper.save(update_fields=list(_SANDBOX_DEFAULTS.keys()))
        return str(keeper.id)


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
