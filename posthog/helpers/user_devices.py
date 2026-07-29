from typing import Optional

from django.conf import settings
from django.core.signing import BadSignature, TimestampSigner
from django.http import HttpRequest, HttpResponse

from posthog.models import User

KNOWN_DEVICE_COOKIE = "ph_device_{user_id}"
KNOWN_DEVICE_COOKIE_MAX_AGE = 2 * 365 * 24 * 60 * 60  # 2 years
KNOWN_DEVICE_COOKIE_SALT = "posthog.known_device_cookie"

# Signature used when there is no user agent to parse. One shared bucket rather than a per-request one,
# so a client we can't identify is alerted on once instead of on every login — and so an attacker can't
# mint a fresh "device" (or suppress the alert) by withholding the header.
UNKNOWN_DEVICE_SIGNATURE = "unknown"


def ua_signature(user_agent: Optional[str]) -> Optional[str]:
    """Stable device identity derived from a user agent.

    Deliberately version-free: browsers update themselves, so neither a point release nor a major bump
    makes something a different device.
    """
    if not user_agent:
        return None
    from user_agents import parse  # noqa: PLC0415 — heavy dep, request-time only (matches get_short_user_agent)

    ua = parse(user_agent)
    device = "mobile" if ua.is_mobile else "tablet" if ua.is_tablet else "pc" if ua.is_pc else "other"
    return f"{ua.browser.family}|{ua.os.family}|{device}".lower()


def get_login_device_signature(request: HttpRequest) -> str:
    return ua_signature(request.headers.get("user-agent")) or UNKNOWN_DEVICE_SIGNATURE


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
