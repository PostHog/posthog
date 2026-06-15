"""
Auto-provision an initial gateway for every team.

Gateways are project-scoped, so the initial one binds to the canonical (parent)
team and child environments share it. New teams via the post_save signal here,
existing teams via migration 1216. It's an ordinary gateway — teams may rename
or delete it.
"""

from django.db.models.signals import post_save

from posthog.models.gateway import DEFAULT_GATEWAY_SLUG, Gateway
from posthog.models.team.team import Team


def provision_default_gateway(team_id: int) -> None:
    """Create the team's initial gateway if absent.

    Unscoped manager (no team context in the signal), keyed on the canonical
    team_id so get_or_create matches where TeamScopedRootMixin.save() writes.
    """
    Gateway.all_teams.get_or_create(team_id=team_id, slug=DEFAULT_GATEWAY_SLUG)


def _provision_on_team_create(sender: type[Team], instance: Team, created: bool, **kwargs: object) -> None:
    # Only a brand-new canonical team provisions. A child environment shares its
    # parent's gateway, already provisioned when the parent was created — re-running
    # get_or_create here would resurrect a "default" the team deleted or renamed.
    if not created or instance.parent_team_id is not None:
        return
    provision_default_gateway(instance.id)


def connect_signal_handlers() -> None:
    post_save.connect(_provision_on_team_create, sender=Team, dispatch_uid="provision_default_gateway")
