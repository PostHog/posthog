"""
Abstract model for main-DB models that should be team-scoped fail-closed.

Main-DB counterpart of `ProductTeamModel`. Bundles the canonical-team
save() rewrite from `RootTeamMixin` with the fail-closed `TeamScopedManager`,
so new main-DB models opt into both with a single base class.

Usage:

    from posthog.models.scoping.root_mixin import TeamScopedRootMixin

    class Campaign(TeamScopedRootMixin):
        team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
        name = models.CharField(max_length=255)

    # In DRF view (mixin sets canonical team context):
    Campaign.objects.all()              # Auto-filtered to canonical team

    # Explicit cross-team:
    Campaign.objects.unscoped().all()   # No filtering

    # Background jobs (auto-resolves to canonical):
    with team_scope(team_id):
        Campaign.objects.all()

The pre-existing `RootTeamMixin` stays in place for the ~263 legacy main-DB
models that haven't audited their call sites yet — adopting fail-closed
requires walking every read path. `TeamScopedRootMixin` is the prescribed
default for *new* main-DB models so they start fail-closed.
"""

from __future__ import annotations

from posthog.models.scoping.manager import TeamScopedManager
from posthog.models.utils import RootTeamMixin


class TeamScopedRootMixin(RootTeamMixin):
    """Abstract base for main-DB models that want fail-closed team scoping.

    Inherits the canonical-team save() rewrite from `RootTeamMixin` and
    overrides `objects` to use the fail-closed `TeamScopedManager`.
    Subclasses still declare their own `team = models.ForeignKey(...)` —
    `RootTeamMixin` does not declare the FK so cascade behavior remains
    a per-model decision.
    """

    objects = TeamScopedManager()

    class Meta:
        abstract = True


__all__ = ["TeamScopedRootMixin"]
