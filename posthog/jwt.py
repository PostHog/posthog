from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

from django.conf import settings

import jwt
from cryptography.hazmat.primitives import serialization


class PosthogJwtAudience(Enum):
    UNSUBSCRIBE = "posthog:unsubscribe"
    EXPORTED_ASSET = "posthog:exported_asset"
    IMPERSONATED_USER = "posthog:impersonted_user"
    EXPORT_RENDERER = "posthog:export_renderer"
    LIVESTREAM = "posthog:livestream"
    SHARING_PASSWORD_PROTECTED = "posthog:sharing_password_protected"


class AgentInternalAudience(Enum):
    """Audiences for cross-service JWTs signed with `AGENT_INTERNAL_SIGNING_KEY`.

    Both Django (mints) and the node services (verify) read the same key.
    `aud` scopes a token to one receiving service so a token minted for
    the janitor can't be replayed against the ingress.

    Mirror constants in services/agent-shared/src/runtime/internal-jwt.ts —
    if you add an audience, add it on both sides.
    """

    INGRESS_PREVIEW = "agent-ingress.preview"
    JANITOR_RPC = "agent-janitor.rpc"


def encode_jwt(payload: dict, expiry_delta: timedelta, audience: PosthogJwtAudience) -> str:
    """
    Create a JWT ensuring that the correct audience and signing token is used
    """
    if not isinstance(audience, PosthogJwtAudience):
        raise Exception("Audience must be in the list of PostHog-supported audiences")

    encoded_jwt = jwt.encode(
        {
            **payload,
            "exp": datetime.now(tz=UTC) + expiry_delta,
            "aud": audience.value,
        },
        settings.SECRET_KEY,
        algorithm="HS256",
    )

    return encoded_jwt


def decode_jwt(token: str, audience: PosthogJwtAudience) -> dict[str, Any]:
    info = jwt.decode(token, settings.SECRET_KEY, audience=audience.value, algorithms=["HS256"])

    return info


def encode_agent_internal_jwt(
    payload: dict[str, Any],
    expiry_delta: timedelta,
    audience: AgentInternalAudience,
) -> str:
    """HS256 JWT for trusted-service ↔ trusted-service calls in the agent platform.

    Signed with `settings.AGENT_INTERNAL_SIGNING_KEY` (the same key the
    node services verify against). Distinct from `encode_jwt` because the
    latter signs with `SECRET_KEY` which the node services don't have.
    """
    key = settings.AGENT_INTERNAL_SIGNING_KEY
    if not key:
        raise RuntimeError("AGENT_INTERNAL_SIGNING_KEY is not configured")
    return jwt.encode(
        {
            **payload,
            "exp": datetime.now(tz=UTC) + expiry_delta,
            "aud": audience.value,
        },
        key,
        algorithm="HS256",
    )


def decode_agent_internal_jwt(token: str, audience: AgentInternalAudience) -> dict[str, Any]:
    key = settings.AGENT_INTERNAL_SIGNING_KEY
    if not key:
        raise RuntimeError("AGENT_INTERNAL_SIGNING_KEY is not configured")
    return jwt.decode(token, key, audience=audience.value, algorithms=["HS256"])


def get_oidc_public_key() -> Any:
    """Derive the verification key from the configured OIDC RSA private key.

    We don't memoize because the PEM is parsed once per request and parsing
    is cheap (~ tens of microseconds); caching would risk staleness on
    in-process key rotation.
    """
    pem = getattr(settings, "OIDC_RSA_PRIVATE_KEY", None)
    if not pem:
        return None
    private_key = serialization.load_pem_private_key(pem.encode(), password=None)
    return private_key.public_key()
