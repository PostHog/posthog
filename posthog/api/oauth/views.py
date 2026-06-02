import json
import uuid
import hashlib
import calendar
from datetime import timedelta
from typing import TypedDict, cast
from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import DisallowedRedirect
from django.db import OperationalError
from django.http import JsonResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

import structlog
import posthoganalytics
from oauth2_provider.compat import login_not_required
from oauth2_provider.exceptions import OAuthToolkitError
from oauth2_provider.http import OAuth2ResponseRedirect
from oauth2_provider.oauth2_validators import OAuth2Validator
from oauth2_provider.settings import oauth2_settings
from oauth2_provider.views import (
    ClientProtectedScopedResourceView,
    ConnectDiscoveryInfoView,
    JwksInfoView,
    RevokeTokenView,
    TokenView,
    UserInfoView,
)
from oauth2_provider.views.mixins import OAuthLibMixin
from oauthlib.oauth2 import InvalidGrantError
from rest_framework import serializers, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.api.oauth.cimd import (
    CIMD_THROTTLE_CLASSES,
    CIMDFetchError,
    CIMDValidationError,
    get_application_by_client_id,
    get_or_create_cimd_application,
    is_cimd_client_id,
)
from posthog.helpers.impersonation import get_original_user_from_session, is_impersonated_session
from posthog.middleware import is_read_only_impersonation
from posthog.models import OAuthAccessToken, OAuthApplication, Organization, Team, User
from posthog.models.oauth import OAuthApplicationAccessLevel, OAuthGrant, OAuthRefreshToken
from posthog.scopes import OIDC_SCOPES, UNPRIVILEGED_SCOPES, downgrade_scopes_to_read_only, get_oauth_scopes_supported
from posthog.security.url_validation import has_authority_bypass_chars
from posthog.user_permissions import UserPermissions
from posthog.utils import render_template
from posthog.views import login_required

logger = structlog.get_logger(__name__)


# Clients for which we must NOT issue refresh tokens. The token response will omit
# "refresh_token" and no OAuthRefreshToken row will be created. Entries are matched
# against the app's cimd_metadata_url for CIMD clients, and against client_id otherwise.
CLIENT_IDS_WITHOUT_REFRESH_TOKEN: frozenset[str] = frozenset(
    {
        # PostHog Wizard CLI (CIMD) — short-lived auth, no persistent session needed.
        "https://us.posthog.com/api/oauth/wizard/client-metadata",
        "https://eu.posthog.com/api/oauth/wizard/client-metadata",
    }
)

# Sentinel for the per-request impersonator_id cache so None (no impersonator) is
# distinguishable from "not resolved yet".
_IMPERSONATOR_CACHE_UNSET: object = object()


def get_region_info() -> dict | None:
    """Return region metadata if running on PostHog Cloud US/EU, else None."""
    cloud = getattr(settings, "CLOUD_DEPLOYMENT", None)
    if cloud in ("US", "EU"):
        region = cloud.lower()
        return {"posthog_region": region, "posthog_base_url": settings.SITE_URL}
    return None


def _temporarily_unavailable_response(retry_after_seconds: int = 1) -> JsonResponse:
    """RFC 6749 `temporarily_unavailable` response with HTTP 503 and Retry-After.

    Use for transient failures (e.g. database connection-pool saturation) so OAuth
    clients back off and retry instead of treating the request as permanently failed.
    """
    response = JsonResponse(
        {
            "error": "temporarily_unavailable",
            "error_description": "The authorization server is temporarily unable to handle the request. Please retry.",
        },
        status=503,
    )
    response["Retry-After"] = str(retry_after_seconds)
    return response


def _impersonator_id_for_request(request) -> int | None:
    """Return the staff user id that should tag any OAuth token minted on behalf of this request.

    Returns the original (staff) user's id when the Django session is an active impersonation
    session, otherwise None. Threaded through oauthlib via the `credentials` dict so the
    validator can stamp `impersonated_by` on the grant / access token / refresh token.
    """
    if not is_impersonated_session(request):
        return None
    original_user = get_original_user_from_session(request)
    return original_user.pk if original_user else None


def _scoped_organization_ids(
    user: User,
    access_level: str | None,
    scoped_organization_ids: list[str] | None,
    scoped_team_ids: list[int] | None,
) -> set[uuid.UUID]:
    """Resolve the set of organizations a grant with this access scope would reach.

    `all` access (or any unscoped grant) reaches every organization the user belongs to;
    `organization` access is the listed organizations; `team` access is the organizations
    owning the listed teams.
    """
    if access_level == OAuthApplicationAccessLevel.ORGANIZATION.value and scoped_organization_ids:
        return {uuid.UUID(str(org_id)) for org_id in scoped_organization_ids}
    if access_level == OAuthApplicationAccessLevel.TEAM.value and scoped_team_ids:
        return set(Team.objects.filter(pk__in=scoped_team_ids).values_list("organization_id", flat=True))
    return set(user.organizations.values_list("id", flat=True))


def _impersonation_ai_processing_block(
    request,
    *,
    access_level: str | None = None,
    scoped_organization_ids: list[str] | None = None,
    scoped_team_ids: list[int] | None = None,
) -> Response | None:
    """Block OAuth during impersonation when an in-scope organization has disabled AI data processing.

    Some organizations explicitly opt out of AI processing of their data
    (`Organization.is_ai_data_processing_approved`). A staff member impersonating a customer
    must not be able to grant an OAuth client access to that data in that case (the MCP being
    the motivating case). This does not apply to customers authorizing a client themselves —
    they have already consented for their own data.

    Mirrors the fail-closed check used elsewhere for AI features: only an explicit `True`
    counts as approved, so a null/unset value is treated as not approved. Returns a 403
    `Response` to short-circuit with, or `None` to proceed.
    """
    if not is_impersonated_session(request):
        return None

    organization_ids = _scoped_organization_ids(request.user, access_level, scoped_organization_ids, scoped_team_ids)
    if not organization_ids:
        return None

    has_disabled_org = (
        Organization.objects.filter(id__in=organization_ids).exclude(is_ai_data_processing_approved=True).exists()
    )
    if not has_disabled_org:
        return None

    return Response(
        {
            "error": "access_denied",
            "error_description": "This organization has disabled AI data processing, so it cannot be authorized for an OAuth client while impersonating.",
        },
        status=status.HTTP_403_FORBIDDEN,
    )


