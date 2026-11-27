import time
from dataclasses import field
from datetime import UTC, datetime, timedelta
from typing import Literal

from posthog.dataclasses import frozen
from posthog.jwt import PosthogJwtAudience
from posthog.scoped_service_jwt import ScopedServiceJwtPurpose

RecordingApiOp = Literal["read", "delete"]

# Direct callers mint a fresh token per request, so a short lifetime suffices. The rasterizer
# can't re-mint mid-render and reuses one relayed token across a whole render, so it passes a
# longer ttl explicitly.
DEFAULT_RECORDING_API_TOKEN_TTL = timedelta(minutes=5)

RECORDING_API_JWT_PURPOSE = ScopedServiceJwtPurpose(
    audience=PosthogJwtAudience.RECORDING_API,
    settings_name="RECORDING_API_JWT_SECRET",
    default_ttl=DEFAULT_RECORDING_API_TOKEN_TTL,
)


def recording_api_signing_keys() -> list[str]:
    """The comma-separated `new_key,old_key` set, newest first. Whitespace-trimmed (matching the
    Node verifier's parseJwtKeys) and empty entries dropped."""
    return RECORDING_API_JWT_PURPOSE.signing_keys()


def recording_api_jwt_enabled() -> bool:
    """True once a dedicated signing secret is configured. recording-api accepts no other credential,
    so callers check this first and raise RecordingApiConfigurationError when it is False."""
    return RECORDING_API_JWT_PURPOSE.enabled()


def recording_api_auth_headers(team_id: int, op: RecordingApiOp) -> dict[str, str]:
    """Auth headers for a recording-api request: a freshly minted team + operation scoped Bearer
    token. Raises RuntimeError when the signing secret is not configured."""
    return {"Authorization": f"Bearer {mint_recording_api_token(team_id, op)}"}


def mint_recording_api_token(team_id: int, op: RecordingApiOp, ttl: timedelta = DEFAULT_RECORDING_API_TOKEN_TTL) -> str:
    """Mint a team + operation scoped token for recording-api. Signs with the newest key;
    recording-api verifies against the full key set, so rotation works without breaking callers."""
    return RECORDING_API_JWT_PURPOSE.mint({"team_id": team_id, "op": op}, ttl=ttl)


# Long enough for an agent to read a large recording's blocks with one token.
STAFF_RECORDING_API_TOKEN_TTL = timedelta(minutes=15)

RECORDING_API_STAFF_JWT_PURPOSE = ScopedServiceJwtPurpose(
    audience=PosthogJwtAudience.RECORDING_API_STAFF,
    settings_name="RECORDING_API_STAFF_JWT_SECRET",
    default_ttl=STAFF_RECORDING_API_TOKEN_TTL,
)


@frozen
class StaffRecordingApiToken:
    token: str = field(repr=False)
    expires_at: datetime


# Matches recording-api's boot check, since a short HMAC key can be guessed offline from one minted token.
MIN_STAFF_KEY_BYTES = 32


def staff_key_problem() -> str | None:
    """Why this pod must not mint staff tokens, or None when its staff key is usable."""
    staff_keys = RECORDING_API_STAFF_JWT_PURPOSE.signing_keys()
    if not staff_keys:
        return "RECORDING_API_STAFF_JWT_SECRET is not set on this pod"
    if any(len(key.encode()) < MIN_STAFF_KEY_BYTES for key in staff_keys):
        return f"RECORDING_API_STAFF_JWT_SECRET keys must be at least {MIN_STAFF_KEY_BYTES} bytes"
    return None


def mint_recording_api_staff_token(team_id: int, actor: str, reason: str) -> StaffRecordingApiToken:
    """Mint a read-only token for one team that recording-api logs with the actor and reason on every request."""
    now = int(time.time())
    token = RECORDING_API_STAFF_JWT_PURPOSE.mint(
        # recording-api checks the token's age against iat, which encode_jwt does not set.
        {
            "team_id": team_id,
            "op": "read",
            "actor": actor,
            "reason": reason,
            "iat": now,
        }
    )
    return StaffRecordingApiToken(
        token=token, expires_at=datetime.fromtimestamp(now, tz=UTC) + STAFF_RECORDING_API_TOKEN_TTL
    )
