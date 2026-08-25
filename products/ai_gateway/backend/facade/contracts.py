"""
Contract types for ai_gateway.

Stable, framework-free frozen dataclasses that define what this product exposes
to the rest of the codebase. No Django imports.
"""

from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class SpendLimit:
    """
    One person's cap on gateway spend.

    `limit_usd` and `window_seconds` are None when no cap is set. `available` is
    False where the gateway cannot hold a cap at all, so a cap a client shows
    there informs only.
    """

    limit_usd: str | None
    window_seconds: int | None
    available: bool
