"""
Facade for ai_gateway.

This is the ONLY module other products (and the presentation layer) are allowed
to import. It returns frozen dataclasses and never leaks the gateway's own
request or response shapes, so the gateway can change behind it.
"""

from posthog.models.user import User

from .. import logic
from ..logic import SpendLimitsRejected, SpendLimitsUnavailable, SpendLimitsUnsupported
from .contracts import SpendLimit

__all__ = [
    "SpendLimit",
    "SpendLimitsRejected",
    "SpendLimitsUnavailable",
    "SpendLimitsUnsupported",
    "clear_spend_limit",
    "get_spend_limit",
    "set_spend_limit",
]


def get_spend_limit(team_id: int, user: User) -> SpendLimit:
    return logic.read_spend_limit(team_id, user)


def set_spend_limit(team_id: int, user: User, *, limit_usd: str, window_seconds: int) -> SpendLimit:
    return logic.write_spend_limit(team_id, user, limit_usd=limit_usd, window_seconds=window_seconds)


def clear_spend_limit(team_id: int, user: User) -> SpendLimit:
    return logic.remove_spend_limit(team_id, user)
