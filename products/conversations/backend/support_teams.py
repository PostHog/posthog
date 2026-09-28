"""
Token management for the SupportHog Microsoft Teams bot.

Handles:
- The three values ingress verifies inbound Bot Framework activities with (signing keys, audience, issuers)
- Graph API token refresh (per-tenant, for listing teams/channels/users)
- Bot Framework token acquisition (global, for sending replies)
- Save/clear config with activity logging
"""

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast
from urllib.parse import urlparse

from django.core.cache import cache
from django.db import transaction

import redis
import requests
import structlog

from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.instance_setting import get_instance_settings
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.team.team import Team
from posthog.redis import get_client
from posthog.security.url_validation import is_url_allowed

from products.conversations.backend.models import TeamConversationsTeamsConfig

if TYPE_CHECKING:
    from posthog.models.user import User

logger = structlog.get_logger(__name__)

BOTFRAMEWORK_OPENID_METADATA_URL = "https://login.botframework.com/v1/.well-known/openidconfiguration"
BOTFRAMEWORK_MULTITENANT_TOKEN_URL = "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token"

# Allowlist of host suffixes that Microsoft uses for Bot Framework / Teams
# service endpoints. The `serviceUrl` inside inbound activities is plain JSON
# and is not covered by the inbound JWT signature, so we must validate it
# before sending the bot's bearer token to it.
#   - smba.trafficmanager.net        -> public Azure (regional subpaths: /teams/, /emea/, /uk/, ...)
#   - smba.infra.gcs.azure.us        -> Azure US Government
#   - smba.infra.gcs.azure.cn        -> Azure China (Mooncake)
#   - botframework.com / api.botframework.com -> Bot Framework direct endpoints
TRUSTED_TEAMS_SERVICE_URL_HOST_SUFFIXES = (
    "smba.trafficmanager.net",
    "smba.infra.gcs.azure.us",
    "smba.infra.gcs.azure.cn",
    "botframework.com",
    "api.botframework.com",
)
BOTFRAMEWORK_SINGLETENANT_TOKEN_URL_TEMPLATE = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
GRAPH_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"

JWKS_CACHE_KEY = "supporthog:teams:jwks"
JWKS_CACHE_TTL_SECONDS = 60 * 60  # 1 hour
BOT_TOKEN_CACHE_KEY = "supporthog:teams:bot_token"
BOT_TOKEN_CACHE_TTL_SECONDS = 50 * 60  # 50 min (tokens live ~1h)
GRAPH_REFRESH_LOCK_KEY_PREFIX = "supporthog:teams:graph_refresh_lock"
GRAPH_REFRESH_LOCK_TIMEOUT_SECONDS = 30
GRAPH_REFRESH_LOCK_BLOCKING_TIMEOUT_SECONDS = 10

# Must match products.conversations.backend.api.teams_oauth.TEAMS_OAUTH_SCOPES.
# Refresh requests should request the same scopes as the original authorization
# to avoid Azure AD scope-mismatch errors. TeamsAppInstallation.ReadWriteForTeam
# is deliberately omitted here — that's requested at authorize time but we don't
# need it on refresh for Graph user/channel reads.
#
# ChannelMessage.Read.All (delegated) powers the shared-channel message poller:
# shared/private channels never push ambient messages over the bot webhook, so we
# pull them from Graph's per-channel messages/delta as the connecting admin.
# ChannelMessage.Send (delegated) lets us post confirmation cards and agent replies
# back into shared channels via Graph, since the bot connector can't write there.
GRAPH_REFRESH_SCOPES = (
    "Team.ReadBasic.All Channel.ReadBasic.All User.ReadBasic.All "
    "ChannelMessage.Read.All ChannelMessage.Send offline_access openid profile"
)

# Tenants that authorized before ChannelMessage.Send was added never consented to it,
# and Azure AD rejects a refresh-token grant that requests an unconsented scope
# (AADSTS65001). We fall back to this read-only set so the poller keeps working for
# those tenants — sending will 403 until an admin reconnects and grants Send.
GRAPH_REFRESH_SCOPES_READONLY = (
    "Team.ReadBasic.All Channel.ReadBasic.All User.ReadBasic.All ChannelMessage.Read.All offline_access openid profile"
)

