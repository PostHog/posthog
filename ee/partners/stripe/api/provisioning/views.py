"""Stripe Projects provisioning endpoints (APP 0.1d provider surface).

Mounted under ``/api/partners/stripe/``. Stripe is the only accepted caller:
every request is authenticated with the global ``Stripe-Signature`` HMAC, and
resource endpoints additionally require a bearer token issued to the Stripe
Projects OAuth app (the token endpoint accepts PKCE in place of the HMAC).

Check order is part of the observable wire behavior (which error a request
with several problems gets). Endpoints whose checks are uniform - signature
then API-Version before the handler - inherit them from
:class:`SignatureCheckedMixin` so a new endpoint cannot ship without them.
``account_requests`` and ``oauth/token`` interleave their checks with body
parsing (body errors before the signature requirement; PKCE accepted in place
of the HMAC), so those two run every check explicitly in the handler.
"""

from __future__ import annotations

import re
import base64
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Any, ClassVar, cast

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from drf_spectacular.utils import extend_schema
from rest_framework.authentication import BaseAuthentication
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.exceptions_capture import capture_exception
from posthog.models.oauth import OAuthAccessToken, OAuthRefreshToken
from posthog.models.team.team import Team
from posthog.models.team.team_provisioning_config import TeamProvisioningConfig
from posthog.models.user import User
from posthog.models.utils import generate_random_oauth_access_token, generate_random_oauth_refresh_token
from posthog.utils import get_instance_region

from ee.partners.stripe.api.provisioning import AUTH_CODE_CACHE_PREFIX, DEEP_LINK_CACHE_PREFIX
from ee.partners.stripe.api.provisioning.analytics import capture_provisioning_event
from ee.partners.stripe.api.provisioning.authentication import StripeBearerAuthentication
from ee.partners.stripe.api.provisioning.billing import try_activate_billing_with_spt
from ee.partners.stripe.api.provisioning.constants import (
    ACCESS_TOKEN_EXPIRY_SECONDS,
    ANALYTICS_SERVICE_ID,
    DEEP_LINK_TTL_SECONDS,
    PAY_AS_YOU_GO_SERVICE_ID,
    STRIPE_CONTRACTED_SCOPES,
    SUPPORTED_VERSIONS,
)
from ee.partners.stripe.api.provisioning.core import (
    ProjectIdCollisionError,
    StripeOAuthAppMissingError,
    compute_partner_scoped_teams,
    get_available_teams_for_user,
    get_oauth_app_for_code,
    get_provisioning_service_id,
    handle_existing_user,
    handle_new_user,
    is_safe_deep_link_path,
    is_stripe_oauth_app,
    lock_application,
    maybe_create_provisioned_pat,
    region_to_host,
    remove_team_from_token_scopes,
    resolve_or_create_project_team,
    set_provisioning_service_id,
)
from ee.partners.stripe.api.provisioning.exceptions import Envelope, PreRenderedError, SpecError, render_spec_error
from ee.partners.stripe.api.provisioning.region_proxy import RegionProxyMixin
from ee.partners.stripe.api.provisioning.serializers import (
    AccountRequestSerializer,
    DeepLinkSerializer,
    ResourceCreateSerializer,
    RotateCredentialsSerializer,
    UpdateServiceSerializer,
    first_error_message,
)
from ee.partners.stripe.api.provisioning.services_catalog import get_services
from ee.partners.stripe.api.provisioning.signature import verify_api_version, verify_stripe_signature
from ee.partners.stripe.api.provisioning.throttling import (
    AccountRequestsThrottle,
    ResourceCreatesThrottle,
    TokenExchangesThrottle,
    enforce_stripe_rate_limit,
)

_CODE_CHALLENGE_RE = re.compile(r"[A-Za-z0-9_\-]+")


