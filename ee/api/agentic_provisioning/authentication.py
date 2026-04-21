from __future__ import annotations

import hmac
import time
import uuid

from django.conf import settings
from django.utils import timezone

import structlog
import posthoganalytics
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request

from posthog.api.oauth.cimd import (
    CIMD_PROVISIONING_DEFAULTS,
    get_application_by_client_id,
    is_cimd_client_id,
    is_cimd_registration_in_progress,
    is_cimd_url_blocked,
    register_cimd_provisioning_application_task,
)
from posthog.exceptions_capture import capture_exception
from posthog.models.oauth import OAuthApplication, find_oauth_access_token

from .signature import _compute_hmac, _get_raw_body, _parse_signature_header

logger = structlog.get_logger(__name__)

BEARER_PREFIX = "Bearer "
STRIPE_SIGNATURE_HEADER = "HTTP_STRIPE_SIGNATURE"
MAX_TIMESTAMP_DRIFT_SECONDS = 300


class ProvisioningAuthentication(BaseAuthentication):
    """Authenticates provisioning requests from any registered partner.

    Partners are OAuthApplications with provisioning fields set (provisioning_auth_method
    is non-empty). The OAuthApplication handles standard OAuth (tokens, scopes, consent)
    and also stores provisioning config: auth method, signing secret, feature flags
    (provisioning_can_create_accounts, provisioning_can_provision_resources), and rate limits.

    Partners are identified from request signals (HMAC header, Bearer token, or
    client_id param) and dispatched to the matching auth strategy. Returns None
    if no partner is identified, allowing Stripe Projects HMAC auth to handle the request.
    """

    cimd_registration_pending: bool = False

    def authenticate(self, request: Request):
        app = self._identify_partner(request)
        if app is None:
            return None

        try:
            if app.provisioning_auth_method == "hmac":
                user = self._verify_hmac(request, app)
                _capture_auth_event(app, "success", endpoint=request.path)
                return (user, app)
            elif app.provisioning_auth_method == "bearer":
                user = self._verify_bearer(request, app)
                _capture_auth_event(app, "success", endpoint=request.path)
                return (user, app)
            elif app.provisioning_auth_method == "pkce":
                _capture_auth_event(app, "success", endpoint=request.path)
                return self._verify_pkce(request, app)
        except AuthenticationFailed:
            _capture_auth_event(app, "verification_failed", endpoint=request.path)
            raise

        return None

    def _identify_partner(self, request: Request) -> OAuthApplication | None:
        app = None

        # 1. Check for HMAC signature header -> look up by signing secret
        if request.META.get(STRIPE_SIGNATURE_HEADER):
            app = self._identify_hmac_partner(request)

        # 2. Check for Bearer token -> look up OAuthApplication
        if app is None:
            auth_header = request.META.get("HTTP_AUTHORIZATION", "")
            if auth_header.startswith(BEARER_PREFIX):
                app = self._identify_bearer_partner(auth_header)

        # 3. Check for client_id in request body (PKCE public clients)
        if app is None:
            client_id = request.data.get("client_id") or request.query_params.get("client_id")
            if client_id:
                app = self._identify_pkce_partner(client_id)

        if app is not None and not app.provisioning_active:
            return None

        return app

    def _identify_hmac_partner(self, request: Request) -> OAuthApplication | None:
        apps = OAuthApplication.objects.filter(
            provisioning_auth_method="hmac",
            provisioning_signing_secret__isnull=False,
            provisioning_active=True,
        )

        sig_header = request.META.get(STRIPE_SIGNATURE_HEADER, "")
        parsed = _parse_signature_header(sig_header)
        if parsed is None:
            return None

        timestamp_str, signature_hex = parsed
        body = _get_raw_body(request)
        if body is None:
            return None

        for app in apps:
            if not app.provisioning_signing_secret:
                continue
            expected = _compute_hmac(app.provisioning_signing_secret, timestamp_str, body)
            if hmac.compare_digest(expected.lower(), signature_hex.lower()):
                return app

        return None

    def _identify_bearer_partner(self, auth_header: str) -> OAuthApplication | None:
        token_value = auth_header[len(BEARER_PREFIX) :].strip()
        if not token_value:
            return None

        access_token = find_oauth_access_token(token_value)
        if access_token is None:
            return None

        if access_token.expires and access_token.expires < timezone.now():
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
                try:
                    if not app.is_provisioning_partner:
                        for field, value in CIMD_PROVISIONING_DEFAULTS.items():
                            setattr(app, field, value)
                        app.save(update_fields=list(CIMD_PROVISIONING_DEFAULTS.keys()))
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

            # New CIMD URL: kick off background registration, don't block the worker
            if not is_cimd_registration_in_progress(client_id):
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

    def _verify_hmac(self, request: Request, app: OAuthApplication):
        sig_header = request.META.get(STRIPE_SIGNATURE_HEADER, "")
        parsed = _parse_signature_header(sig_header)
        if parsed is None:
            raise AuthenticationFailed("Missing or malformed signature header")

        timestamp_str, signature_hex = parsed
        timestamp = int(timestamp_str)
        if abs(int(time.time()) - timestamp) > MAX_TIMESTAMP_DRIFT_SECONDS:
            raise AuthenticationFailed("Timestamp too old or too far in the future")

        body = _get_raw_body(request)
        if body is None:
            raise AuthenticationFailed("Unable to read request body for signature verification")

        expected = _compute_hmac(app.provisioning_signing_secret, timestamp_str, body)
        if not hmac.compare_digest(expected.lower(), signature_hex.lower()):
            raise AuthenticationFailed("Signature verification failed")

        return None

    def _verify_bearer(self, request: Request, app: OAuthApplication):
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith(BEARER_PREFIX):
            raise AuthenticationFailed("Missing bearer token")

        token_value = auth_header[len(BEARER_PREFIX) :].strip()
        if not token_value:
            raise AuthenticationFailed("Missing bearer token")

        access_token = find_oauth_access_token(token_value)
        if access_token is None:
            raise AuthenticationFailed("Invalid access token")

        if access_token.expires and access_token.expires < timezone.now():
            raise AuthenticationFailed("Access token expired")

        if access_token.application_id != app.id:
            raise AuthenticationFailed("Token not issued for this partner")

        return access_token.user

    def _verify_pkce(self, request: Request, app: OAuthApplication):
        return (None, app)