SUPPORTHOG_TEAMS_GRAPH_MESSAGE_KEY_PREFIX = "supporthog:teams:graph-msg:"
# Long TTL: polled thread replies and outbound Graph posts must stay deduped across
# the every-minute sweep (and Bot Framework-style retries on transient failures).
SUPPORTHOG_TEAMS_GRAPH_MESSAGE_TTL_SECONDS = 30 * 24 * 60 * 60


def _teams_graph_message_key(team_id: int, channel_id: str, message_id: str) -> str:
    # Graph chatMessage ids are tick-based and only unique within a channel, so the
    # dedup key must be scoped by team + channel to avoid cross-tenant collisions.
    return f"{SUPPORTHOG_TEAMS_GRAPH_MESSAGE_KEY_PREFIX}{team_id}:{channel_id}:{message_id}"


def mark_teams_graph_message_seen(team_id: int, channel_id: str, message_id: str) -> None:
    """Record a Graph chatMessage id so the shared-channel reply poller won't re-ingest it."""
    if not message_id or not channel_id:
        return
    cache.set(
        _teams_graph_message_key(team_id, channel_id, message_id),
        True,
        timeout=SUPPORTHOG_TEAMS_GRAPH_MESSAGE_TTL_SECONDS,
    )


def is_teams_graph_message_seen(team_id: int, channel_id: str, message_id: str) -> bool:
    """Return True if this Graph message id was already processed (read-only check)."""
    if not message_id or not channel_id:
        return False
    return cache.get(_teams_graph_message_key(team_id, channel_id, message_id)) is not None


def get_teams_instance_settings() -> dict:
    return get_instance_settings(
        [
            "SUPPORT_TEAMS_APP_ID",
            "SUPPORT_TEAMS_APP_SECRET",
            "SUPPORT_TEAMS_APP_TENANT_ID",
        ]
    )


def get_botframework_issuers() -> frozenset[str]:
    """
    Microsoft Teams / Bot Framework signs inbound activities with a service
    token issued by Bot Framework. We validate that issuer only.

    We deliberately do NOT accept the Azure-AD-issued variants
    (``https://sts.windows.net/<channel_tenant>/`` and
    ``https://login.microsoftonline.com/<channel_tenant>/v2.0``): their signing
    keys live in a different JWKS than the one we query
    (``login.botframework.com``), so any token carrying those issuers would
    fail signature verification anyway. Keeping them in the allowlist would be
    dead code at best and a foot-gun for any future change that trusts
    issuers from unverified claims.

    See: https://learn.microsoft.com/en-us/azure/bot-service/rest-api/bot-framework-rest-connector-authentication
    """
    return frozenset({"https://api.botframework.com"})


def get_teams_app_id() -> str | None:
    """The bot's app id, which is the audience every inbound activity token must carry."""
    app_id = str(get_teams_instance_settings().get("SUPPORT_TEAMS_APP_ID") or "")
    return app_id or None


def _allowed_jwks_uri(jwks_uri: str) -> str | None:
    """The URI, once it passes the SSRF allowlist, or None when it does not.

    The value comes out of a document Microsoft serves rather than out of PostHog's own
    configuration, so it is checked before anything fetches it, the same way
    ``posthog/api/id_jag.py`` checks the JWKS URI it discovers.
    """
    allowed, reason = is_url_allowed(jwks_uri)
    if not allowed:
        logger.warning("teams_jwks_uri_not_allowed", reason=reason)
        return None
    return jwks_uri


def get_botframework_jwks_uri() -> str | None:
    """The signing-key URI from the Bot Framework OpenID metadata document.

    Ingress calls this on every inbound activity, so the discovery result is cached for an hour
    rather than fetched each time.
    """
    cached_uri = cache.get(JWKS_CACHE_KEY)
    if cached_uri:
        # Only the discovery below writes this key, and it writes an allowed URI. Re-checking
        # here would put a DNS lookup on every inbound activity, and a lookup that failed would
        # read as an unconfigured instance.
        return str(cached_uri)

    try:
        response = requests.get(BOTFRAMEWORK_OPENID_METADATA_URL, timeout=10)
        response.raise_for_status()
        jwks_uri = response.json().get("jwks_uri")
    except Exception:
        logger.exception("teams_jwks_metadata_fetch_failed")
        return None

    if not jwks_uri:
        logger.warning("teams_jwks_metadata_without_uri")
        return None

    allowed_uri = _allowed_jwks_uri(str(jwks_uri))
    if allowed_uri:
        cache.set(JWKS_CACHE_KEY, allowed_uri, JWKS_CACHE_TTL_SECONDS)
    return allowed_uri


