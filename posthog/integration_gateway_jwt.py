from datetime import UTC, datetime, timedelta
from typing import Any

from django.conf import settings

import jwt

# Must equal the Rust/nodejs gateway's JWT_AUDIENCE and PosthogJwtAudience.INTEGRATION_GATEWAY.
INTEGRATION_GATEWAY_AUDIENCE = "posthog:integration_gateway"
JWT_ALGORITHM = "HS256"


def encode_integration_gateway_jwt(team_id: int, caller: str, expiry_delta: timedelta) -> str:
    """Mint a team-scoped JWT the integration gateway accepts. Fails closed if unconfigured."""
    secret = settings.INTEGRATION_GATEWAY_JWT_SECRET
    if not secret:
        raise RuntimeError("INTEGRATION_GATEWAY_JWT_SECRET is not configured")
    return jwt.encode(
        {
            "team_id": team_id,
            "caller": caller,
            "exp": datetime.now(tz=UTC) + expiry_delta,
            "aud": INTEGRATION_GATEWAY_AUDIENCE,
        },
        secret,
        algorithm=JWT_ALGORITHM,
    )


def decode_integration_gateway_jwt(token: str) -> dict[str, Any]:
    secret = settings.INTEGRATION_GATEWAY_JWT_SECRET
    if not secret:
        raise RuntimeError("INTEGRATION_GATEWAY_JWT_SECRET is not configured")
    return jwt.decode(token, secret, audience=INTEGRATION_GATEWAY_AUDIENCE, algorithms=[JWT_ALGORITHM])
