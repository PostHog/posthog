"""Cookie that carries a pending OAuth authorization through login and signup.

`/oauth/authorize` needs a session. A visitor without one is sent to `/login?next=...`,
and from there may go through signup and email verification before coming back. Only the
opaque `next` URL travels with them, so nothing on those screens can name the application
they are connecting.

This cookie makes that context readable on every `posthog.com` host, the website included,
which the app context cannot do because only the app's own documents receive it. The cookie
holds public application metadata only: the same name and logo the consent screen shows.
"""

import json
from urllib.parse import quote, unquote

from django.http import HttpRequest, HttpResponse

from posthog.dataclasses import frozen

PENDING_OAUTH_CONNECTION_COOKIE = "ph_pending_oauth_connection"

# Long enough to sign up and verify an email address, short enough that an abandoned
# connection does not keep branding the login page for days.
PENDING_OAUTH_CONNECTION_MAX_AGE_SECONDS = 60 * 60

# The cookie is shared with the website, so it is scoped to the registrable domain when
# the request host is under it. Any other host (localhost, a preview domain) gets a
# host-only cookie, because a browser drops a cookie whose Domain does not cover the host.
_SHARED_COOKIE_DOMAIN = "posthog.com"

# Column limits of the application row these values come from. Anything longer arrived
# from a forged cookie, and the reader treats it as absent.
_MAX_CLIENT_NAME_LENGTH = 255
_MAX_CLIENT_ID_LENGTH = 2048
# Browsers cap a whole cookie near 4 KB. A logo URI past this is left out rather than
# risk the browser rejecting the entire cookie.
_MAX_LOGO_URI_LENGTH = 1024
_MAX_HOST_LENGTH = 253


def _optional_str(value: object, max_length: int) -> str | None:
    if not isinstance(value, str) or not value or len(value) > max_length:
        return None
    return value


@frozen
class PendingOAuthConnection:
    """What the auth screens and the website may say about the application being connected."""

    client_name: str
    client_id: str
    logo_uri: str | None = None
    # Host of the registered redirect URI the visitor returns to, when it is a web URL.
    redirect_host: str | None = None

    def to_cookie_value(self) -> str:
        payload = {
            "client_name": self.client_name,
            "client_id": self.client_id,
            "logo_uri": _optional_str(self.logo_uri, _MAX_LOGO_URI_LENGTH),
            "redirect_host": self.redirect_host,
        }
        compact = {key: value for key, value in payload.items() if value is not None}
        # Percent-encoding keeps the value inside the cookie-safe alphabet, and it is what
        # `decodeURIComponent` on the reading side expects.
        return quote(json.dumps(compact, separators=(",", ":")), safe="")

    @classmethod
    def from_cookie_value(cls, raw: str | None) -> "PendingOAuthConnection | None":
        if not raw:
            return None
        try:
            payload = json.loads(unquote(raw))
        except (ValueError, TypeError):
            return None
        if not isinstance(payload, dict):
            return None
        client_name = _optional_str(payload.get("client_name"), _MAX_CLIENT_NAME_LENGTH)
        client_id = _optional_str(payload.get("client_id"), _MAX_CLIENT_ID_LENGTH)
        if client_name is None or client_id is None:
            return None
        return cls(
            client_name=client_name,
            client_id=client_id,
            logo_uri=_optional_str(payload.get("logo_uri"), _MAX_LOGO_URI_LENGTH),
            redirect_host=_optional_str(payload.get("redirect_host"), _MAX_HOST_LENGTH),
        )


def _cookie_domain(request: HttpRequest) -> str | None:
    host = request.get_host().rsplit(":", 1)[0].lower()
    if host == _SHARED_COOKIE_DOMAIN or host.endswith("." + _SHARED_COOKIE_DOMAIN):
        return _SHARED_COOKIE_DOMAIN
    return None


def set_pending_oauth_connection_cookie(
    request: HttpRequest, response: HttpResponse, connection: PendingOAuthConnection
) -> None:
    # nosemgrep: python.django.security.audit.secure-cookies.django-secure-set-cookie (httponly=False intentional, read by JS on the app and on the website)
    response.set_cookie(
        key=PENDING_OAUTH_CONNECTION_COOKIE,
        value=connection.to_cookie_value(),
        max_age=PENDING_OAUTH_CONNECTION_MAX_AGE_SECONDS,
        path="/",
        domain=_cookie_domain(request),
        secure=request.is_secure(),
        httponly=False,
        samesite="Lax",
    )


def clear_pending_oauth_connection_cookie(request: HttpRequest, response: HttpResponse) -> None:
    """End the pending connection. A no-op without the cookie, so the deletion header is not
    attached to the many authorizations that started from an already signed-in session."""
    if PENDING_OAUTH_CONNECTION_COOKIE not in request.COOKIES:
        return
    response.delete_cookie(PENDING_OAUTH_CONNECTION_COOKIE, path="/", domain=_cookie_domain(request), samesite="Lax")


def read_pending_oauth_connection(request: HttpRequest) -> PendingOAuthConnection | None:
    return PendingOAuthConnection.from_cookie_value(request.COOKIES.get(PENDING_OAUTH_CONNECTION_COOKIE))
