"""
Team mixin for product models on separate databases.

Multi-DB counterpart of RootTeamMixin. Provides:
- team_id as a plain BigIntegerField (no FK to Team — can't cross databases)
- save() rewrites team_id to canonical (parent if child env, else self) so
  data always lives at the canonical team_id — symmetric with reads
- Auto-scoping fail-closed manager
- unscoped() escape hatch for intentional cross-team queries

Usage:

    from posthog.models.scoping.product_mixin import ProductTeamModel

    class Repo(ProductTeamModel):
        repo_name = models.CharField(max_length=255)

    # In DRF view (mixin sets canonical team context):
    Repo.objects.all()              # Auto-filtered to canonical team

    # Explicit cross-team:
    Repo.objects.unscoped().all()   # No filtering

    # Background jobs (caller passes canonical team_id):
    with team_scope(canonical_team_id):
        Repo.objects.all()
"""

from __future__ import annotations

from typing import Any

from django.db import models

from posthog.models.scoping.manager import TeamScopedManager, TeamScopedQuerySet, resolve_effective_team_id


class ProductTeamQuerySet(TeamScopedQuerySet):
    """QuerySet for product models on separate databases.

    Inherits unscoped() and _apply_team_filter from TeamScopedQuerySet.
    The shared filter just does `filter(team_id=team_id)` so there's no
    cross-DB JOIN — works fine for separate-DB models.
    """

    def unscoped(self) -> ProductTeamQuerySet:
        """Return a queryset that bypasses automatic team scoping."""
        return ProductTeamQuerySet(self.model, using=self._db)  # type: ignore[attr-defined]


class ProductTeamManager(TeamScopedManager):
    """Fail-closed manager for product models on separate databases."""

    _queryset_class = ProductTeamQuerySet


class ProductTeamModel(models.Model):
    """Abstract base for product models that live on a separate database.

    Provides team_id as a plain BigIntegerField (no FK constraint) and a
    fail-closed manager that auto-scopes queries by the current team
    context. save() rewrites team_id to the canonical id (parent if the
    team is a child environment, the team's own id otherwise) so writes
    and reads agree on where data lives — same convention as
    RootTeamMixin for main-DB models.

    Accessing .objects without team context raises TeamScopeError. Use
    .unscoped (the second Manager) for intentional cross-team access in
    admin / migrations / background jobs without context.
    """

    team_id = models.BigIntegerField(db_index=True)

    objects = ProductTeamManager()
    unscoped = models.Manager()  # noqa: DJ012 — both are managers, ruff misclassifies this

    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        # Rewrite child team_ids to their parent so data always lives at
        # the canonical id. Mirrors RootTeamMixin.save() for main-DB models.
        # Only resolve on insert / when team_id changes — re-saving an
        # existing row shouldn't pay the lookup cost on every save().
        if self.team_id is not None:
            self.team_id = resolve_effective_team_id(self.team_id)
        super().save(*args, **kwargs)
