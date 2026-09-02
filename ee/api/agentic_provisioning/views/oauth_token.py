"""POST /oauth/token — exchange auth codes or refresh tokens for access tokens.

Follows RFC 6749's flat ``{"error", "error_description"}`` error shape, except
for partner rate limits, which keep the typed envelope (their historical wire
shape on this endpoint).
"""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import constant_time_compare

import structlog
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.oauth.client_assertion import ClientAssertionError, extract_client_assertion, verify_client_assertion
from posthog.api.oauth.client_auth import extract_client_credentials, verify_client_secret
from posthog.models.oauth import OAuthAccessToken, OAuthApplication, OAuthRefreshToken
from posthog.models.user import User
from posthog.models.utils import generate_random_oauth_access_token, generate_random_oauth_refresh_token
from posthog.scopes import narrow_scopes_to_ceiling, scopes_within_ceiling

from ee.api.agentic_provisioning.analytics import capture_provisioning_event
from ee.api.agentic_provisioning.constants import (
    ACCESS_TOKEN_EXPIRY_SECONDS,
    AUTH_CODE_CACHE_PREFIX,
    PARTNER_TOKEN_EXPIRY_SECONDS,
)
from ee.api.agentic_provisioning.exceptions import ProvisioningError
from ee.api.agentic_provisioning.ratelimits import Budget, rate_limited
from ee.api.agentic_provisioning.tokens import (
    compute_partner_scoped_teams,
    get_available_teams_for_user,
    lock_application,
)
from ee.api.agentic_provisioning.views.base import ProvisioningAPIView

logger = structlog.get_logger(__name__)


def _require_client_authentication(request: Request, oauth_app: OAuthApplication, grant_type: str) -> None:
    """Make confidential partners prove themselves before their grant is spent.

    Public partners keep ``code_verifier`` as their only client authentication, which is what
    RFC 7636 prescribes and RFC 6749 section 3.2.1 expects. The app is resolved from the grant
    rather than from a caller-supplied client_id, so a confidential partner cannot reach the
    public path by presenting nothing.
    """
    if not oauth_app.requires_client_authentication:
        return

    if oauth_app.uses_private_key_jwt_auth:
        _verify_assertion_or_fail(request, oauth_app, grant_type)
        return

    credentials = extract_client_credentials(request)
    if credentials is None:
        capture_provisioning_event(
            "token_exchange", "missing_client_credentials", partner=oauth_app, grant_type=grant_type
        )
        raise ProvisioningError("invalid_client", "client_id and client_secret are required", status=401)

    if not constant_time_compare(credentials.client_id, oauth_app.client_id) or not verify_client_secret(
        credentials.client_secret, oauth_app.client_secret or ""
    ):
        capture_provisioning_event(
            "token_exchange", "invalid_client_credentials", partner=oauth_app, grant_type=grant_type
        )
        raise ProvisioningError("invalid_client", "Invalid client credentials", status=401)


def _verify_assertion_or_fail(request: Request, oauth_app: OAuthApplication, grant_type: str) -> None:
    assertion = extract_client_assertion(request)
    if assertion is None:
        capture_provisioning_event(
            "token_exchange", "missing_client_assertion", partner=oauth_app, grant_type=grant_type
        )
        raise ProvisioningError("invalid_client", "A client_assertion is required", status=401)

    # The assertion is verified against the app the grant names, so an assertion validly
    # signed by a different client cannot be used to redeem this one's grant.
    if not constant_time_compare(assertion.client_id, oauth_app.client_id):
        capture_provisioning_event(
            "token_exchange", "client_assertion_mismatch", partner=oauth_app, grant_type=grant_type
        )
        raise ProvisioningError("invalid_client", "Client assertion does not match this grant", status=401)

    try:
        verify_client_assertion(oauth_app, assertion.client_assertion)
    except ClientAssertionError as exc:
        capture_provisioning_event(
            "token_exchange", "invalid_client_assertion", partner=oauth_app, grant_type=grant_type
        )
        raise ProvisioningError("invalid_client", str(exc), status=401)


