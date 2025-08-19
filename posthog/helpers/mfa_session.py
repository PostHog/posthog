import time
from django.http import HttpRequest
from django.conf import settings

MFA_VERIFIED_SESSION_KEY = "mfa_verified"


def set_mfa_verified_in_session(request: HttpRequest, verified: bool = True) -> None:
    if verified:
        request.session[MFA_VERIFIED_SESSION_KEY] = True
    else:
        clear_mfa_session_flags(request)


def is_mfa_verified_in_session(request: HttpRequest) -> bool:
    if not request.session.get(MFA_VERIFIED_SESSION_KEY):
        return False

    if is_mfa_session_expired(request):
        clear_mfa_session_flags(request)
        return False

    return True


def clear_mfa_session_flags(request: HttpRequest) -> None:
    request.session.pop(MFA_VERIFIED_SESSION_KEY, None)


def is_mfa_session_expired(request: HttpRequest) -> bool:
    session_created_at = request.session.get(settings.SESSION_COOKIE_CREATED_AT_KEY)
    if not session_created_at:
        return True

    return time.time() - session_created_at > settings.SESSION_COOKIE_AGE
