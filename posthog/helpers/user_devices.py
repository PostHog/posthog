from django.conf import settings
from django.core.signing import BadSignature, TimestampSigner
from django.http import HttpRequest, HttpResponse

from posthog.models import User

KNOWN_DEVICE_COOKIE = "ph_device_{user_id}"
KNOWN_DEVICE_COOKIE_MAX_AGE = 2 * 365 * 24 * 60 * 60  # 2 years
KNOWN_DEVICE_COOKIE_SALT = "posthog.known_device_cookie"


def _signer(user: User) -> TimestampSigner:
    # `user.uuid` guarantees a per-user salt even when `user.password` is empty
    # on password reset all prior cookies auto-invalidate
    return TimestampSigner(salt=f"{KNOWN_DEVICE_COOKIE_SALT}:{user.uuid}:{user.password}")


def build_known_device_cookie_value(user: User) -> str:
    return _signer(user).sign(str(user.pk))


def has_valid_known_device_cookie(request: HttpRequest, user: User) -> bool:
    value = request.COOKIES.get(KNOWN_DEVICE_COOKIE.format(user_id=user.id))
    if not value:
        return False
    try:
        return _signer(user).unsign(value, max_age=KNOWN_DEVICE_COOKIE_MAX_AGE) == str(user.pk)
    except (BadSignature, ValueError):
        return False


def set_known_device_cookie(response: HttpResponse, user: User) -> None:
    response.set_cookie(
        KNOWN_DEVICE_COOKIE.format(user_id=user.id),
        build_known_device_cookie_value(user),
        max_age=KNOWN_DEVICE_COOKIE_MAX_AGE,
        httponly=True,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite="Lax",
    )
