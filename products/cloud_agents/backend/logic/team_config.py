"""Read and lock the `TeamCloudAgentsConfig` row of a project."""

from __future__ import annotations

from posthog.models import Team
from posthog.models.scoping import team_scope
from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.models.team.extensions import get_or_create_team_extension

from ..models import TeamCloudAgentsConfig


def get_team_config(team_id: int) -> TeamCloudAgentsConfig:
    """Return the config row of the project. The first read creates it with no values set."""
    # The row belongs to the canonical team, the same team that the scoped manager filters by.
    canonical_id = resolve_effective_team_id(team_id)
    with team_scope(canonical_id, canonical=True):
        return get_or_create_team_extension(Team.objects.get(id=canonical_id), TeamCloudAgentsConfig)


def lock_team_config(team_id: int) -> TeamCloudAgentsConfig:
    """Lock the config row until the transaction ends. Use it as the per-project lock of this product.

    Team and Organization rows must not be the lock: foreign-key checks of unrelated writes wait on them.
    """
    config = get_team_config(team_id)
    return TeamCloudAgentsConfig.objects.for_team(team_id).select_for_update().get(pk=config.pk)