class StripeProvisioningAPIView(RegionProxyMixin, APIView):
    """Base for every endpoint in this namespace.

    Unauthenticated by default; errors raised as :class:`SpecError` render in
    the view's spec envelope.
    """

    authentication_classes: list[type[BaseAuthentication]] = []
    permission_classes: list = []
    spec_envelope: ClassVar[Envelope] = "flat"

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, PreRenderedError):
            return exc.response
        if isinstance(exc, SpecError):
            return render_spec_error(exc, self.spec_envelope)
        return super().handle_exception(exc)


class SignatureCheckedMixin:
    """Runs the spec's mandatory Stripe-Signature and API-Version checks as
    part of the request flow (after authentication, before the handler), so
    every endpoint built on it is signed-only by construction. A bearer alone
    is never sufficient: a stolen token without the signing secret cannot mint
    keys or read credentials."""

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)  # type: ignore[misc]
        if error := verify_stripe_signature(request):
            raise PreRenderedError(error)
        if error := verify_api_version(request):
            raise PreRenderedError(error)


# ---------------------------------------------------------------------------
# GET /provisioning/health - liveness probe, returns supported protocol versions
# ---------------------------------------------------------------------------


class HealthView(SignatureCheckedMixin, StripeProvisioningAPIView):
    @extend_schema(exclude=True)
    def get(self, request: Request) -> Response:
        return Response({"supported_versions": SUPPORTED_VERSIONS, "status": "ok"})


# ---------------------------------------------------------------------------
# GET /provisioning/services - returns the catalog of provisionable services
# ---------------------------------------------------------------------------


class ServicesView(SignatureCheckedMixin, StripeProvisioningAPIView):
    @extend_schema(exclude=True)
    def get(self, request: Request) -> Response:
        return Response({"data": get_services()})


# ---------------------------------------------------------------------------
# POST /provisioning/account_requests - onboard a new or existing user and
# return an auth code
# ---------------------------------------------------------------------------


class AccountRequestsView(StripeProvisioningAPIView):
    spec_envelope = "typed"
    region_proxy_strategy = "body_region"

    @extend_schema(exclude=True)
    def post(self, request: Request) -> Response:
        if error := verify_api_version(request):
            return error

        serializer = AccountRequestSerializer(data=request.data)
        if not serializer.is_valid():
            raise SpecError("invalid_request", first_error_message(serializer.errors))
        data = serializer.validated_data

        request_id = data["id"]
        email = data["email"]
        scopes = data["scopes"]
        configuration = data["configuration"]
        orchestrator = data["orchestrator"]

        # Partner account ID: generic field, with the Stripe-nested form preferred
        orchestrator_type = orchestrator.get("type", "")
        if orchestrator_type == "stripe":
            stripe_info = orchestrator.get("stripe") or {}
            partner_account_id = stripe_info.get("account", "")
        else:
            partner_account_id = orchestrator.get("account", "")

        if not request.headers.get("stripe-signature"):
            raise SpecError("unauthorized", "Authentication required", status=401)
        if error := verify_stripe_signature(request):
            return error

        if not partner_account_id:
            capture_provisioning_event("account_request", "error", error_code="missing_stripe_account")
            raise SpecError("invalid_request", "orchestrator.stripe.account is required")

        enforce_stripe_rate_limit(AccountRequestsThrottle, request, self)

        code_challenge = data["code_challenge"]
        code_challenge_method = data["code_challenge_method"]
        if code_challenge and code_challenge_method != "S256":
            raise SpecError("invalid_request", "Only S256 code_challenge_method is supported")
        if code_challenge and (
            len(code_challenge) < 43 or len(code_challenge) > 128 or not _CODE_CHALLENGE_RE.fullmatch(code_challenge)
        ):
            raise SpecError("invalid_request", "code_challenge must be 43-128 characters using base64url charset")

        region = (configuration.get("region") or "US").upper()

        requested_team_id = configuration.get("team_id")
        if requested_team_id is not None:
            try:
                requested_team_id = int(requested_team_id)
            except (ValueError, TypeError):
                raise SpecError("invalid_request", "configuration.team_id must be an integer", request_id=request_id)

        existing_user = User.objects.filter(email=email).first()

        if existing_user:
            return Response(
                handle_existing_user(
                    request_id,
                    existing_user,
                    scopes,
                    partner_account_id,
                    region,
                    requested_team_id,
                    code_challenge,
                    code_challenge_method,
                )
            )

        return Response(
            handle_new_user(
                request_id,
                data,
                email,
                scopes,
                partner_account_id,
                region,
                code_challenge,
                code_challenge_method,
            )
        )