class OAuthAuthorizationContext(TypedDict):
    user: User


class OAuthAuthorizationSerializer(serializers.Serializer):
    client_id = serializers.CharField()
    redirect_uri = serializers.CharField(required=False, allow_null=True, default=None)
    response_type = serializers.CharField(required=False)
    state = serializers.CharField(required=False, allow_null=True, default=None)
    code_challenge = serializers.CharField(required=False, allow_null=True, default=None)
    code_challenge_method = serializers.CharField(required=False, allow_null=True, default=None)
    nonce = serializers.CharField(required=False, allow_null=True, default=None)
    claims = serializers.CharField(required=False, allow_null=True, default=None)
    scope = serializers.CharField()
    allow = serializers.BooleanField()
    prompt = serializers.CharField(required=False, allow_null=True, default=None)
    approval_prompt = serializers.CharField(required=False, allow_null=True, default=None)
    access_level = serializers.ChoiceField(choices=[level.value for level in OAuthApplicationAccessLevel])
    scoped_organizations = serializers.ListField(
        child=serializers.CharField(), required=False, allow_null=True, default=[]
    )
    scoped_teams = serializers.ListField(child=serializers.IntegerField(), required=False, allow_null=True, default=[])

    def __init__(self, *args, **kwargs):
        context = kwargs.get("context", {})
        if "user" not in context:
            raise ValueError("OAuthAuthorizationSerializer requires 'user' in context")
        super().__init__(*args, **kwargs)

    def validate_scoped_organizations(self, scoped_organization_ids: list[str]) -> list[str]:
        access_level = self.initial_data.get("access_level")
        requesting_user: User = self.context["user"]
        user_permissions = UserPermissions(requesting_user)
        org_memberships = user_permissions.organization_memberships

        if access_level == OAuthApplicationAccessLevel.ORGANIZATION.value:
            if not scoped_organization_ids or len(scoped_organization_ids) == 0:
                raise serializers.ValidationError("scoped_organizations is required when access_level is organization")
            try:
                organization_uuids = [uuid.UUID(org_id) for org_id in scoped_organization_ids]
                for org_uuid in organization_uuids:
                    if org_uuid not in org_memberships or not org_memberships[org_uuid].level:
                        raise serializers.ValidationError("Invalid organization specified or you do not have access.")
            except ValueError:
                raise serializers.ValidationError("Invalid organization UUID provided in scoped_organizations.")
            return scoped_organization_ids
        elif scoped_organization_ids and len(scoped_organization_ids) > 0:
            raise serializers.ValidationError(
                f"scoped_organizations is not allowed when access_level is {access_level}"
            )
        return []

    def validate_scoped_teams(self, scoped_team_ids: list[int]) -> list[int]:
        access_level = self.initial_data.get("access_level")
        requesting_user: User = self.context["user"]
        user_permissions = UserPermissions(requesting_user)

        if access_level == OAuthApplicationAccessLevel.TEAM.value:
            if not scoped_team_ids or len(scoped_team_ids) == 0:
                raise serializers.ValidationError("scoped_teams is required when access_level is team")

            teams = Team.objects.filter(pk__in=scoped_team_ids)
            if len(teams) != len(scoped_team_ids):
                raise serializers.ValidationError("Invalid team specified or you do not have access.")

            for team in teams:
                if user_permissions.team(team).effective_membership_level is None:
                    raise serializers.ValidationError("Invalid team specified or you do not have access.")
            return scoped_team_ids
        elif scoped_team_ids and len(scoped_team_ids) > 0:
            raise serializers.ValidationError(f"scoped_teams is not allowed when access_level is {access_level}")
        return []


