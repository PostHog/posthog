from datetime import timedelta
from typing import Literal

from django.conf import settings

import structlog

from posthog.jwt import PosthogJwtAudience
from posthog.scoped_service_jwt import ScopedServiceJwtPurpose

logger = structlog.get_logger(__name__)

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
    """True once a dedicated signing secret is configured. Until then callers fall back to the
    legacy X-Internal-Api-Secret, so the JWT scheme can be rolled out per environment (dev, then
    prod) without leaving any environment unauthenticated in the meantime."""
    return RECORDING_API_JWT_PURPOSE.enabled()


def recording_api_auth_headers(team_id: int, op: RecordingApiOp) -> dict[str, str]:
    """Auth headers for a recording-api request. Sends the legacy shared secret (when configured)
    and a freshly minted team + operation scoped Bearer token (when the signing secret is
    configured), so recording-api accepts either and rollout stays order-independent."""
    headers: dict[str, str] = {}
    if settings.INTERNAL_API_SECRET:
        headers["X-Internal-Api-Secret"] = settings.INTERNAL_API_SECRET
    if recording_api_jwt_enabled():
        headers["Authorization"] = f"Bearer {mint_recording_api_token(team_id, op)}"
    if not headers:
        # Neither secret configured: the request will be sent unauthenticated and recording-api will
        # reject it. Surface the misconfiguration here (the caller otherwise only sees an opaque 401).
        logger.warning("recording_api.no_auth_configured")
    return headers


def mint_recording_api_token(team_id: int, op: RecordingApiOp, ttl: timedelta = DEFAULT_RECORDING_API_TOKEN_TTL) -> str:
    """Mint a team + operation scoped token for recording-api. Signs with the newest key;
    recording-api verifies against the full key set, so rotation works without breaking callers."""
    return RECORDING_API_JWT_PURPOSE.mint({"team_id": team_id, "op": op}, ttl=ttl)