def is_trusted_teams_service_url(service_url: str) -> bool:
    """
    Return True iff `service_url` is an HTTPS URL whose host matches one of the
    Microsoft Bot Framework / Teams service endpoints we trust.

    The `serviceUrl` field inside an inbound Bot Framework activity is JSON and
    is not covered by the inbound JWT signature. This guard must be called
    before sending the bot's bearer token to it.
    """
    if not service_url:
        return False
    try:
        parsed = urlparse(service_url)
    except ValueError:
        return False
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in TRUSTED_TEAMS_SERVICE_URL_HOST_SUFFIXES)


def _get_bot_token_url() -> str:
    """
    Return the OAuth token endpoint for the bot.

    - MultiTenant (default): login.microsoftonline.com/botframework.com/...
    - SingleTenant (if SUPPORT_TEAMS_APP_TENANT_ID is set): login.microsoftonline.com/<tenantId>/...

    Bot Connector rejects multi-tenant tokens when the Azure Bot resource is
    registered as SingleTenant, so single-tenant deployments must set
    SUPPORT_TEAMS_APP_TENANT_ID to the tenant where the app is registered.
    """
    tenant_id = str(get_teams_instance_settings().get("SUPPORT_TEAMS_APP_TENANT_ID") or "").strip()
    if tenant_id:
        return BOTFRAMEWORK_SINGLETENANT_TOKEN_URL_TEMPLATE.format(tenant_id=tenant_id)
    return BOTFRAMEWORK_MULTITENANT_TOKEN_URL


def get_bot_from_id() -> str:
    """
    Return the bot's Bot Framework channel account id (form `28:<app_id>`).

    Required by the Bot Connector REST API on outbound activities — Bot Connector
    does infer bot identity from the bearer token, but including `from.id` explicitly
    avoids undocumented fallback behavior and matches the Activity schema.
    """
    app_id = get_teams_app_id()
    if not app_id:
        raise ValueError("SUPPORT_TEAMS_APP_ID not configured")
    return f"28:{app_id}"


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

    token_url = _get_bot_token_url()
    resp = requests.post(
        token_url,
        data={
            "grant_type": "client_credentials",
            "client_id": app_id,
            "client_secret": app_secret,
            "scope": "https://api.botframework.com/.default",
        },
        timeout=15,
    )

    if resp.status_code != 200:
        logger.warning(
            "teams_bot_token_fetch_failed", status=resp.status_code, body=resp.text[:200], token_url=token_url
        )
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

    def _post_refresh(scope: str) -> requests.Response:
        return requests.post(
            GRAPH_TOKEN_URL,
            data={
                "client_id": app_id,
                "client_secret": app_secret,
                "refresh_token": config.teams_graph_refresh_token,
                "grant_type": "refresh_token",
                "scope": scope,
            },
            timeout=15,
        )

    resp = _post_refresh(GRAPH_REFRESH_SCOPES)
    # Azure AD returns 400 (AADSTS65001 / invalid_scope) when a requested scope was
    # never consented — e.g. a tenant that connected before ChannelMessage.Send
    # existed. Retry read-only so polling survives (send stays 403 until reconnect).
    # Only 400 means scope denial; 429/5xx are transient and must NOT downgrade the
    # token to read-only, so they fall through to the failure path below.
    if resp.status_code == 400:
        logger.warning(
            "teams_graph_token_refresh_retry_readonly",
            team_id=config.team_id,
            status=resp.status_code,
        )
        resp = _post_refresh(GRAPH_REFRESH_SCOPES_READONLY)

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


def _graph_token_still_fresh(config: TeamConversationsTeamsConfig) -> bool:
    return bool(
        config.teams_graph_access_token
        and config.teams_token_expires_at
        and config.teams_token_expires_at > datetime.now(UTC) + timedelta(minutes=5)
    )


