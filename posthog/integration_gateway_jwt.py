from datetime import UTC, datetime, timedelta
from typing import Any

from django.conf import settings

import jwt

# Scoped service-to-service JWT for calling the integration-gateway Rust service. Signed with a
# dedicated per-purpose key (INTEGRATION_GATEWAY_JWT_SECRET) — NOT SECRET_KEY / JWT_SIGNING_KEY /
# INTERNAL_API_SECRET, so a leak is limited to this one caller->callee hop (see .agents/security.md).
# The `aud` and claim shape are the contract the gateway verifies (rust/integration-gateway/src/auth).

JWT_ALGORITHM = "HS256"

# Must match `JWT_AUDIENCE` in rust/integration-gateway/src/auth/claims.rs.
INTEGRATION_GATEWAY_AUDIENCE = "posthog:integration_gateway"


def encode_integration_gateway_jwt(team_id: int, caller: str, expiry_delta: timedelta) -> str:
    """Mint a short-lived token scoping a gateway call to one team.

    `team_id` pins the token to a single team — the gateway returns only rows for that team.
    `caller` is self-asserted (e.g. "django", "batch-exports") and used purely for the audit trail.
    Fails closed: raises if the dedicated secret isn't provisioned rather than signing with an empty
    or fallback key.
    """
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
    """Verify a gateway token (test/utility helper — the gateway itself verifies in Rust)."""
    secret = settings.INTEGRATION_GATEWAY_JWT_SECRET
    if not secret:
        raise RuntimeError("INTEGRATION_GATEWAY_JWT_SECRET is not configured")

    return jwt.decode(token, secret, audience=INTEGRATION_GATEWAY_AUDIENCE, algorithms=[JWT_ALGORITHM])
