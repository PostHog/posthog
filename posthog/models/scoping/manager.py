"""
Team-scoped manager and queryset for automatic IDOR protection.

Provides drop-in replacement for RootTeamManager that automatically filters
queries by the current team_id from context.
"""

from typing import Self, TypeVar

from django.db import models
from django.db.models import Q, Subquery

from posthog.models.scoping import get_current_team_context, get_current_team_id
from posthog.person_db_router import PERSONS_DB_MODELS

T = TypeVar("T", bound=models.Model)


class TeamFilterMixin:
    """
    Mixin that provides team filtering logic.

    Handles both regular models (using JOINs) and PERSONS_DB_MODELS (cross-database).
    Uses cached parent_team_id from context when available to avoid extra queries.
    """

    model: type[models.Model]

    def _apply_team_filter(self, team_id: int) -> Self:
        """Apply team filtering with parent team logic (from RootTeamQuerySet)."""
        from posthog.models.team import Team

        # For persons DB models, we can't join with the Team table (cross-database)
        if self.model._meta.model_name in PERSONS_DB_MODELS:
            effective_team_id = self._get_effective_team_id_for_persons_db(team_id)
            return self.filter(team_id=effective_team_id)

        # For non-persons DB models: use JOIN logic from RootTeamQuerySet
        parent_team_subquery = Team.objects.filter(id=team_id).values("parent_team_id")[:1]
        team_filter = Q(team_id=Subquery(parent_team_subquery)) | Q(team_id=team_id, team__parent_team_id__isnull=True)
        return self.filter(team_filter)

    def _get_effective_team_id_for_persons_db(self, team_id: int) -> int:
        """
        Get the effective team ID for PERSONS_DB_MODELS.

        Uses cached parent_team_id from context if available, otherwise fetches from DB.
        """
        from posthog.models.team import Team

        # Try to use cached parent_team_id from context
        ctx = get_current_team_context()
        if ctx is not None and ctx.team_id == team_id:
            return ctx.effective_team_id

        # Fall back to DB query if not in context or different team_id
        try:
            team = Team.objects.using("default").get(id=team_id)
            return team.parent_team_id if team.parent_team_id else team_id
        except Team.DoesNotExist:
            return team_id


class TeamScopedQuerySet(TeamFilterMixin, models.QuerySet[T]):
    """
    QuerySet that supports automatic team scoping.

    Provides an `unscoped()` method to bypass automatic filtering when you
    need to explicitly query across teams.
    """

    def unscoped(self) -> "TeamScopedQuerySet[T]":
        """
        Return a queryset that bypasses automatic team scoping.

        Use this when you explicitly need to query across teams:
            FeatureFlag.objects.unscoped().filter(key="my-flag")

        This creates a fresh queryset without any team filtering applied.
        """
        return TeamScopedQuerySet(self.model, using=self._db)


class TeamScopedManager(models.Manager[T]):
    """
    Manager that provides automatic team scoping.

    When the current team_id is set in context (via middleware or team_scope()),
    all queries will be automatically filtered to that team.

    To bypass automatic filtering, use .unscoped():
        MyModel.objects.unscoped().all()

    Note: The team filter is applied when accessing the manager (e.g., Model.objects),
    not at query evaluation time. This covers the vast majority of use cases where
    you access the model within the same request/task context.
    """

    _queryset_class = TeamScopedQuerySet

    def get_queryset(self) -> TeamScopedQuerySet[T]:
        qs = self._queryset_class(self.model, using=self._db)
        team_id = get_current_team_id()
        if team_id is not None:
            qs = qs._apply_team_filter(team_id)
        return qs

    def unscoped(self) -> TeamScopedQuerySet[T]:
        """Return an unscoped queryset that bypasses automatic team filtering."""
        return self._queryset_class(self.model, using=self._db)


class BackwardsCompatibleTeamScopedQuerySet(TeamFilterMixin, models.QuerySet[T]):
    """
    QuerySet that supports both automatic scoping and explicit team_id filtering.

    Maintains backwards compatibility with existing code that does:
        Model.objects.filter(team_id=some_id)

    When team_id is explicitly passed to filter(), it takes precedence over
    automatic context-based scoping.
    """

    def filter(self, *args, **kwargs) -> "BackwardsCompatibleTeamScopedQuerySet[T]":
        # If team_id is explicitly passed, handle it with parent team logic
        if "team_id" in kwargs:
            team_id = kwargs.pop("team_id")
            # Apply the team filter (handles parent team logic)
            filtered = self._apply_team_filter_compat(team_id)
            # Apply any remaining filters
            if args or kwargs:
                return filtered.filter(*args, **kwargs)
            return filtered
        return super().filter(*args, **kwargs)

    def unscoped(self) -> "BackwardsCompatibleTeamScopedQuerySet[T]":
        """Return a queryset that bypasses automatic team scoping."""
        return BackwardsCompatibleTeamScopedQuerySet(self.model, using=self._db)

    def _apply_team_filter_compat(self, team_id: int) -> "BackwardsCompatibleTeamScopedQuerySet[T]":
        """
        Apply team filtering for backwards compatible queryset.

        Uses super().filter() to avoid recursion through our filter override.
        """
        from posthog.models.team import Team

        # For persons DB models, we can't join with the Team table (cross-database)
        if self.model._meta.model_name in PERSONS_DB_MODELS:
            effective_team_id = self._get_effective_team_id_for_persons_db(team_id)
            return super().filter(team_id=effective_team_id)

        # For non-persons DB models: use JOIN logic from RootTeamQuerySet
        parent_team_subquery = Team.objects.filter(id=team_id).values("parent_team_id")[:1]
        team_filter = Q(team_id=Subquery(parent_team_subquery)) | Q(team_id=team_id, team__parent_team_id__isnull=True)
        return super().filter(team_filter)


class BackwardsCompatibleTeamScopedManager(models.Manager[T]):
    """
    Manager that provides automatic team scoping while maintaining backwards compatibility.

    Supports:
    - Automatic scoping from context: Model.objects.all()
    - Explicit team_id filtering: Model.objects.filter(team_id=X)
    - Unscoped queries: Model.objects.unscoped().all()

    Use this during migration from RootTeamManager. Once all code is updated
    to use context-based scoping, switch to TeamScopedManager.
    """

    _queryset_class = BackwardsCompatibleTeamScopedQuerySet

    def get_queryset(self) -> BackwardsCompatibleTeamScopedQuerySet[T]:
        qs = self._queryset_class(self.model, using=self._db)
        team_id = get_current_team_id()
        if team_id is not None:
            qs = qs._apply_team_filter(team_id)
        return qs

    def unscoped(self) -> BackwardsCompatibleTeamScopedQuerySet[T]:
        """Return an unscoped queryset that bypasses automatic team filtering."""
        return self._queryset_class(self.model, using=self._db)

    def filter(self, *args, **kwargs) -> BackwardsCompatibleTeamScopedQuerySet[T]:
        """Filter with support for explicit team_id."""
        return self.get_queryset().filter(*args, **kwargs)


__all__ = [
    "TeamScopedQuerySet",
    "TeamScopedManager",
    "BackwardsCompatibleTeamScopedQuerySet",
    "BackwardsCompatibleTeamScopedManager",
]
