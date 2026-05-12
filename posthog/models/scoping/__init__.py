# Team Scoping Context
#
# Provides automatic team scoping for Django models using Python's ContextVar.
# Models using TeamScopedManager / ProductTeamModel will read this context
# and auto-filter their queries.
#
# Contract: the team_id stored in context is the **canonical** team_id where
# data lives — i.e. the parent team's id when the team is a child environment,
# or the team's own id when it's a root team. Callers (the DRF mixin, Celery
# task helpers, manual `team_scope()` callers) are responsible for resolving
# to the canonical id before setting context. ProductTeamModel.save() also
# rewrites to the canonical id, so writes and reads stay symmetric.
#
# Usage:
#   # In DRF nested views — set automatically by TeamAndOrgViewSetMixin:
#   FeatureFlag.objects.all()  # Auto-filtered to canonical team
#
#   # Explicit cross-team query (escape hatch):
#   FeatureFlag.objects.unscoped().all()  # No team filtering
#
#   # In background jobs / management commands (caller passes canonical id):
#   with team_scope(canonical_team_id):
#       FeatureFlag.objects.all()

import inspect
import functools
from collections.abc import Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")


# The current canonical team_id, or None if no scope is set.
_current_team_id: ContextVar[int | None] = ContextVar("current_team_id", default=None)


def get_current_team_id() -> int | None:
    """Get the current canonical team_id, or None if no scope is set."""
    return _current_team_id.get()


def set_current_team_id(team_id: int | None) -> Token[int | None]:
    """Set the current canonical team_id. Returns a token to reset it later.

    Pass `None` to clear context (used by `unscoped()`).
    """
    return _current_team_id.set(team_id)


def reset_current_team_id(token: Token[int | None]) -> None:
    """Reset the current team_id to its previous value."""
    _current_team_id.reset(token)


@contextmanager
def team_scope(team_id: int, *, canonical: bool = False) -> Generator[None, None, None]:
    """
    Context manager to set the current team_id for a block of code.

    By default, resolves `team_id` to its canonical id (parent if the team
    is a child environment, the team's own id otherwise) — one Team lookup
    per scope entry. This guarantees the manager's filter finds rows
    regardless of whether the caller passed a parent or a child id.

    Pass `canonical=True` if the caller has already resolved (or is using
    a synthetic id in tests). Skipping resolution silently scopes queries
    to whatever id was passed; if it isn't actually canonical, reads will
    return zero rows from the wrong scope.

    Example:
        # Production: caller may have a child id, framework resolves
        with team_scope(team_id):
            flags = FeatureFlag.objects.all()

        # Test or pre-resolved caller: skip the lookup
        with team_scope(self.team.id, canonical=True):
            flags = FeatureFlag.objects.all()
    """
    if not canonical:
        # Imported here to avoid the manager → __init__ circular dependency
        from posthog.models.scoping.manager import resolve_effective_team_id

        team_id = resolve_effective_team_id(team_id)
    token = set_current_team_id(team_id)
    try:
        yield
    finally:
        reset_current_team_id(token)


@contextmanager
def unscoped() -> Generator[None, None, None]:
    """
    Context manager to temporarily disable automatic team scoping.

    Useful when you explicitly need to query across teams.

    Example:
        with unscoped():
            all_flags = FeatureFlag.objects.all()  # All teams
    """
    token = set_current_team_id(None)
    try:
        yield
    finally:
        reset_current_team_id(token)


def with_team_scope(
    team_id_param: str = "team_id",
    *,
    canonical: bool = False,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """
    Decorator that wraps a function in a team_scope() context.

    Extracts the team_id from the function's arguments and sets it as the
    current team context for the duration of the function call. Auto-resolves
    to canonical via `team_scope()` — callers can pass any team_id (raw or
    canonical) and the framework guarantees the manager's filter finds
    rows.

    Pass `canonical=True` if the wrapped function will only ever be called
    with already-canonical team_ids (or in tests with synthetic ids) to skip
    the per-call Team lookup.

    Args:
        team_id_param: Name of the parameter containing the team_id.
                      Defaults to "team_id".

    Example:
        @shared_task
        @with_team_scope()
        def my_task(team_id: int, other_arg: str):
            # team context is automatically set from team_id parameter
            flags = FeatureFlag.objects.all()  # Auto-filtered to team_id

        @shared_task
        @with_team_scope(team_id_param="project_team_id")
        def another_task(project_team_id: int):
            # team context set from project_team_id parameter
            pass
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        # Cache signature inspection at decoration time (not per-call)
        sig = inspect.signature(func)
        params = list(sig.parameters.keys())
        param_index = params.index(team_id_param) if team_id_param in params else None

        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            # Try to get team_id from kwargs first
            team_id = kwargs.get(team_id_param)

            # If not in kwargs, try to get from positional args using cached index
            if team_id is None and param_index is not None and param_index < len(args):
                team_id = args[param_index]

            if team_id is None:
                raise ValueError(
                    f"with_team_scope: Could not find '{team_id_param}' parameter. "
                    f"Ensure the function has a '{team_id_param}' parameter or "
                    f"specify a different parameter name."
                )

            # `bool` is a subclass of `int` — slips past `isinstance(_, int)`
            if isinstance(team_id, bool) or not isinstance(team_id, int):
                raise TypeError(f"with_team_scope: '{team_id_param}' must be an int, got {type(team_id).__name__}")

            with team_scope(team_id, canonical=canonical):
                return func(*args, **kwargs)

        return wrapper

    return decorator


__all__ = [
    "get_current_team_id",
    "set_current_team_id",
    "reset_current_team_id",
    "team_scope",
    "unscoped",
    "with_team_scope",
]