# ---------------------------------------------------------------------------
# POST /oauth/token - exchange auth codes or refresh tokens for access tokens
# ---------------------------------------------------------------------------


class OAuthTokenView(StripeProvisioningAPIView):
    spec_envelope = "oauth"
    region_proxy_strategy = "token_lookup"

    @extend_schema(exclude=True)
    def post(self, request: Request) -> Response:
        grant_type = request.data.get("grant_type", "")

        if grant_type == "authorization_code":
            return self._exchange_authorization_code(request)
        elif grant_type == "refresh_token":
            return self._exchange_refresh_token(request)

        capture_provisioning_event("token_exchange", "unsupported_grant_type", grant_type=grant_type)
        raise SpecError("unsupported_grant_type", f"Unsupported grant_type: {grant_type}")

    def _exchange_authorization_code(self, request: Request) -> Response:
        code = request.data.get("code", "")
        if not code:
            capture_provisioning_event("token_exchange", "missing_code", grant_type="authorization_code")
            raise SpecError("invalid_request", "code is required")

        cache_key = f"{AUTH_CODE_CACHE_PREFIX}{code}"
        code_data = cache.get(cache_key)
        if code_data is None:
            capture_provisioning_event("token_exchange", "invalid_code", grant_type="authorization_code")
            raise SpecError("invalid_grant", "Invalid or expired authorization code")

        # Auth check: PKCE codes require code_verifier, non-PKCE codes require HMAC.
        # All verification happens BEFORE cache.delete so a failed attempt doesn't consume the code.
        stored_challenge = code_data.get("code_challenge", "")
        has_hmac = bool(request.headers.get("stripe-signature"))
        if stored_challenge:
            code_verifier = request.data.get("code_verifier", "")
            if not code_verifier:
                capture_provisioning_event("token_exchange", "missing_code_verifier", grant_type="authorization_code")
                raise SpecError("invalid_request", "code_verifier is required for PKCE", status=401)
            computed = (
                base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest())
                .rstrip(b"=")
                .decode("ascii")
            )
            if computed != stored_challenge:
                capture_provisioning_event("token_exchange", "pkce_mismatch", grant_type="authorization_code")
                raise SpecError("invalid_grant", "PKCE code_verifier does not match")
        elif not has_hmac:
            capture_provisioning_event("token_exchange", "missing_signature", grant_type="authorization_code")
            raise SpecError("invalid_request", "Authentication required", status=401)
        else:
            if error := verify_stripe_signature(request):
                return error

        # Consume the code before rate limiting so a leaked auth code can't be replayed
        # to burn the bucket. Auth codes are single-use by spec, so the tradeoff
        # (rate-limited client loses the code) is acceptable - clients can
        # re-initiate the OAuth flow if rate-limited.
        cache.delete(cache_key)

        enforce_stripe_rate_limit(TokenExchangesThrottle, request, self)

        user_id = code_data["user_id"]
        team_id = code_data["team_id"]
        scopes = code_data.get("scopes", [])

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            capture_provisioning_event("token_exchange", "user_not_found", grant_type="authorization_code")
            raise SpecError("invalid_grant", "User not found")

        try:
            oauth_app = get_oauth_app_for_code(code_data)
        except StripeOAuthAppMissingError:
            capture_provisioning_event("token_exchange", "oauth_app_missing", grant_type="authorization_code")
            raise SpecError("server_error", "OAuth application is not configured", status=500)

        # Stripe-only namespace: a consent-flow code bound to another partner's
        # app is not redeemable here and must use that partner's own surface.
        if not is_stripe_oauth_app(oauth_app):
            capture_provisioning_event("token_exchange", "non_stripe_app", grant_type="authorization_code")
            raise SpecError("invalid_grant", "Authorization code was not issued for the Stripe Projects app")

        # Lock the app row before reading the revoke stamp and minting, so this serializes
        # with revoke_application_sessions (see lock_application). Provisioning auth codes
        # live in the cache, not OAuthGrant, so the revoke's sweep can't reach them - the
        # `issued_at` carried on the code is what a revoke is checked against. Codes minted
        # without the field fail closed (they expire in AUTH_CODE_TTL_SECONDS and the
        # client can re-run the flow).
        with transaction.atomic():
            locked_app = lock_application(oauth_app.pk) if oauth_app else None
            sessions_revoked_at = locked_app.sessions_revoked_at if locked_app else None
            if sessions_revoked_at is not None:
                issued_at_raw = code_data.get("issued_at")
                issued_at = datetime.fromisoformat(issued_at_raw) if issued_at_raw else None
                if issued_at is None or issued_at < sessions_revoked_at:
                    capture_provisioning_event("token_exchange", "sessions_revoked", grant_type="authorization_code")
                    raise SpecError("invalid_grant", "Application sessions were revoked; re-authorize.")

            # No scope ceiling in this namespace: Stripe is trusted with full
            # access, so it receives exactly the scopes it requested (falling back
            # to the default Stripe set when none were requested).
            requested_scopes = scopes if scopes else list(STRIPE_CONTRACTED_SCOPES)
            scope_str = " ".join(requested_scopes)

            token_expiry = ACCESS_TOKEN_EXPIRY_SECONDS

            scoped_teams = compute_partner_scoped_teams(oauth_app, user, team_id)
            # A partner token carries its restriction in scoped_teams alone, and the standard
            # OAuth permission check treats an empty scoped_teams as unrestricted (permissions.py).
            # compute_partner_scoped_teams returns [] exactly when the base team is gone or the
            # user lost access, so minting here would hand out a project-unrestricted bearer.
            # Fail closed and force re-authorization.
            if not scoped_teams:
                capture_provisioning_event("token_exchange", "no_accessible_teams", grant_type="authorization_code")
                raise SpecError("invalid_grant", "No accessible teams for this authorization; re-authorize.")

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
            raise SpecError("invalid_request", "refresh_token is required")

        # Lock the app row first (revoke_application_sessions locks it before sweeping tokens),
        # then re-read the refresh token under that lock, so the rotate-and-mint serializes with
        # the revoke: either we hold the lock and our new tokens land before its sweep, or it
        # committed first and we see the token already revoked (or the stamp) and reject. Looking
        # the app up by id first (without locking the token row) keeps the lock order app→token,
        # matching the revoke, so the two can't deadlock.
        with transaction.atomic():
            application_id = (
                OAuthRefreshToken.objects.filter(token=refresh_token_value, revoked__isnull=True)
                .values_list("application_id", flat=True)
                .first()
            )
            locked_app = lock_application(application_id) if application_id else None
            old_refresh = (
                OAuthRefreshToken.objects.select_related("user", "access_token")
                .filter(token=refresh_token_value, revoked__isnull=True)
                .first()
            )
            if old_refresh is None:
                capture_provisioning_event("token_exchange", "invalid_refresh_token", grant_type="refresh_token")
                raise SpecError("invalid_grant", "Invalid or revoked refresh token")

            oauth_app = locked_app

            # Stripe-only namespace: refresh tokens minted for any other
            # application (or with no application) are not rotatable here.
            # Checked before any token row is mutated.
            if oauth_app is None or not is_stripe_oauth_app(oauth_app):
                capture_provisioning_event("token_exchange", "non_stripe_app", grant_type="refresh_token")
                raise SpecError("invalid_grant", "Refresh token was not issued for the Stripe Projects app")
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
                raise SpecError("invalid_grant", "No accessible teams for this token; re-authorize.")
            old_scope = (
                old_refresh.access_token.scope if old_refresh.access_token else " ".join(STRIPE_CONTRACTED_SCOPES)
            )

            sessions_revoked_at = locked_app.sessions_revoked_at if locked_app else None
            if sessions_revoked_at is not None and old_refresh.created < sessions_revoked_at:
                capture_provisioning_event("token_exchange", "sessions_revoked", grant_type="refresh_token")
                raise SpecError("invalid_grant", "Application sessions were revoked; re-authorize.")

            # No scope ceiling in this namespace: carry the prior token's scopes
            # forward unchanged.
            new_scope = old_scope

            enforce_stripe_rate_limit(TokenExchangesThrottle, request, self)

            old_access = old_refresh.access_token
            old_refresh.access_token = None
            old_refresh.revoked = timezone.now()
            old_refresh.save(update_fields=["access_token", "revoked"])

            if old_access:
                old_access.delete()

            token_expiry = ACCESS_TOKEN_EXPIRY_SECONDS

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


