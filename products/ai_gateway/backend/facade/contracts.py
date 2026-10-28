"""
Contract types for ai_gateway.

Frozen dataclasses that define what this product exposes.
No Django imports. Used by facade as inputs/outputs.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic.dataclasses import dataclass

from .enums import DevTokenClient, DevTokenStatus


@dataclass(frozen=True)
class DevToken:
    id: UUID
    client: DevTokenClient
    cap_usd: Decimal
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    status: DevTokenStatus
    # None when the token is not live or the gateway did not answer.
    remaining_usd: Decimal | None = None


@dataclass(frozen=True)
class MintedDevToken:
    id: UUID
    token: str
    cap_usd: Decimal
    expires_at: datetime
    gateway_url: str
    product: str


@dataclass(frozen=True)
class DevTokenUsage:
    daily_cap_usd: Decimal
    used_usd: Decimal
    token_cap_usd: Decimal
    ttl_seconds: int
    tokens: list[DevToken]


@dataclass(frozen=True)
class DevUserUsage:
    user_id: int | None
    email: str | None
    distinct_id: str
    tokens_minted_24h: int
    tokens_minted_30d: int
    live_tokens: int
    revoked_30d: int
    reserved_usd_24h: Decimal
    spend_usd_24h: Decimal
    spend_usd_7d: Decimal
    spend_usd_30d: Decimal
    last_minted_at: datetime | None


@dataclass(frozen=True)
class DevTokenActivity:
    at: datetime
    activity: str
    actor_email: str | None
    owner_email: str | None
    client: DevTokenClient | None
    cap_usd: Decimal | None


@dataclass(frozen=True)
class DevTeamUsage:
    paying_team_id: int
    users: list[DevUserUsage]
    activity: list[DevTokenActivity]


class DevTokenRefused(Exception):
    """A mint, exchange or revoke the caller cannot have. `code` is stable for clients."""

    def __init__(self, code: str, detail: str, http_status: int) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.http_status = http_status
