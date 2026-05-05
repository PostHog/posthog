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

from posthog.models.scoping import get_current_team_context, get_current_team_id
from posthog.person_db_router import PERSONS_DB_MODELS

T = TypeVar("T", bound=models.Model)


class TeamScopeError(Exception):
    """Raised when a team-scoped model is queried without team context.

    To fix, either:
    - Set team context: TeamAndOrgViewSetMixin sets it for nested DRF views
      from the URL team_id; use team_scope()/with_team_scope() elsewhere
      (Celery tasks, management commands, admin actions).
    - Opt out explicitly: Model.objects.unscoped().all()
    """

    pass


def resolve_effective_team_id(team_id: int) -> int:
    """Resolve effective team_id (parent if child, else team_id).

    Single source of truth for parent-team resolution. Used by both
    TeamScopedManager (main DB models) and ProductTeamModel (separate-DB
    models) — extracting one helper prevents the two code paths from
    drifting on cache invariants.

    Raises TeamScopeError if the team doesn't exist on the main DB —
    matches the rest of the fail-closed posture (silent fallback would
    let `team_scope(typo)` quietly scope queries to a non-existent team).
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
        team = Team.objects.using("default").only("parent_team_id").get(id=team_id)
    except Team.DoesNotExist:
        raise TeamScopeError(f"Team {team_id} not found on default DB")
    return team.parent_team_id or team_id


class TeamScopedQuerySet(models.QuerySet[T]):
    """
    QuerySet that supports automatic team scoping.

    Provides an `unscoped()` method to bypass automatic filtering when you
    need to explicitly query across teams.
    """

    def _apply_team_filter(self, team_id: int) -> "TeamScopedQuerySet[T]":
        """Apply team filtering with parent team logic (from RootTeamQuerySet)."""
        if self.model._meta.model_name in PERSONS_DB_MODELS:
            effective_team_id = resolve_effective_team_id(team_id)
            return self.filter(team_id=effective_team_id)

        # Fast path: if context already cached parent_team_id for this team, skip
        # the resolution roundtrip and use a plain `team_id = X` filter.
        ctx = get_current_team_context()
        if ctx is not None and ctx.team_id == team_id and ctx.parent_team_id is not None:
            return self.filter(team_id=ctx.parent_team_id)

        # Cold path: resolve parent_team_id once, then plain integer filter.
        # Previously used `Q(Subquery) | Q(JOIN)` — same result, much worse plan.
        effective_team_id = resolve_effective_team_id(team_id)
        return self.filter(team_id=effective_team_id)

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

    def for_team(self, team_id: int, parent_team_id: int | None = None) -> TeamScopedQuerySet[T]:
        """Explicitly scope to a team. Useful outside request context.

        Pass `parent_team_id` if you already know it (e.g. inside a loop over
        teams) to avoid a Team lookup per call.
        """
        if parent_team_id is not None:
            return cast(
                "TeamScopedQuerySet[T]",
                self._queryset_class(self.model, using=self._db).filter(team_id=parent_team_id),
            )
        return self._queryset_class(self.model, using=self._db)._apply_team_filter(team_id)


__all__ = [
    "TeamScopeError",
    "TeamScopedQuerySet",
    "TeamScopedManager",
]