# ---------------------------------------------------------------------------
# Resource endpoints - bearer-authenticated, status envelope
# ---------------------------------------------------------------------------


class StripeResourceAPIView(SignatureCheckedMixin, StripeProvisioningAPIView):
    spec_envelope = "status"
    region_proxy_strategy = "bearer_lookup"
    authentication_classes = [StripeBearerAuthentication]

    def parse_resource_team_id(self, resource_id: str, access_token: OAuthAccessToken) -> int:
        try:
            team_id = int(resource_id)
        except (ValueError, TypeError):
            raise SpecError("invalid_resource_id", "Invalid resource ID", resource_id=resource_id)

        # TODO: latent bug - this checks only the token's issuance-time scoped_teams,
        # not the user's current team-level access. If the user is later removed from
        # the team/org, the (long-lived) bearer can still read/rotate/update/remove
        # the resource until it is refreshed (refresh re-derives scope via
        # compute_partner_scoped_teams). Revalidate live access here to close it.
        if team_id not in (access_token.scoped_teams or []):
            raise SpecError("forbidden", "Resource not accessible with this token", resource_id=resource_id, status=403)
        return team_id

    def get_team(self, team_id: int, resource_id: str) -> Team:
        try:
            return Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            raise SpecError("not_found", "Resource not found", resource_id=resource_id, status=404)