def get_graph_token(team: Team) -> str:
    """
    Get a valid Graph API token for the team, refreshing if expired.

    A per-team Redis lock serializes refreshes to avoid thundering-herd calls
    against Azure AD: refresh-token rotation means the first successful refresh
    invalidates the stored refresh token, so concurrent refreshers would race
    and all but one would fail.
    """
    config = get_or_create_team_extension(team, TeamConversationsTeamsConfig)

    if not config.teams_graph_access_token:
        raise ValueError("No Graph API token configured")

    if _graph_token_still_fresh(config):
        return str(config.teams_graph_access_token)

    lock_key = f"{GRAPH_REFRESH_LOCK_KEY_PREFIX}:{team.pk}"
    redis_client = get_client()
    lock = redis_client.lock(
        lock_key,
        timeout=GRAPH_REFRESH_LOCK_TIMEOUT_SECONDS,
        blocking_timeout=GRAPH_REFRESH_LOCK_BLOCKING_TIMEOUT_SECONDS,
    )
    try:
        acquired = lock.acquire(blocking=True)
    except redis.exceptions.LockError:
        acquired = False

    if not acquired:
        # Another worker is refreshing; re-read to pick up their result.
        config.refresh_from_db(
            fields=["teams_graph_access_token", "teams_graph_refresh_token", "teams_token_expires_at"]
        )
        if _graph_token_still_fresh(config):
            return str(config.teams_graph_access_token)
        raise ValueError("Graph API token refresh contended and still stale after wait")

    try:
        # Double-checked locking: the winner of the race already refreshed while
        # we were blocked on acquire(), so re-read before spending another call.
        config.refresh_from_db(
            fields=["teams_graph_access_token", "teams_graph_refresh_token", "teams_token_expires_at"]
        )
        if _graph_token_still_fresh(config):
            return str(config.teams_graph_access_token)
        return refresh_graph_token(config)
    finally:
        try:
            lock.release()
        except redis.exceptions.LockError:
            pass


def store_teams_service_url(tenant_id: str, service_url: str) -> None:
    """Persist the tenant's Bot Framework serviceUrl on its Teams config.

    The shared-channel poller pulls messages from Graph and has no inbound
    activity to read serviceUrl from, so it reuses this value — captured here
    from any inbound webhook activity (install welcome, help command, mention,
    or channel message) — to post confirmation cards and route agent replies.

    Writes only when the value changes (≈once per tenant) and is a no-op for
    tenants without a config row (e.g. AppSource validators pre-OAuth).
    """
    service_url = (service_url or "").rstrip("/")
    if not tenant_id or not service_url or not is_trusted_teams_service_url(service_url):
        return
    TeamConversationsTeamsConfig.objects.filter(teams_tenant_id=tenant_id).exclude(
        teams_service_url=service_url
    ).update(teams_service_url=service_url)


def save_teams_token(
    *,
    team: Team,
    user: "User",
    is_impersonated_session: bool,
    access_token: str,
    refresh_token: str,
    tenant_id: str,
    expires_in: int = 3600,
) -> None:
    config = get_or_create_team_extension(team, TeamConversationsTeamsConfig)
    old_tenant_id = config.teams_tenant_id

    with transaction.atomic():
        # Re-read the team row under FOR UPDATE so that a concurrent write to
        # conversations_settings (e.g. a Slack OAuth callback landing at the
        # same time) serializes behind us and can't clobber our merge. The
        # whole-blob read/modify/write pattern would otherwise silently drop
        # any field the other writer added while we held the pre-read copy.
        locked_team = Team.objects.select_for_update().only("conversations_settings").get(pk=team.pk)
        settings_blob = dict(locked_team.conversations_settings or {})
        settings_blob["teams_enabled"] = True
        locked_team.conversations_settings = settings_blob

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
        locked_team.save(update_fields=["conversations_settings"])
        team.conversations_settings = settings_blob

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
    team: Team,
    user: "User",
    is_impersonated_session: bool,
) -> None:
    config = get_or_create_team_extension(team, TeamConversationsTeamsConfig)
    old_tenant_id = config.teams_tenant_id
    if old_tenant_id is None:
        return

    with transaction.atomic():
        # See save_teams_token for the select_for_update rationale.
        locked_team = Team.objects.select_for_update().only("conversations_settings").get(pk=team.pk)
        settings_blob = dict(locked_team.conversations_settings or {})
        settings_blob["teams_enabled"] = False
        settings_blob.pop("teams_team_id", None)
        settings_blob.pop("teams_team_name", None)
        settings_blob.pop("teams_channel_id", None)
        settings_blob.pop("teams_channel_name", None)
        settings_blob.pop("teams_channels", None)
        locked_team.conversations_settings = settings_blob

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
        locked_team.save(update_fields=["conversations_settings"])
        team.conversations_settings = settings_blob

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
