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


def _with_error_code(url: str, error_code: str) -> str:
    """Attach `error_code` to a relative URL, keeping it ahead of any fragment.

    `next` is the whole path the modal was opened from, fragment included, and a query string placed
    after the `#` reads as fragment text - leaving the frontend with no error code to report.
    """
    path, fragment_separator, fragment = url.partition("#")
    joiner = "&" if "?" in path else "?"
    # url is either a literal or a same-origin path validated by get_safe_next_url, and the error code
    # is urlencoded, so this is a redirect target, not HTML
    # nosemgrep: python.flask.security.audit.directly-returned-format-string.directly-returned-format-string
    return f"{path}{joiner}{urlencode({'error_code': error_code})}{fragment_separator}{fragment}"


def sso_failure_redirect_url(request: HttpRequest, error_code: str, is_reauth: bool | None = None) -> str:
    """Where to send the browser when an SSO flow fails.

    A re-auth still has a valid session, so it goes back to the page that opened the modal with the
    error attached. /login is wrong for it even as a fallback: the frontend bounces a signed-in user
    off that route (sceneLogic's `onlyUnauthenticated` handling) and drops the error code on the way.
    """
    if is_reauth is None:
        is_reauth = is_sso_reauth_complete(request)

    if is_reauth:
        next_url = get_safe_next_url(request.GET.get("next") or getattr(request, "session", {}).get("next"), request)
        return _with_error_code(next_url or "/", error_code)

    return _with_error_code("/login", error_code)