class ResourcesCreateView(StripeResourceAPIView):
    @extend_schema(exclude=True)
    def post(self, request: Request) -> Response:
        user = cast(User, request.user)
        access_token = cast(OAuthAccessToken, request.auth)

        app = access_token.application
        enforce_stripe_rate_limit(
            ResourceCreatesThrottle,
            request,
            self,
            message="Rate limit exceeded. Try again later.",
            envelope="status",
        )

        serializer = ResourceCreateSerializer(data=request.data, context={"application": app})
        if not serializer.is_valid():
            raise SpecError("invalid_request", first_error_message(serializer.errors))
        data = serializer.validated_data

        service_id = data["service_id"]
        label_prefix = data["label_prefix"]

        scoped_teams = access_token.scoped_teams or []
        if not scoped_teams:
            capture_provisioning_event("resource_created", "error", partner=app, error_code="no_team")
            raise SpecError("no_team", "No team associated with this token")

        project_id = data["project_id"]
        configuration = data["configuration"]

        if project_id:
            try:
                team, scoped_teams = resolve_or_create_project_team(
                    project_id, scoped_teams, user, configuration, access_token
                )
            except ProjectIdCollisionError:
                capture_provisioning_event(
                    "resource_created", "error", partner=app, error_code="project_id_conflict", project_id=project_id
                )
                raise SpecError("project_id_conflict", "Project ID already linked to another organization", status=409)
            if team is None:
                capture_provisioning_event(
                    "resource_created", "error", partner=app, error_code="not_found", project_id=project_id
                )
                raise SpecError("not_found", "Resource not found", status=404)
        else:
            team_id = scoped_teams[0]
            try:
                team = Team.objects.get(id=team_id)
            except Team.DoesNotExist:
                capture_provisioning_event(
                    "resource_created", "error", partner=app, error_code="team_not_found", team_id=team_id
                )
                raise SpecError("team_not_found", "Team not found", resource_id=str(team_id), status=404)

        # TODO: latent bug - this runs on every call, so a repeated create for
        # an existing team overwrites its service_id (not idempotent), and the
        # write lands before the billing checks below.
        resolved_service_id = service_id or ANALYTICS_SERVICE_ID
        set_provisioning_service_id(team, resolved_service_id)

        # TODO: latent bug - the team, provisioning config, and token scopes
        # are already persisted; a billing failure below returns an error to
        # the orchestrator while leaving a usable, unbilled project behind.
        billing_result = try_activate_billing_with_spt(data["payment_credentials"], team, user)
        has_spt = billing_result is not None
        if billing_result is False:
            capture_provisioning_event(
                "resource_created",
                "error",
                partner=app,
                error_code="requires_payment_credentials",
                service_id=resolved_service_id,
                team_id=team.id,
                has_spt=has_spt,
            )
            # TODO: update_service reports this same billing failure as
            # billing_activation_failed; the two codes should converge.
            raise SpecError("requires_payment_credentials", "Billing activation failed", resource_id=str(team.id))

        if resolved_service_id == PAY_AS_YOU_GO_SERVICE_ID and billing_result is None:
            capture_provisioning_event(
                "resource_created",
                "error",
                partner=app,
                error_code="requires_payment_credentials",
                service_id=resolved_service_id,
                team_id=team.id,
            )
            raise SpecError("requires_payment_credentials", "Payment credentials required for paid plan")

        region = get_instance_region() or "US"
        host = region_to_host(region)

        capture_provisioning_event(
            "resource_created",
            "success",
            partner=app,
            service_id=resolved_service_id,
            team_id=team.id,
            has_spt=has_spt,
            billing_result=str(billing_result),
        )

        access_configuration: dict[str, str] = {
            "api_key": team.api_token,
            "host": host,
        }
        if personal_api_key := maybe_create_provisioned_pat(user, team, access_token.scope, label_prefix=label_prefix):
            access_configuration["personal_api_key"] = personal_api_key

        return Response(
            {
                "status": "complete",
                "id": str(team.id),
                "service_id": resolved_service_id,
                "complete": {
                    "access_configuration": access_configuration,
                },
            }
        )


