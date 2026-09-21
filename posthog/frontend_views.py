from typing import Any
from urllib.parse import urlparse, urlunparse

from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import ensure_csrf_cookie

from posthog.models.instance_setting import get_instance_setting
from posthog.utils import render_template
from posthog.views import login_required

APP_POSTHOG_HOST = "app.posthog.com"
# Canonical per-region hosts a `ph_current_instance` cookie is allowed to resolve to.
# Restricting to this set keeps the cookie from being turned into an open redirect.
_REGION_HOSTS = {"us.posthog.com", "eu.posthog.com"}


def region_host_from_current_instance(cookie_value: str | None) -> str | None:
    """Map a `ph_current_instance` cookie (an instance SITE_URL) to its canonical region
    host, or None when it isn't a recognized cloud region. Mirrors the frontend
    `cleanedCookieSubdomain` in RedirectToLoggedInInstance.tsx — the value is sometimes
    wrapped in quotes by the cookie serializer, so strip those before parsing."""
    if not cookie_value:
        return None
    hostname = urlparse(cookie_value.replace('"', "")).hostname
    return hostname if hostname in _REGION_HOSTS else None


def app_region_redirect(request: HttpRequest) -> HttpResponseRedirect | None:
    """For `app.posthog.com` page loads, send the browser to the region the user is
    actually logged into (per the `ph_current_instance` cookie), preserving the path and
    query. Falls back to the `REDIRECT_APP_TO_US` instance setting when there's no region
    cookie. Returns None when no redirect applies so callers render normally.

    This has to run before the `login_required` auth gate: `app.posthog.com` is the US
    backend, so an EU user hitting a deep link like /organization/billing is otherwise
    bounced to /login on US first, and only the login page honors the cookie."""
    if request.method not in ("GET", "HEAD"):
        return None
    if request.get_host().split(":")[0] != APP_POSTHOG_HOST:
        return None

    target_host = region_host_from_current_instance(request.COOKIES.get("ph_current_instance"))
    if target_host is None and get_instance_setting("REDIRECT_APP_TO_US"):
        target_host = "us.posthog.com"
    if target_host is None:
        return None

    url = "https://{}{}".format(target_host, request.get_full_path())
    if url_has_allowed_host_and_scheme(url, target_host, True):
        return HttpResponseRedirect(url)
    return None


# Frontend routes that only make sense signed out, matched on the exact path so
# `/signup/<invite_id>`, `/login/2fa` and `/login/2fa_setup` are left alone.
ONLY_UNAUTHENTICATED_PATHS = frozenset({"/login", "/signup"})


def post_auth_destination(request: HttpRequest) -> str:
    """Where a signed-in visitor to an only-unauthenticated route belongs. Mirrors the
    frontend `loginRedirectTarget`: the `?next=` an OAuth partner or the `login_required`
    decorator put there, otherwise the app root. Always a same-origin relative path."""
    next_path = request.GET.get("next")
    if not next_path or not url_has_allowed_host_and_scheme(next_path, allowed_hosts=None):
        return "/"
    parsed = urlparse(next_path)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/"):
        return "/"
    if parsed.path.rstrip("/") in ONLY_UNAUTHENTICATED_PATHS:
        return "/"
    return urlunparse(("", "", parsed.path, parsed.params, parsed.query, ""))


def only_unauthenticated_redirect(request: HttpRequest) -> HttpResponseRedirect | None:
    """Send a signed-in browser away from `/login` and `/signup` before the document is
    rendered. Without this the SPA boots the auth screen, sees the session in its app
    context, and replaces the URL itself, which the person reads as a surprise logout.
    Returns None when no redirect applies so callers render normally."""
    if request.method not in ("GET", "HEAD"):
        return None
    if request.path.rstrip("/") not in ONLY_UNAUTHENTICATED_PATHS:
        return None
    if not request.user.is_authenticated:
        return None
    return HttpResponseRedirect(post_auth_destination(request))


@ensure_csrf_cookie
def _render_home(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
    return render_template("index.html", request)


# Wrapped once at import time (as `login_required(home)` used to be) so the catch-all
# authenticated route doesn't rebuild the wrapper on every request.
_login_required_render_home = login_required(_render_home)


def home(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
    """Entrypoint for the unauthenticated frontend routes (login, signup, …). Runs the
    cross-region redirect before rendering so `app.posthog.com` visitors land on their
    logged-in region (see `app_region_redirect`), then sends an already signed-in visitor
    on to the app (see `only_unauthenticated_redirect`)."""
    region_redirect = app_region_redirect(request)
    if region_redirect is not None:
        return region_redirect
    signed_in_redirect = only_unauthenticated_redirect(request)
    if signed_in_redirect is not None:
        return signed_in_redirect
    return _render_home(request, *args, **kwargs)


def home_with_region_redirect(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
    """Catch-all entrypoint for authenticated frontend routes. The cross-region redirect
    runs before `login_required` so `app.posthog.com` deep links reach the right region
    without a detour through the login page (see `app_region_redirect`). It wraps
    `_render_home` rather than `home` so the redirect check runs exactly once per request."""
    region_redirect = app_region_redirect(request)
    if region_redirect is not None:
        return region_redirect
    return _login_required_render_home(request, *args, **kwargs)
