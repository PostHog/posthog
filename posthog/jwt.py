from datetime import datetime, timedelta, UTC
from enum import Enum
from typing import Any, Optional

import jwt
from django.conf import settings


class PosthogJwtAudience(Enum):
    UNSUBSCRIBE = "posthog:unsubscribe"
    EXPORTED_ASSET = "posthog:exported_asset"
    # This is used by background jobs on behalf of the user e.g. exports
    IMPERSONATED_USER = "posthog:impersonated_user"
    # Meant for client authentication such as the Toolbar or CLI tools
    CLIENT = "posthog:client"
    LIVESTREAM = "posthog:livestream"


def encode_jwt(
    payload: dict, expiry_delta: timedelta, audience: PosthogJwtAudience, scopes: Optional[list[str]] = None
) -> str:
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
            "scope": ",".join(scopes) if scopes else None,
        },
        settings.SECRET_KEY,
        algorithm="HS256",
    )

    return encoded_jwt


def decode_jwt(token: str, audience: PosthogJwtAudience) -> dict[str, Any]:
    info = jwt.decode(token, settings.SECRET_KEY, audience=audience.value, algorithms=["HS256"])

    return info
