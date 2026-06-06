"""
Auto-provision a default gateway for every team.

Gateways are project-scoped, so the default binds to the canonical (parent) team
and child environments share it. New teams via the post_save signal here,
existing teams via migration 1213.
"""

from django.db.models.signals import post_save

from posthog.models.gateway import DEFAULT_GATEWAY_SLUG, Gateway
from posthog.models.team.team import Team


def provision_default_gateway(team_id: int) -> None:
    """Create the team's default gateway if absent.

    Unscoped manager (no team context in the signal), keyed on the canonical
    team_id so get_or_create matches where TeamScopedRootMixin.save() writes.
    """
    Gateway.all_teams.get_or_create(
        team_id=team_id,
        slug=DEFAULT_GATEWAY_SLUG,
        defaults={"is_default": True},
    )


def _provision_on_team_create(sender: type[Team], instance: Team, created: bool, **kwargs: object) -> None:
    if not created:
        return
    canonical_team_id = instance.parent_team_id or instance.id
    provision_default_gateway(canonical_team_id)


def connect_signal_handlers() -> None:
    post_save.connect(_provision_on_team_create, sender=Team, dispatch_uid="provision_default_gateway")
