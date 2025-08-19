import time
from django.http import HttpRequest
from django.conf import settings

MFA_VERIFIED_SESSION_KEY = "mfa_verified"
MFA_VERIFIED_AT_SESSION_KEY = "mfa_verified_at"
MFA_SESSION_TIMEOUT = getattr(settings, "MFA_SESSION_TIMEOUT", 8 * 60 * 60)


def set_mfa_verified_in_session(request: HttpRequest, verified: bool = True) -> None:
    if verified:
        request.session[MFA_VERIFIED_SESSION_KEY] = True
        request.session[MFA_VERIFIED_AT_SESSION_KEY] = time.time()
    else:
        clear_mfa_session_flags(request)


def is_mfa_verified_in_session(request: HttpRequest) -> bool:
    if not request.session.get(MFA_VERIFIED_SESSION_KEY):
        return False

    mfa_verified_at = request.session.get(MFA_VERIFIED_AT_SESSION_KEY)
    if not mfa_verified_at:
        return False

    if is_mfa_session_expired(request):
        clear_mfa_session_flags(request)
        return False

    return True


def clear_mfa_session_flags(request: HttpRequest) -> None:
    request.session.pop(MFA_VERIFIED_SESSION_KEY, None)
    request.session.pop(MFA_VERIFIED_AT_SESSION_KEY, None)


def is_mfa_session_expired(request: HttpRequest) -> bool:
    mfa_verified_at = request.session.get(MFA_VERIFIED_AT_SESSION_KEY)
    if not mfa_verified_at:
        return True

    if MFA_SESSION_TIMEOUT <= 0:
        return False

    return time.time() - mfa_verified_at > MFA_SESSION_TIMEOUT