def _capture_auth_event(app: OAuthApplication, outcome: str, **extra: object) -> None:
    posthoganalytics.capture(
        "agentic_provisioning auth",
        distinct_id=f"agentic_provisioning_{uuid.uuid4().hex[:16]}",
        properties={
            "outcome": outcome,
            "partner_type": app.provisioning_partner_type,
            "auth_method": app.provisioning_auth_method,
            "app_id": str(app.id),
            **extra,
        },
    )


# --- Stripe Projects HMAC auth (kept for backward compatibility) ---


class StripeProvisioningBearerAuthentication(BaseAuthentication):
    def authenticate(self, request: Request):
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith(BEARER_PREFIX):
            return None

        token_value = auth_header[len(BEARER_PREFIX) :].strip()
        if not token_value:
            return None

        access_token = find_oauth_access_token(token_value)
        if access_token is None:
            raise AuthenticationFailed("Invalid access token")

        if access_token.expires and access_token.expires < timezone.now():
            raise AuthenticationFailed("Access token expired")

        if not _is_stripe_oauth_app(access_token.application):
            raise AuthenticationFailed("Token not issued for Stripe provisioning")

        return (access_token.user, access_token)


def _is_stripe_oauth_app(app) -> bool:
    if app is None:
        return False
    return app.client_id == settings.STRIPE_POSTHOG_OAUTH_CLIENT_ID
