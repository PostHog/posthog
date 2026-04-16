import hashlib

from django.conf import settings
from django.core.signing import BadSignature
from django.http import HttpRequest, HttpResponse

from two_factor.views.utils import get_remember_device_cookie, validate_remember_device_cookie

from posthog.models import User
from posthog.redis import get_client

TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days

# Long-lived signed cookie that marks a browser as "known" for a given user so we
# don't spam new-device emails on UA/IP drift. Signed with the user's password hash
# via django-two-factor's signer — auto-invalidates on password reset, can't be
# forged without knowing the password. A distinct otp_device_id keeps these
# cookies disjoint from actual 2FA remember-device cookies.
KNOWN_LOGIN_COOKIE_MAX_AGE = 2 * 365 * 24 * 60 * 60  # 2 years
_OTP_DEVICE_ID = "login_device"


def known_login_cookie_name(user_id: int) -> str:
    return f"ph_lid_{user_id}"


def build_known_login_cookie_value(user: User) -> str:
    return get_remember_device_cookie(user=user, otp_device_id=_OTP_DEVICE_ID)


def has_valid_known_login_cookie(request: HttpRequest, user: User) -> bool:
    value = request.COOKIES.get(known_login_cookie_name(user.id))
    if not value:
        return False
    try:
        return bool(validate_remember_device_cookie(value, user=user, otp_device_id=_OTP_DEVICE_ID))
    except BadSignature:
        return False


def set_known_login_cookie(response: HttpResponse, user: User) -> None:
    response.set_cookie(
        known_login_cookie_name(user.id),
        build_known_login_cookie_value(user),
        max_age=KNOWN_LOGIN_COOKIE_MAX_AGE,
        httponly=True,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite="Lax",
    )


def check_and_cache_login_device(user_id: int, location: str, short_user_agent: str) -> bool:
    """Check if this is a new device and cache it for 30 days"""

    # Create a unique device identifier based on location + user agent
    device_fingerprint = f"{location}:{short_user_agent}"
    # TODO switch to sha256 hash
    # device_fingerprint is user controllable. a hash collision might be possible with md5
    # nosemgrep: python.lang.security.insecure-hash-algorithms-md5.insecure-hash-algorithm-md5
    device_hash = hashlib.md5(device_fingerprint.encode()).hexdigest()
    cache_key = f"login_device:{user_id}:{device_hash}"

    # Check if this device has logged in before
    redis_client = get_client()
    device_exists = redis_client.exists(cache_key)

    if device_exists:
        redis_client.expire(cache_key, TTL_SECONDS)
        return False
    else:
        redis_client.setex(cache_key, TTL_SECONDS, "1")
        return True
