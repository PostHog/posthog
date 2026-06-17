from __future__ import annotations

from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team

from products.tasks.backend.models import SandboxEnvironment

CONVERSATIONS_SUPPORT_REPLY_ENV_NAME = "CONVERSATIONS_SUPPORT_REPLY"


def get_or_create_support_sandbox_env(team_id: int) -> str:
    """Get or create the sandbox environment for conversations support reply drafting.

    Returns the env ID as a string. Uses update_or_create to reassert policy on every call.
    """
    env, _ = SandboxEnvironment.objects.update_or_create(
        team_id=team_id,
        name=CONVERSATIONS_SUPPORT_REPLY_ENV_NAME,
        defaults={
            "network_access_level": SandboxEnvironment.NetworkAccessLevel.TRUSTED,
            "private": False,
            "internal": True,
        },
    )
    return str(env.id)


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
