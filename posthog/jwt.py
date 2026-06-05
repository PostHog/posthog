import hashlib
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

from django.conf import settings

import jwt
from cryptography.hazmat.primitives import serialization

JWT_ALGORITHM = "HS256"


class PosthogJwtAudience(Enum):
    UNSUBSCRIBE = "posthog:unsubscribe"
    EXPORTED_ASSET = "posthog:exported_asset"
    IMPERSONATED_USER = "posthog:impersonted_user"
    EXPORT_RENDERER = "posthog:export_renderer"
    LIVESTREAM = "posthog:livestream"
    SHARING_PASSWORD_PROTECTED = "posthog:sharing_password_protected"


def signing_key_fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _signing_key() -> str:
    return settings.JWT_SIGNING_KEY


def _verification_keys() -> list[str]:
    return [_signing_key(), *settings.JWT_SIGNING_KEY_FALLBACKS]


def encode_jwt(payload: dict, expiry_delta: timedelta, audience: PosthogJwtAudience) -> str:
    """
    Create a JWT ensuring that the correct audience and signing token is used
    """
    if not isinstance(audience, PosthogJwtAudience):
        raise Exception("Audience must be in the list of PostHog-supported audiences")

    return jwt.encode(
        {
            **payload,
            "exp": datetime.now(tz=UTC) + expiry_delta,
            "aud": audience.value,
        },
        _signing_key(),
        algorithm=JWT_ALGORITHM,
    )


def decode_jwt(token: str, audience: PosthogJwtAudience) -> dict[str, Any]:
    last_error: jwt.InvalidSignatureError | None = None
    for key in _verification_keys():
        try:
            return jwt.decode(token, key, audience=audience.value, algorithms=[JWT_ALGORITHM])
        except jwt.InvalidSignatureError as error:
            last_error = error

    raise last_error or jwt.InvalidSignatureError("Signature verification failed")


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
