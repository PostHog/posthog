from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

from django.conf import settings

import jwt

# Trusted-service ↔ trusted-service JWTs for the agent platform. Signed with
# AGENT_INTERNAL_SIGNING_KEY (the key the node services verify against) — distinct
# from posthog.jwt's SECRET_KEY-signed tokens, which the node services can't verify.

JWT_ALGORITHM = "HS256"


class AgentInternalAudience(Enum):
    """`aud` scopes a token to one receiving service, so a token minted for the
    janitor can't be replayed against the ingress. Mirror these in
    services/agent-shared/src/runtime/internal-jwt.ts — add to both sides.
    """

    INGRESS_PREVIEW = "agent-ingress.preview"
    INGRESS_RPC = "agent-ingress.rpc"
    JANITOR_RPC = "agent-janitor.rpc"


def encode_agent_internal_jwt(payload: dict[str, Any], expiry_delta: timedelta, audience: AgentInternalAudience) -> str:
    key = settings.AGENT_INTERNAL_SIGNING_KEY
    if not key:
        raise RuntimeError("AGENT_INTERNAL_SIGNING_KEY is not configured")
    return jwt.encode(
        {**payload, "exp": datetime.now(tz=UTC) + expiry_delta, "aud": audience.value},
        key,
        algorithm=JWT_ALGORITHM,
    )


def decode_agent_internal_jwt(token: str, audience: AgentInternalAudience) -> dict[str, Any]:
    key = settings.AGENT_INTERNAL_SIGNING_KEY
    if not key:
        raise RuntimeError("AGENT_INTERNAL_SIGNING_KEY is not configured")
    return jwt.decode(token, key, audience=audience.value, algorithms=[JWT_ALGORITHM])
