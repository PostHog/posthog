from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect, JsonResponse
from django.views.decorators.csrf import csrf_exempt

import jwt
import requests
import structlog
from loginas.utils import is_impersonated_session
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.models.instance_setting import get_instance_settings
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.rate_limit import TeamsOAuthCallbackThrottle

from products.conversations.backend.models import TeamConversationsTeamsConfig
from products.conversations.backend.permissions import IsConversationsAdmin
from products.conversations.backend.support_teams import clear_teams_token, save_teams_token

logger = structlog.get_logger(__name__)

STATE_SALT = "conversations.supporthog.teams.oauth"
STATE_MAX_AGE_SECONDS = 10 * 60

TEAMS_OAUTH_SCOPES = (
    "Team.ReadBasic.All Channel.ReadBasic.All TeamsAppInstallation.ReadWriteForTeam "
    # User.ReadBasic.All is needed to resolve a Teams user's email via
    # GET /users/{aadObjectId} — User.Read alone only grants /me.
    "User.ReadBasic.All offline_access openid profile"
)
AZURE_AD_AUTHORIZE_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
AZURE_AD_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
AZURE_AD_OPENID_METADATA_URL = "https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration"

AZURE_AD_JWKS_URI_CACHE_KEY = "conversations:teams:azure_ad_jwks_uri"
AZURE_AD_JWKS_URI_CACHE_TTL_SECONDS = 60 * 60  # 1 hour
AZURE_AD_JWT_CLOCK_TOLERANCE_SECONDS = 5 * 60


def _get_azure_ad_jwks_client() -> jwt.PyJWKClient:
    """Fetch Azure AD's JWKS URI from OpenID metadata, cached for 1 hour."""
    cached_uri = cache.get(AZURE_AD_JWKS_URI_CACHE_KEY)
    if cached_uri:
        return jwt.PyJWKClient(cached_uri)

    resp = requests.get(AZURE_AD_OPENID_METADATA_URL, timeout=10)
    resp.raise_for_status()
    jwks_uri = resp.json().get("jwks_uri")
    if not jwks_uri:
        raise ValueError("Azure AD OpenID metadata missing jwks_uri")
    cache.set(AZURE_AD_JWKS_URI_CACHE_KEY, jwks_uri, AZURE_AD_JWKS_URI_CACHE_TTL_SECONDS)
    return jwt.PyJWKClient(jwks_uri)


def _verify_id_token(id_token: str, client_id: str) -> dict:
    """
    Verify the id_token returned by Azure AD's authorization-code exchange and
    return its claims. The `tid` claim is load-bearing — it routes every later
    inbound Bot Framework activity to the right PostHog team — so trusting an
    unverified payload here would be an attribution bypass if the id_token ever
    reached this code path from a less trustworthy source.

    We verify signature + audience + expiry. Issuer validation is skipped because
    Azure AD issues id_tokens with a tenant-specific issuer
    (``https://login.microsoftonline.com/<tid>/v2.0``) whose tenant we don't
    know up-front; signature + audience together are sufficient to prove the
    token was minted by Azure AD for this app.
    """
    jwks_client = _get_azure_ad_jwks_client()
    signing_key = jwks_client.get_signing_key_from_jwt(id_token)
    return jwt.decode(
        id_token,
        signing_key.key,
        algorithms=["RS256", "RS384", "RS512"],
        audience=client_id,
        options={
            "verify_exp": True,
            "verify_aud": True,
            "verify_iss": False,
        },
        leeway=AZURE_AD_JWT_CLOCK_TOLERANCE_SECONDS,
    )


def _append_query(url: str, params: dict[str, str]) -> str:
    parsed = urlparse(url)
    current = dict(parse_qsl(parsed.query, keep_blank_values=True))
    current.update(params)
    return urlunparse(parsed._replace(query=urlencode(current)))


def _get_callback_url() -> str:
    return urljoin(settings.SITE_URL.rstrip("/") + "/", "api/conversations/v1/teams/callback")


def _safe_next_path(team_id: int, next_path: str | None) -> str:
    default_path = f"/project/{team_id}/settings/support"
    if not next_path:
        return default_path
    if not next_path.startswith("/") or next_path.startswith("//"):
        return default_path
    return next_path


def _error_response(next_path: str | None, error_message: str, status_code: int) -> HttpResponse:
    if next_path:
        redirect_url = _append_query(
            urljoin(settings.SITE_URL.rstrip("/") + "/", next_path.lstrip("/")), {"error": error_message}
        )
        return HttpResponseRedirect(redirect_url)
    return JsonResponse({"error": error_message}, status=status_code)


class TeamsAuthorizeView(APIView):
    permission_classes = [IsAuthenticated, IsConversationsAdmin]

    def get(self, request: Request, *args, **kwargs) -> Response:
        support_settings = get_instance_settings(["SUPPORT_TEAMS_APP_ID"])
        client_id = str(support_settings.get("SUPPORT_TEAMS_APP_ID") or "")
        if not client_id:
            return Response({"error": "Support Teams OAuth client ID is not configured"}, status=503)

        user = request.user
        if not isinstance(user, User) or user.current_team is None:
            return Response({"error": "No current team selected"}, status=400)

        team_id = user.current_team.id
        user_id = getattr(user, "id", None)
        if not isinstance(user_id, int):
            return Response({"error": "Invalid user id"}, status=400)

        next_path = _safe_next_path(team_id, request.query_params.get("next"))
        state_payload = {
            "team_id": team_id,
            "user_id": user_id,
            "next": next_path,
        }
        state = signing.dumps(state_payload, salt=STATE_SALT)

        oauth_url = _append_query(
            AZURE_AD_AUTHORIZE_URL,
            {
                "client_id": client_id,
                "response_type": "code",
                "redirect_uri": _get_callback_url(),
                "scope": TEAMS_OAUTH_SCOPES,
                "state": state,
                "response_mode": "query",
            },
        )
        return Response({"url": oauth_url})


