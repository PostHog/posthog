"""
Team-scoped manager and queryset for tenant isolation.

Fail-closed: raises TeamScopeError when no team context is set, unless
explicitly opted out via .unscoped(). This forces every code path to
declare its team context — there is no silent "return everything" mode.

This is a defense-in-depth convenience layer, not a complete security
boundary. Django's _base_manager bypasses custom managers for related-
object access, and raw SQL bypasses the ORM entirely. Use this alongside
explicit team checks at the API layer.
"""

from typing import TypeVar, cast

from django.db import models
from django.db.models import Q, Subquery

from posthog.models.scoping import get_current_team_context, get_current_team_id
from posthog.person_db_router import PERSONS_DB_MODELS

T = TypeVar("T", bound=models.Model)


class TeamScopeError(Exception):
    """Raised when a team-scoped model is queried without team context.

    To fix, either:
    - Set team context: use TeamScopingMiddleware (requests) or
      team_scope()/with_team_scope() (background jobs)
    - Opt out explicitly: Model.objects.unscoped().all()
    """

    pass


def _get_effective_team_id_for_persons_db(team_id: int) -> int:
    """Get the effective team ID for PERSONS_DB_MODELS.

    Uses cached parent_team_id from context if available, otherwise fetches from DB.
    """
    from posthog.models.team import Team

    # Only trust cached value when parent_team_id was explicitly resolved.
    # `None` could mean "this is a root team" or "we just don't know yet" —
    # falling back to team_id in the latter case would silently scope queries
    # to the child team and miss data stored under the parent.
    ctx = get_current_team_context()
    if ctx is not None and ctx.team_id == team_id and ctx.parent_team_id is not None:
        return ctx.parent_team_id

    try:
        team = Team.objects.using("default").get(id=team_id)
        return team.parent_team_id if team.parent_team_id else team_id
    except Team.DoesNotExist:
        return team_id


class TeamScopedQuerySet(models.QuerySet[T]):
    """
    QuerySet that supports automatic team scoping.

    Provides an `unscoped()` method to bypass automatic filtering when you
    need to explicitly query across teams.
    """

    def _apply_team_filter(self, team_id: int) -> "TeamScopedQuerySet[T]":
        """Apply team filtering with parent team logic (from RootTeamQuerySet)."""
        from posthog.models.team import Team

        if self.model._meta.model_name in PERSONS_DB_MODELS:
            effective_team_id = _get_effective_team_id_for_persons_db(team_id)
            return self.filter(team_id=effective_team_id)

        # If context already cached parent_team_id for this team, skip the subquery+join
        # and use a plain `team_id = X` filter. Saves a correlated subquery and a JOIN
        # on every read through the manager. Only safe when parent_team_id is explicitly
        # set — None could mean "this is a root team" or "we don't know yet".
        ctx = get_current_team_context()
        if ctx is not None and ctx.team_id == team_id and ctx.parent_team_id is not None:
            return self.filter(team_id=ctx.parent_team_id)

        parent_team_subquery = Team.objects.filter(id=team_id).values("parent_team_id")[:1]
        team_filter = Q(team_id=Subquery(parent_team_subquery)) | Q(team_id=team_id, team__parent_team_id__isnull=True)
        return self.filter(team_filter)

    def unscoped(self) -> "TeamScopedQuerySet[T]":
        """
        Return a queryset that bypasses automatic team scoping.

        Use this when you explicitly need to query across teams:
            FeatureFlag.objects.unscoped().filter(key="my-flag")

        This creates a fresh queryset without any team filtering applied.
        """
        return cast("TeamScopedQuerySet[T]", TeamScopedQuerySet(self.model, using=self._db))  # type: ignore[attr-defined]


class TeamScopedManager(models.Manager[T]):
    """
    Fail-closed manager that enforces team scoping.

    When team context is set (via middleware or team_scope()), queries are
    automatically filtered. When no context is set, raises TeamScopeError.

    Escape hatches:
    - .unscoped()      — returns unfiltered queryset (for intentional cross-team access)
    - .for_team(id)    — explicitly scope to a team outside request context
    """

    _queryset_class = TeamScopedQuerySet

    def get_queryset(self) -> TeamScopedQuerySet[T]:
        qs: TeamScopedQuerySet[T] = self._queryset_class(self.model, using=self._db)
        team_id = get_current_team_id()
        if team_id is not None:
            return qs._apply_team_filter(team_id)
        raise TeamScopeError(
            f"No team context set for {self.model.__name__}. "
            f"Use team_scope(), @with_team_scope(), or .unscoped() for cross-team access."
        )

    def unscoped(self) -> TeamScopedQuerySet[T]:
        """Return an unscoped queryset that bypasses automatic team filtering."""
        return self._queryset_class(self.model, using=self._db)

    def for_team(self, team_id: int) -> TeamScopedQuerySet[T]:
        """Explicitly scope to a team. Useful outside request context."""
        return self._queryset_class(self.model, using=self._db)._apply_team_filter(team_id)


__all__ = [
    "TeamScopeError",
    "TeamScopedQuerySet",
    "TeamScopedManager",
]
