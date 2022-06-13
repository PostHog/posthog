from datetime import datetime
from enum import Enum
from django.conf import settings
import jwt
from datetime import timedelta, timezone


class PosthogJwtAudience(Enum):
    UNSUBSCRIBE = "posthog:unsubscribe"
    EXPORTED_ASSET = "posthog:exported_asset"


def encode_jwt(payload: dict, expiry_delta: timedelta, audience: PosthogJwtAudience) -> str:
    """
    Create a JWT ensuring that the correct audience and signing token is used
    """
    if not isinstance(audience, PosthogJwtAudience):
        raise Exception("Audience must be in the list of Posthog supported audiences")

    encoded_jwt = jwt.encode(
        {**payload, "exp": datetime.now(tz=timezone.utc) + expiry_delta, "aud": audience.value},
        settings.SECRET_KEY,
        algorithm="HS256",
    )

    return encoded_jwt


def decode_jwt(token: str, audience: PosthogJwtAudience) -> str:
    info = jwt.decode(token, settings.SECRET_KEY, audience=audience.value, algorithms=["HS256"])

    return info
