from enum import StrEnum

from django.conf import settings
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.http import HttpResponse

# A stolen copy stays usable this long, and each expiry costs Chrome one refresh round trip.
COOKIE_MAX_AGE_SECONDS = 10 * 60
# A request that left the browser just before expiry still carries the old value.
COOKIE_GRACE_SECONDS = 60
_SALT = "posthog.dbsc.bound-cookie"


class CookieCheck(StrEnum):
    VALID = "valid"
    MISSING = "missing"
    EXPIRED = "expired"
    BAD_SIGNATURE = "bad_signature"
    WRONG_SESSION = "wrong_session"


def cookie_name() -> str:
    # The __Host- prefix needs the Secure attribute, which local HTTP development leaves off.
    return "__Host-ph_dbsc" if settings.SESSION_COOKIE_SECURE else "ph_dbsc"


def cookie_attributes() -> str:
    attributes = "Path=/; HttpOnly; SameSite=Lax"
    return f"{attributes}; Secure" if settings.SESSION_COOKIE_SECURE else attributes


def _signer() -> TimestampSigner:
    keys: list[str | bytes] = list(settings.DBSC_COOKIE_SIGNING_KEYS)
    return TimestampSigner(key=keys[0], fallback_keys=keys[1:], salt=_SALT)


def set_bound_cookie(response: HttpResponse, binding_id: str) -> None:
    response.set_cookie(
        cookie_name(),
        _signer().sign(binding_id),
        max_age=COOKIE_MAX_AGE_SECONDS,
        path="/",
        secure=settings.SESSION_COOKIE_SECURE,
        httponly=True,
        samesite="Lax",
    )


def check_bound_cookie(value: str | None, binding_id: str) -> CookieCheck:
    if not value:
        return CookieCheck.MISSING
    try:
        signed_id = _signer().unsign(value, max_age=COOKIE_MAX_AGE_SECONDS + COOKIE_GRACE_SECONDS)
    except SignatureExpired:
        return CookieCheck.EXPIRED
    except BadSignature:
        return CookieCheck.BAD_SIGNATURE
    return CookieCheck.VALID if signed_id == binding_id else CookieCheck.WRONG_SESSION
