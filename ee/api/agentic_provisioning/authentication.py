from __future__ import annotations

import hashlib

from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.utils import timezone

import structlog
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request

from posthog.api.oauth.cimd import (
    apply_provisioning_defaults,
    enqueue_cimd_refresh_if_stale,
    get_application_by_client_id,
    is_cimd_client_id,
    is_cimd_registration_in_progress,
    is_cimd_url_blocked,
    register_cimd_provisioning_application_task,
)
from posthog.exceptions_capture import capture_exception
from posthog.models.oauth import OAuthAccessToken, OAuthApplication, find_oauth_access_token
from posthog.models.user import User

from ee.api.agentic_provisioning.analytics import capture_auth_event
from ee.api.agentic_provisioning.exceptions import ProvisioningError

logger = structlog.get_logger(__name__)

BEARER_PREFIX = "Bearer "


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

    Partners are OAuthApplications with provisioning fields set (provisioning_auth_method
    is non-empty). The OAuthApplication handles standard OAuth (tokens, scopes, consent)
    and also stores provisioning config: auth method, feature flags
    (provisioning_can_create_accounts, provisioning_can_provision_resources), and rate limits.

    Partners are identified from request signals (Bearer token or client_id param)
    and dispatched to the matching auth strategy. Returns None if no partner is
    identified.
    """

    cimd_registration_pending: bool = False

    def authenticate(self, request: Request):
        app = self._identify_partner(request)
        if app is None:
            return None

        try:
            if app.provisioning_auth_method == "bearer":
                user = self._verify_bearer(request, app)
                capture_auth_event(app, "success", endpoint=request.path)
                return (user, app)
            elif app.provisioning_auth_method == "pkce":
                capture_auth_event(app, "success", endpoint=request.path)
                return self._verify_pkce(request, app)
        except AuthenticationFailed:
            capture_auth_event(app, "verification_failed", endpoint=request.path)
            raise

        return None

    def _identify_partner(self, request: Request) -> OAuthApplication | None:
        app = None

        # 1. Check for Bearer token -> look up OAuthApplication
        if request.headers.get("authorization", "").startswith(BEARER_PREFIX):
            app = self._identify_bearer_partner(request)

        # 2. Check for client_id in request body (PKCE public clients)
        if app is None:
            client_id = request.data.get("client_id") or request.query_params.get("client_id")
            if client_id:
                app = self._identify_pkce_partner(client_id)

        if app is not None and not app.provisioning_active:
            return None

        return app

    def _identify_bearer_partner(self, request: Request) -> OAuthApplication | None:
        try:
            access_token = resolve_bearer_access_token(request)
        except BearerTokenError:
            return None

        app = access_token.application
        if app is None or not app.is_provisioning_partner:
            return None

        return app if app.provisioning_active else None

    def _identify_pkce_partner(self, client_id: str) -> OAuthApplication | None:
        if is_cimd_client_id(client_id):
            if is_cimd_url_blocked(client_id):
                return None

            app = OAuthApplication.objects.filter(cimd_metadata_url=client_id).first()
            if app is not None:
                # The raw lookup above bypasses get_or_create_cimd_application, so the
                # CIMD document's TTL-based refresh never fires on this path. Enqueue it
                # here so edits to live metadata (scope ceiling, redirect_uris, config)
                # propagate instead of freezing at first registration. Refresh stays
                # async; this request still serves the existing app.
                try:
                    enqueue_cimd_refresh_if_stale(client_id)
                except Exception as e:
                    logger.warning(
                        "provisioning_cimd_refresh_enqueue_error",
                        client_id=client_id,
                        error=str(e),
                        error_type=type(e).__name__,
                    )

                try:
                    if not app.is_provisioning_partner:
                        apply_provisioning_defaults(app)
                except Exception as e:
                    logger.warning(
                        "provisioning_cimd_backfill_error",
                        client_id=client_id,
                        error=str(e),
                        error_type=type(e).__name__,
                    )
                    capture_exception(e)
                    try:
                        app.refresh_from_db()
                    except Exception:
                        return None
                return app if app.provisioning_active else None

            # New CIMD URL: kick off background registration, don't block the worker.
            # cache.add is atomic - coalesces concurrent first-time requests so only
            # one gets to enqueue until the worker's own fetch lock takes over.
            if not is_cimd_registration_in_progress(client_id):
                enqueue_key = f"cimd:enqueued:{hashlib.sha256(client_id.encode()).hexdigest()}"
                if cache.add(enqueue_key, True, timeout=30):
                    register_cimd_provisioning_application_task.delay(client_id)
            self.cimd_registration_pending = True
            return None

        try:
            app = get_application_by_client_id(client_id)
            if not app.is_provisioning_partner or not app.provisioning_active:
                return None
            return app
        except OAuthApplication.DoesNotExist:
            return None

    def _verify_bearer(self, request: Request, app: OAuthApplication):
        try:
            access_token = resolve_bearer_access_token(request)
        except BearerTokenError as exc:
            raise AuthenticationFailed(str(exc))

        if access_token.application_id != app.id:
            raise AuthenticationFailed("Token not issued for this partner")

        return access_token.user

    def _verify_pkce(self, request: Request, app: OAuthApplication):
        return (None, app)


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

        # The token must belong to an active provisioning partner's app.
        app = access_token.application
        if app is None or not app.is_provisioning_partner:
            raise ProvisioningError("unauthorized", "Authentication failed", status=401)

        # Only bearer/pkce partners are supported. An app configured with any other
        # auth method (e.g. a leftover hmac partner row) must fail closed here, or its
        # outstanding bearer tokens could still reach the resource and deep-link
        # endpoints without the second factor that method implied.
        if app.provisioning_auth_method not in ("bearer", "pkce"):
            raise ProvisioningError("unauthorized", "Authentication failed", status=401)
        if not app.provisioning_active:
            raise ProvisioningError("unauthorized", "Partner is deactivated", status=401)
        if not app.provisioning_can_provision_resources:
            raise ProvisioningError("forbidden", "Resource provisioning not enabled for this partner", status=403)

        return access_token.user, access_token

    def authenticate_header(self, request: Request) -> str:
        return "Bearer"


def authenticate_confidential_partner(request: Request) -> OAuthApplication:
    """Identify a provisioning partner, requiring proof-bearing auth.

    Only Bearer partners carry proof that the caller controls the partner.
    PKCE partners are identified solely by a public ``client_id`` anyone can send, so
    they never qualify for these endpoints — they exchange GitHub OAuth codes and read
    back GitHub account metadata, which must sit behind a real partner trust boundary.

    Raises :class:`ProvisioningError` when no qualifying partner is identified.
    """
    auth = ProvisioningAuthentication()
    try:
        result = auth.authenticate(request)
    except AuthenticationFailed:
        result = None
    partner = result[1] if result else None
    if partner is None:
        raise ProvisioningError("unauthorized", "Authentication required", status=401)
    if partner.provisioning_auth_method != "bearer":
        raise ProvisioningError("forbidden", "This endpoint requires a confidential partner", status=403)
    return partner


class ConfidentialPartnerAuthentication(BaseAuthentication):
    """DRF form of :func:`authenticate_confidential_partner`, so confidential
    endpoints declare it in ``authentication_classes`` and can't ship without
    it. The partner rides ``request.auth``; these endpoints act for the partner,
    not an end user, so the user stays anonymous."""

    def authenticate(self, request: Request) -> tuple[AnonymousUser, OAuthApplication]:
        return AnonymousUser(), authenticate_confidential_partner(request)

    def authenticate_header(self, request: Request) -> str:
        return "Bearer"
