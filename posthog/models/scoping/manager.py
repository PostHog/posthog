"""
Team-scoped manager and queryset for tenant isolation.

Fail-closed: raises TeamScopeError when no team context is set, unless
explicitly opted out via .unscoped(). This forces every code path to
declare its team context — there is no silent "return everything" mode.

This is a defense-in-depth convenience layer, not a complete security
boundary. Django's `_default_manager` / `_base_manager` (used for admin
querysets, related-object access like `repo.runs.all()`, generic
relations, `prefetch_related`, DRF default querysets) intentionally
route through the unscoped sibling manager via
`ProductTeamModel.Meta.default_manager_name = "all_teams"` — the
framework expects an unfiltered manager and a fail-closed default would
raise on framework code that has no team context. Raw SQL bypasses the
ORM entirely. Use this alongside explicit team checks at the API layer.
"""

import os
from collections.abc import AsyncIterator, Iterator
from functools import cache
from typing import Any, TypeVar, cast

from django.conf import settings
from django.core.exceptions import FieldFetchBlocked
from django.db import models
from django.db.models.fetch_modes import FetchMode, FetchPeers
from django.db.models.query_utils import DeferredAttribute

from posthog.models.scoping import get_current_team_id, peer_lazy_loads

T = TypeVar("T", bound=models.Model)


class FetchRelationPeers(FetchPeers):
    """`FETCH_PEERS` for relations, `FETCH_ONE` for deferred fields."""

    __slots__ = ()

    def fetch(self, fetcher: Any, instance: models.Model) -> None:
        # Django's DeferredAttribute.fetch_many overwrites a value the caller already
        # assigned on a peer, and raises KeyError when a peer row is gone.
        if isinstance(fetcher, DeferredAttribute):
            fetcher.fetch_one(instance)
        else:
            super().fetch(fetcher, instance)

    def __reduce__(self) -> str:
        return "FETCH_RELATION_PEERS"


FETCH_RELATION_PEERS = FetchRelationPeers()


def _has_live_peers(instance: models.Model) -> bool:
    live = 0
    for peer in instance._state.peers:
        if peer() is not None:
            live += 1
            if live > 1:
                return True
    return False


def _fix_hint(fetcher: Any, field: str) -> str:
    if isinstance(fetcher, DeferredAttribute):
        return f'add "{field}" to only(), or remove it from defer()'
    # Only a GenericForeignKey has a content type field, and select_related() cannot follow one.
    # Importing GenericForeignKey here would load the ContentType model before the app registry is ready.
    if hasattr(fetcher.field, "ct_field"):
        return f'add prefetch_related("{field}")'
    return f'add select_related("{field}") or prefetch_related("{field}")'


class FetchRaiseOnPeers(FetchRelationPeers):
    """Test-only `FETCH_RELATION_PEERS` that raises when a lazy load would run once per row.

    A row from `.get()`, `.first()` or a one-row result has no live peers and loads as usual.
    A site listed in `peer_lazy_loads_baseline.txt` loads like production.
    """

    __slots__ = ()

    def fetch(self, fetcher: Any, instance: models.Model) -> None:
        if _has_live_peers(instance):
            label, field = instance._meta.label, fetcher.field.name
            entry = peer_lazy_loads.blocked_entry(label, field)
            if entry is not None:
                raise FieldFetchBlocked(
                    f"Lazy load of {label}.{field} on a row from a multi-row query, which costs one query per row. "
                    f"Load it with the query: {_fix_hint(fetcher, field)}. Entry: {entry}"
                ) from None
        super().fetch(fetcher, instance)

    def __reduce__(self) -> str:
        return "FETCH_RAISE_ON_PEERS"


FETCH_RAISE_ON_PEERS = FetchRaiseOnPeers()


