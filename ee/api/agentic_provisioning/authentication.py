from __future__ import annotations

from typing import NoReturn

from django.contrib.auth.models import AnonymousUser
from django.utils import timezone

import structlog
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request

from posthog.api.oauth.cimd import (
    enqueue_cimd_refresh_if_stale,
    get_application_by_client_id,
    is_cimd_client_id,
    is_cimd_url_blocked,
)
from posthog.api.oauth.client_assertion import (
    ClientAssertionError,
    ResolvedClientAssertion,
    extract_client_assertion,
    verify_client_assertion,
)
from posthog.api.oauth.client_auth import ClientCredentials, extract_client_credentials, verify_client_secret
from posthog.models.oauth import OAuthAccessToken, OAuthApplication, find_oauth_access_token
from posthog.models.user import User

from ee.api.agentic_provisioning.analytics import capture_auth_event
from ee.api.agentic_provisioning.exceptions import ProvisioningError

logger = structlog.get_logger(__name__)

BEARER_PREFIX = "Bearer "

CLIENT_REGISTRATION_PATH = "/api/agentic/provisioning/client_registration"
# Every endpoint here requires an already-registered client, so the one actionable thing to
# tell a caller we don't recognize is where to register and get its setup diagnosed.
CLIENT_NOT_REGISTERED_MESSAGE = (
    f"No provisioning client is registered for this client_id. Register it at POST {CLIENT_REGISTRATION_PATH}"
)


class BearerTokenError(Exception):
    """The bearer header is missing, unknown, or expired; the message is the
    wire-safe reason each authenticator maps into its own failure type."""


def resolve_bearer_access_token(request: Request) -> OAuthAccessToken:
    """Parse the Authorization header and return the live access token it names.

    Shared by every bearer path in this module so token resolution (header
    parsing, lookup, expiry) can't drift between authenticators; policy checks
    (partner flags, app binding) stay with each caller.
    """
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith(BEARER_PREFIX):
        raise BearerTokenError("Missing bearer token")

    token_value = auth_header[len(BEARER_PREFIX) :].strip()
    if not token_value:
        raise BearerTokenError("Missing bearer token")

    access_token = find_oauth_access_token(token_value)
    if access_token is None:
        raise BearerTokenError("Invalid access token")

    if access_token.expires and access_token.expires < timezone.now():
        raise BearerTokenError("Access token expired")

    return access_token


class ProvisioningAuthentication(BaseAuthentication):
    """Authenticates provisioning requests from any registered partner.

    Partners are OAuthApplications with ``is_provisioning_partner`` set. The OAuthApplication
    handles standard OAuth (tokens, scopes, consent) and also stores provisioning config:
    capabilities and rate limits (see OAuthApplication.provisioning).

    How a partner proves itself follows from its registered ``token_endpoint_auth_method``
    (RFC 7591), not from what a given request happens to carry: ``private_key_jwt`` partners
    sign an assertion, ``client_secret_*`` partners present their secret, and ``none``
    partners are identified by a bare client_id and rely on PKCE. These endpoints act for the
    partner rather than for an end user, so no user is ever returned. Returns None if no
    partner is identified.
    """

    def authenticate(self, request: Request) -> tuple[None, OAuthApplication] | None:
        app = self._identify_partner(request)
        if app is None:
            return None

        capture_auth_event(app, "success", endpoint=request.path)
        return (None, app)

    def _identify_partner(self, request: Request) -> OAuthApplication | None:
        # 1. A signed assertion identifies and proves a private_key_jwt partner at once.
        assertion = extract_client_assertion(request)
        if assertion is not None:
            return self._identify_assertion_partner(request, assertion)

        # 2. So do client credentials, for a partner registered with a secret.
        credentials = extract_client_credentials(request)
        if credentials is not None:
            return self._identify_client_secret_partner(request, credentials)

        # 3. A bare client_id identifies a public client, which relies on PKCE.
        client_id = request.data.get("client_id") or request.query_params.get("client_id")
        if not client_id:
            return None

        app = self._identify_pkce_partner(client_id)
        if app is None:
            # The caller named a client, so tell it the client is unknown rather than
            # returning a bare "unauthorized" it cannot act on.
            raise AuthenticationFailed(CLIENT_NOT_REGISTERED_MESSAGE)

        # A confidential partner that presented no proof must not fall through to the public
        # path. Its client_id is published like any other, so honoring it here would let
        # anyone act as that partner simply by sending nothing else.
        if app.requires_client_authentication:
            self._reject(request, app, "This client must authenticate")

        return app

    def _reject(self, request: Request, app: OAuthApplication, reason: str) -> NoReturn:
        """Fail a partner that was identified but did not prove itself."""
        capture_auth_event(app, "verification_failed", endpoint=request.path)
        raise AuthenticationFailed(reason)

    def _identify_assertion_partner(
        self, request: Request, assertion: ResolvedClientAssertion
    ) -> OAuthApplication | None:
        app = self._resolve_partner(assertion.client_id)
        if app is None:
            raise AuthenticationFailed(CLIENT_NOT_REGISTERED_MESSAGE)
        if not app.uses_private_key_jwt_auth:
            self._reject(request, app, "This client does not authenticate with a client assertion")

        try:
            verify_client_assertion(app, assertion.client_assertion)
        except ClientAssertionError as exc:
            self._reject(request, app, str(exc))

        return app

    def _identify_client_secret_partner(
        self, request: Request, credentials: ClientCredentials
    ) -> OAuthApplication | None:
        app = self._resolve_partner(credentials.client_id)
        if app is None:
            return None
        if not app.uses_client_secret_auth:
            self._reject(request, app, "This client does not authenticate with a client secret")

        if not verify_client_secret(credentials.client_secret, app.client_secret or ""):
            self._reject(request, app, "Invalid client credentials")

        return app

    def _resolve_partner(self, client_id: str) -> OAuthApplication | None:
        """Look up an active provisioning partner by client_id.

        Unlike the PKCE path this never *registers* an unknown CIMD client: a caller that
        brought its own proof has to already exist for that proof to mean anything.
        """
        try:
            app = get_application_by_client_id(client_id)
        except OAuthApplication.DoesNotExist:
            return None

        if not app.is_provisioning_partner or not app.provisioning.active:
            return None

        if app.is_cimd_client:
            # A confidential CIMD partner reaches every provisioning endpoint through this
            # path, so without a refresh here its metadata document would never be re-read
            # again: scope ceiling and jwks_uri edits would freeze at whatever the app was
            # promoted with. Async, so this request still serves the app we already have.
            try:
                enqueue_cimd_refresh_if_stale(app.cimd_metadata_url or client_id)
            except Exception as e:
                logger.warning(
                    "provisioning_cimd_refresh_enqueue_error",
                    client_id=client_id,
                    error=str(e),
                    error_type=type(e).__name__,
                )

        return app

    def _identify_pkce_partner(self, client_id: str) -> OAuthApplication | None:
        """Resolve a public client from its client_id alone.

        Registering an unknown client is not this path's job. It used to be, by enqueueing a
        background CIMD fetch and answering "retry shortly", which meant a partner's first
        call always failed for a reason indistinguishable from a typo. Registration is now an
        explicit call to client_registration, so an unknown client_id simply does not resolve
        and the caller is pointed there.
        """
        if is_cimd_client_id(client_id) and is_cimd_url_blocked(client_id):
            return None
        return self._resolve_partner(client_id)


