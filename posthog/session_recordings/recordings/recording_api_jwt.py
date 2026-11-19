from datetime import timedelta
from typing import Literal

from posthog.jwt import PosthogJwtAudience
from posthog.scoped_service_jwt import ScopedServiceJwtPurpose

RecordingApiOp = Literal["read", "delete", "write"]

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