class OAuthValidator(OAuth2Validator):
    def _is_dynamic_client(self, request) -> bool:
        """Check if the client was registered dynamically (DCR or CIMD)."""
        if hasattr(request, "client") and request.client:
            return getattr(request.client, "is_dcr_client", False) or getattr(request.client, "is_cimd_client", False)
        return False

    def _should_skip_refresh_token(self, request) -> bool:
        # No refresh tokens for impersonation-minted tokens.
        if self._get_impersonator_id(request) is not None:
            return True

        # CIMD clients expose their canonical id via cimd_metadata_url (the model's
        # client_id is an auto-generated UUID for those). Gate on is_cimd_client so
        # a stray cimd_metadata_url on a non-CIMD app can't flip the behavior.
        client_key: str | None = None
        if not hasattr(request, "client") or not request.client:
            client_key = None
        elif getattr(request.client, "is_cimd_client", False):
            client_key = getattr(request.client, "cimd_metadata_url", None)
        else:
            client_key = getattr(request.client, "client_id", None)
        return bool(client_key and client_key in CLIENT_IDS_WITHOUT_REFRESH_TOKEN)

    def _load_application(self, client_id, request):
        """
        Load the application from the database, supporting CIMD URL-form client_ids.

        For URL-format client_ids, looks up by cimd_metadata_url.
        Does NOT fetch metadata — that only happens in validate_client_id().
        """

        assert hasattr(request, "client"), '"request" instance has no "client" attribute'

        # Already fetched previously before, just return what's been validated already
        if request.client:
            return request.client

        # CIMD URLs are looked up by cimd_metadata_url, not the auto-generated client_id UUID
        app: OAuthApplication | None = None
        if is_cimd_client_id(client_id):
            app = OAuthApplication.objects.filter(cimd_metadata_url=client_id).first()
        else:
            app = OAuthApplication.objects.filter(client_id=client_id).first()

        if app is None or not app.is_usable(request):
            return None

        request.client = app
        return request.client

    def validate_client_id(self, client_id, request, *args, **kwargs):
        """
        Validate client_id, supporting CIMD URL-form client_ids.

        For CIMD URLs, always routes through get_or_create_cimd_application()
        so that metadata is refreshed when the cache expires.
        For standard client_ids, loads directly from the database.
        """

        # CIMD URLs always go through get_or_create to ensure metadata refresh
        if is_cimd_client_id(client_id):
            try:
                app = get_or_create_cimd_application(client_id)
                request.client = app
                return True
            except (CIMDFetchError, CIMDValidationError) as e:
                logger.warning("cimd_resolution_failed", client_id=client_id, error=str(e))
                return False

        # Standard UUID lookup
        if self._load_application(client_id, request) is not None:
            return True

        return False

    def validate_redirect_uri(self, client_id, redirect_uri, request, *args, **kwargs):
        """
        Validate redirect_uri, extending RFC 8252 Section 7.3 loopback handling
        to include 'localhost'.

        Django OAuth Toolkit already allows any port for 127.0.0.1 and ::1, but
        not for 'localhost'. Native apps like Claude Code register
        http://localhost/callback and request http://localhost:<ephemeral>/callback.
        """

        if has_authority_bypass_chars(redirect_uri):
            return False

        if request.client.redirect_uri_allowed(redirect_uri):
            return True

        # Extend RFC 8252 Section 7.3 loopback port flexibility to 'localhost'.
        #
        # DOT's redirect_to_uri_allowed() already skips the port check when the
        # *registered* URI uses http://127.0.0.1 or http://[::1], but 'localhost'
        # is not in that list. Many CIMD clients (e.g. Claude Code) register
        # http://localhost/callback (no port) and then request
        # http://localhost:<ephemeral_port>/callback at runtime.
        #
        # We handle this by stripping the port from the request URI and
        # re-checking against the registered URIs. This only applies when the
        # request URI is http://localhost with an explicit port.
        parsed = urlparse(redirect_uri)
        if parsed.scheme == "http" and parsed.hostname == "localhost" and parsed.port:
            portless = f"http://localhost{parsed.path}"
            if parsed.query:
                portless += f"?{parsed.query}"
            return request.client.redirect_uri_allowed(portless)

        return False

    # OIDC + introspection are accepted independently of the per-app ceiling.
    # They are identity / token-management scopes, not resource permissions.
    _ALWAYS_ALLOWED_SCOPES: frozenset[str] = frozenset(OIDC_SCOPES) | {"introspection"}

    def validate_scopes(self, client_id, scopes, client, request, *args, **kwargs):
        """Enforce the per-application scope ceiling from `OAuthApplication.scopes`.

        Resolution:
        - empty / omitted `scope=` -> grant the effective ceiling (mutate
          `request.scopes` so oauthlib's default-resolution doesn't fall back
          to just ["openid"] from DEFAULT_SCOPES).
        - any subset of `effective_scopes` plus the always-allowed (OIDC,
          introspection) -> grant as requested.
        - any value outside that union (including `*` when the app has an
          explicit ceiling) -> reject. oauthlib turns the False return into
          `InvalidScopeError` / RFC 6749 `error=invalid_scope`.

        Empty `application.scopes` resolves to UNPRIVILEGED_SCOPES (the broad
        default), and `*` is accepted in that mode so existing clients (the
        PostHog Code CLI today) keep working until wildcard retirement.
        """
        app_scopes = getattr(client, "scopes", None) or []
        has_ceiling = bool(app_scopes)
        effective = frozenset(app_scopes) if has_ceiling else UNPRIVILEGED_SCOPES

        requested = set(scopes or [])
        if not requested:
            request.scopes = sorted(effective | self._ALWAYS_ALLOWED_SCOPES)
            return True

        to_check = requested - self._ALWAYS_ALLOWED_SCOPES
        if not to_check:
            return True

        if has_ceiling:
            allowed = "*" not in to_check and to_check.issubset(effective)
        else:
            allowed = to_check.issubset(UNPRIVILEGED_SCOPES | {"*"})

        if not allowed:
            logger.warning(
                "oauth_scope_ceiling_rejected",
                client_id=client_id,
                is_first_party=getattr(client, "is_first_party", False),
                requested=sorted(to_check),
                ceiling=sorted(effective),
            )
        return allowed

    def get_original_scopes(self, refresh_token, request, *args, **kwargs):
        """Cap refreshed scopes at the application's current ceiling.

        DOT's refresh grant copies the prior access token's scopes verbatim and never
        re-runs `validate_scopes`, so a token minted before a ceiling was tightened would
        keep refreshing into the old, broader set. Intersecting with `application.scopes`
        means a narrowed app drops the removed scopes on the next refresh.

        Always-allowed scopes (OIDC, introspection) pass through, mirroring
        `validate_scopes`. Resolution when the app has a ceiling:
        - a `*` token is left untouched: narrowing it would strip all resource access
          on refresh, and `*` is still issued to legacy clients. Its retirement is
          handled separately in #60330 (coupled to #60342).
        - a token whose scopes have no overlap with the ceiling can't be narrowed
          without emptying it, so we reject the refresh (`invalid_grant`) — the client
          re-authorizes and gets a token within the current ceiling, rather than
          silently keeping out-of-ceiling access.

        An empty `application.scopes` (no ceiling) is a no-op.
        """
        original = super().get_original_scopes(refresh_token, request, *args, **kwargs)
        # DOT's base returns the stored scope as a space-delimited string; oauthlib
        # `scope_to_list`s whatever we return, so a list back is fine.
        original_list = original.split() if isinstance(original, str) else list(original)
        # `request.client` is not always populated when oauthlib calls this during the
        # refresh grant, so fall back to resolving the application from the token row.
        application = getattr(request, "client", None)
        if application is None:
            rt = OAuthRefreshToken.objects.filter(token=refresh_token).select_related("application").first()
            application = rt.application if rt else None

        app_scopes = set(getattr(application, "scopes", None) or [])
        if not app_scopes:
            return original_list

        original_set = set(original_list)
        if "*" in original_set:
            return original_list

        narrowed = (original_set & app_scopes) | (original_set & self._ALWAYS_ALLOWED_SCOPES)
        if not narrowed:
            # Raised inside oauthlib's validate_token_request, which create_token_response
            # wraps and turns into an RFC 6749 `invalid_grant` 400 — not a 500.
            raise InvalidGrantError(
                description="Token scopes are no longer within the application's allowed scopes; re-authorize.",
                request=request,
            )
        return sorted(narrowed)

    def rotate_refresh_token(self, request) -> bool:
        """
        Don't rotate refresh tokens for dynamically registered (DCR/CIMD) clients.

        MCP clients (v0, Claude Code, Cursor, etc.) don't reliably save the new
        refresh token returned during rotation, causing sessions to break when
        they reuse the original token after the grace period. This matches the
        behavior of Google, Apple, Okta (for native apps), and AWS Cognito which
        all issue non-rotating refresh tokens.

        Non-dynamic OAuth clients still get rotation per the default setting.
        """
        if self._is_dynamic_client(request):
            return False
        return oauth2_settings.ROTATE_REFRESH_TOKEN

    def _get_token_expires_in(self, request) -> int:
        """
        Returns access token expiry in seconds.
        Dynamically registered (DCR/CIMD) clients get extended TTL since they
        don't reliably refresh. Impersonation-minted tokens are capped to the
        impersonation idle timeout so they can't outlive the admin's session.
        """
        if self._get_impersonator_id(request) is not None:
            return settings.IMPERSONATION_IDLE_TIMEOUT_SECONDS
        if self._is_dynamic_client(request):
            return 60 * 60 * 24 * 7  # 7 days
        return oauth2_settings.ACCESS_TOKEN_EXPIRE_SECONDS

    def save_bearer_token(self, token, request, *args, **kwargs):
        """
        Override to use custom token expiry for certain clients.
        Sets token["expires_in"] before calling parent, which uses this value
        when calculating the actual expiry datetime stored in the database.
        """
        expires_in = self._get_token_expires_in(request)
        token["expires_in"] = expires_in
        # Impersonation-minted tokens are short-lived and refresh-less so they can't
        # outlive the admin's impersonation session; clients re-auth instead.
        skip_refresh = self._should_skip_refresh_token(request)
        if skip_refresh:
            # Dropping the key short-circuits DOT's refresh-token branch so no
            # OAuthRefreshToken is created and none is returned in the response.
            token.pop("refresh_token", None)
        client_id = getattr(request.client, "client_id", None) if hasattr(request, "client") else None
        logger.info(
            "oauth_save_bearer_token",
            client_id_prefix=str(client_id)[:8] if client_id else "unknown",
            is_dcr_client=expires_in != oauth2_settings.ACCESS_TOKEN_EXPIRE_SECONDS,
            expires_in=expires_in,
            refresh_token_suppressed=skip_refresh,
            grant_type=getattr(request, "grant_type", "unknown"),
        )
        return super().save_bearer_token(token, request, *args, **kwargs)

    def get_additional_claims(self, request):
        return {
            "given_name": request.user.first_name,
            "family_name": request.user.last_name,
            "email": request.user.email,
            "email_verified": request.user.is_email_verified or False,
            "sub": str(request.user.uuid),
        }

    def _create_access_token(self, expires, request, token, source_refresh_token=None):
        id_token = token.get("id_token", None)
        if id_token:
            id_token = self._load_id_token(id_token)

        scoped_teams, scoped_organizations = self._get_scoped_teams_and_organizations(
            request, access_token=None, grant=None, refresh_token=source_refresh_token
        )

        return OAuthAccessToken.objects.create(
            user=request.user,
            scope=token.get("scope", None),
            expires=expires,
            token=token.get("access_token", None),
            id_token=id_token,
            application=request.client,
            source_refresh_token=source_refresh_token,
            scoped_teams=scoped_teams,
            scoped_organizations=scoped_organizations,
            impersonated_by_id=self._get_impersonator_id(request, refresh_token=source_refresh_token),
        )

    def _create_authorization_code(self, request, code, expires=None):
        scoped_teams, scoped_organizations = self._get_scoped_teams_and_organizations(
            request, access_token=None, grant=None, refresh_token=None
        )

        if not expires:
            expires = timezone.now() + timedelta(seconds=cast(int, oauth2_settings.AUTHORIZATION_CODE_EXPIRE_SECONDS))
        return OAuthGrant.objects.create(
            application=request.client,
            user=request.user,
            code=code.get("code", None),
            expires=expires,
            redirect_uri=request.redirect_uri,
            scope=" ".join(request.scopes),
            code_challenge=request.code_challenge or "",
            code_challenge_method=request.code_challenge_method or "",
            nonce=request.nonce or "",
            claims=json.dumps(request.claims or {}),
            scoped_teams=scoped_teams,
            scoped_organizations=scoped_organizations,
            impersonated_by_id=self._get_impersonator_id(request),
        )

    def _create_refresh_token(self, request, refresh_token_code, access_token, previous_refresh_token):
        if previous_refresh_token:
            token_family = previous_refresh_token.token_family
        else:
            token_family = uuid.uuid4()

        scoped_teams, scoped_organizations = self._get_scoped_teams_and_organizations(
            request, access_token=None, grant=None, refresh_token=previous_refresh_token
        )

        return OAuthRefreshToken.objects.create(
            user=request.user,
            token=refresh_token_code,
            application=request.client,
            access_token=access_token,
            token_family=token_family,
            scoped_teams=scoped_teams,
            scoped_organizations=scoped_organizations,
            # access_token already has impersonated_by computed via _create_access_token above —
            # propagate it so the refresh token is revoked alongside its access token.
            impersonated_by_id=access_token.impersonated_by_id if access_token else None,
        )

    def _get_impersonator_id(self, request, refresh_token: OAuthRefreshToken | None = None):
        """Resolve the impersonator (staff user) that should be tagged on a newly-minted token.

        Priority:
        1. `impersonated_by_id` attribute set on the oauthlib request — populated from the
           `credentials` dict during `/oauth/authorize` POST and GET auto-approval paths.
        2. The previous refresh token (token rotation inherits the tag).
        3. The authorization code grant referenced in the request body (code-exchange flow at
           `/oauth/token`, where there is no impersonated session to read from).

        Returns the staff user's id, or None if not impersonator-issued.
        """
        impersonator_id = getattr(request, "impersonated_by_id", None)
        if impersonator_id:
            return impersonator_id

        if refresh_token and refresh_token.impersonated_by_id:
            return refresh_token.impersonated_by_id

        # Code-exchange path: look up the grant via the `code` body param (same pattern
        # as `_get_scoped_teams_and_organizations`). `save_bearer_token` triggers up to
        # three calls per code exchange (`_get_token_expires_in`,
        # `_should_skip_refresh_token`, `_create_access_token`), so the grant lookup is
        # memoized on the oauthlib request.
        cached = getattr(request, "_posthog_impersonator_id", _IMPERSONATOR_CACHE_UNSET)
        if cached is not _IMPERSONATOR_CACHE_UNSET:
            return cached

        resolved: int | None = None
        if request.decoded_body:
            try:
                code = dict(request.decoded_body).get("code", None)
                if code:
                    grant = OAuthGrant.objects.only("impersonated_by_id").get(code=code)
                    resolved = grant.impersonated_by_id
            except OAuthGrant.DoesNotExist:
                pass

        request._posthog_impersonator_id = resolved
        return resolved

    def _get_scoped_teams_and_organizations(
        self,
        request,
        access_token: OAuthAccessToken | None,
        grant: OAuthGrant | None = None,
        refresh_token: OAuthRefreshToken | None = None,
    ):
        scoped_teams = None
        scoped_organizations = None

        if hasattr(request, "scoped_teams") and hasattr(request, "scoped_organizations"):
            scoped_teams = request.scoped_teams
            scoped_organizations = request.scoped_organizations
        elif access_token:
            scoped_teams = access_token.scoped_teams
            scoped_organizations = access_token.scoped_organizations
        elif refresh_token:
            scoped_teams = refresh_token.scoped_teams
            scoped_organizations = refresh_token.scoped_organizations
        elif grant:
            scoped_teams = grant.scoped_teams
            scoped_organizations = grant.scoped_organizations

        # Only fall back to the authorization code when no other scope source exists,
        # so a `code` param injected into a refresh request cannot escalate scopes.
        if scoped_teams is None and scoped_organizations is None and request.decoded_body:
            try:
                code = dict(request.decoded_body).get("code", None)
                if code:
                    code_grant = OAuthGrant.objects.get(code=code)
                    scoped_teams = code_grant.scoped_teams
                    scoped_organizations = code_grant.scoped_organizations
            except OAuthGrant.DoesNotExist:
                pass

        # Only raise when we have no scope information at all. A token scoped to just
        # teams or just organizations is valid — we treat `None` and `[]` as equivalent.
        if scoped_teams is None and scoped_organizations is None:
            raise OAuthToolkitError("Unable to find scoped_teams or scoped_organizations")

        return scoped_teams, scoped_organizations


