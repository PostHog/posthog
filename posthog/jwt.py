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