class ResourceDetailView(StripeResourceAPIView):
    @extend_schema(exclude=True)
    def get(self, request: Request, resource_id: str) -> Response:
        access_token = cast(OAuthAccessToken, request.auth)

        # TODO: latent gap - unlike update_service/remove there is no
        # cross-application ownership check on TeamProvisioningConfig, so a
        # token whose scope includes a team provisioned by another application
        # can still read its credentials.
        team_id = self.parse_resource_team_id(resource_id, access_token)
        team = self.get_team(team_id, resource_id)

        service_id = get_provisioning_service_id(team)
        region = get_instance_region() or "US"
        host = region_to_host(region)

        return Response(
            {
                "status": "complete",
                "id": resource_id,
                "service_id": service_id,
                "complete": {
                    "access_configuration": {
                        "api_key": team.api_token,
                        "host": host,
                    },
                },
            }
        )


class RotateCredentialsView(StripeResourceAPIView):
    @extend_schema(exclude=True)
    def post(self, request: Request, resource_id: str) -> Response:
        user = cast(User, request.user)
        access_token = cast(OAuthAccessToken, request.auth)

        serializer = RotateCredentialsSerializer(data=request.data, context={"resource_id": resource_id})
        if not serializer.is_valid():
            raise SpecError("invalid_request", first_error_message(serializer.errors), resource_id=resource_id)
        label_prefix = serializer.validated_data["label_prefix"]

        # TODO: latent gap - unlike update_service/remove there is no
        # cross-application ownership check on TeamProvisioningConfig, so a
        # token whose scope includes a team provisioned by another application
        # can rotate its credentials.
        team_id = self.parse_resource_team_id(resource_id, access_token)
        team = self.get_team(team_id, resource_id)

        try:
            # The bearer flow resolves the token outside DRF's session machinery,
            # so read impersonation off the token directly.
            team.reset_token_and_save(user=user, is_impersonated_session=access_token.impersonated_by_id is not None)
        except Exception:
            capture_exception(additional_properties={"team_id": team_id})
            capture_provisioning_event("credential_rotation", "failed", team_id=team_id)
            raise SpecError(
                "credential_rotation_failed", "Failed to rotate credentials", resource_id=resource_id, status=500
            )

        capture_provisioning_event("credential_rotation", "success", team_id=team_id)

        service_id = get_provisioning_service_id(team)
        region = get_instance_region() or "US"
        host = region_to_host(region)

        access_configuration: dict[str, str] = {
            "api_key": team.api_token,
            "host": host,
        }
        if personal_api_key := maybe_create_provisioned_pat(user, team, access_token.scope, label_prefix=label_prefix):
            access_configuration["personal_api_key"] = personal_api_key

        return Response(
            {
                "status": "complete",
                "id": resource_id,
                "service_id": service_id,
                "complete": {
                    "access_configuration": access_configuration,
                },
            }
        )