@cache
def default_fetch_mode() -> FetchMode:
    # PYTEST_VERSION keeps it out of servers and management commands that CI starts with TEST=1.
    if settings.TEST and "PYTEST_VERSION" in os.environ:
        return FETCH_RAISE_ON_PEERS
    return FETCH_RELATION_PEERS


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
    """Resolve a team_id to its canonical id (parent if child, else self).

    Used by:
    - TeamAndOrgViewSetMixin to compute the canonical id once per request
    - ProductTeamModel.save() to keep writes symmetric with reads
    - Anyone with a raw team_id who needs to set context

    Raises TeamScopeError if the team doesn't exist on the main DB —
    matches the rest of the fail-closed posture (silent fallback would
    let `team_scope(typo)` quietly scope queries to a non-existent team).
    """
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

    Defaults to `FETCH_RELATION_PEERS`: a lazy related read on one row loads
    it for every row the same query returned, in one query. Tests use
    `FETCH_RAISE_ON_PEERS`, so that read raises unless its site is baselined.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._fetch_mode = default_fetch_mode()

    def iterator(self, chunk_size: int | None = None) -> Iterator[T]:
        return super(TeamScopedQuerySet, self._without_streamed_peers()).iterator(chunk_size)

    def aiterator(self, chunk_size: int = 2000) -> AsyncIterator[T]:
        return super(TeamScopedQuerySet, self._without_streamed_peers()).aiterator(chunk_size)

    def _without_streamed_peers(self) -> "TeamScopedQuerySet[T]":
        # A streamed query shares one peer list across all its rows, and FETCH_PEERS
        # scans that list on each lazy read, so a loop that reads a relation per row
        # costs O(rows²). The rows a loop has dropped are not batched anyway.
        if isinstance(self._fetch_mode, FetchRelationPeers):
            return self.fetch_mode(models.FETCH_ONE)
        return self

    def _apply_team_filter(self, team_id: int) -> "TeamScopedQuerySet[T]":
        """Apply team filtering. Caller passes the canonical team_id; we
        trust it and filter directly. No DB resolution at read time —
        ProductTeamModel.save() and the DRF mixin keep the contract that
        team_ids in scope are always canonical (parent or root)."""
        return self.filter(team_id=team_id)

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

    When team context is set (via TeamAndOrgViewSetMixin or team_scope()),
    queries are automatically filtered. When no context is set, raises
    TeamScopeError.

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

    def for_team(self, team_id: int, *, canonical: bool = False) -> TeamScopedQuerySet[T]:
        """Explicitly scope to a team. Useful outside request context.

        Auto-resolves `team_id` to canonical via `resolve_effective_team_id`
        (one Team lookup per call). Bulk callers iterating over many teams
        can pre-resolve once and pass `canonical=True` to skip the per-call
        lookup.

        Pass `canonical=True` only when the caller has independently
        verified the id is canonical (or is using a synthetic id in tests).
        """
        if not canonical:
            team_id = resolve_effective_team_id(team_id)
        return self._queryset_class(self.model, using=self._db)._apply_team_filter(team_id)


class EnvironmentScopedManager(TeamScopedManager[T]):
    """Fail-closed manager for models where sibling environments must stay isolated.

    `TeamScopedManager`'s contract is canonical (project-level) team ids: ambient
    request scope and `for_team()` both resolve a child environment's id to the
    parent. For per-environment rows (e.g. signing secrets) that is a cross-
    environment leak: reads for one environment would select another's row.

    Here `for_team()` filters by the literal id given, and ambient-context reads
    are refused so a canonicalized id can never silently pick a sibling's row.
    """

    def get_queryset(self) -> TeamScopedQuerySet[T]:
        raise TeamScopeError(
            f"{self.model.__name__} is environment-scoped: ambient team scope is canonical "
            "(project-level) and could select a sibling environment's row. "
            "Use .for_team(team_id) with the environment's own id, or .unscoped()."
        )

    def for_team(self, team_id: int, *, canonical: bool = False) -> TeamScopedQuerySet[T]:
        return self._queryset_class(self.model, using=self._db)._apply_team_filter(team_id)


__all__ = [
    "TeamScopeError",
    "TeamScopedQuerySet",
    "TeamScopedManager",
    "EnvironmentScopedManager",
    "resolve_effective_team_id",
]
