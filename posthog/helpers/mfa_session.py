import time
from django.http import HttpRequest
from django.conf import settings
from loginas.utils import is_impersonated_session
from two_factor.utils import default_device
from rest_framework.exceptions import PermissionDenied

MFA_VERIFIED_SESSION_KEY = "mfa_verified"

WHITELISTED_PATHS = [
    "/api/users/@me/two_factor_start_setup/",
    "/api/users/@me/two_factor_validate/",
    "/api/users/@me/two_factor_status/",
    "/api/users/@me/two_factor_backup_codes/",
    "/api/users/@me/two_factor_disable/",
    "/logout/",
    "/api/logout/",
    "/api/login/",
    "/api/login/token/",
    "/_health/",
]

WHITELISTED_PREFIXES = [
    "/static/",
    "/uploaded_media/",
]


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


def enforce_mfa(request, user):
    """
    Enforce MFA requirements for authenticated users in organizations that require it.
    """
    if is_path_whitelisted(request.path):
        return

    organization = getattr(user, "organization", None)
    if organization and organization.enforce_2fa:
        if is_impersonated_session(request._request):
            return

        if not default_device(user):
            raise PermissionDenied(detail="2FA setup required", code="mfa_setup_required")

        if not is_mfa_verified_in_session(request._request):
            raise PermissionDenied(detail="2FA verification required", code="mfa_verification_required")


def is_path_whitelisted(path):
    """
    Check if the request path should bypass MFA enforcement.
    """
    # Exact path matches
    if path in WHITELISTED_PATHS:
        return True

    # Prefix matches
    for prefix in WHITELISTED_PREFIXES:
        if path.startswith(prefix):
            return True

    return False
