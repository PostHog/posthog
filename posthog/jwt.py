from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict

import jwt
from django.conf import settings


class PosthogJwtAudience(Enum):
    UNSUBSCRIBE = "posthog:unsubscribe"
    EXPORTED_ASSET = "posthog:exported_asset"
    IMPERSONATED_USER = "posthog:impersonted_user"  # This is used by background jobs on behalf of the user e.g. exports


def encode_jwt(payload: dict, expiry_delta: timedelta, audience: PosthogJwtAudience) -> str:
    """
    Create a JWT ensuring that the correct audience and signing token is used
    """
    if not isinstance(audience, PosthogJwtAudience):
        raise Exception("Audience must be in the list of PostHog-supported audiences")

    encoded_jwt = jwt.encode(
        {
            **payload,
            "exp": datetime.now(tz=timezone.utc) + expiry_delta,
            "aud": audience.value,
        },
        settings.SECRET_KEY,
        algorithm="HS256",
    )

    return encoded_jwt


def decode_jwt(token: str, audience: PosthogJwtAudience) -> Dict[str, Any]:
    info = jwt.decode(token, settings.SECRET_KEY, audience=audience.value, algorithms=["HS256"])

    return info
