"""
Auto-provision a default gateway for every team.

Every team gets one gateway named "default" so first-party credentials always
have something to bind to. Bound to the canonical (parent) team — gateways are
project-scoped, not environment-scoped — so child environments share the
project's default rather than each minting their own.

New teams are provisioned by the post_save signal here; existing teams by the
backfill migration (1213). Provisioning is idempotent: get_or_create against the
canonical team + "default" slug, guarded by the per-team unique constraints.
"""

from django.db.models.signals import post_save

import structlog

from posthog.models.gateway import DEFAULT_GATEWAY_SLUG, Gateway
from posthog.models.team.team import Team

logger = structlog.get_logger(__name__)


def provision_default_gateway(team_id: int) -> None:
    """Create the team's default gateway if it doesn't already have one.

    Uses the unscoped `all_teams` manager — there is no team context in the
    signal — and writes against the canonical team_id so the row lands where
    TeamScopedRootMixin.save() would put it and get_or_create's lookup matches.
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
