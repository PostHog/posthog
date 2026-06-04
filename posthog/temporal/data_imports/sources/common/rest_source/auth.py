from base64 import b64encode
from datetime import UTC, datetime, timedelta
from typing import Literal, Optional

from requests import PreparedRequest
from requests.auth import AuthBase

from posthog.temporal.data_imports.sources.common.http import make_tracked_session

TApiKeyLocation = Literal["header", "query", "param", "cookie"]
TOAuth2GrantType = Literal["client_credentials", "refresh_token"]

# Used when the token endpoint omits `expires_in`; mirrors the 1-hour default
# the existing SalesforceAuth assumes. The safety margin re-mints slightly early
# so a token never expires mid-request.
_OAUTH2_DEFAULT_EXPIRES_IN = 3600
_OAUTH2_EXPIRY_MARGIN = timedelta(seconds=60)


class AuthConfigBase(AuthBase):
    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        return request

    def __bool__(self) -> bool:
        return True

    def secret_values(self) -> tuple[str, ...]:
        """Credential strings this auth carries, for log redaction.

        The tracked HTTP transport masks these wherever they appear in logged
        URLs, headers, and sampled bodies — so a credential injected under a
        param/header name the denylist scrubber can't know in advance (e.g. an
        API key in a query param) is still redacted. Each subclass declares its
        own secret so the list can't drift from the field that holds it.
        """
        return ()


class BearerTokenAuth(AuthConfigBase):
    def __init__(self, token: Optional[str] = None) -> None:
        self.token = token

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        request.headers["Authorization"] = f"Bearer {self.token}"
        return request

    def secret_values(self) -> tuple[str, ...]:
        return (self.token,) if self.token else ()


class APIKeyAuth(AuthConfigBase):
    def __init__(
        self,
        api_key: Optional[str] = None,
        name: str = "Authorization",
        location: TApiKeyLocation = "header",
    ) -> None:
        self.api_key = api_key
        self.name = name
        self.location = location

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        if self.location == "header":
            request.headers[self.name] = self.api_key or ""
        elif self.location in ("query", "param"):
            request.prepare_url(request.url, {self.name: self.api_key})
        elif self.location == "cookie":
            request.prepare_cookies({self.name: self.api_key or ""})
        return request

    def secret_values(self) -> tuple[str, ...]:
        return (self.api_key,) if self.api_key else ()


class HttpBasicAuth(AuthConfigBase):
    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        self.username = username
        self.password = password

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        encoded = b64encode(f"{self.username}:{self.password}".encode()).decode()
        request.headers["Authorization"] = f"Basic {encoded}"
        return request

    def secret_values(self) -> tuple[str, ...]:
        return (self.password,) if self.password else ()


class OAuth2TokenError(Exception):
    """Raised when the OAuth2 token endpoint rejects the credential exchange."""


class OAuth2Auth(AuthConfigBase):
    """OAuth2 ``client_credentials`` / ``refresh_token`` authenticator.

    Exchanges user-supplied credentials at a token endpoint for an access token
    at request time and injects it as a ``Bearer`` (or custom-prefixed) header,
    re-minting on expiry. The token is cached in-memory for the life of this auth
    object only — nothing is persisted, so rotating single-use refresh tokens are
    not supported (a fresh access token is obtained from the stable
    ``refresh_token`` / client credentials on each new sync).

    Modeled on :class:`~posthog.temporal.data_imports.sources.salesforce.auth.SalesforceAuth`,
    but generic over a user-provided ``token_url`` and client credentials. The
    token POST goes through ``make_tracked_session()`` so it is logged and the
    credentials are redacted; ``token_url`` itself is vetted for SSRF at manifest
    validation time, the same as every other URL in a custom-source manifest.
    """

    def __init__(
        self,
        token_url: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        grant_type: TOAuth2GrantType = "refresh_token",
        refresh_token: Optional[str] = None,
        scopes: Optional[list[str] | str] = None,
        access_token_name: str = "access_token",
        expires_in_name: str = "expires_in",
        header_prefix: str = "Bearer",
    ) -> None:
        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.grant_type = grant_type
        self.refresh_token = refresh_token
        # Normalize scopes to the space-delimited string the token endpoint expects.
        self.scopes = " ".join(scopes) if isinstance(scopes, list) else scopes
        self.access_token_name = access_token_name
        self.expires_in_name = expires_in_name
        self.header_prefix = header_prefix
        self._access_token: Optional[str] = None
        self._expires_at: Optional[datetime] = None

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        if self._access_token is None or self._is_expired():
            self._obtain_token()
        request.headers["Authorization"] = f"{self.header_prefix} {self._access_token}"
        return request

    def _is_expired(self) -> bool:
        if self._expires_at is None:
            return True
        return datetime.now(UTC) >= self._expires_at

    def _obtain_token(self) -> None:
        if not self.token_url:
            raise OAuth2TokenError("token_url is required to obtain an OAuth2 access token")

        body: dict[str, str] = {"grant_type": self.grant_type}
        if self.client_id:
            body["client_id"] = self.client_id
        if self.client_secret:
            body["client_secret"] = self.client_secret
        if self.grant_type == "refresh_token":
            if not self.refresh_token:
                raise OAuth2TokenError("refresh_token is required for the refresh_token grant")
            body["refresh_token"] = self.refresh_token
        if self.scopes:
            body["scope"] = self.scopes

        session = make_tracked_session(redact_values=self.secret_values())
        response = session.post(self.token_url, data=body, timeout=30)
        if response.status_code >= 400:
            raise OAuth2TokenError(
                f"Token endpoint {self.token_url} returned HTTP {response.status_code}: {response.text[:200]}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise OAuth2TokenError(f"Token endpoint {self.token_url} returned a non-JSON response") from exc

        token = payload.get(self.access_token_name)
        if not token:
            raise OAuth2TokenError(f"Token endpoint {self.token_url} response had no {self.access_token_name!r} field")
        self._access_token = token

        expires_in = payload.get(self.expires_in_name)
        try:
            # float() first so a string like "300.0" parses instead of falling
            # back to the 1-hour default and masking a genuinely short TTL.
            seconds = int(float(expires_in)) if expires_in is not None else _OAUTH2_DEFAULT_EXPIRES_IN
        except (TypeError, ValueError):
            seconds = _OAUTH2_DEFAULT_EXPIRES_IN
        # Re-mint slightly before expiry, but never let the safety margin push the
        # deadline into the past for a short-lived token — otherwise the token
        # reads as already-expired and re-mints on every paginated request.
        margin = min(_OAUTH2_EXPIRY_MARGIN, timedelta(seconds=seconds / 2))
        self._expires_at = datetime.now(UTC) + timedelta(seconds=seconds) - margin

    def secret_values(self) -> tuple[str, ...]:
        return tuple(value for value in (self.client_secret, self.refresh_token, self._access_token) if value)


def auth_secret_values(auth: Optional[AuthBase]) -> tuple[str, ...]:
    """Secret credential strings carried by an auth object, for log redaction.

    Delegates to :meth:`AuthConfigBase.secret_values` so the knowledge of which
    field is secret lives on each auth class. Returns ``()`` for ``None`` or any
    auth that isn't an :class:`AuthConfigBase`.
    """
    return auth.secret_values() if isinstance(auth, AuthConfigBase) else ()
