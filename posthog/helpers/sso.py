from urllib.parse import urlencode

from django.http import HttpRequest
from django.utils.http import url_has_allowed_host_and_scheme


def get_safe_next_url(next_url: str | None, request: HttpRequest) -> str | None:
    """Return next_url only when it's a safe same-origin/relative redirect target, else None.

    The value is embedded into emailed verification links, so an unvalidated next
    would be an open-redirect / phishing vector.
    """
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return next_url
    return None


def _is_authenticated(request: HttpRequest) -> bool:
    # Not every request reaching these helpers has been through AuthenticationMiddleware
    user = getattr(request, "user", None)
    return bool(user and user.is_authenticated)


def is_sso_reauth_begin(request: HttpRequest) -> bool:
    """Whether an outgoing SSO flow is a step-up re-auth of the session that's already signed in.

    The re-authentication modal appends `reauth=true` to the provider link (see
    TimeSensitiveAuthentication.tsx).
    """
    return _is_authenticated(request) and request.GET.get("reauth") == "true"


def is_sso_reauth_complete(request: HttpRequest) -> bool:
    """Same question on the way back from the IdP, where the flag lives in the session.

    `do_auth` copies it there on the way out, per `SOCIAL_AUTH_FIELDS_STORED_IN_SESSION`, and clears
    it when the flow didn't ask for a re-auth.
    """
    if not _is_authenticated(request):
        return False
    return getattr(request, "session", {}).get("reauth") == "true"


def sso_failure_redirect_url(request: HttpRequest, error_code: str, is_reauth: bool | None = None) -> str:
    """Where to send the browser when an SSO flow fails.

    A re-auth still has a valid session, so it goes back to the page that opened the modal with the
    error attached; bouncing it to /login would show a sign-in form to someone who is signed in.
    """
    if is_reauth is None:
        is_reauth = is_sso_reauth_complete(request)

    if is_reauth:
        next_url = get_safe_next_url(request.GET.get("next") or getattr(request, "session", {}).get("next"), request)
        if next_url:
            separator = "&" if "?" in next_url else "?"
            return f"{next_url}{separator}{urlencode({'error_code': error_code})}"

    return f"/login?{urlencode({'error_code': error_code})}"
