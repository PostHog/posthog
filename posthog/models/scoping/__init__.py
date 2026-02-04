# Team Scoping Context
#
# This module provides automatic team scoping for Django models.
# When a request comes in, the middleware sets the current team_id in a ContextVar.
# Models that inherit from TeamScopedMixin will automatically filter by this team_id.
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
#
#   # Or explicitly unscoped:
#   FeatureFlag.objects.unscoped().filter(...)

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Optional

# The current team_id, set by middleware or explicitly via team_scope()
_current_team_id: ContextVar[Optional[int]] = ContextVar("current_team_id", default=None)


def get_current_team_id() -> Optional[int]:
    """Get the current team_id from context, or None if not set."""
    return _current_team_id.get()


def set_current_team_id(team_id: Optional[int]) -> Token[Optional[int]]:
    """Set the current team_id in context. Returns a token to reset it later."""
    return _current_team_id.set(team_id)


def reset_current_team_id(token: Token[Optional[int]]) -> None:
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
