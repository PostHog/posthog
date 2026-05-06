"""
Abstract model for product models on separate databases.

Multi-DB counterpart of RootTeamMixin. Provides:
- team_id as a plain BigIntegerField (no FK to Team — can't cross databases)
- save() rewrites team_id to canonical (parent if child env, else self) so
  data always lives at the canonical team_id — symmetric with reads
- Auto-scoping fail-closed manager via `TeamScopedManager` (the same
  manager main-DB models use)

Usage:

    from posthog.models.scoping.product_mixin import ProductTeamModel

    class Repo(ProductTeamModel):
        repo_name = models.CharField(max_length=255)

    # In DRF view (mixin sets canonical team context):
    Repo.objects.all()              # Auto-filtered to canonical team

    # Explicit cross-team:
    Repo.objects.unscoped().all()   # No filtering

    # Background jobs (auto-resolves to canonical):
    with team_scope(team_id):
        Repo.objects.all()
"""

from __future__ import annotations

from typing import Any

from django.db import models

from posthog.models.scoping.manager import TeamScopedManager, resolve_effective_team_id


class ProductTeamModel(models.Model):
    """Abstract base for product models that live on a separate database.

    Provides team_id as a plain BigIntegerField (no FK constraint) and a
    fail-closed manager that auto-scopes queries by the current team
    context. save() rewrites team_id to the canonical id (parent if the
    team is a child environment, the team's own id otherwise) so writes
    and reads agree on where data lives — same convention as
    RootTeamMixin for main-DB models.

    Two managers:
    - `objects` (TeamScopedManager): fail-closed, auto-scopes by context.
      Raises TeamScopeError when no context is set. This is the manager
      Django admin / Model.objects / `_default_manager` resolves to.
    - `all_teams` (plain Manager): bypass for admin / migrations / contexts
      that genuinely need cross-team access. Named distinctly from the
      queryset method `Model.objects.unscoped()` to avoid the autocomplete
      footgun where `Model.unscoped.filter(...)` looks like "I'm being
      explicit about scoping" but actually returns every team's rows.
    """

    team_id = models.BigIntegerField(db_index=True)

    objects = TeamScopedManager()
    all_teams = models.Manager()  # noqa: DJ012 — both are managers, ruff misclassifies this

    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        # Rewrite child team_ids to canonical on insert / when team_id is
        # being written. Updates that don't touch team_id skip the lookup —
        # otherwise every status transition / unrelated field update would
        # pay the Team roundtrip. Mirrors RootTeamMixin.save() for main-DB
        # models.
        update_fields = kwargs.get("update_fields")
        team_id_changed = update_fields is None or "team_id" in update_fields
        if (self._state.adding or team_id_changed) and self.team_id is not None:
            self.team_id = resolve_effective_team_id(self.team_id)
        super().save(*args, **kwargs)
