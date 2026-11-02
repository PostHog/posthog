from __future__ import annotations

from enum import StrEnum
from typing import NoReturn

from django.utils import timezone

import structlog
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request

from posthog.api.oauth.cimd import enqueue_cimd_refresh_if_stale
from posthog.api.oauth.client_assertion import (
    PRIVATE_KEY_REQUIRED_MESSAGE,
    UNREADABLE_CLIENT_ASSERTION_MESSAGE,
    ClientAssertionError,
    ResolvedClientAssertion,
    extract_client_assertion,
    presents_client_assertion,
    verify_client_assertion,
)
from posthog.api.oauth.client_auth import ClientCredentials, extract_client_credentials, verify_client_secret
from posthog.auth import ACCOUNT_BLOCKED_DETAIL, account_refused
from posthog.models.activity_logging.utils import ActivityCredentialMixin
from posthog.models.oauth import OAuthAccessToken, OAuthApplication, ProvisioningSigning, find_oauth_access_token
from posthog.models.user import User

from products.security.backend.facade.api import REFUSAL_CODE as SECURITY_REFUSAL_CODE

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


class ClientProof(StrEnum):
    ASSERTION = "assertion"
    CLIENT_SECRET = "client_secret"
    CLIENT_ID = "client_id"


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


class ProvisioningAuthentication(ActivityCredentialMixin, BaseAuthentication):
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

    activity_credential_type = "partner"

    def __init__(self) -> None:
        super().__init__()
        self.client_proof: ClientProof | None = None

    def authenticate(self, request: Request) -> tuple[None, OAuthApplication] | None:
        identified = self._identify_partner(request)
        if identified is None:
            return None
        app, proof = identified

        signing = app.provisioning_signing
        signed = proof is ClientProof.ASSERTION
        if not signed and signing is ProvisioningSigning.REQUIRED:
            self._reject(
                request,
                app,
                PRIVATE_KEY_REQUIRED_MESSAGE,
                outcome="private_key_required",
                provisioning_signing=signing.request_tag(signed=False),
            )

        self.client_proof = proof
        capture_auth_event(
            app, "success", endpoint=request.path, provisioning_signing=signing.request_tag(signed=signed)
        )
        # A client_id alone is something anyone can send, so only a partner that proved itself with a
        # secret or a signed assertion is recorded by id.
        self.record_activity_actor(None, str(app.id) if proof is not ClientProof.CLIENT_ID else None)
        return (None, app)

    def _identify_partner(self, request: Request) -> tuple[OAuthApplication, ClientProof] | None:
        # 1. A signed assertion identifies and proves a private_key_jwt partner at once.
        assertion = extract_client_assertion(request)
        if assertion is not None:
            return self._identify_assertion_partner(request, assertion), ClientProof.ASSERTION

        # 2. So do client credentials, for a partner registered with a secret.
        credentials = extract_client_credentials(request)
        if credentials is not None:
            secret_partner = self._identify_client_secret_partner(request, credentials)
            return None if secret_partner is None else (secret_partner, ClientProof.CLIENT_SECRET)

        # An assertion that does not resolve must fail here, or the bare client_id below would accept it unverified.
        if presents_client_assertion(request):
            raise AuthenticationFailed(UNREADABLE_CLIENT_ASSERTION_MESSAGE)

        # 3. A bare client_id identifies a public client, which relies on PKCE.
        client_id = request.data.get("client_id") or request.query_params.get("client_id")
        if not client_id:
            return None

        app = self._identify_pkce_partner(client_id)
        if app is None:
            # The caller named a client, so tell it the client is unknown rather than
            # returning a bare "unauthorized" it cannot act on.
            raise AuthenticationFailed(CLIENT_NOT_REGISTERED_MESSAGE)

        # A client_id proves nothing. A key-based partner that must sign goes on to the signing check, which refuses it.
        if app.requires_client_authentication and not (
            app.uses_private_key_jwt_auth and app.provisioning_signing is not ProvisioningSigning.NOT_REQUIRED
        ):
            self._reject(request, app, "This client must authenticate")

        return app, ClientProof.CLIENT_ID

    def _reject(
        self,
        request: Request,
        app: OAuthApplication,
        reason: str,
        *,
        outcome: str = "verification_failed",
        **extra: object,
    ) -> NoReturn:
        """Fail a partner that was identified but did not prove itself."""
        capture_auth_event(app, outcome, endpoint=request.path, **extra)
        raise AuthenticationFailed(reason)

    def _identify_assertion_partner(self, request: Request, assertion: ResolvedClientAssertion) -> OAuthApplication:
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
            app = OAuthApplication.objects.get(client_id=client_id)
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
                enqueue_cimd_refresh_if_stale(app.client_id)
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
        return self._resolve_partner(client_id)


class ProvisioningBearerAuthentication(ActivityCredentialMixin, BaseAuthentication):
    """Authenticate a provisioning partner via an OAuth bearer token, for the
    resource and deep-link endpoints.

    Returns ``(user, access_token)`` so views read the token off ``request.auth``.
    Raises :class:`ProvisioningError` (rendered in the view's envelope) on failure.
    """

    activity_credential_type = "oauth"

    def authenticate(self, request: Request) -> tuple[User, OAuthAccessToken]:
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
        if app.cannot_meet_provisioning_signature:
            raise ProvisioningError("unauthorized", PRIVATE_KEY_REQUIRED_MESSAGE, status=401)
        if not app.provisioning.can_provision_resources:
            raise ProvisioningError("forbidden", "Resource provisioning not enabled for this partner", status=403)

        # Deactivating a user drops their login sessions but leaves OAuth tokens intact, so the
        # token has to fail closed here the way `posthog.auth._validate_token` does for the main
        # API. A token with no user cannot identify a caller at all, and the views downstream
        # read `request.user` as a User, so it fails closed too.
        user = access_token.user
        if user is None or not user.is_active:
            raise ProvisioningError("unauthorized", "Authentication failed", status=401)
        if account_refused(
            request,
            user,
            call_site="agentic_provisioning_token",
            impersonated=access_token.impersonated_by_id is not None,
        ):
            raise ProvisioningError(SECURITY_REFUSAL_CODE, ACCOUNT_BLOCKED_DETAIL, status=403)

        self.record_activity_actor(
            user, str(access_token.application_id), impersonated_by_id=access_token.impersonated_by_id
        )
        return user, access_token

    def authenticate_header(self, request: Request) -> str:
        return "Bearer"
