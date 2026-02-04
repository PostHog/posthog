"""
Team-scoped manager and queryset for automatic IDOR protection.

This module provides a drop-in replacement for RootTeamManager that automatically
filters queries by the current team_id from context.
"""

from typing import TYPE_CHECKING, Any, TypeVar

from django.db import models
from django.db.models import Q, Subquery

from posthog.models.scoping import get_current_team_id
from posthog.person_db_router import PERSONS_DB_MODELS

if TYPE_CHECKING:
    pass

T = TypeVar("T", bound=models.Model)


class TeamScopedQuerySet(models.QuerySet[T]):
    """
    QuerySet that can automatically filter by team_id from context.

    This extends the existing RootTeamQuerySet pattern but adds:
    - Automatic scoping via get_queryset() when context is set
    - An unscoped() method to bypass automatic filtering
    """

    _is_unscoped: bool = False

    def _clone(self) -> "TeamScopedQuerySet[T]":
        """Preserve the _is_unscoped flag when cloning."""
        clone = super()._clone()
        clone._is_unscoped = self._is_unscoped
        return clone

    def unscoped(self) -> "TeamScopedQuerySet[T]":
        """
        Return a queryset that bypasses automatic team scoping.

        Use this when you explicitly need to query across teams:
            FeatureFlag.objects.unscoped().filter(key="my-flag")
        """
        clone = self._clone()
        clone._is_unscoped = True
        return clone

    def _apply_team_filter(self, team_id: int) -> "TeamScopedQuerySet[T]":
        """Apply team filtering with parent team logic (from RootTeamQuerySet)."""
        from posthog.models.team import Team

        # Check if this model is in the persons database
        if self.model._meta.model_name in PERSONS_DB_MODELS:
            # For persons DB models, we can't join with the Team table (cross-database)
            try:
                team = Team.objects.using("default").get(id=team_id)
                effective_team_id = team.parent_team_id if team.parent_team_id else team_id
            except Team.DoesNotExist:
                effective_team_id = team_id
            return super().filter(team_id=effective_team_id)
        else:
            # For non-persons DB models: use the original logic with JOIN
            parent_team_subquery = Team.objects.filter(id=team_id).values("parent_team_id")[:1]
            team_filter = Q(team_id=Subquery(parent_team_subquery)) | Q(
                team_id=team_id, team__parent_team_id__isnull=True
            )
            return super().filter(team_filter)

    def _iterator(self, **kwargs: Any) -> Any:
        """
        Apply automatic team scoping right before iteration.

        This is the key method - it's called when the queryset is actually evaluated.
        By applying the filter here, we ensure that:
        1. Chained filters work correctly
        2. The team context is read at evaluation time, not queryset creation time
        """
        if not self._is_unscoped:
            team_id = get_current_team_id()
            if team_id is not None:
                # Apply team filter to self before iterating
                # We need to be careful here - we can't modify self, so we filter
                # This is a bit tricky - we need to ensure the filter is applied
                filtered = self._apply_team_filter(team_id)
                # Copy the filtered queryset's query to self
                self.query = filtered.query
        return super()._iterator(**kwargs)


class TeamScopedManager(models.Manager[T]):
    """
    Manager that provides automatic team scoping.

    When the current team_id is set in context (via middleware or team_scope()),
    all queries will be automatically filtered to that team.

    To bypass automatic filtering, use .unscoped():
        MyModel.objects.unscoped().all()
    """

    def get_queryset(self) -> TeamScopedQuerySet[T]:
        return TeamScopedQuerySet(self.model, using=self._db)

    def unscoped(self) -> TeamScopedQuerySet[T]:
        """Return an unscoped queryset that bypasses automatic team filtering."""
        return self.get_queryset().unscoped()


# For backwards compatibility with existing code that uses filter(team_id=X)
class BackwardsCompatibleTeamScopedQuerySet(TeamScopedQuerySet[T]):
    """
    QuerySet that supports both automatic scoping and explicit team_id filtering.

    This maintains backwards compatibility with existing code that does:
        Model.objects.filter(team_id=some_id)
    """

    def filter(self, *args: Any, **kwargs: Any) -> "BackwardsCompatibleTeamScopedQuerySet[T]":
        # If team_id is explicitly passed, handle it specially (from RootTeamQuerySet)
        if "team_id" in kwargs:
            team_id = kwargs.pop("team_id")
            filtered = self._apply_team_filter(team_id)
            # Mark as unscoped since we've explicitly set the team
            filtered._is_unscoped = True
            if args or kwargs:
                return filtered.filter(*args, **kwargs)
            return filtered
        return super().filter(*args, **kwargs)


class BackwardsCompatibleTeamScopedManager(models.Manager[T]):
    """
    Manager that provides automatic team scoping while maintaining backwards compatibility.

    Supports:
    - Automatic scoping from context: Model.objects.all()
    - Explicit team_id filtering: Model.objects.filter(team_id=X)
    - Unscoped queries: Model.objects.unscoped().all()
    """

    def get_queryset(self) -> BackwardsCompatibleTeamScopedQuerySet[T]:
        return BackwardsCompatibleTeamScopedQuerySet(self.model, using=self._db)

    def unscoped(self) -> BackwardsCompatibleTeamScopedQuerySet[T]:
        """Return an unscoped queryset that bypasses automatic team filtering."""
        return self.get_queryset().unscoped()

    def filter(self, *args: Any, **kwargs: Any) -> BackwardsCompatibleTeamScopedQuerySet[T]:
        return self.get_queryset().filter(*args, **kwargs)