class UpdateServiceView(StripeResourceAPIView):
    @extend_schema(exclude=True)
    def post(self, request: Request, resource_id: str) -> Response:
        user = cast(User, request.user)
        access_token = cast(OAuthAccessToken, request.auth)

        team_id = self.parse_resource_team_id(resource_id, access_token)
        team = self.get_team(team_id, resource_id)

        # A config with a non-null application belongs to the partner that provisioned
        # it; a null application is unclaimed (every team gets one by default) and is
        # mutable by any in-scope caller. Reject only a cross-partner mutation.
        owning_application_id = (
            TeamProvisioningConfig.objects.filter(team_id=team_id).values_list("application_id", flat=True).first()
        )
        if owning_application_id is not None and owning_application_id != access_token.application_id:
            raise SpecError(
                "forbidden", "Resource owned by a different provisioning partner", resource_id=resource_id, status=403
            )

        serializer = UpdateServiceSerializer(data=request.data, context={"resource_id": resource_id})
        if not serializer.is_valid():
            raise SpecError("invalid_request", first_error_message(serializer.errors), resource_id=resource_id)
        data = serializer.validated_data
        service_id = data["service_id"]

        billing_result = try_activate_billing_with_spt(data["payment_credentials"], team, user)
        has_spt = billing_result is not None
        if billing_result is False:
            capture_provisioning_event(
                "update_service",
                "error",
                error_code="billing_activation_failed",
                service_id=service_id,
                team_id=team_id,
                has_spt=has_spt,
            )
            raise SpecError(
                "billing_activation_failed",
                "Failed to activate billing with payment credentials",
                resource_id=resource_id,
            )

        if service_id == PAY_AS_YOU_GO_SERVICE_ID and billing_result is None:
            capture_provisioning_event(
                "update_service",
                "error",
                error_code="requires_payment_credentials",
                service_id=service_id,
                team_id=team_id,
            )
            raise SpecError(
                "requires_payment_credentials", "Payment credentials required for paid plan", resource_id=resource_id
            )

        set_provisioning_service_id(team, service_id)

        region = get_instance_region() or "US"
        host = region_to_host(region)

        capture_provisioning_event(
            "update_service",
            "success",
            service_id=service_id,
            team_id=team_id,
            has_spt=has_spt,
            billing_result=str(billing_result),
        )

        return Response(
            {
                "status": "complete",
                "id": resource_id,
                "service_id": service_id,
                "complete": {
                    "access_configuration": {
                        "api_key": team.api_token,
                        "host": host,
                    },
                },
            }
        )


