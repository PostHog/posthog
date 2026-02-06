# Team Scoping Context
#
# Provides automatic team scoping for Django models using Python's ContextVar.
# When a request comes in, middleware sets the current team_id in a ContextVar.
# Models using TeamScopedManager will automatically filter by this team_id.
#
# Usage:
#   # In request context (automatic via middleware):
#   FeatureFlag.objects.all()  # Auto-filtered to current team
#
#   # Explicit cross-team query (escape hatch):
#   FeatureFlag.objects.unscoped().all()  # No team filtering
#
#   # In background jobs (no request context):
#   with team_scope(team_id):
#       FeatureFlag.objects.all()  # Filtered to specified team

import inspect
import functools
from collections.abc import Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")

# The current team_id, set by middleware or explicitly via team_scope()
_current_team_id: ContextVar[int | None] = ContextVar("current_team_id", default=None)


def get_current_team_id() -> int | None:
    """Get the current team_id from context, or None if not set."""
    return _current_team_id.get()


def set_current_team_id(team_id: int | None) -> Token[int | None]:
    """Set the current team_id in context. Returns a token to reset it later."""
    return _current_team_id.set(team_id)


def reset_current_team_id(token: Token[int | None]) -> None:
    """Reset the current team_id to its previous value."""
    _current_team_id.reset(token)


@contextmanager
def team_scope(team_id: int) -> Generator[None, None, None]:
    """
    Context manager to set the current team_id for a block of code.

    Useful for background jobs or tests where there's no request context.

    Example:
        with team_scope(123):
            flags = FeatureFlag.objects.all()  # Auto-filtered to team 123
    """
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
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """
    Decorator that wraps a function in a team_scope() context.

    Extracts the team_id from the function's arguments and sets it as the
    current team context for the duration of the function call.

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
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            # Try to get team_id from kwargs first
            team_id = kwargs.get(team_id_param)

            # If not in kwargs, try to get from positional args
            if team_id is None:
                sig = inspect.signature(func)
                params = list(sig.parameters.keys())
                if team_id_param in params:
                    param_index = params.index(team_id_param)
                    if param_index < len(args):
                        team_id = args[param_index]

            if team_id is None:
                raise ValueError(
                    f"with_team_scope: Could not find '{team_id_param}' parameter. "
                    f"Ensure the function has a '{team_id_param}' parameter or "
                    f"specify a different parameter name."
                )

            with team_scope(team_id):
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
