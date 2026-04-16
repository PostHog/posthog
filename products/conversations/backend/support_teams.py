"""
Token management and request validation for the SupportHog Microsoft Teams bot.

Handles:
- Bot Framework JWT validation (inbound activities from Azure Bot Service)
- Graph API token refresh (per-tenant, for listing teams/channels/users)
- Bot Framework token acquisition (global, for sending replies)
- Save/clear config with activity logging
"""

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast

from django.core.cache import cache
from django.db import transaction
from django.http import HttpRequest

import jwt
import requests
import structlog

from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.instance_setting import get_instance_settings
from posthog.models.team.extensions import get_or_create_team_extension

from products.conversations.backend.models import TeamConversationsTeamsConfig

if TYPE_CHECKING:
    from posthog.models.team.team import Team
    from posthog.models.user import User

logger = structlog.get_logger(__name__)

BOTFRAMEWORK_OPENID_METADATA_URL = "https://login.botframework.com/v1/.well-known/openidconfiguration"
BOTFRAMEWORK_TOKEN_ISSUER = "https://api.botframework.com"
BOTFRAMEWORK_TOKEN_URL = "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token"
GRAPH_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"

JWKS_CACHE_KEY = "supporthog:teams:jwks"
JWKS_CACHE_TTL_SECONDS = 60 * 60  # 1 hour
BOT_TOKEN_CACHE_KEY = "supporthog:teams:bot_token"
BOT_TOKEN_CACHE_TTL_SECONDS = 50 * 60  # 50 min (tokens live ~1h)

JWT_CLOCK_TOLERANCE_SECONDS = 5 * 60

# Must match products.conversations.backend.api.teams_oauth.TEAMS_OAUTH_SCOPES.
# Refresh requests should request the same scopes as the original authorization
# to avoid Azure AD scope-mismatch errors.
GRAPH_REFRESH_SCOPES = "Team.ReadBasic.All Channel.ReadBasic.All User.Read offline_access openid profile"


def get_teams_instance_settings() -> dict:
    return get_instance_settings(["SUPPORT_TEAMS_APP_ID", "SUPPORT_TEAMS_APP_SECRET"])


def get_bot_from_id() -> str:
    """
    Return the bot's Bot Framework channel account id (form `28:<app_id>`).

    Required by the Bot Connector REST API on outbound activities — Bot Connector
    does infer bot identity from the bearer token, but including `from.id` explicitly
    avoids undocumented fallback behavior and matches the Activity schema.
    """
    app_id = str(get_teams_instance_settings().get("SUPPORT_TEAMS_APP_ID") or "")
    if not app_id:
        raise ValueError("SUPPORT_TEAMS_APP_ID not configured")
    return f"28:{app_id}"


def _get_jwks_client() -> jwt.PyJWKClient:
    """Fetch the JWKS URI from Bot Framework OpenID metadata, cached for 1 hour."""
    cached_uri = cache.get(JWKS_CACHE_KEY)
    if cached_uri:
        return jwt.PyJWKClient(cached_uri)

    try:
        resp = requests.get(BOTFRAMEWORK_OPENID_METADATA_URL, timeout=10)
        resp.raise_for_status()
        jwks_uri = resp.json().get("jwks_uri")
        if jwks_uri:
            cache.set(JWKS_CACHE_KEY, jwks_uri, JWKS_CACHE_TTL_SECONDS)
            return jwt.PyJWKClient(jwks_uri)
    except Exception:
        logger.exception("teams_jwks_metadata_fetch_failed")

    raise ValueError("Failed to fetch Bot Framework JWKS metadata")


def validate_teams_request(request: HttpRequest) -> dict:
    """
    Validate an incoming Bot Framework activity by checking the JWT bearer token.

    Returns the decoded JWT claims on success.
    Raises ValueError on any validation failure.
    """
    settings = get_teams_instance_settings()
    app_id = str(settings.get("SUPPORT_TEAMS_APP_ID") or "")
    if not app_id:
        raise ValueError("SUPPORT_TEAMS_APP_ID not configured")

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise ValueError("Missing or invalid Authorization header")

    token = auth_header[7:]

    try:
        jwks_client = _get_jwks_client()
        signing_key = jwks_client.get_signing_key_from_jwt(token)

        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "RS384", "RS512"],
            issuer=BOTFRAMEWORK_TOKEN_ISSUER,
            audience=app_id,
            options={
                "verify_exp": True,
                "verify_iss": True,
                "verify_aud": True,
            },
            leeway=timedelta(seconds=JWT_CLOCK_TOLERANCE_SECONDS),
        )
        return claims
    except jwt.ExpiredSignatureError:
        raise ValueError("JWT token expired")
    except jwt.InvalidTokenError as e:
        raise ValueError(f"JWT validation failed: {e}")


def invalidate_bot_framework_token() -> None:
    """Drop the cached bot token — call after a 401 from Bot Connector."""
    cache.delete(BOT_TOKEN_CACHE_KEY)


def get_bot_framework_token(force_refresh: bool = False) -> str:
    """
    Get a Bot Framework token for sending replies using the global bot credentials.
    Cached in Redis for 50 minutes (tokens live ~1 hour).
    """
    if not force_refresh:
        cached = cache.get(BOT_TOKEN_CACHE_KEY)
        if cached:
            return cached

    settings = get_teams_instance_settings()
    app_id = str(settings.get("SUPPORT_TEAMS_APP_ID") or "")
    app_secret = str(settings.get("SUPPORT_TEAMS_APP_SECRET") or "")

    if not app_id or not app_secret:
        raise ValueError("Teams bot credentials not configured")

    resp = requests.post(
        BOTFRAMEWORK_TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": app_id,
            "client_secret": app_secret,
            "scope": "https://api.botframework.com/.default",
        },
        timeout=15,
    )

    if resp.status_code != 200:
        logger.warning("teams_bot_token_fetch_failed", status=resp.status_code, body=resp.text[:200])
        raise ValueError("Failed to get Bot Framework token")

    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise ValueError("Bot Framework token response missing access_token")

    expires_in = int(data.get("expires_in", 3600))
    ttl = min(expires_in - 600, BOT_TOKEN_CACHE_TTL_SECONDS)  # 10 min safety margin
    if ttl > 0:
        cache.set(BOT_TOKEN_CACHE_KEY, token, ttl)

    return token