class OAuthAuthorizationView(OAuthLibMixin, APIView):
    """
    This view handles incoming requests to /authorize.

    A GET request to /authorize validates the request and decides if it should:
        a) Redirect to the redirect_uri with error parameters
        b) Show an error state (e.g. when no redirect_uri is available)
        c) Show an authorize page

    A POST request is made to /authorize with allow=True if the user authorizes the request and allow=False otherwise.
    This returns a redirect_uri in it's response body to redirect the user to. In a successful flow, this will include a code
    parameter. In a failed flow, this will include error paramaters.
    """

    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    server_class = oauth2_settings.OAUTH2_SERVER_CLASS
    validator_class = oauth2_settings.OAUTH2_VALIDATOR_CLASS

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated()]
        return []

    @method_decorator(login_required)
    def get(self, request, *args, **kwargs):
        # Rate-limit new CIMD application creation by IP.
        # Must happen here (not in the OAuthValidator) because the validator
        # only receives an oauthlib Request which lacks request.META for IP extraction.
        client_id = request.query_params.get("client_id")
        if is_cimd_client_id(client_id) and not OAuthApplication.objects.filter(cimd_metadata_url=client_id).exists():
            for throttle_cls in CIMD_THROTTLE_CLASSES:
                throttle = throttle_cls()
                if not throttle.allow_request(request, view=self):
                    logger.warning("cimd_rate_limited", client_id=client_id, scope=throttle.scope, wait=throttle.wait())
                    return Response(
                        {
                            "error": "invalid_client",
                            "error_description": "Too many new client registrations. Try again later.",
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

        try:
            scopes, credentials = self.validate_authorization_request(request)
        except OAuthToolkitError as error:
            # Try to resolve the application so error redirects can use its allowed schemes
            # (e.g. vscode:// or other custom schemes registered by the client)
            error_application = None
            client_id = request.query_params.get("client_id")
            if client_id:
                try:
                    error_application = get_application_by_client_id(client_id)
                except OAuthApplication.DoesNotExist:
                    pass
            return self.error_response(error, application=error_application, state=request.query_params.get("state"))

        # Handle login prompt
        if request.query_params.get("prompt") == "login":
            return Response({"error": "login_required"}, status=status.HTTP_401_UNAUTHORIZED)

        # Get application and scope details
        try:
            application = get_application_by_client_id(credentials["client_id"])
        except OAuthApplication.DoesNotExist:
            return Response({"error": "Invalid client_id"}, status=status.HTTP_400_BAD_REQUEST)

        # Track OAuth authorization attempts with the authenticated user
        registration_type = "cimd" if application.is_cimd_client else ("dcr" if application.is_dcr_client else "manual")
        posthoganalytics.capture(
            distinct_id=str(request.user.distinct_id),
            event="oauth_authorization_requested",
            properties={
                "client_name": application.name,
                "app_id": str(application.pk),
                "registration_type": registration_type,
                "is_verified": application.is_verified,
                "is_first_party": application.is_first_party,
                **({"cimd_url": application.cimd_metadata_url} if application.is_cimd_client else {}),
            },
        )

        impersonator_id = _impersonator_id_for_request(request)
        credentials["impersonated_by_id"] = impersonator_id

        scope_str = " ".join(scopes)
        if is_read_only_impersonation(request):
            scope_str = downgrade_scopes_to_read_only(scope_str)

        # First-party apps skip consent screen entirely
        if application.is_first_party:
            if block := _impersonation_ai_processing_block(request):
                return block
            try:
                org_ids = request.user.organizations.values_list("id", flat=True)
                credentials["scoped_organizations"] = [str(org_id) for org_id in org_ids]
                credentials["scoped_teams"] = []

                uri, headers, body, status_code = self.create_authorization_response(
                    request=request, scopes=scope_str, credentials=credentials, allow=True
                )
                return self.redirect(uri, application)
            except OAuthToolkitError as error:
                return self.error_response(error, application, state=request.query_params.get("state"))

        # Check for auto-approval
        if request.query_params.get("approval_prompt", oauth2_settings.REQUEST_APPROVAL_PROMPT) == "auto":
            try:
                tokens = OAuthAccessToken.objects.filter(
                    user=request.user, application=application, expires__gt=timezone.now()
                ).all()

                # `scope_str` already reflects the read-only downgrade applied above (when
                # impersonating), so its split form is the effective set we need to match.
                for token in tokens:
                    if token.allow_scopes(scope_str.split()):
                        # Conservative fallback: check every org the impersonated user belongs to,
                        # not just the existing token's scope. Auto-approval during impersonation
                        # is a near-dead path (those tokens are short-lived, refresh-less, and
                        # revoked on logout), so the broader check isn't worth threading the
                        # matched token's scope through — the precise check lives in the POST path.
                        if block := _impersonation_ai_processing_block(request):
                            return block
                        uri, headers, body, status_code = self.create_authorization_response(
                            request=request, scopes=scope_str, credentials=credentials, allow=True
                        )
                        return self.redirect(uri, application)
            except OAuthToolkitError as error:
                return self.error_response(error, application, state=request.query_params.get("state"))

        return render_template(
            "index.html",
            request,
            context={
                "oauth_application": {
                    "name": application.name,
                    "client_id": application.client_id,
                    "is_verified": application.is_verified,
                    "logo_uri": application.logo_uri,
                }
            },
        )

    def post(self, request, *args, **kwargs):
        serializer = OAuthAuthorizationSerializer(data=request.data, context={"user": request.user})

        if not serializer.is_valid():
            client_id = request.data.get("client_id", "unknown")
            logger.warning("oauth_authorize_validation_error", client_id=client_id, errors=serializer.errors)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            application = get_application_by_client_id(serializer.validated_data["client_id"])
        except OAuthApplication.DoesNotExist:
            logger.warning("oauth_authorize_invalid_client", client_id=serializer.validated_data["client_id"])
            return Response({"error": "Invalid client_id"}, status=status.HTTP_400_BAD_REQUEST)

        credentials = {
            "client_id": serializer.validated_data["client_id"],
            "redirect_uri": serializer.validated_data["redirect_uri"],
            "response_type": serializer.validated_data.get("response_type"),
            "state": serializer.validated_data.get("state"),
            "scoped_organizations": serializer.validated_data.get("scoped_organizations"),
            "scoped_teams": serializer.validated_data.get("scoped_teams"),
            "impersonated_by_id": _impersonator_id_for_request(request),
        }

        # Add optional fields if present
        for field in ["code_challenge", "code_challenge_method", "nonce", "claims"]:
            if serializer.validated_data.get(field):
                credentials[field] = serializer.validated_data[field]

        scopes = serializer.validated_data.get("scope", "")
        if is_read_only_impersonation(request):
            scopes = downgrade_scopes_to_read_only(scopes)

        if serializer.validated_data["allow"]:
            if block := _impersonation_ai_processing_block(
                request,
                access_level=serializer.validated_data.get("access_level"),
                scoped_organization_ids=serializer.validated_data.get("scoped_organizations"),
                scoped_team_ids=serializer.validated_data.get("scoped_teams"),
            ):
                return block

        try:
            uri, headers, body, status_code = self.create_authorization_response(
                request=request,
                scopes=scopes,
                credentials=credentials,
                allow=serializer.validated_data["allow"],
            )

        except OAuthToolkitError as error:
            logger.warning(
                "oauth_authorize_toolkit_error",
                client_id=serializer.validated_data["client_id"],
                error=str(error),
            )
            return self.error_response(
                error, application, no_redirect=True, state=serializer.validated_data.get("state")
            )

        logger.debug("Success url for the request: %s", uri)

        redirect = self.redirect(uri, application)

        return Response(
            {
                "redirect_to": redirect.url,
            },
            status=status.HTTP_200_OK,
        )

    def redirect(self, redirect_to, application: OAuthApplication | None):
        if application is None:
            # The application can be None in case of an error during app validation.
            # Intentionally use stricter fallback (only http/https) since we can't verify
            # what schemes were pre-registered without a valid application.
            allowed_schemes = ["http", "https"]
        else:
            allowed_schemes = application.get_allowed_schemes()

        return OAuth2ResponseRedirect(redirect_to, allowed_schemes)

    def error_response(self, error, application, no_redirect=False, **kwargs):
        """
        Handle errors either by redirecting to redirect_uri with a json in the body containing
        error details or providing an error response
        """
        redirect, error_response = super().error_response(error, **kwargs)

        if redirect:
            if no_redirect:
                return Response(
                    {
                        "redirect_to": error_response["url"],
                    },
                    status=status.HTTP_200_OK,
                )
            try:
                return self.redirect(error_response["url"], application)
            except DisallowedRedirect:
                logger.warning(
                    "oauth_disallowed_redirect_scheme",
                    redirect_url=error_response["url"],
                )
                # Fall through to JSON error response below

        return Response(
            {
                "error": error_response["error"].error,
                "error_description": error_response["error"].description,
            },
            status=error_response["error"].status_code,
        )


class OAuthTokenView(TokenView):
    """
    OAuth2 Token endpoint.

    This implements a POST request with the following parameters:
    - grant_type: The type of grant to use - only "authorization_code" is supported.
    - code: The authorization code received from the /authorize request.
    - redirect_uri: The redirect URI to use - this is the same as the redirect_uri used in the authorization request.
    - code_verifier: The code verifier that was used to generate the code_challenge. The code_challenge is a sha256 hash
    of the code_verifier that was sent in the authorization request.

    RFC 6749 requires x-www-form-urlencoded, but this endpoint also accepts application/json for convenience.
    """

    def post(self, request, *args, **kwargs):
        if request.content_type == "application/json" and request.body:
            try:
                json_data = json.loads(request.body)
                request.POST = request.POST.copy()
                for key, value in json_data.items():
                    request.POST[key] = value
            except (json.JSONDecodeError, ValueError):
                return JsonResponse(
                    {"error": "invalid_request", "error_description": "Invalid JSON payload"},
                    status=400,
                )

        grant_type = request.POST.get("grant_type", "unknown")
        client_id = request.POST.get("client_id", "")
        client_id_prefix = client_id[:8] if client_id else "unknown"
        redirect_uri = request.POST.get("redirect_uri", "")
        logger.info(
            "oauth_token_request",
            grant_type=grant_type,
            client_id_prefix=client_id_prefix,
            redirect_uri=redirect_uri,
        )

        try:
            response = super().post(request, *args, **kwargs)
        except OAuthAccessToken.DoesNotExist:
            # django-oauth-toolkit's token response path re-reads the access token it
            # just issued; concurrent requests racing on the same authorization code
            # can surface this as DoesNotExist. Map to the standard 400 invalid_grant.
            logger.warning(
                "oauth_token_access_token_missing",
                grant_type=grant_type,
                client_id_prefix=client_id_prefix,
                redirect_uri=redirect_uri,
            )
            return JsonResponse(
                {
                    "error": "invalid_grant",
                    "error_description": "Authorization code is invalid or has already been used",
                },
                status=400,
            )
        except OperationalError as e:
            # PgBouncer kills queries that wait too long for a backend connection with
            # `query_wait_timeout`. The resulting OperationalError otherwise bubbles up
            # as an unhandled 500 — translate it into a retryable response.
            if "query_wait_timeout" not in str(e):
                raise
            logger.warning(
                "oauth_token_db_pool_pressure",
                grant_type=grant_type,
                client_id_prefix=client_id_prefix,
                redirect_uri=redirect_uri,
                error=str(e),
            )
            return _temporarily_unavailable_response()

        logger.info(
            "oauth_token_response",
            grant_type=grant_type,
            client_id_prefix=client_id_prefix,
            redirect_uri=redirect_uri,
            status=response.status_code,
        )

        if response.status_code == 200:
            try:
                response_data = json.loads(response.content)
                access_token_value = response_data.get("access_token")

                if access_token_value:
                    access_token = OAuthAccessToken.objects.get(token=access_token_value)
                    scoped_teams = list(access_token.scoped_teams or [])
                    scoped_organizations = list(access_token.scoped_organizations or [])

                    # First-party clients (PostHog Code) read scoped_teams from /oauth/token
                    # to populate the project selector. When the app is org-scoped only,
                    # access_token.scoped_teams is empty in the DB by design — derive teams
                    # from scoped_organizations so clients keep working without weakening
                    # the stored token scope.
                    # TODO(@charlesvien): remove this after a migration period in PostHog Code.
                    if (
                        not scoped_teams
                        and scoped_organizations
                        and access_token.application
                        and access_token.application.is_first_party
                    ):
                        scoped_teams = list(
                            Team.objects.filter(organization_id__in=scoped_organizations).values_list("pk", flat=True)
                        )

                    response_data["scoped_teams"] = scoped_teams
                    response_data["scoped_organizations"] = scoped_organizations

                    if region_info := get_region_info():
                        response_data.update(region_info)
                    return JsonResponse(response_data)
            except (json.JSONDecodeError, OAuthAccessToken.DoesNotExist) as e:
                logger.warning(f"Error adding scoped fields to token response: {e}")

        return response


class OAuthRevokeTokenView(RevokeTokenView):
    """
    OAuth2 Revoke Token endpoint.

    This endpoint is used to revoke a token. It implements a POST request with the following parameters:
    - token: The token to revoke.
    - token_type_hint(optional): The type of token to revoke - either "access_token" or "refresh_token"
    """

    pass


@method_decorator(csrf_exempt, name="dispatch")
@method_decorator(login_not_required, name="dispatch")
class OAuthIntrospectTokenView(ClientProtectedScopedResourceView):
    """
    Implements an endpoint for token introspection based
    on RFC 7662 https://rfc-editor.org/rfc/rfc7662.html

    To access this view the request must pass a OAuth2 Bearer Token
    which is allowed to access the scope `introspection`. Alternatively,
    if the client_id and client_secret are provided, the request is
    authenticated using client credentials and does not require the `introspection` scope.

    Self-introspection: An access token can always introspect itself without
    requiring the `introspection` scope. This allows MCP clients to discover
    their own token's scopes and permissions during initialization. Refresh
    tokens cannot self-introspect (they are not usable as Bearer credentials).
    """

    required_scopes = ["introspection"]

    def _is_self_introspection(self, request) -> bool:
        """
        Check if the request is an access token introspecting itself.

        Self-introspection only applies to access tokens — refresh tokens cannot
        be used as Bearer tokens per OAuth 2.0, so they never reach this path.
        """
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return False
        bearer_token = auth_header[7:]

        if request.method == "GET":
            token_to_introspect = request.GET.get("token")
        else:
            token_to_introspect = request.POST.get("token")
            if not token_to_introspect and request.content_type == "application/json" and request.body:
                try:
                    token_to_introspect = json.loads(request.body).get("token")
                except (json.JSONDecodeError, ValueError):
                    pass

        return bool(bearer_token and token_to_introspect and bearer_token == token_to_introspect)

    def verify_request(self, request):
        """
        Allow self-introspection without the introspection scope.

        Per RFC 7662, expired tokens should get {"active": false} rather than
        a 401/403 rejection. We allow self-introspection for any token that
        exists in the database, regardless of expiry. The get_token_response
        method handles returning active: false for expired tokens.
        """
        if self._is_self_introspection(request):
            bearer_token = request.headers.get("Authorization", "")[7:]
            token_checksum = hashlib.sha256(bearer_token.encode("utf-8")).hexdigest()
            try:
                OAuthAccessToken.objects.get(token_checksum=token_checksum)
            except OAuthAccessToken.DoesNotExist:
                return False, request
            return True, request
        return super().verify_request(request)

    @staticmethod
    def get_token_response(token_value=None):
        """
        RFC 7662 Token Introspection response.

        Per Section 2.2, inactive/unknown tokens MUST return {"active": false} with no
        additional information. Active tokens include the required "active" field plus
        optional fields (token_type, scope, client_id, exp) as applicable.

        We search across all supported token types (access then refresh) per Section 2.1:
        "If the server is unable to locate the token using the given hint, it MUST extend
        its search across all of its supported token types."
        """
        if not token_value:
            return JsonResponse({"active": False}, status=200)

        # Try access token first (indexed lookup via token_checksum)
        token_checksum = hashlib.sha256(token_value.encode("utf-8")).hexdigest()
        try:
            access_token = OAuthAccessToken.objects.get(token_checksum=token_checksum)
        except OAuthAccessToken.DoesNotExist:
            access_token = None

        if access_token:
            # RFC 7662 Section 2.2: expired tokens MUST return {"active": false}
            if not access_token.is_valid():
                return JsonResponse({"active": False}, status=200)
            data = {
                "active": True,
                "token_type": "access_token",
                "scope": access_token.scope,
                "scoped_teams": access_token.scoped_teams or [],
                "scoped_organizations": access_token.scoped_organizations or [],
                "exp": int(calendar.timegm(access_token.expires.timetuple())),
            }
            if access_token.application:
                data["client_id"] = access_token.application.client_id
                data["client_name"] = access_token.application.name
            return JsonResponse(data)

        # Fall back to refresh token (lookup by plaintext token — OAuthRefreshToken has
        # no token_checksum field; revoked tokens filtered via revoked__isnull=True)
        try:
            refresh_token = OAuthRefreshToken.objects.get(token=token_value, revoked__isnull=True)
        except OAuthRefreshToken.DoesNotExist:
            refresh_token = None

        if refresh_token:
            # Refresh tokens lack scope and exp fields on AbstractRefreshToken,
            # so we only return the fields that are available
            data = {
                "active": True,
                "token_type": "refresh_token",
                "scoped_teams": refresh_token.scoped_teams or [],
                "scoped_organizations": refresh_token.scoped_organizations or [],
            }
            if refresh_token.application:
                data["client_id"] = refresh_token.application.client_id
                data["client_name"] = refresh_token.application.name
            return JsonResponse(data)

        return JsonResponse({"active": False}, status=200)

    def get(self, request, *args, **kwargs):
        """
        Get the token from the URL parameters.
        URL: https://example.com/introspect?token=mF_9.B5f-4.1JqM
        """
        return self.get_token_response(request.GET.get("token", None))

    def post(self, request, *args, **kwargs):
        """
        Get the token from the body (supports both form-urlencoded and JSON).
        Form: token=mF_9.B5f-4.1JqM
        JSON: {"token": "mF_9.B5f-4.1JqM"}
        """
        token = request.POST.get("token")
        if not token and request.content_type == "application/json" and request.body:
            try:
                json_data = json.loads(request.body)
                token = json_data.get("token")
            except (json.JSONDecodeError, ValueError):
                pass
        return self.get_token_response(token)


class OAuthConnectDiscoveryInfoView(ConnectDiscoveryInfoView):
    pass


class OAuthJwksInfoView(JwksInfoView):
    pass


class OAuthUserInfoView(UserInfoView):
    pass


class OAuthAuthorizationServerMetadataView(APIView):
    """
    OAuth 2.0 Authorization Server Metadata (RFC 8414).

    This endpoint enables MCP clients to discover PostHog's OAuth endpoints,
    including the DCR registration endpoint for dynamic client registration.

    Unlike OIDC Discovery (/.well-known/openid-configuration), this endpoint
    is specifically for OAuth-only clients that need DCR support.
    """

    permission_classes = []
    authentication_classes = []

    def get(self, request, *args, **kwargs):
        # Build base URL from request
        base_url = request.build_absolute_uri("/").rstrip("/")

        all_scopes = get_oauth_scopes_supported()

        metadata = {
            # Required by RFC 8414
            "issuer": base_url,
            "authorization_endpoint": f"{base_url}/oauth/authorize/",
            "token_endpoint": f"{base_url}/oauth/token/",
            # Other endpoints
            "revocation_endpoint": f"{base_url}/oauth/revoke/",
            "introspection_endpoint": f"{base_url}/oauth/introspect/",
            "userinfo_endpoint": f"{base_url}/oauth/userinfo/",
            "jwks_uri": f"{base_url}/.well-known/jwks.json",
            # Dynamic Client Registration (RFC 7591)
            "registration_endpoint": f"{base_url}/oauth/register/",
            # Supported features
            "scopes_supported": all_scopes,
            "response_types_supported": ["code"],
            "response_modes_supported": ["query"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "token_endpoint_auth_methods_supported": ["none", "client_secret_post"],
            "code_challenge_methods_supported": ["S256"],
            # Service documentation
            "service_documentation": "https://posthog.com/docs/api",
            # Client ID Metadata Document (draft-ietf-oauth-client-id-metadata-document-00)
            "client_id_metadata_document_supported": True,
        }

        if region_info := get_region_info():
            metadata.update(region_info)

        return JsonResponse(metadata)
