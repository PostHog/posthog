import time
import datetime

from django.conf import settings
from django.http import HttpRequest

from loginas.utils import is_impersonated_session
from rest_framework.exceptions import PermissionDenied
from two_factor.utils import default_device

from posthog.settings.web import AUTHENTICATION_BACKENDS

# Enforce Two-Factor Authentication only on sessions created after this date
TWO_FACTOR_ENFORCEMENT_FROM_DATE = datetime.datetime(2025, 9, day=22, hour=13)

TWO_FACTOR_VERIFIED_SESSION_KEY = "two_factor_verified"

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
    "/api/users/@me/",
    "/_health/",
]

WHITELISTED_PREFIXES = [
    "/static/",
    "/uploaded_media/",
    "/api/instance_status",
    "/api/signup",
    "/api/social_signup",
    "/login/google-oauth2",
    "/login/github",
    "/login/gitlab",
    "/login/saml",
    "/complete/google-oauth2",
    "/complete/github",
    "/complete/gitlab",
    "/complete/saml",
    "/api/saml/metadata",
]


def set_two_factor_verified_in_session(request: HttpRequest, verified: bool = True) -> None:
    if verified:
        request.session[TWO_FACTOR_VERIFIED_SESSION_KEY] = True
    else:
        clear_two_factor_session_flags(request)


def is_two_factor_verified_in_session(request: HttpRequest) -> bool:
    if not request.session.get(TWO_FACTOR_VERIFIED_SESSION_KEY):
        return False

    if is_two_factor_session_expired(request):
        clear_two_factor_session_flags(request)
        return False

    return True


def clear_two_factor_session_flags(request: HttpRequest) -> None:
    request.session.pop(TWO_FACTOR_VERIFIED_SESSION_KEY, None)


def is_two_factor_session_expired(request: HttpRequest) -> bool:
    session_created_at = request.session.get(settings.SESSION_COOKIE_CREATED_AT_KEY)
    if not session_created_at:
        return True

    return time.time() - session_created_at > settings.SESSION_COOKIE_AGE


def enforce_two_factor(request, user):
    """
    Enforce Two-Factor Authentication requirements for authenticated users in organizations that require it.
    Excludes paths that are whitelisted and domains that have SSO enforcement enabled.
    """
    if is_path_whitelisted(request.path):
        return

    # We currently don't enforce 2FA for any SSO-authenticated users, as we depend on the SSO provider to handle 2FA
    # TODO: This will soon be made configurable
    if is_sso_authentication_backend(request._request):
        return

    organization = getattr(user, "organization", None)
    if organization and organization.enforce_2fa:
        # Same as above, we don't enforce 2FA on SSO-enforced domains, we depend on the SSO provider to handle 2FA
        # TODO: This will soon be made configurable
        if is_domain_sso_enforced(request._request):
            return

        if not is_two_factor_enforcement_in_effect(request._request):
            return

        if is_impersonated_session(request._request):
            return

        if not default_device(user):
            raise PermissionDenied(detail="2FA setup required", code="two_factor_setup_required")

        if not is_two_factor_verified_in_session(request._request):
            raise PermissionDenied(detail="2FA verification required", code="two_factor_verification_required")


def is_path_whitelisted(path):
    """
    Check if the request path should bypass Two-Factor Authentication enforcement.
    """
    if path in WHITELISTED_PATHS:
        return True

    for prefix in WHITELISTED_PREFIXES:
        if path.startswith(prefix):
            return True

    return False


def is_two_factor_enforcement_in_effect(request: HttpRequest):
    session_created_at = request.session.get(settings.SESSION_COOKIE_CREATED_AT_KEY)

    if not session_created_at:
        return False

    return datetime.datetime.fromtimestamp(session_created_at) >= TWO_FACTOR_ENFORCEMENT_FROM_DATE


def is_domain_sso_enforced(request: HttpRequest):
    from posthog.models.organization_domain import OrganizationDomain

    if not hasattr(request.user, "email"):
        return False

    return bool(OrganizationDomain.objects.get_sso_enforcement_for_email_address(request.user.email))


def is_sso_authentication_backend(request: HttpRequest):
    SSO_AUTHENTICATION_BACKENDS = []
    NON_SSO_AUTHENTICATION_BACKENDS = ["axes.backends.AxesBackend", "django.contrib.auth.backends.ModelBackend"]

    if not hasattr(request, "session"):
        return False

    # Check if we're in EE, if yes, use the EE settings, otherwise use the posthog settings
    try:
        from ee import settings

        SSO_AUTHENTICATION_BACKENDS = settings.AUTHENTICATION_BACKENDS
    except ImportError:
        SSO_AUTHENTICATION_BACKENDS = AUTHENTICATION_BACKENDS

    # Remove the non-SSO backends from the list
    SSO_AUTHENTICATION_BACKENDS = list(set(SSO_AUTHENTICATION_BACKENDS) - set(NON_SSO_AUTHENTICATION_BACKENDS))

    return request.session.get("_auth_user_backend") in SSO_AUTHENTICATION_BACKENDS