class ResourceRemoveView(StripeResourceAPIView):
    """Detaches the resource from the orchestrator: removes it from the token's
    scope and clears provisioning metadata. Preserves the underlying team and
    user data so the customer can still access PostHog directly."""

    @extend_schema(exclude=True)
    def post(self, request: Request, resource_id: str) -> Response:
        access_token = cast(OAuthAccessToken, request.auth)

        team_id = self.parse_resource_team_id(resource_id, access_token)

        try:
            # Clear the mapping only if it is unclaimed or owned by the caller's
            # application; an in-scope partner must not delete another partner's
            # provisioning mapping for the same team.
            # TODO: latent gap - when the config is owned by another application
            # the delete is silently skipped, yet the team is still stripped
            # from token scopes and "removed" is returned, so the mapping
            # survives with no signal to the caller.
            config = TeamProvisioningConfig.objects.filter(team_id=team_id).first()
            if config is not None and config.application_id in (None, access_token.application_id):
                config.delete()
        except Exception:
            capture_exception(additional_properties={"team_id": team_id, "step": "remove_provisioning_config"})
            capture_provisioning_event("resource_removed", "error", team_id=team_id, error_code="remove_config_failed")
            raise SpecError("remove_failed", "Failed to remove resource", resource_id=resource_id, status=500)

        remove_team_from_token_scopes(access_token, team_id)

        capture_provisioning_event("resource_removed", "success", team_id=team_id)

        return Response({"status": "removed", "id": resource_id})


# ---------------------------------------------------------------------------
# POST /provisioning/deep_links
# ---------------------------------------------------------------------------


class DeepLinksView(StripeResourceAPIView):
    @extend_schema(exclude=True)
    def post(self, request: Request) -> Response:
        access_token = cast(OAuthAccessToken, request.auth)

        serializer = DeepLinkSerializer(data=request.data)
        if not serializer.is_valid():
            raise SpecError("invalid_request", first_error_message(serializer.errors))
        data = serializer.validated_data

        # `purpose` is a free-form label retained for analytics. `path` is the generic
        # destination: any in-app path the partner wants the user to land on after login.
        purpose = data["purpose"]
        path = data["path"]
        if path and not is_safe_deep_link_path(path):
            capture_provisioning_event(
                "deep_link_created", "invalid_path", partner=access_token.application, purpose=purpose
            )
            raise SpecError("invalid_path", "path must be a relative in-app path beginning with a single '/'")

        scoped_teams = access_token.scoped_teams or []
        team_id = scoped_teams[0] if scoped_teams else None

        region = get_instance_region() or "US"
        host = region_to_host(region)

        token = secrets.token_urlsafe(32)
        cache.set(
            f"{DEEP_LINK_CACHE_PREFIX}{token}",
            {
                "user_id": access_token.user_id,
                "team_id": team_id,
                "purpose": purpose,
                "path": path or None,
            },
            timeout=DEEP_LINK_TTL_SECONDS,
        )

        expires_at = timezone.now() + timedelta(seconds=DEEP_LINK_TTL_SECONDS)

        url = f"{host}/api/partners/stripe/login?token={token}"
        if team_id:
            url += f"&team_id={team_id}"

        capture_provisioning_event(
            "deep_link_created", "success", partner=access_token.application, purpose=purpose, team_id=team_id
        )

        return Response(
            {
                "purpose": purpose,
                "url": url,
                "expires_at": expires_at.isoformat(),
            }
        )