class TeamsDisconnectView(APIView):
    permission_classes = [IsAuthenticated, IsConversationsAdmin]

    def post(self, request: Request, *args, **kwargs) -> Response:
        user = request.user
        if not isinstance(user, User) or user.current_team is None:
            return Response({"error": "No current team selected"}, status=400)

        clear_teams_token(
            team=user.current_team,
            user=user,
            is_impersonated_session=is_impersonated_session(request),
        )
        return Response({"ok": True})


@csrf_exempt
def teams_oauth_callback(request: HttpRequest) -> HttpResponse:
    # IP throttle in front of any Azure AD token exchange — otherwise a stranger
    # can loop a valid `state` param and force us to make outbound POSTs.
    throttle = TeamsOAuthCallbackThrottle()
    if not throttle.allow_request(Request(request), view=None):  # type: ignore[arg-type]
        return JsonResponse({"error": "Too Many Requests"}, status=429)

    request_user = getattr(request, "user", None)
    request_user_id = getattr(request_user, "id", None)
    if not isinstance(request_user, User) or not isinstance(request_user_id, int):
        return JsonResponse({"error": "Authentication required"}, status=401)

    state_raw = request.GET.get("state")
    code = request.GET.get("code")
    oauth_error = request.GET.get("error")

    state_data: dict
    next_path: str | None = None

    try:
        if not state_raw:
            return JsonResponse({"error": "Missing OAuth state"}, status=400)
        state_data = signing.loads(state_raw, salt=STATE_SALT, max_age=STATE_MAX_AGE_SECONDS)
        next_path = state_data.get("next")
    except signing.SignatureExpired:
        return JsonResponse({"error": "OAuth state expired"}, status=400)
    except signing.BadSignature:
        return JsonResponse({"error": "Invalid OAuth state"}, status=400)

    if oauth_error:
        return _error_response(next_path, oauth_error, 400)

    if not code:
        return _error_response(next_path, "missing_code", 400)

    support_settings = get_instance_settings(["SUPPORT_TEAMS_APP_ID", "SUPPORT_TEAMS_APP_SECRET"])
    client_id = str(support_settings.get("SUPPORT_TEAMS_APP_ID") or "")
    client_secret = str(support_settings.get("SUPPORT_TEAMS_APP_SECRET") or "")
    if not client_id or not client_secret:
        return _error_response(next_path, "support_teams_not_configured", 503)

    # Exchange authorization code for tokens
    try:
        response = requests.post(
            AZURE_AD_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": _get_callback_url(),
                "grant_type": "authorization_code",
                "scope": TEAMS_OAUTH_SCOPES,
            },
            timeout=15,
        )
        payload = response.json()
    except Exception:
        return _error_response(next_path, "oauth_exchange_failed", 502)

    if response.status_code != 200 or not payload.get("access_token"):
        return _error_response(next_path, str(payload.get("error") or "oauth_exchange_failed"), 400)

    access_token = payload["access_token"]
    refresh_token = payload.get("refresh_token", "")
    expires_in = int(payload.get("expires_in", 3600))

    if not refresh_token:
        return _error_response(next_path, "missing_refresh_token", 400)

    id_token = payload.get("id_token", "")
    if not id_token:
        return _error_response(next_path, "missing_id_token", 400)

    try:
        id_claims = _verify_id_token(id_token, client_id)
    except jwt.InvalidTokenError as e:
        logger.warning("teams_id_token_invalid", error=str(e))
        return _error_response(next_path, "invalid_id_token", 400)
    except Exception:
        logger.exception("teams_id_token_verification_failed")
        return _error_response(next_path, "id_token_verification_failed", 502)

    tenant_id = id_claims.get("tid")
    if not isinstance(tenant_id, str) or not tenant_id:
        return _error_response(next_path, "missing_tenant_id", 400)

    user_id = state_data.get("user_id")
    team_id = state_data.get("team_id")
    if not isinstance(user_id, int) or not isinstance(team_id, int):
        return _error_response(next_path, "invalid_state_payload", 400)
    if request_user_id != user_id:
        return _error_response(next_path, "oauth_user_mismatch", 403)

    try:
        user = User.objects.get(id=user_id)
        team = Team.objects.get(id=team_id)
    except (User.DoesNotExist, Team.DoesNotExist):
        return _error_response(next_path, "team_or_user_not_found", 404)

    if not OrganizationMembership.objects.filter(user_id=user.id, organization_id=team.organization_id).exists():
        return _error_response(next_path, "forbidden_team_access", 403)

    try:
        with transaction.atomic():
            conflicting_config = (
                TeamConversationsTeamsConfig.objects.select_for_update()
                .filter(teams_tenant_id=tenant_id)
                .exclude(team_id=team.id)
                .first()
            )
            if conflicting_config:
                return _error_response(next_path, "teams_tenant_already_connected", 409)

            save_teams_token(
                team=team,
                user=user,
                is_impersonated_session=is_impersonated_session(request),
                access_token=access_token,
                refresh_token=refresh_token,
                tenant_id=tenant_id,
                expires_in=expires_in,
            )
    except IntegrityError:
        return _error_response(next_path, "teams_tenant_already_connected", 409)

    redirect_url = _append_query(
        urljoin(settings.SITE_URL.rstrip("/") + "/", _safe_next_path(team.id, next_path).lstrip("/")),
        {"supportTeamsConnected": "1"},
    )
    return HttpResponseRedirect(redirect_url)
