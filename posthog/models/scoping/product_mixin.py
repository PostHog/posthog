"""
Team mixin for product models on separate databases.

Multi-DB counterpart of RootTeamMixin. Provides:
- team_id as a plain BigIntegerField (no FK to Team — can't cross databases)
- Auto-scoping via ContextVar middleware (same as TeamScopedManager)
- Parent team resolution without JOINs (fetches from main DB or context cache)
- unscoped() escape hatch for intentional cross-team queries

Shares the same ContextVar infrastructure and middleware as TeamScopedManager.
The only difference is how the team filter is applied: plain team_id filtering
instead of JOINing to Team. This prevents the two approaches from drifting.

Usage:

    from posthog.models.scoping.product_mixin import ProductTeamModel

    class Repo(ProductTeamModel):
        repo_name = models.CharField(max_length=255)

    # In request context (automatic via middleware):
    Repo.objects.all()              # Auto-filtered to current team

    # Explicit cross-team:
    Repo.objects.unscoped().all()   # No filtering

    # Background jobs:
    with team_scope(team_id):
        Repo.objects.all()          # Filtered to team_id
"""

from __future__ import annotations

from django.db import models

from posthog.models.scoping import get_current_team_context
from posthog.models.scoping.manager import TeamScopedManager, TeamScopedQuerySet


def _resolve_effective_team_id(team_id: int) -> int:
    """Resolve parent team without a JOIN.

    Uses the cached parent_team_id from ContextVar if available,
    otherwise does a single-row fetch from the main database.
    """
    # Only trust cached value when parent_team_id was explicitly resolved.
    # `None` could mean "this is a root team" or "we just don't know yet" —
    # falling back to team_id in the latter case would silently scope queries
    # to the child team and miss data stored under the parent.
    ctx = get_current_team_context()
    if ctx is not None and ctx.team_id == team_id and ctx.parent_team_id is not None:
        return ctx.parent_team_id

    from posthog.models.team import Team

    try:
        team = Team.objects.using("default").get(id=team_id)
        return team.parent_team_id if team.parent_team_id else team_id
    except Team.DoesNotExist:
        return team_id


class ProductTeamQuerySet(TeamScopedQuerySet):
    """QuerySet for product models on separate databases.

    Inherits unscoped() from TeamScopedQuerySet. Overrides
    _apply_team_filter to avoid JOINing to Team across databases.
    """

    def unscoped(self) -> ProductTeamQuerySet:
        """Return a queryset that bypasses automatic team scoping."""
        return ProductTeamQuerySet(self.model, using=self._db)  # type: ignore[attr-defined]

    def _apply_team_filter(self, team_id: int) -> ProductTeamQuerySet:
        """Apply team filter using plain team_id (no JOIN)."""
        effective_id = _resolve_effective_team_id(team_id)
        return super(TeamScopedQuerySet, self).filter(team_id=effective_id)


class ProductTeamManager(TeamScopedManager):
    """Fail-closed manager for product models on separate databases.

    Subclass of TeamScopedManager — shares the same get_queryset flow
    and ContextVar integration. Only the queryset class differs (uses
    ProductTeamQuerySet which filters by plain team_id instead of JOIN).
    """

    _queryset_class = ProductTeamQuerySet

    def for_team(self, team_id: int) -> ProductTeamQuerySet:
        """Explicitly scope to a team. Useful outside request context."""
        effective_id = _resolve_effective_team_id(team_id)
        return ProductTeamQuerySet(self.model, using=self._db).filter(team_id=effective_id)


class ProductTeamModel(models.Model):
    """Abstract base for product models that live on a separate database.

    Provides team_id as a plain BigIntegerField (no FK constraint)
    and a fail-closed manager that auto-scopes queries by the current
    team context.

    Accessing .objects without team context raises TeamScopeError.
    Use .unscoped for intentional cross-team access (migrations, admin,
    background jobs without context).
    """

    team_id = models.BigIntegerField(db_index=True)

    objects = ProductTeamManager()
    unscoped = models.Manager()  # noqa: DJ012 — both are managers, ruff misclassifies this

    class Meta:
        abstract = True