class OAuthTokenView(ProvisioningAPIView):
    error_envelope = "oauth"
    region_proxy_strategy = "token_lookup"
    # The partner is resolved from the grant being redeemed, not from the request, so
    # authentication happens in _require_client_authentication once the grant is known.
    authenticates_in_handler = True

    # Two buckets, charged manually once the grant names the partner. Refreshes are
    # split from new authorizations because partner tokens live one hour: charging
    # rotations to the exchange budget capped a partner's live end users at roughly
    # that budget. Both keep the typed envelope, their historical wire shape here.
    @rate_limited("token_exchanges", budget=Budget(burst=10, per_hour=20), charge="manual", envelope="typed")
    @rate_limited("token_refreshes", charge="manual", envelope="typed")
    def post(self, request: Request) -> Response:
        grant_type = request.data.get("grant_type", "")

        if grant_type == "authorization_code":
            return self._exchange_authorization_code(request)
        elif grant_type == "refresh_token":
            return self._exchange_refresh_token(request)

        capture_provisioning_event("token_exchange", "unsupported_grant_type", grant_type=grant_type)
        raise ProvisioningError("unsupported_grant_type", f"Unsupported grant_type: {grant_type}")

    def _exchange_authorization_code(self, request: Request) -> Response:
        code = request.data.get("code", "")
        if not code:
            capture_provisioning_event("token_exchange", "missing_code", grant_type="authorization_code")
            raise ProvisioningError("invalid_request", "code is required")

        cache_key = f"{AUTH_CODE_CACHE_PREFIX}{code}"
        code_data = cache.get(cache_key)
        if code_data is None:
            capture_provisioning_event("token_exchange", "invalid_code", grant_type="authorization_code")
            raise ProvisioningError("invalid_grant", "Invalid or expired authorization code")

        # Auth check: every code requires PKCE verification. All verification happens
        # BEFORE cache.delete so a failed attempt doesn't consume the code.
        stored_challenge = code_data.get("code_challenge", "")
        if not stored_challenge:
            capture_provisioning_event("token_exchange", "missing_code_challenge", grant_type="authorization_code")
            raise ProvisioningError("invalid_request", "Authentication required", status=401)

        code_verifier = request.data.get("code_verifier", "")
        if not code_verifier:
            capture_provisioning_event("token_exchange", "missing_code_verifier", grant_type="authorization_code")
            raise ProvisioningError("invalid_request", "code_verifier is required for PKCE", status=401)
        computed = (
            base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest())
            .rstrip(b"=")
            .decode("ascii")
        )
        if computed != stored_challenge:
            capture_provisioning_event("token_exchange", "pkce_mismatch", grant_type="authorization_code")
            raise ProvisioningError("invalid_grant", "PKCE code_verifier does not match")

        # Resolved before the code is consumed because a confidential partner's client
        # authentication is checked against this app, and that check has to be able to fail
        # without spending the code. An unknown partner_id therefore leaves the code in the
        # cache to expire on its own; it is unusable either way.
        oauth_app: OAuthApplication | None = None
        partner_id = code_data.get("partner_id", "")
        if partner_id:
            try:
                oauth_app = OAuthApplication.objects.get(id=partner_id)
            except (OAuthApplication.DoesNotExist, ValidationError, ValueError):
                logger.warning("token_exchange_app_missing", partner_id=partner_id)
        if oauth_app is None:
            capture_provisioning_event("token_exchange", "oauth_app_missing", grant_type="authorization_code")
            raise ProvisioningError("invalid_grant", "Unknown application for this authorization code")

        _require_client_authentication(request, oauth_app, "authorization_code")

        # Consume the code before rate limiting so a leaked auth code can't be replayed
        # to burn the partner's bucket. Auth codes are single-use by spec, so the
        # tradeoff (rate-limited client loses the code) is acceptable — clients can
        # re-initiate the OAuth flow if rate-limited.
        cache.delete(cache_key)

        self.charge_rate_limit(request, oauth_app, endpoint="token_exchanges")

        user_id = code_data["user_id"]
        team_id = code_data["team_id"]
        scopes = code_data.get("scopes", [])

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            capture_provisioning_event("token_exchange", "user_not_found", grant_type="authorization_code")
            raise ProvisioningError("invalid_grant", "User not found")

        # Lock the app row before reading the revoke stamp and minting, so this serializes
        # with revoke_application_sessions (see lock_application). Provisioning auth codes
        # live in the cache, not OAuthGrant, so the revoke's sweep can't reach them — the
        # `issued_at` carried on the code is what a revoke is checked against. Codes minted
        # before `issued_at` shipped lack the field; fail closed (they expire in
        # AUTH_CODE_TTL_SECONDS and the client can re-run the flow).
        with transaction.atomic():
            locked_app = lock_application(oauth_app.pk)
            sessions_revoked_at = locked_app.sessions_revoked_at if locked_app else None
            if sessions_revoked_at is not None:
                issued_at_raw = code_data.get("issued_at")
                issued_at = datetime.fromisoformat(issued_at_raw) if issued_at_raw else None
                if issued_at is None or issued_at < sessions_revoked_at:
                    capture_provisioning_event("token_exchange", "sessions_revoked", grant_type="authorization_code")
                    raise ProvisioningError("invalid_grant", "Application sessions were revoked; re-authorize.")

            # Direct-mint bypasses /authorize's OAuthValidator, so the per-app scope
            # ceiling has to be enforced here before the token is created by hand.
            app_scopes = locked_app.ceiling_scopes if locked_app else []
            # Codes are minted with their scopes already resolved (account_requests
            # defaults an omitted list to the app ceiling before consent), so an empty
            # list means a stale or hand-crafted code. Defaulting at exchange time would
            # grant scopes the consent screen never displayed.
            if not scopes:
                capture_provisioning_event("token_exchange", "empty_scopes", grant_type="authorization_code")
                raise ProvisioningError("invalid_scope", "Authorization code carries no scopes; re-authorize.")
            requested_scopes = scopes
            if not scopes_within_ceiling(requested_scopes, app_scopes):
                capture_provisioning_event("token_exchange", "scope_ceiling_exceeded", grant_type="authorization_code")
                raise ProvisioningError("invalid_scope", "Requested scopes exceed the application's allowed scopes")
            scope_str = " ".join(requested_scopes)

            token_expiry = (
                PARTNER_TOKEN_EXPIRY_SECONDS
                if oauth_app and oauth_app.is_provisioning_partner
                else ACCESS_TOKEN_EXPIRY_SECONDS
            )

            scoped_teams = compute_partner_scoped_teams(oauth_app, user, team_id)
            # A partner token carries its restriction in scoped_teams alone, and the standard
            # OAuth permission check treats an empty scoped_teams as unrestricted (permissions.py).
            # compute_partner_scoped_teams returns [] exactly when the base team is gone or the
            # user lost access, so minting here would hand out a project-unrestricted bearer.
            # Fail closed and force re-authorization.
            if not scoped_teams:
                capture_provisioning_event("token_exchange", "no_accessible_teams", grant_type="authorization_code")
                raise ProvisioningError("invalid_grant", "No accessible teams for this authorization; re-authorize.")

            access_token_value = generate_random_oauth_access_token(None)
            access_token = OAuthAccessToken.objects.create(
                application=oauth_app,
                token=access_token_value,
                user=user,
                expires=timezone.now() + timedelta(seconds=token_expiry),
                scope=scope_str,
                scoped_teams=scoped_teams,
            )

            refresh_token_value = generate_random_oauth_refresh_token(None)
            OAuthRefreshToken.objects.create(
                application=oauth_app,
                token=refresh_token_value,
                user=user,
                access_token=access_token,
                scoped_teams=scoped_teams,
            )

        account_id = str(code_data.get("org_id", ""))

        available_teams = get_available_teams_for_user(user)

        capture_provisioning_event(
            "token_exchange",
            "success",
            partner=oauth_app,
            grant_type="authorization_code",
            team_id=team_id,
            user_id=user.id,
            granted_team_count=len(scoped_teams),
        )

        return Response(
            {
                "token_type": "bearer",
                "access_token": access_token_value,
                "refresh_token": refresh_token_value,
                "expires_in": token_expiry,
                "account": {
                    "id": account_id,
                    "payment_credentials": "orchestrator",
                    "available_teams": available_teams,
                },
            }
        )

    def _exchange_refresh_token(self, request: Request) -> Response:
        refresh_token_value = request.data.get("refresh_token", "")
        if not refresh_token_value:
            capture_provisioning_event("token_exchange", "missing_refresh_token", grant_type="refresh_token")
            raise ProvisioningError("invalid_request", "refresh_token is required")

        # Authenticate the client before opening the transaction. Verification is expensive
        # (a password-hash comparison, or a JWKS fetch on a cache miss), so doing it here
        # keeps that work out of the row lock taken below, where it would serialize every
        # concurrent refresh for the partner. Resolving the app unlocked is safe because only
        # its registration state is read, which the lock does not protect anyway.
        application_id = (
            OAuthRefreshToken.objects.filter(token=refresh_token_value, revoked__isnull=True)
            .values_list("application_id", flat=True)
            .first()
        )
        if application_id:
            unlocked_app = OAuthApplication.objects.filter(id=application_id).first()
            if unlocked_app is not None:
                _require_client_authentication(request, unlocked_app, "refresh_token")

        # Lock the app row first (revoke_application_sessions locks it before sweeping tokens),
        # then re-read the refresh token under that lock, so the rotate-and-mint serializes with
        # the revoke: either we hold the lock and our new tokens land before its sweep, or it
        # committed first and we see the token already revoked (or the stamp) and reject. Looking
        # the app up by id first (without locking the token row) keeps the lock order app→token,
        # matching the revoke, so the two can't deadlock.
        with transaction.atomic():
            locked_app = lock_application(application_id) if application_id else None
            old_refresh = (
                OAuthRefreshToken.objects.select_related("user", "access_token")
                .filter(token=refresh_token_value, revoked__isnull=True)
                .first()
            )
            if old_refresh is None:
                capture_provisioning_event("token_exchange", "invalid_refresh_token", grant_type="refresh_token")
                raise ProvisioningError("invalid_grant", "Invalid or revoked refresh token")

            oauth_app = locked_app
            user = old_refresh.user
            old_scoped_teams = old_refresh.scoped_teams or []

            # base_team_id at refresh: the first team in the prior scope. The consent team
            # (authorized at grant time) has the lowest id and sorts first at issuance;
            # partner-provisioned teams are always created later, so they take higher ids
            # and are only ever appended after it. [0] is therefore the consent team. This
            # ordering is load-bearing: compute_partner_scoped_teams re-adds the consent
            # team only when it is base_team_id (it has no TeamProvisioningConfig for this
            # app), so a lower-id provisioned team becoming [0] would silently drop the
            # consent team from the refreshed scope. If the prior token was somehow empty-
            # scoped, fall back to zero so the helper short-circuits without claiming a team.
            base_team_id = old_scoped_teams[0] if old_scoped_teams else 0
            scoped_teams = compute_partner_scoped_teams(oauth_app, user, base_team_id)

            # Same fail-closed rule as issuance: an empty scoped_teams is unrestricted under the
            # standard permission check, so a refresh whose base team vanished or whose access was
            # revoked must re-authorize rather than rotate into a project-unrestricted token.
            # Checked before any token row is mutated so a rejected refresh never revokes the
            # caller's only token.
            if not scoped_teams:
                capture_provisioning_event("token_exchange", "no_accessible_teams", grant_type="refresh_token")
                raise ProvisioningError("invalid_grant", "No accessible teams for this token; re-authorize.")

            # A rotated-away access token leaves no scope to carry over; the refreshed
            # token gets an empty scope rather than inheriting anything implicit.
            old_scope = old_refresh.access_token.scope if old_refresh.access_token else ""

            sessions_revoked_at = locked_app.sessions_revoked_at if locked_app else None
            if sessions_revoked_at is not None and old_refresh.created < sessions_revoked_at:
                capture_provisioning_event("token_exchange", "sessions_revoked", grant_type="refresh_token")
                raise ProvisioningError("invalid_grant", "Application sessions were revoked; re-authorize.")

            # Cap the refreshed scope at the app's current ceiling before touching any
            # token rows — a since-tightened ceiling must drop the removed scopes, and a
            # token now fully outside the ceiling has to re-authorize rather than refresh.
            # Done up front so a rejected refresh never revokes the caller's only token.
            app_scopes = oauth_app.ceiling_scopes if oauth_app else []
            narrowed_scopes = narrow_scopes_to_ceiling(old_scope.split(), app_scopes)
            if narrowed_scopes is None:
                capture_provisioning_event("token_exchange", "scope_ceiling_exceeded", grant_type="refresh_token")
                raise ProvisioningError(
                    "invalid_grant",
                    "Token scopes are no longer within the application's allowed scopes; re-authorize.",
                )
            new_scope = " ".join(narrowed_scopes)

            # Not is_provisioning_partner: an admin clearing that flag to disable a partner
            # leaves its outstanding refresh tokens working, and they must stay throttled.
            if oauth_app and oauth_app.carries_provisioning_config:
                self.charge_rate_limit(request, oauth_app, endpoint="token_refreshes")

            old_access = old_refresh.access_token
            old_refresh.access_token = None
            old_refresh.revoked = timezone.now()
            old_refresh.save(update_fields=["access_token", "revoked"])

            if old_access:
                old_access.delete()

            token_expiry = (
                PARTNER_TOKEN_EXPIRY_SECONDS
                if oauth_app and oauth_app.is_provisioning_partner
                else ACCESS_TOKEN_EXPIRY_SECONDS
            )

            new_access_value = generate_random_oauth_access_token(None)
            new_access = OAuthAccessToken.objects.create(
                application=oauth_app,
                token=new_access_value,
                user=user,
                expires=timezone.now() + timedelta(seconds=token_expiry),
                scope=new_scope,
                scoped_teams=scoped_teams,
            )

            new_refresh_value = generate_random_oauth_refresh_token(None)
            OAuthRefreshToken.objects.create(
                application=oauth_app,
                token=new_refresh_value,
                user=user,
                access_token=new_access,
                scoped_teams=scoped_teams,
            )

        capture_provisioning_event(
            "token_exchange",
            "success",
            partner=oauth_app,
            grant_type="refresh_token",
            team_id=base_team_id,
            user_id=user.id if user else None,
            granted_team_count=len(scoped_teams),
        )

        return Response(
            {
                "token_type": "bearer",
                "access_token": new_access_value,
                "refresh_token": new_refresh_value,
                "expires_in": token_expiry,
            }
        )