class ProvisioningBearerAuthentication(BaseAuthentication):
    """Authenticate a provisioning partner via an OAuth bearer token, for the
    resource and deep-link endpoints.

    Returns ``(user, access_token)`` so views read the token off ``request.auth``.
    Raises :class:`ProvisioningError` (rendered in the view's envelope) on failure.
    """

    def authenticate(self, request: Request) -> tuple[User | None, OAuthAccessToken]:
        try:
            access_token = resolve_bearer_access_token(request)
        except BearerTokenError as exc:
            raise ProvisioningError("unauthorized", str(exc), status=401)

        # The token must belong to an active provisioning partner's app. An app that was never
        # a partner, or has been un-flagged as one, must fail closed here rather than having
        # its outstanding access tokens still reach the resource and deep-link endpoints.
        app = access_token.application
        if app is None or not app.is_provisioning_partner:
            raise ProvisioningError("unauthorized", "Authentication failed", status=401)

        if not app.provisioning.active:
            raise ProvisioningError("unauthorized", "Partner is deactivated", status=401)
        if not app.provisioning.can_provision_resources:
            raise ProvisioningError("forbidden", "Resource provisioning not enabled for this partner", status=403)

        return access_token.user, access_token

    def authenticate_header(self, request: Request) -> str:
        return "Bearer"


def authenticate_confidential_partner(request: Request, *, capability: str) -> OAuthApplication:
    """Identify a provisioning partner, requiring proof-bearing auth and an explicitly granted
    capability.

    Only confidential partners carry proof that the caller controls the partner. Public
    partners are identified solely by a ``client_id`` anyone can send, so they never qualify
    for these endpoints — they exchange GitHub OAuth codes and read back GitHub account
    metadata, which must sit behind a real partner trust boundary.

    Authenticating is necessary but not sufficient. A CIMD client self-registers by publishing
    a metadata document, and one that declares ``private_key_jwt`` becomes a confidential
    client whose assertions it can sign with its own published key, so it would clear a
    confidential-only gate without any PostHog involvement. ``capability`` names the
    ``provisioning`` flag an admin has to grant on top, which self-registration never sets.

    Raises :class:`ProvisioningError` when no qualifying partner is identified.
    """
    auth = ProvisioningAuthentication()
    try:
        result = auth.authenticate(request)
    except AuthenticationFailed as exc:
        # Keep the reason: "this client must authenticate" and "this client is not registered"
        # call for different fixes, and a flat 401 tells the partner neither.
        raise ProvisioningError("unauthorized", str(exc.detail), status=401)
    partner = result[1] if result else None
    if partner is None:
        raise ProvisioningError("unauthorized", CLIENT_NOT_REGISTERED_MESSAGE, status=401)
    if not partner.requires_client_authentication:
        raise ProvisioningError("forbidden", "This endpoint requires a confidential partner", status=403)
    if not getattr(partner.provisioning, capability):
        raise ProvisioningError("forbidden", "This endpoint is not enabled for this partner", status=403)
    return partner


class ConfidentialPartnerAuthentication(BaseAuthentication):
    """DRF form of :func:`authenticate_confidential_partner`, so confidential
    endpoints declare it in ``authentication_classes`` and can't ship without
    it. The partner rides ``request.auth``; these endpoints act for the partner,
    not an end user, so the user stays anonymous.

    Subclassed per capability rather than parameterized, because DRF instantiates
    authentication classes with no arguments."""

    capability: str

    def authenticate(self, request: Request) -> tuple[AnonymousUser, OAuthApplication]:
        return AnonymousUser(), authenticate_confidential_partner(request, capability=self.capability)

    def authenticate_header(self, request: Request) -> str:
        return "Basic"


class GitHubGrantsAuthentication(ConfidentialPartnerAuthentication):
    capability = "can_use_github_grants"