def refresh_graph_token(config: TeamConversationsTeamsConfig) -> str:
    """
    Refresh the per-tenant Graph API access token using the stored refresh token.
    Updates the config in-place and saves to DB.
    Returns the fresh access token.
    """
    if not config.teams_graph_refresh_token:
        raise ValueError("No Graph API refresh token stored")

    settings = get_teams_instance_settings()
    app_id = str(settings.get("SUPPORT_TEAMS_APP_ID") or "")
    app_secret = str(settings.get("SUPPORT_TEAMS_APP_SECRET") or "")

    if not app_id or not app_secret:
        raise ValueError("Teams bot credentials not configured")

    resp = requests.post(
        GRAPH_TOKEN_URL,
        data={
            "client_id": app_id,
            "client_secret": app_secret,
            "refresh_token": config.teams_graph_refresh_token,
            "grant_type": "refresh_token",
            "scope": GRAPH_REFRESH_SCOPES,
        },
        timeout=15,
    )

    if resp.status_code != 200:
        logger.warning(
            "teams_graph_token_refresh_failed",
            team_id=config.team_id,
            status=resp.status_code,
        )
        raise ValueError("Failed to refresh Graph API token")

    data = resp.json()
    access_token = data.get("access_token")
    if not access_token:
        raise ValueError("Graph token response missing access_token")

    config.teams_graph_access_token = access_token
    if data.get("refresh_token"):
        config.teams_graph_refresh_token = data["refresh_token"]

    expires_in = int(data.get("expires_in", 3600))
    config.teams_token_expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
    config.save(update_fields=["teams_graph_access_token", "teams_graph_refresh_token", "teams_token_expires_at"])

    return access_token


def get_graph_token(team: "Team") -> str:
    """Get a valid Graph API token for the team, refreshing if expired."""
    config = get_or_create_team_extension(team, TeamConversationsTeamsConfig)

    if not config.teams_graph_access_token:
        raise ValueError("No Graph API token configured")

    # Refresh if expired or about to expire (5 min buffer)
    if config.teams_token_expires_at and config.teams_token_expires_at > datetime.now(UTC) + timedelta(minutes=5):
        return str(config.teams_graph_access_token)

    return refresh_graph_token(config)


def save_teams_token(
    *,
    team: "Team",
    user: "User",
    is_impersonated_session: bool,
    access_token: str,
    refresh_token: str,
    tenant_id: str,
    expires_in: int = 3600,
) -> None:
    config = get_or_create_team_extension(team, TeamConversationsTeamsConfig)
    old_tenant_id = config.teams_tenant_id

    settings = team.conversations_settings or {}
    settings["teams_enabled"] = True
    team.conversations_settings = settings

    with transaction.atomic():
        config.teams_tenant_id = tenant_id
        config.teams_graph_access_token = access_token
        config.teams_graph_refresh_token = refresh_token
        config.teams_token_expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
        config.save(
            update_fields=[
                "teams_tenant_id",
                "teams_graph_access_token",
                "teams_graph_refresh_token",
                "teams_token_expires_at",
            ]
        )
        team.save(update_fields=["conversations_settings"])

    log_activity(
        organization_id=team.organization_id,
        team_id=team.pk,
        user=cast("User", user),
        was_impersonated=is_impersonated_session,
        scope="Team",
        item_id=team.pk,
        activity="updated",
        detail=Detail(
            name=str(team.name),
            changes=[
                Change(
                    type="Team",
                    action="created" if old_tenant_id is None else "changed",
                    field="teams_tenant_id",
                    before=old_tenant_id,
                    after=tenant_id,
                ),
            ],
        ),
    )


def clear_teams_token(
    *,
    team: "Team",
    user: "User",
    is_impersonated_session: bool,
) -> None:
    config = get_or_create_team_extension(team, TeamConversationsTeamsConfig)
    old_tenant_id = config.teams_tenant_id
    if old_tenant_id is None:
        return

    settings = team.conversations_settings or {}
    settings["teams_enabled"] = False
    settings.pop("teams_team_id", None)
    settings.pop("teams_team_name", None)
    settings.pop("teams_channel_id", None)
    settings.pop("teams_channel_name", None)
    team.conversations_settings = settings

    with transaction.atomic():
        config.teams_tenant_id = None
        config.teams_graph_access_token = None
        config.teams_graph_refresh_token = None
        config.teams_token_expires_at = None
        config.save(
            update_fields=[
                "teams_tenant_id",
                "teams_graph_access_token",
                "teams_graph_refresh_token",
                "teams_token_expires_at",
            ]
        )
        team.save(update_fields=["conversations_settings"])

    log_activity(
        organization_id=team.organization_id,
        team_id=team.pk,
        user=cast("User", user),
        was_impersonated=is_impersonated_session,
        scope="Team",
        item_id=team.pk,
        activity="updated",
        detail=Detail(
            name=str(team.name),
            changes=[
                Change(
                    type="Team",
                    action="deleted",
                    field="teams_tenant_id",
                    before=old_tenant_id,
                    after=None,
                ),
            ],
        ),
    )
