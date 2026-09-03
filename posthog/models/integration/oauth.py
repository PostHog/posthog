"""Generic OAuth connect/refresh dispatcher shared by every generic-OAuth integration kind."""

import json
import time
import base64
import hashlib
import secrets
from dataclasses import field, replace
from datetime import timedelta
from typing import NoReturn
from urllib.parse import parse_qs, urlencode, urlparse

from django.conf import settings
from django.core.cache import cache

import requests
import structlog
from requests.auth import HTTPBasicAuth
from rest_framework.exceptions import ValidationError

from posthog.cache_utils import cache_for
from posthog.dataclasses import frozen
from posthog.egress.slack.observability import record_slack_api_response
from posthog.models.instance_setting import get_instance_settings
from posthog.models.user import User
from posthog.plugins.plugin_server_api import reload_integrations_on_workers
from posthog.schema_enums import SlackIntegrationScope
from posthog.scopes import get_oauth_scopes_supported

from . import common, model, refresh_tracking

logger = structlog.get_logger(__name__)


def _extract_oauth_error_message(res: requests.Response) -> str | None:
    """Pull a human-readable error from a failed OAuth token-exchange response.

    Most providers (Stripe, Google, etc.) return JSON of the shape
    `{"error": "...", "error_description": "..."}`. Fall back to the raw body
    (truncated) when the JSON has none of those fields, or when the body isn't
    JSON at all — better to dump a snippet than to swallow the cause silently
    and let the caller render a status-code-only message.
    """
    try:
        body = res.json()
    except Exception:
        text = (res.text or "").strip()
        return text[:300] if text else None

    if isinstance(body, dict):
        description = body.get("error_description") or body.get("message")
        code = body.get("error")
        if description and code:
            return f"{code}: {description}"
        if description:
            return str(description)
        if code:
            return str(code)

    # Unknown shape — surface a serialized snippet so the customer at least sees what came back.
    try:
        snippet = json.dumps(body)
    except (TypeError, ValueError):
        snippet = (res.text or "").strip()
    return snippet[:300] if snippet else None


def _raise_oauth_validation_error(kind: str, res: requests.Response) -> NoReturn:
    """Raise a ValidationError describing a failed OAuth token exchange.

    DRF turns ValidationError into a 400 with a populated `detail`, so the frontend toast renders
    a useful message instead of the generic "Something went wrong" fallback that follows from a
    bare Exception (which surfaces as a 500 with no detail).
    """
    provider_error = _extract_oauth_error_message(res)
    if provider_error:
        raise ValidationError(f"{kind} OAuth failed: {provider_error}")
    raise ValidationError(f"{kind} OAuth failed (status {res.status_code}). Please try again.")


# Instagram API with Facebook Login: the professional account is reached through the Facebook Page
# it is linked to, so the grant needs the page permissions as well as the Instagram ones. These are
# the Facebook Login permission names. The `instagram_business_*` names belong to Instagram Login, a
# separate flow with its own authorize host, so the dialog rejects them as invalid scopes here.
# https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login
INSTAGRAM_OAUTH_SCOPE = (
    "instagram_basic instagram_manage_insights instagram_manage_comments pages_show_list pages_read_engagement"
)


@frozen
class OauthConfig:
    authorize_url: str
    token_url: str
    client_id: str
    client_secret: str = field(repr=False)
    scope: str
    id_path: str
    name_path: str
    token_info_url: str | None = None
    token_info_graphql_query: str | None = None
    token_info_config_fields: list[str] | None = None
    additional_authorize_params: dict[str, str] | None = None
    client_id_fallback: str | None = None
    client_secret_fallback: str | None = field(default=None, repr=False)
    # When true, the authorize/token-exchange flow uses PKCE (RFC 7636, S256)
    pkce: bool = False
    # When set, disconnecting the integration also revokes the grant at the provider
    token_revoke_url: str | None = None


# Slack accepts comma-separated scopes on the OAuth authorize URL. The canonical list is the
# StrEnum declared in posthog/schema.py (generated from the SlackIntegrationScope enum in
# frontend/src/types.ts via `hogli build:schema`), so widening it on either side stays in sync.
#
# Every scope here is approved for the public Cloud app, so the same list is requested on every
# instance. Staging a scope Slack hasn't approved needs a DEV/local-only branch again — see the
# note by SlackIntegrationScope in frontend/src/types.ts.
POSTHOG_SLACK_SCOPE = ",".join(scope.value for scope in SlackIntegrationScope)


def _salesforce_instance_host(instance_url: str | None) -> str | None:
    # Every Salesforce-issued instance_url host ends in .salesforce.com: login/test, the
    # pod hosts (na1.salesforce.com, ...), and My Domain variants like
    # acme.my.salesforce.com and acme--sandbox.sandbox.my.salesforce.com. Validating at
    # the point of use means a stray write to integration.config can't cause the shared
    # SALESFORCE_CONSUMER_SECRET to be POSTed to an attacker origin during a refresh,
    # even if a future endpoint or admin tool exposes config as writable. Returns
    # "https://<host>" for a legitimate value, None otherwise (caller falls back to the
    # hardcoded prod URL).
    if not instance_url:
        return None
    try:
        parsed = urlparse(instance_url)
        # port/hostname/username/password are lazily parsed from netloc on access, and
        # port in particular raises ValueError on a non-numeric or out-of-range value
        # (e.g. https://host:abc/). Keep every derived-property read inside the try so a
        # poisoned instance_url can never crash the refresh sweep.
        if parsed.scheme != "https" or parsed.port is not None or parsed.username or parsed.password:
            return None
        host = (parsed.hostname or "").lower()
    except ValueError:
        return None
    if not host.endswith(".salesforce.com"):
        return None
    return f"https://{host}"


# Kinds authorized against Salesforce's OAuth server, so they share its quirks: the token
# response often omits expires_in, and refresh/revoke must go to the org's own instance host
# rather than the hardcoded login host (sandbox orgs reject the prod endpoints).
SALESFORCE_OAUTH_KINDS = ("salesforce", "pardot")

# PostHog connect. Unlike every other OAuth kind — which points at a fixed third-party provider —
# the `posthog` kind points at *another PostHog project*, in a region chosen by the user at connect
# time. That region may differ from the connecting project's or be the same one (same-region is just
# region == your own). So its authorize/token/userinfo URLs and client credentials are resolved per
# target region rather than baked into a static config. The connecting side is the OAuth client; the
# target region is the authorization server (its /oauth/authorize, /oauth/token, /oauth/userinfo,
# /oauth/revoke already exist). `openid`+`email` are always requested on top of the user-selected
# scopes so /oauth/userinfo can identify the connected account (`sub`/`email`).
POSTHOG_CONNECT_KIND = "posthog"

# `DEV` points at a local/self-hosted cell (`POSTHOG_CONNECT_BASE_URL_DEV` defaults to
# http://localhost:8000) and the token exchange is a server-side POST, so a production instance must
# never treat `DEV` as a real, connectable region — otherwise an org member could point the backend
# at a URL of their choosing. Gate it behind an explicit dev/test context rather than relying on the
# client id/secret env vars being unset.
_POSTHOG_CONNECT_ALLOW_DEV = bool(settings.DEBUG or settings.TEST or settings.E2E_TESTING)

POSTHOG_CONNECT_ALLOWED_REGIONS = ("US", "EU", *(("DEV",) if _POSTHOG_CONNECT_ALLOW_DEV else ()))

POSTHOG_CONNECT_DEFAULT_SCOPES = ("task:read", "task:write")

POSTHOG_CONNECT_IDENTITY_SCOPES = ("openid", "email")

# A connection can proxy any request the granted scopes allow, so the user may pick from the full set
# of user-grantable OAuth scopes (the same set the consent screen advertises — excludes internal,
# hidden, and privileged scopes). The real bound is enforced twice more downstream: the target cell's
# OAuthApplication.allowed_scopes at consent time, and the target's per-request scope checks. Identity
# scopes are auto-added and not part of this set.
POSTHOG_CONNECT_GRANTABLE_SCOPES = frozenset(get_oauth_scopes_supported())


# nosemgrep: tuple-return-prefer-dataclass -- private helper, both call sites a few lines below in this file
def _posthog_connect_target(region: str | None) -> tuple[str, str, str]:
    """Resolve (base_url, client_id, client_secret) for a remote target cell.

    Raises NotImplementedError for an unknown or unconfigured region so the connect/refresh
    paths fail closed (surfaced to the user as a reconnect error) rather than silently hitting
    the wrong cell.
    """
    normalized = (region or "").upper()
    if normalized == "DEV" and not _POSTHOG_CONNECT_ALLOW_DEV:
        # Defense in depth: even if a `DEV` region row somehow reaches here in production, refuse to
        # resolve it so the backend never POSTs a token exchange to the dev base URL.
        raise NotImplementedError("PostHog connect DEV region is only available in dev/test")
    targets = {
        "US": (
            settings.POSTHOG_CONNECT_BASE_URL_US,
            settings.POSTHOG_CONNECT_OAUTH_CLIENT_ID_US,
            settings.POSTHOG_CONNECT_OAUTH_CLIENT_SECRET_US,
        ),
        "EU": (
            settings.POSTHOG_CONNECT_BASE_URL_EU,
            settings.POSTHOG_CONNECT_OAUTH_CLIENT_ID_EU,
            settings.POSTHOG_CONNECT_OAUTH_CLIENT_SECRET_EU,
        ),
        "DEV": (
            settings.POSTHOG_CONNECT_BASE_URL_DEV,
            settings.POSTHOG_CONNECT_OAUTH_CLIENT_ID_DEV,
            settings.POSTHOG_CONNECT_OAUTH_CLIENT_SECRET_DEV,
        ),
    }
    if normalized not in targets:
        raise NotImplementedError(f"PostHog connect OAuth not supported for region {region!r}")
    base_url, client_id, client_secret = targets[normalized]
    if not base_url or not client_id or not client_secret:
        raise NotImplementedError(f"PostHog connect app not configured for region {normalized}")
    return base_url.rstrip("/"), client_id, client_secret


def posthog_connect_base_url(region: str | None) -> str:
    """Public base URL of a remote target cell (e.g. https://eu.posthog.com), for callers that
    need to reach its API with a `posthog` integration token. Raises for unknown/unconfigured regions."""
    base_url, _, _ = _posthog_connect_target(region)
    return base_url


class OauthIntegration:
    supported_kinds = [
        "slack",
        "posthog",
        "salesforce",
        "hubspot",
        "google-ads",
        "google-analytics",
        "google-calendar",
        "google-search-console",
        "google-sheets",
        "snapchat",
        "linkedin-ads",
        "reddit-ads",
        "tiktok-ads",
        "bing-ads",
        "meta-ads",
        "instagram",
        "intercom",
        "linear",
        "clickup",
        "jira",
        "pardot",
        "pinterest-ads",
        "stripe",
        "resend",
        "youtube-analytics",
    ]
    integration: model.Integration

    def __str__(self) -> str:
        return f"OauthIntegration(integration={self.integration.id}, kind={self.integration.kind}, team={self.integration.team_id})"

    def __init__(self, integration: model.Integration) -> None:
        self.integration = integration

    @classmethod
    @cache_for(timedelta(minutes=5))
    def oauth_config_for_kind(cls, kind: str, region: str | None = None) -> OauthConfig:
        # `region` only applies to the `posthog` remote kind, whose endpoints depend on the
        # target cell. cache_for keys on all args, so each (kind, region) pair caches separately;
        # every other kind is called without region and keeps its single cached entry.
        config = cls._build_oauth_config(kind, region)
        fallback = settings.OAUTH_CLIENT_FALLBACKS.get(kind)
        if fallback and fallback.get("client_secret"):
            config = replace(
                config,
                client_secret_fallback=fallback["client_secret"],
                client_id_fallback=fallback.get("client_id") or config.client_id,
            )
        return config

    @classmethod
    def _build_oauth_config(cls, kind: str, region: str | None = None) -> OauthConfig:
        if kind == "posthog":
            base_url, client_id, client_secret = _posthog_connect_target(region)
            return OauthConfig(
                authorize_url=f"{base_url}/oauth/authorize",
                token_url=f"{base_url}/oauth/token",
                token_info_url=f"{base_url}/oauth/userinfo",
                token_info_config_fields=["sub", "email"],
                token_revoke_url=f"{base_url}/oauth/revoke",
                client_id=client_id,
                client_secret=client_secret,
                # Default only; authorize_url overrides with the user-selected scopes (plus the
                # identity scopes). Token exchange/refresh don't send scope, so this is unused there.
                scope=" ".join([*POSTHOG_CONNECT_DEFAULT_SCOPES, *POSTHOG_CONNECT_IDENTITY_SCOPES]),
                id_path="sub",
                name_path="email",
                pkce=True,
            )
        if kind == "slack":
            from_settings = get_instance_settings(
                [
                    "SLACK_APP_CLIENT_ID",
                    "SLACK_APP_CLIENT_SECRET",
                    "SLACK_APP_SIGNING_SECRET",
                ]
            )

            if not from_settings["SLACK_APP_CLIENT_ID"] or not from_settings["SLACK_APP_CLIENT_SECRET"]:
                raise NotImplementedError("Slack app not configured")

            return OauthConfig(
                authorize_url="https://slack.com/oauth/v2/authorize",
                token_url="https://slack.com/api/oauth.v2.access",
                client_id=from_settings["SLACK_APP_CLIENT_ID"],
                client_secret=from_settings["SLACK_APP_CLIENT_SECRET"],
                scope=POSTHOG_SLACK_SCOPE,
                id_path="team.id",
                name_path="team.name",
            )
        elif kind == "salesforce":
            if not settings.SALESFORCE_CONSUMER_KEY or not settings.SALESFORCE_CONSUMER_SECRET:
                raise NotImplementedError("Salesforce app not configured")

            return OauthConfig(
                authorize_url="https://login.salesforce.com/services/oauth2/authorize",
                token_url="https://login.salesforce.com/services/oauth2/token",
                token_revoke_url="https://login.salesforce.com/services/oauth2/revoke",
                client_id=settings.SALESFORCE_CONSUMER_KEY,
                client_secret=settings.SALESFORCE_CONSUMER_SECRET,
                scope="full refresh_token",
                id_path="instance_url",
                name_path="instance_url",
                pkce=True,
            )
        elif kind == "salesforce-sandbox":
            if not settings.SALESFORCE_CONSUMER_KEY or not settings.SALESFORCE_CONSUMER_SECRET:
                raise NotImplementedError("Salesforce app not configured")

            return OauthConfig(
                authorize_url="https://test.salesforce.com/services/oauth2/authorize",
                token_url="https://test.salesforce.com/services/oauth2/token",
                token_revoke_url="https://test.salesforce.com/services/oauth2/revoke",
                client_id=settings.SALESFORCE_CONSUMER_KEY,
                client_secret=settings.SALESFORCE_CONSUMER_SECRET,
                scope="full refresh_token",
                id_path="instance_url",
                name_path="instance_url",
                pkce=True,
            )
        elif kind == "pardot":
            if not settings.SALESFORCE_CONSUMER_KEY or not settings.SALESFORCE_CONSUMER_SECRET:
                raise NotImplementedError("Salesforce app not configured")

            # Account Engagement (formerly Pardot) authorizes against Salesforce, so this reuses the
            # Salesforce connected app rather than registering a second one. It needs its own kind
            # because `pardot_api` is not covered by the `full` scope the `salesforce` kind requests:
            # a Salesforce integration authorized for the CRM cannot call the Account Engagement API,
            # and a token scoped for Account Engagement should not appear in the CRM picker.
            return OauthConfig(
                authorize_url="https://login.salesforce.com/services/oauth2/authorize",
                token_url="https://login.salesforce.com/services/oauth2/token",
                token_revoke_url="https://login.salesforce.com/services/oauth2/revoke",
                client_id=settings.SALESFORCE_CONSUMER_KEY,
                client_secret=settings.SALESFORCE_CONSUMER_SECRET,
                scope="pardot_api refresh_token",
                id_path="instance_url",
                name_path="instance_url",
                pkce=True,
            )
        elif kind == "hubspot":
            if not settings.HUBSPOT_APP_CLIENT_ID or not settings.HUBSPOT_APP_CLIENT_SECRET:
                raise NotImplementedError("Hubspot app not configured")

            return OauthConfig(
                authorize_url="https://app.hubspot.com/oauth/authorize",
                token_url="https://api.hubapi.com/oauth/v1/token",
                token_info_url="https://api.hubapi.com/oauth/v1/access-tokens/:access_token",
                token_info_config_fields=["hub_id", "hub_domain", "user", "user_id", "scopes"],
                client_id=settings.HUBSPOT_APP_CLIENT_ID,
                client_secret=settings.HUBSPOT_APP_CLIENT_SECRET,
                scope="tickets crm.objects.contacts.write sales-email-read crm.objects.companies.read crm.objects.deals.read crm.objects.contacts.read crm.objects.quotes.read crm.objects.companies.write",
                additional_authorize_params={
                    # NOTE: these scopes are only available on certain hubspot plans and as such are optional.
                    # crm.objects.leads.read is Sales Hub Pro+/Enterprise only — requesting it as a
                    # mandatory scope would fail the whole authorization for portals that lack it.
                    # The owners/commerce/product scopes are the same story: the data warehouse
                    # source offers those tables, but the objects only exist on portals with the
                    # matching hub, so they stay optional and their tables start deselected.
                    "optional_scope": (
                        "analytics.behavioral_events.send behavioral_events.event_definitions.read_write "
                        "crm.objects.leads.read crm.objects.owners.read crm.objects.line_items.read "
                        "crm.objects.products.read crm.objects.invoices.read crm.objects.orders.read "
                        "crm.objects.subscriptions.read crm.objects.commercepayments.read"
                    )
                },
                id_path="hub_id",
                name_path="hub_domain",
            )
        elif kind == "google-ads":
            if not settings.GOOGLE_ADS_APP_CLIENT_ID or not settings.GOOGLE_ADS_APP_CLIENT_SECRET:
                raise NotImplementedError("Google Ads app not configured")

            return OauthConfig(
                authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
                # forces the consent screen, otherwise we won't receive a refresh token
                additional_authorize_params={"access_type": "offline", "prompt": "consent"},
                token_info_url="https://openidconnect.googleapis.com/v1/userinfo",
                token_info_config_fields=["sub", "email"],
                token_url="https://oauth2.googleapis.com/token",
                client_id=settings.GOOGLE_ADS_APP_CLIENT_ID,
                client_secret=settings.GOOGLE_ADS_APP_CLIENT_SECRET,
                scope="https://www.googleapis.com/auth/adwords https://www.googleapis.com/auth/userinfo.email",
                id_path="sub",
                name_path="email",
            )
        elif kind == "google-analytics":
            if not settings.GOOGLE_ANALYTICS_APP_CLIENT_ID or not settings.GOOGLE_ANALYTICS_APP_CLIENT_SECRET:
                raise NotImplementedError("Google Analytics app not configured")

            return OauthConfig(
                authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
                # forces the consent screen, otherwise we won't receive a refresh token
                additional_authorize_params={"access_type": "offline", "prompt": "consent"},
                token_info_url="https://openidconnect.googleapis.com/v1/userinfo",
                token_info_config_fields=["sub", "email"],
                token_url="https://oauth2.googleapis.com/token",
                client_id=settings.GOOGLE_ANALYTICS_APP_CLIENT_ID,
                client_secret=settings.GOOGLE_ANALYTICS_APP_CLIENT_SECRET,
                scope="https://www.googleapis.com/auth/analytics.readonly https://www.googleapis.com/auth/userinfo.email",
                id_path="sub",
                name_path="email",
            )
        elif kind == "google-calendar":
            if not settings.GOOGLE_CALENDAR_APP_CLIENT_ID or not settings.GOOGLE_CALENDAR_APP_CLIENT_SECRET:
                raise NotImplementedError("Google Calendar app not configured")

            return OauthConfig(
                authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
                # forces the consent screen, otherwise we won't receive a refresh token
                additional_authorize_params={"access_type": "offline", "prompt": "consent"},
                token_info_url="https://openidconnect.googleapis.com/v1/userinfo",
                token_info_config_fields=["sub", "email"],
                token_url="https://oauth2.googleapis.com/token",
                client_id=settings.GOOGLE_CALENDAR_APP_CLIENT_ID,
                client_secret=settings.GOOGLE_CALENDAR_APP_CLIENT_SECRET,
                scope="https://www.googleapis.com/auth/calendar.readonly https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/userinfo.email",
                id_path="sub",
                name_path="email",
            )
        elif kind == "google-search-console":
            if not settings.GOOGLE_SEARCH_CONSOLE_APP_CLIENT_ID or not settings.GOOGLE_SEARCH_CONSOLE_APP_CLIENT_SECRET:
                raise NotImplementedError("Google Search Console app not configured")

            return OauthConfig(
                authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
                additional_authorize_params={"access_type": "offline", "prompt": "consent"},
                token_info_url="https://openidconnect.googleapis.com/v1/userinfo",
                token_info_config_fields=["sub", "email"],
                token_url="https://oauth2.googleapis.com/token",
                client_id=settings.GOOGLE_SEARCH_CONSOLE_APP_CLIENT_ID,
                client_secret=settings.GOOGLE_SEARCH_CONSOLE_APP_CLIENT_SECRET,
                scope="https://www.googleapis.com/auth/webmasters.readonly https://www.googleapis.com/auth/userinfo.email",
                id_path="sub",
                name_path="email",
            )
        elif kind == "google-sheets":
            if not settings.SOCIAL_AUTH_GOOGLE_OAUTH2_KEY or not settings.SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET:
                raise NotImplementedError("Google Sheets app not configured")

            return OauthConfig(
                authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
                # forces the consent screen, otherwise we won't receive a refresh token
                additional_authorize_params={"access_type": "offline", "prompt": "consent"},
                token_info_url="https://openidconnect.googleapis.com/v1/userinfo",
                token_info_config_fields=["sub", "email"],
                token_url="https://oauth2.googleapis.com/token",
                client_id=settings.SOCIAL_AUTH_GOOGLE_OAUTH2_KEY,
                client_secret=settings.SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET,
                scope="https://www.googleapis.com/auth/spreadsheets https://www.googleapis.com/auth/userinfo.email",
                id_path="sub",
                name_path="email",
            )
        elif kind == "youtube-analytics":
            if not settings.YOUTUBE_ANALYTICS_APP_CLIENT_ID or not settings.YOUTUBE_ANALYTICS_APP_CLIENT_SECRET:
                raise NotImplementedError("YouTube Analytics app not configured")

            return OauthConfig(
                authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
                # forces the consent screen, otherwise we won't receive a refresh token
                additional_authorize_params={"access_type": "offline", "prompt": "consent"},
                token_info_url="https://openidconnect.googleapis.com/v1/userinfo",
                token_info_config_fields=["sub", "email"],
                token_url="https://oauth2.googleapis.com/token",
                client_id=settings.YOUTUBE_ANALYTICS_APP_CLIENT_ID,
                client_secret=settings.YOUTUBE_ANALYTICS_APP_CLIENT_SECRET,
                # `yt-analytics.readonly` reads the reports; `youtube.readonly` lists the account's
                # channels so the user picks one instead of hunting for its ID. Channel reports carry
                # no revenue metrics, so `yt-analytics-monetary.readonly` is deliberately not asked for.
                scope=(
                    "https://www.googleapis.com/auth/yt-analytics.readonly "
                    "https://www.googleapis.com/auth/youtube.readonly "
                    "https://www.googleapis.com/auth/userinfo.email"
                ),
                id_path="sub",
                name_path="email",
            )
        elif kind == "snapchat":
            if not settings.SNAPCHAT_APP_CLIENT_ID or not settings.SNAPCHAT_APP_CLIENT_SECRET:
                raise NotImplementedError("Snapchat app not configured")

            return OauthConfig(
                authorize_url="https://accounts.snapchat.com/accounts/oauth2/auth",
                token_url="https://accounts.snapchat.com/accounts/oauth2/token",
                token_info_url="https://adsapi.snapchat.com/v1/me",
                token_info_config_fields=["me.id", "me.email"],
                client_id=settings.SNAPCHAT_APP_CLIENT_ID,
                client_secret=settings.SNAPCHAT_APP_CLIENT_SECRET,
                scope="snapchat-offline-conversions-api snapchat-marketing-api",
                id_path="me.id",
                name_path="me.email",
            )
        elif kind == "linkedin-ads":
            if not settings.LINKEDIN_APP_CLIENT_ID or not settings.LINKEDIN_APP_CLIENT_SECRET:
                raise NotImplementedError("LinkedIn Ads app not configured")

            # Note: We extract user info from id_token JWT instead of calling token_info_url
            # because LinkedIn's /v2/userinfo endpoint has intermittent issues returning
            # REVOKED_ACCESS_TOKEN errors for valid tokens. See JWT extraction below.
            return OauthConfig(
                authorize_url="https://www.linkedin.com/oauth/v2/authorization",
                token_url="https://www.linkedin.com/oauth/v2/accessToken",
                client_id=settings.LINKEDIN_APP_CLIENT_ID,
                client_secret=settings.LINKEDIN_APP_CLIENT_SECRET,
                scope="r_ads rw_conversions r_ads_reporting openid profile email",
                id_path="sub",
                name_path="email",
            )
        elif kind == "bing-ads":
            if not settings.BING_ADS_CLIENT_ID or not settings.BING_ADS_CLIENT_SECRET:
                raise NotImplementedError("Bing Ads app not configured")

            return OauthConfig(
                authorize_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
                token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
                client_id=settings.BING_ADS_CLIENT_ID,
                client_secret=settings.BING_ADS_CLIENT_SECRET,
                scope="https://ads.microsoft.com/msads.manage offline_access openid profile",
                id_path="id",
                name_path="userPrincipalName",
            )
        elif kind == "intercom":
            if not settings.INTERCOM_APP_CLIENT_ID or not settings.INTERCOM_APP_CLIENT_SECRET:
                raise NotImplementedError("Intercom app not configured")

            return OauthConfig(
                authorize_url="https://app.intercom.com/oauth",
                token_url="https://api.intercom.io/auth/eagle/token",
                token_info_url="https://api.intercom.io/me",
                token_info_config_fields=["id", "email", "app.region"],
                client_id=settings.INTERCOM_APP_CLIENT_ID,
                client_secret=settings.INTERCOM_APP_CLIENT_SECRET,
                scope="",
                id_path="id",
                name_path="email",
            )
        elif kind == "linear":
            if not settings.LINEAR_APP_CLIENT_ID or not settings.LINEAR_APP_CLIENT_SECRET:
                raise NotImplementedError("Linear app not configured")

            return OauthConfig(
                authorize_url="https://linear.app/oauth/authorize",
                additional_authorize_params={"actor": "application"},
                token_url="https://api.linear.app/oauth/token",
                token_info_url="https://api.linear.app/graphql",
                token_info_graphql_query="{ viewer { organization { id name urlKey } } }",
                token_info_config_fields=[
                    "data.viewer.organization.id",
                    "data.viewer.organization.name",
                    "data.viewer.organization.urlKey",
                ],
                client_id=settings.LINEAR_APP_CLIENT_ID,
                client_secret=settings.LINEAR_APP_CLIENT_SECRET,
                scope="read issues:create",
                id_path="data.viewer.organization.id",
                name_path="data.viewer.organization.name",
            )
        elif kind == "meta-ads":
            if not settings.META_ADS_APP_CLIENT_ID or not settings.META_ADS_APP_CLIENT_SECRET:
                raise NotImplementedError("Meta Ads app not configured")

            return OauthConfig(
                authorize_url=f"https://www.facebook.com/{common.META_GRAPH_API_VERSION}/dialog/oauth",
                token_url=f"https://graph.facebook.com/{common.META_GRAPH_API_VERSION}/oauth/access_token",
                token_info_url=f"https://graph.facebook.com/{common.META_GRAPH_API_VERSION}/me",
                token_info_config_fields=["id", "name", "email"],
                client_id=settings.META_ADS_APP_CLIENT_ID,
                client_secret=settings.META_ADS_APP_CLIENT_SECRET,
                scope="ads_read",
                id_path="id",
                name_path="name",
            )
        elif kind == "instagram":
            if not settings.INSTAGRAM_APP_CLIENT_ID or not settings.INSTAGRAM_APP_CLIENT_SECRET:
                raise NotImplementedError("Instagram app not configured")

            # Same Facebook Login endpoints as Meta Ads, and the credentials may even be the same
            # Meta app, but the two grants request different scopes so they stay separate kinds.
            # The token response carries no account identifier, so id/name come from `/me`.
            return OauthConfig(
                authorize_url=f"https://www.facebook.com/{common.META_GRAPH_API_VERSION}/dialog/oauth",
                token_url=f"https://graph.facebook.com/{common.META_GRAPH_API_VERSION}/oauth/access_token",
                token_info_url=f"https://graph.facebook.com/{common.META_GRAPH_API_VERSION}/me",
                token_info_config_fields=["id", "name"],
                client_id=settings.INSTAGRAM_APP_CLIENT_ID,
                client_secret=settings.INSTAGRAM_APP_CLIENT_SECRET,
                scope=INSTAGRAM_OAUTH_SCOPE,
                id_path="id",
                name_path="name",
            )
        elif kind == "reddit-ads":
            if not settings.REDDIT_ADS_CLIENT_ID or not settings.REDDIT_ADS_CLIENT_SECRET:
                raise NotImplementedError("Reddit Ads app not configured")

            return OauthConfig(
                authorize_url="https://www.reddit.com/api/v1/authorize",
                token_url="https://www.reddit.com/api/v1/access_token",
                client_id=settings.REDDIT_ADS_CLIENT_ID,
                client_secret=settings.REDDIT_ADS_CLIENT_SECRET,
                scope="read adsread adsconversions history adsedit",
                id_path="reddit_user_id",  # We'll extract this from JWT
                # ads-api /me returns the human-readable username under the granted ads scopes
                # (oauth.reddit.com/api/v1/me would need the extra `identity` scope), wrapped in a
                # `data` object. Falls back to the JWT user id when absent.
                token_info_url="https://ads-api.reddit.com/api/v3/me",
                token_info_config_fields=["data.reddit_username"],
                name_path="data.reddit_username",
                additional_authorize_params={"duration": "permanent"},
            )
        elif kind == "tiktok-ads":
            if not settings.TIKTOK_ADS_CLIENT_ID or not settings.TIKTOK_ADS_CLIENT_SECRET:
                raise NotImplementedError("TikTok Ads app not configured")

            return OauthConfig(
                authorize_url="https://business-api.tiktok.com/portal/auth",
                token_url="https://business-api.tiktok.com/open_api/v1.3/oauth2/access_token/",
                client_id=settings.TIKTOK_ADS_CLIENT_ID,
                client_secret=settings.TIKTOK_ADS_CLIENT_SECRET,
                scope="",
                id_path="data.advertiser_ids",
                name_path="data.advertiser_ids",
            )
        elif kind == "clickup":
            if not settings.CLICKUP_APP_CLIENT_ID or not settings.CLICKUP_APP_CLIENT_SECRET:
                raise NotImplementedError("ClickUp app not configured")

            return OauthConfig(
                authorize_url="https://app.clickup.com/api",
                token_url="https://api.clickup.com/api/v2/oauth/token",
                token_info_url="https://api.clickup.com/api/v2/user",
                token_info_config_fields=["user.id", "user.email"],
                client_id=settings.CLICKUP_APP_CLIENT_ID,
                client_secret=settings.CLICKUP_APP_CLIENT_SECRET,
                scope="",
                id_path="user.id",
                name_path="user.email",
            )
        elif kind == "jira":
            if not settings.ATLASSIAN_APP_CLIENT_ID or not settings.ATLASSIAN_APP_CLIENT_SECRET:
                raise NotImplementedError("Atlassian/Jira app not configured")

            return OauthConfig(
                authorize_url="https://auth.atlassian.com/authorize",
                additional_authorize_params={"audience": "api.atlassian.com", "prompt": "consent"},
                token_url="https://auth.atlassian.com/oauth/token",
                token_info_url="https://api.atlassian.com/oauth/token/accessible-resources",
                token_info_config_fields=[],  # Handled specially in integration_from_oauth_response
                client_id=settings.ATLASSIAN_APP_CLIENT_ID,
                client_secret=settings.ATLASSIAN_APP_CLIENT_SECRET,
                scope="read:jira-work write:jira-work offline_access",
                id_path="cloud_id",
                name_path="site_name",
            )
        elif kind == "pinterest-ads":
            if not settings.PINTEREST_ADS_CLIENT_ID or not settings.PINTEREST_ADS_CLIENT_SECRET:
                raise NotImplementedError("Pinterest Ads app not configured")

            return OauthConfig(
                authorize_url="https://www.pinterest.com/oauth/",
                token_url="https://api.pinterest.com/v5/oauth/token",
                token_info_url="https://api.pinterest.com/v5/user_account",
                token_info_config_fields=["id", "username", "business_name"],
                client_id=settings.PINTEREST_ADS_CLIENT_ID,
                client_secret=settings.PINTEREST_ADS_CLIENT_SECRET,
                scope="ads:read user_accounts:read",
                id_path="id",
                name_path="username",
            )
        elif kind == "stripe":
            if not settings.STRIPE_APP_CLIENT_ID or not settings.STRIPE_APP_SECRET_KEY:
                raise NotImplementedError("Stripe app not configured")

            client_id = settings.STRIPE_APP_CLIENT_ID
            client_secret = settings.STRIPE_APP_SECRET_KEY

            authorize_url = (
                settings.STRIPE_APP_OVERRIDE_AUTHORIZE_URL or "https://marketplace.stripe.com/oauth/v2/authorize"
            )
            return OauthConfig(
                authorize_url=authorize_url,
                token_url="https://api.stripe.com/v1/oauth/token",
                client_id=client_id,
                client_secret=client_secret,
                scope="",
                id_path="stripe_user_id",
                name_path="account_name",
            )
        elif kind == "resend":
            if not settings.RESEND_APP_CLIENT_ID or not settings.RESEND_APP_CLIENT_SECRET:
                raise NotImplementedError("Resend app not configured")

            # Resend implements OAuth 2.1: PKCE is required, and access tokens are short-lived
            # (~15m) JWTs while refresh tokens rotate on every use. We register as a confidential
            # client (token_endpoint_auth_method=client_secret_post), so the standard client_secret
            # token-exchange/refresh path applies on top of PKCE. `full_access` is the scope needed
            # to read the warehouse resources (emails/audiences/contacts/domains/broadcasts).
            # The token response carries no account identifier, so id/name are derived from the
            # access-token JWT below (see the resend branch in integration_from_oauth_response).
            # Every OAuth endpoint lives on api.resend.com, including the authorize endpoint that
            # the user's browser opens. This is what Resend publishes at
            # https://api.resend.com/.well-known/oauth-authorization-server. The dashboard host
            # resend.com has no /oauth/authorize route and answers with its own 404 page, so do
            # not move the authorize URL there to match the address users see in the dashboard.
            return OauthConfig(
                authorize_url="https://api.resend.com/oauth/authorize",
                token_url="https://api.resend.com/oauth/token",
                token_revoke_url="https://api.resend.com/oauth/revoke",
                client_id=settings.RESEND_APP_CLIENT_ID,
                client_secret=settings.RESEND_APP_CLIENT_SECRET,
                scope="full_access",
                pkce=True,
                id_path="resend_account_id",
                name_path="resend_account_name",
            )

        raise NotImplementedError(f"Oauth config for kind {kind} not implemented")

    @classmethod
    def redirect_uri(cls, kind: str) -> str:
        # The redirect uri is fixed but should always be https and include the "next" parameter for the frontend to redirect
        if settings.DEBUG and settings.NGROK_URL:
            return f"{settings.NGROK_URL}/integrations/{kind}/callback"
        return f"{settings.SITE_URL.replace('http://', 'https://')}/integrations/{kind}/callback"

    @classmethod
    def authorize_url(
        cls,
        kind: str,
        token: str,
        next: str = "",
        *,
        region: str | None = None,
        scopes: list[str] | None = None,
        team_id: int | None = None,
    ) -> str:
        oauth_config = cls.oauth_config_for_kind(kind, region)

        # Carry the initiating team through the OAuth round-trip. The fixed callback URL is not
        # project-scoped, so without this the SPA re-resolves to the user's default team on
        # reload and the integration lands on the wrong project.
        state_payload: dict[str, str] = {"next": next, "token": token}
        if team_id is not None:
            state_payload["team_id"] = str(team_id)

        scope = oauth_config.scope
        if kind == "posthog":
            # The target cell is the authorization server, so the callback (which runs on the
            # connecting cell) needs to know which region to exchange the code against — carry it
            # in state. Always append the identity scopes so /oauth/userinfo can name the account.
            state_payload["region"] = (region or "").upper()
            requested = list(scopes) if scopes else list(POSTHOG_CONNECT_DEFAULT_SCOPES)
            scope = " ".join(dict.fromkeys([*requested, *POSTHOG_CONNECT_IDENTITY_SCOPES]))

        if kind == "tiktok-ads":
            # TikTok uses different parameter names
            query_params = {
                "app_id": oauth_config.client_id,
                "redirect_uri": cls.redirect_uri(kind),
                "state": urlencode(state_payload),
            }
        else:
            query_params = {
                "client_id": oauth_config.client_id,
                "scope": scope,
                "redirect_uri": cls.redirect_uri(kind),
                "response_type": "code",
                "state": urlencode(state_payload),
                **(oauth_config.additional_authorize_params or {}),
            }

            if oauth_config.pkce:
                # The verifier is cached against the state token so the token exchange —
                # a separate request via the frontend callback — can retrieve it.
                code_verifier = secrets.token_urlsafe(64)
                code_challenge = (
                    base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).rstrip(b"=").decode()
                )
                query_params["code_challenge"] = code_challenge
                query_params["code_challenge_method"] = "S256"
                cache.set(f"oauth_pkce_verifier/{token}", code_verifier, timeout=60 * 5)

        return f"{oauth_config.authorize_url}?{urlencode(query_params)}"

    @classmethod
    def integration_from_oauth_response(
        cls, kind: str, team_id: int, created_by: User, params: dict[str, str]
    ) -> model.Integration:
        region: str | None = None
        if kind == "posthog":
            # The target region was stashed in state at authorize time; the token exchange must hit
            # that same cell. Missing/invalid region fails closed via _posthog_connect_target.
            region = (parse_qs(params.get("state", "")).get("region", [""])[0] or "").upper()

        oauth_config = cls.oauth_config_for_kind(kind, region)

        code_verifier: str | None = None
        if oauth_config.pkce:
            state_token = parse_qs(params.get("state", "")).get("token", [""])[0]
            if state_token:
                verifier_cache_key = f"oauth_pkce_verifier/{state_token}"
                code_verifier = cache.get(verifier_cache_key)
                cache.delete(verifier_cache_key)  # single-use, per RFC 7636
            # Missing verifier still exchanges without PKCE (Salesforce accepts that until it
            # requires PKCE). Log it so the gap is visible before we enforce PKCE provider-side.
            if not code_verifier:
                logger.warning("oauth_pkce_verifier_missing", kind=kind, has_state_token=bool(state_token))
                # posthog is a first-party flow we control both ends of — a missing verifier is never
                # a legacy-provider compat case here, so fail closed rather than exchanging without PKCE.
                if kind == "posthog":
                    raise ValidationError("Remote authorization failed: missing PKCE verifier. Please retry.")

        # Reddit uses HTTP Basic Auth https://github.com/reddit-archive/reddit/wiki/OAuth2 and requires a User-Agent header
        if kind == "reddit-ads":
            res = requests.post(
                oauth_config.token_url,
                auth=HTTPBasicAuth(oauth_config.client_id, oauth_config.client_secret),
                data={
                    "code": params["code"],
                    "redirect_uri": OauthIntegration.redirect_uri(kind),
                    "grant_type": "authorization_code",
                },
                headers={"User-Agent": "PostHog/1.0 by PostHogTeam"},
                timeout=10,
            )
        # Pinterest uses HTTP Basic Auth for token exchange (base64-encoded client_id:client_secret)
        elif kind == "pinterest-ads":
            res = requests.post(
                oauth_config.token_url,
                auth=HTTPBasicAuth(oauth_config.client_id, oauth_config.client_secret),
                data={
                    "code": params["code"],
                    "redirect_uri": OauthIntegration.redirect_uri(kind),
                    "grant_type": "authorization_code",
                },
                timeout=10,
            )
        elif kind == "tiktok-ads":
            # TikTok Ads uses JSON request body instead of form data and maps 'code' to 'auth_code'
            res = requests.post(
                oauth_config.token_url,
                json={
                    "app_id": oauth_config.client_id,
                    "secret": oauth_config.client_secret,
                    "auth_code": params["code"],
                },
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
        elif kind == "stripe":
            # Stripe Apps OAuth authenticates with the developer secret key as HTTP Basic
            # username and does not accept client_id/redirect_uri in the token-exchange body.
            # Connect OAuth (client_id+client_secret in body) is a different system.
            res = requests.post(
                oauth_config.token_url,
                auth=HTTPBasicAuth(oauth_config.client_secret, ""),
                data={
                    "code": params["code"],
                    "grant_type": "authorization_code",
                },
                timeout=10,
            )
        else:
            redirect_uri = OauthIntegration.redirect_uri(kind)
            res = requests.post(
                oauth_config.token_url,
                data={
                    "client_id": oauth_config.client_id,
                    "client_secret": oauth_config.client_secret,
                    "code": params["code"],
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                    **({"code_verifier": code_verifier} if code_verifier else {}),
                },
                timeout=10,
                # allow_redirects=False so a misconfigured/compromised token endpoint can't 30x us
                # into resending client_secret + authorization code to another origin.
                allow_redirects=False,
            )

        if kind == "slack":
            record_slack_api_response(
                res,
                source="oauth",
                workspace_id=None,
                app_id="posthog",
                method="POST",
                endpoint="oauth.v2.access",
            )

        try:
            config: dict = res.json()
        except ValueError:
            # Non-JSON body (e.g. an HTML 502 from a proxy). Keep going so the status-code
            # branch below can surface a structured ValidationError to the frontend.
            config = {}

        access_token = None
        if kind == "tiktok-ads":
            # TikTok has a different response format - access_token is nested under 'data'
            access_token = config.get("data", {}).get("access_token")
        else:
            access_token = config.get("access_token")

        if res.status_code != 200 or not access_token:
            # Hack to try getting sandbox auth token instead of their salesforce production account
            if kind == "salesforce":
                oauth_config = cls.oauth_config_for_kind("salesforce-sandbox")
                res = requests.post(
                    oauth_config.token_url,
                    data={
                        "client_id": oauth_config.client_id,
                        "client_secret": oauth_config.client_secret,
                        "code": params["code"],
                        "redirect_uri": OauthIntegration.redirect_uri(kind),
                        "grant_type": "authorization_code",
                        **({"code_verifier": code_verifier} if code_verifier else {}),
                    },
                    timeout=10,
                )

                try:
                    config = res.json()
                except ValueError:
                    config = {}

                if res.status_code != 200 or not config.get("access_token"):
                    logger.error(f"Oauth error for {kind}", response=res.text)
                    _raise_oauth_validation_error(kind, res)
            else:
                # Include request context so on-call can compare what we sent against what
                # the merchant authorized with in Stripe. Code prefix only, full grant is
                # short-lived but still a credential during its TTL. Never log client_secret.
                logger.error(
                    f"Oauth error for {kind}",
                    response=res.text,
                    status_code=res.status_code,
                    client_id=oauth_config.client_id,
                    redirect_uri=OauthIntegration.redirect_uri(kind),
                    code_prefix=str(params.get("code", ""))[:12],
                )
                # Surface the provider's error to the frontend toast — without this, DRF turns
                # the bare Exception into a generic 500 and the user sees "Something went wrong"
                # with no actionable detail. ValidationError → 400 with `detail` set.
                _raise_oauth_validation_error(kind, res)

        if oauth_config.token_info_url:
            # If token info url is given we call it and check the integration id from there
            if oauth_config.token_info_graphql_query:
                token_info_res = requests.post(
                    oauth_config.token_info_url,
                    headers={"Authorization": f"Bearer {config['access_token']}"},
                    json={"query": oauth_config.token_info_graphql_query},
                    timeout=10,
                    # This call carries the access token; don't let a misconfigured/compromised
                    # provider 30x us into resending it to another origin (matches the exchange/refresh/revoke calls).
                    allow_redirects=False,
                )
            else:
                token_info_res = requests.get(
                    oauth_config.token_info_url.replace(":access_token", config["access_token"]),
                    headers={"Authorization": f"Bearer {config['access_token']}"},
                    timeout=10,
                    allow_redirects=False,
                )

            if token_info_res.status_code == 200:
                data = token_info_res.json()

                # Jira returns an array of accessible resources, extract the first one
                if kind == "jira" and isinstance(data, list):
                    if len(data) > 0:
                        site = data[0]
                        config["cloud_id"] = site.get("id")
                        config["site_name"] = site.get("name")
                        config["site_url"] = site.get("url")
                    else:
                        logger.error(
                            "Jira OAuth returned empty accessible resources array - user may not have access to any Jira sites",
                            kind=kind,
                        )
                        raise ValidationError(
                            "No accessible Jira sites found. Please ensure your Atlassian account has access to at least one Jira site."
                        )
                elif oauth_config.token_info_config_fields:
                    for field in oauth_config.token_info_config_fields:
                        config[field] = common.dot_get(data, field)
            else:
                logger.error(
                    f"OAuth token_info request failed for {kind}",
                    token_info_url=oauth_config.token_info_url,
                    status_code=token_info_res.status_code,
                    response=token_info_res.text[:500],
                )

        integration_id = common.dot_get(config, oauth_config.id_path)

        # Bing Ads id_token is a JWT, extract user ID from it
        if kind == "bing-ads" and not integration_id:
            try:
                id_token = config.get("id_token")
                if id_token:
                    jwt_data = common._decode_jwt_payload(id_token)
                    if jwt_data:
                        bing_user_id = jwt_data.get("oid")
                        bing_username = jwt_data.get("preferred_username")
                        if bing_user_id:
                            config["id"] = bing_user_id
                            config["userPrincipalName"] = bing_username
                            integration_id = bing_user_id
                else:
                    logger.error("Bing Ads OAuth response missing id_token", config_keys=list(config.keys()))
            except Exception:
                logger.exception("Failed to decode Bing Ads JWT")

        # Reddit access token is a JWT, extract user ID from it
        if kind == "reddit-ads" and not integration_id:
            try:
                access_token = config.get("access_token")
                if access_token:
                    jwt_data = common._decode_jwt_payload(access_token)
                    if jwt_data:
                        # Extract user ID from JWT (lid = login ID)
                        reddit_user_id = jwt_data.get("lid", jwt_data.get("aid"))
                        if reddit_user_id:
                            config["reddit_user_id"] = reddit_user_id
                            integration_id = reddit_user_id
            except Exception as e:
                logger.exception("Failed to decode Reddit JWT", error=str(e))

        # Resend's token response carries no account identifier, but the access token is a JWT.
        # Derive the integration id/name from its claims (`sub` is the account subject; email/name
        # are used for a human-readable label when present). Assumes the standard `sub` claim — if
        # Resend uses a different claim, the missing-id guard below raises and the user sees a clear
        # reconnect error rather than a silently mislabeled integration.
        if kind == "resend" and not integration_id:
            try:
                access_token = config.get("access_token")
                if access_token:
                    jwt_data = common._decode_jwt_payload(access_token)
                    if jwt_data:
                        resend_account_id = jwt_data.get("sub")
                        if resend_account_id:
                            config["resend_account_id"] = resend_account_id
                            config["resend_account_name"] = (
                                jwt_data.get("email") or jwt_data.get("name") or f"Resend account {resend_account_id}"
                            )
                            integration_id = resend_account_id
                else:
                    logger.error("Resend OAuth response missing access_token", config_keys=list(config.keys()))
            except Exception:
                logger.exception("Failed to decode Resend JWT")

        # LinkedIn id_token is a JWT, extract user ID and email from it
        # This avoids calling /v2/userinfo which has intermittent REVOKED_ACCESS_TOKEN errors
        if kind == "linkedin-ads" and not integration_id:
            try:
                id_token = config.get("id_token")
                if id_token:
                    jwt_data = common._decode_jwt_payload(id_token)
                    if jwt_data:
                        linkedin_user_id = jwt_data.get("sub")
                        linkedin_email = jwt_data.get("email")
                        if linkedin_user_id:
                            config["sub"] = linkedin_user_id
                            config["email"] = linkedin_email
                            integration_id = linkedin_user_id
                else:
                    logger.error("LinkedIn Ads OAuth response missing id_token", config_keys=list(config.keys()))
            except Exception:
                logger.exception("Failed to decode LinkedIn JWT")

        # Stripe OAuth returns stripe_user_id but no account name — fetch it from the Accounts API
        if kind == "stripe" and integration_id:
            try:
                from stripe import StripeClient  # noqa: PLC0415

                stripe_client = StripeClient(oauth_config.client_secret)
                account = stripe_client.accounts.retrieve(str(integration_id))
                business_profile = getattr(account, "business_profile", None)
                business_name = getattr(business_profile, "name", None) if business_profile else None
                company = getattr(account, "company", None)
                company_name = getattr(company, "name", None) if company else None
                account_name = business_name or company_name or getattr(account, "email", None) or str(integration_id)
                config["account_name"] = f"{account_name} ({integration_id})"
            except Exception:
                logger.exception("Failed to fetch Stripe account name")
                config["account_name"] = str(integration_id)

        # Persist the target region and namespace the dedup key by it, so the same PostHog account
        # connected in two different cells yields two distinct integrations instead of colliding on
        # `sub`. `region` also drives config/refresh/revoke lookups for the lifetime of the row.
        if kind == "posthog" and integration_id:
            config["region"] = region
            integration_id = f"{region}:{integration_id}"
            # Persist the resource scopes the target actually granted (obj:action only, dropping the
            # openid/email identity scopes). The connection proxy uses this to require a caller's own
            # token to cover these scopes before it will wield the connection's grant.
            config["granted_scopes"] = sorted({s for s in (config.get("scope") or "").split() if ":" in s})

        # TikTok can complete OAuth without the user granting any advertiser account, leaving
        # `advertiser_ids` empty. Surface an actionable reconnect message rather than the generic
        # "failed to extract integration ID" 500 the guard below would otherwise raise.
        if kind == "tiktok-ads" and isinstance(integration_id, list) and len(integration_id) == 0:
            raise ValidationError(
                "No TikTok ad accounts were authorized. In TikTok, grant access to at least one "
                "advertiser account, then reconnect."
            )

        if isinstance(integration_id, int):
            integration_id = str(integration_id)
        elif isinstance(integration_id, list) and len(integration_id) > 0:
            integration_id = ",".join(str(item) for item in integration_id)

        if not isinstance(integration_id, str):
            raise Exception(f"Oauth error: failed to extract integration ID for {kind}")

        # Handle TikTok's nested response format
        if kind == "tiktok-ads":
            data = config.pop("data", {})
            # Move other data fields to main config for TikTok
            config.update(data)
            # Best-effort: fetch who authorized this, so it isn't listed as a row of advertiser ids.
            try:
                user_res = requests.get(
                    "https://business-api.tiktok.com/open_api/v1.3/user/info/",
                    headers={"Access-Token": config["access_token"]},
                    timeout=10,
                )
                # TikTok answers 200 even when the call failed; the body `code` (0 = OK) is the outcome.
                body = user_res.json()
                if body.get("code") == 0:
                    user = body.get("data") or {}
                    if user.get("email"):
                        config["user_email"] = user["email"]
                    if user.get("display_name"):
                        config["user_display_name"] = user["display_name"]
            except Exception:
                logger.warning("Failed to fetch TikTok user info for display name")

        sensitive_config: dict = {
            "access_token": config.pop("access_token"),
            # NOTE: We don't actually use the refresh and id tokens (typically they aren't even provided for this sort of service auth)
            # but we ensure they are popped and stored in sensitive config to avoid accidental exposure
            "refresh_token": config.pop("refresh_token", None),
            "id_token": config.pop("id_token", None),
        }

        # Handle case where Salesforce doesn't provide expires_in in initial response
        if not config.get("expires_in") and kind in SALESFORCE_OAUTH_KINDS:
            # Default to 1 hour for Salesforce if not provided (conservative)
            config["expires_in"] = 3600

        # Stripe Apps OAuth tokens don't include expires_in in the response
        if not config.get("expires_in") and kind == "stripe":
            config["expires_in"] = 3600

        config["refreshed_at"] = int(time.time())

        integration, created = model.Integration.objects.update_or_create(
            team_id=team_id,
            kind=kind,
            integration_id=integration_id,
            defaults={
                "config": config,
                "sensitive_config": sensitive_config,
                "created_by": created_by,
            },
        )

        if integration.errors:
            integration.errors = ""
            integration.save()

        if kind == "slack":
            # The cached auth verdict in slack_app is per-integration. A
            # reconnect mints a new bot token, so any stale ``ok=false`` row
            # from the previous token would silently demote this install for
            # the remaining cache TTL. Inline-imported to keep the slack_app
            # module off the core django.setup() path; wrapped so a broken
            # slack_app build can't take down OAuth completion for every
            # integration kind.
            try:
                from products.slack_app.backend.facade.api import (  # noqa: PLC0415
                    invalidate_slack_integration_auth_state,
                )

                invalidate_slack_integration_auth_state(integration.id)
            except Exception:
                logger.warning(
                    "slack_app_auth_state_invalidation_on_oauth_failed",
                    integration_id=integration.id,
                    exc_info=True,
                )

        return integration

    def revoke_token(self) -> None:
        """Revoke the OAuth grant at the provider, for kinds with a revoke endpoint.

        Revoking the refresh token also invalidates its access tokens (per RFC 7009 and
        Salesforce's revoke semantics), so the provider no longer considers PostHog authorized
        after a disconnect. Callers treat this as best-effort — the local deletion proceeds
        regardless.
        """
        region = self.integration.config.get("region") if self.integration.kind == "posthog" else None
        oauth_config = self.oauth_config_for_kind(self.integration.kind, region)
        if not oauth_config.token_revoke_url:
            return

        # Prefer the refresh token: revoking it invalidates the whole grant (and its access
        # tokens), so an attacker holding it can't keep minting access tokens after disconnect.
        refresh_token = self.integration.sensitive_config.get("refresh_token")
        token = refresh_token or self.integration.sensitive_config.get("access_token")
        if not token:
            return

        revoke_url = oauth_config.token_revoke_url
        # Salesforce sandbox integrations are stored under the production kind (the sandbox is
        # only a token-exchange fallback), so the static prod revoke URL would miss them. Revoke
        # at the validated instance host so a stray write to config can't redirect the token to
        # an attacker origin.
        if self.integration.kind in SALESFORCE_OAUTH_KINDS:
            allowed_host = _salesforce_instance_host(self.integration.config.get("instance_url"))
            if allowed_host:
                revoke_url = f"{allowed_host}/services/oauth2/revoke"

        data = {"token": token}
        if self.integration.kind == "resend":
            # Resend registers PostHog as a confidential client (token_endpoint_auth_method=
            # client_secret_post) and requires client authentication on revocation. Without it
            # the endpoint rejects the request and the grant survives the disconnect. The hint
            # tells the provider which token type it received (RFC 7009).
            data["client_id"] = oauth_config.client_id
            data["client_secret"] = oauth_config.client_secret
            data["token_type_hint"] = "refresh_token" if refresh_token else "access_token"

        # allow_redirects=False so a misconfigured/compromised provider can't 30x us into
        # resending the token to another host. raise_for_status surfaces a provider rejection
        # to the caller's capture_exception instead of it passing silently as a revoke.
        response = requests.post(
            revoke_url,
            data=data,
            timeout=10,
            allow_redirects=False,
        )
        response.raise_for_status()

    def access_token_expired(self, time_threshold: timedelta | None = None) -> bool:
        # Not all integrations have refresh tokens or expiries, so we just return False if we can't check

        refresh_token = self.integration.sensitive_config.get("refresh_token")
        expires_in = self.integration.config.get("expires_in")
        refreshed_at = self.integration.config.get("refreshed_at")

        if not refresh_token:
            return False

        if not expires_in and self.integration.kind in SALESFORCE_OAUTH_KINDS:
            # Salesforce tokens typically last 2-4 hours, we'll assume 1 hour (3600 seconds) to be conservative
            expires_in = 3600

        if not expires_in and self.integration.kind == "stripe":
            expires_in = 3600

        if not expires_in or not refreshed_at:
            return False

        # To be really safe we refresh if its half way through the expiry
        time_threshold = time_threshold or timedelta(seconds=expires_in / 2)

        return time.time() > refreshed_at + expires_in - time_threshold.total_seconds()

    def _post_token_refresh(self, oauth_config: OauthConfig, client_id: str, client_secret: str) -> requests.Response:
        # Via the property, so a token that picked up an extra encryption layer is peeled back to
        # the real one instead of being posted to the provider as ciphertext.
        refresh_token = self.integration.refresh_token
        if refresh_token is None:
            # A grant with no refresh token at all is a caller error, not a provider rejection -
            # keep failing loudly rather than posting `None` and reading the 400 back as one.
            raise KeyError("refresh_token")
        kind = self.integration.kind

        # Reddit uses HTTP Basic Auth for token refresh
        if kind == "reddit-ads":
            return requests.post(
                oauth_config.token_url,
                auth=HTTPBasicAuth(client_id, client_secret),
                data={"refresh_token": refresh_token, "grant_type": "refresh_token"},
                # If I use a standard User-Agent, it will throw a 429 too many requests error
                headers={"User-Agent": "PostHog/1.0 by PostHogTeam"},
                timeout=10,
            )
        # Pinterest uses HTTP Basic Auth for token refresh
        elif kind == "pinterest-ads":
            return requests.post(
                oauth_config.token_url,
                auth=HTTPBasicAuth(client_id, client_secret),
                data={"refresh_token": refresh_token, "grant_type": "refresh_token"},
                timeout=10,
            )
        elif kind == "tiktok-ads":
            # Refresh against the Business API app we authorized against, using its app_id/secret and
            # JSON body (mirroring the token exchange). The open.tiktokapis.com/v2 endpoint with
            # client_key belongs to Login Kit — a different TikTok app family whose credentials this
            # integration never holds.
            return requests.post(
                "https://business-api.tiktok.com/open_api/v1.3/oauth2/refresh_token/",
                json={
                    "app_id": client_id,
                    "secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
        elif kind == "bing-ads":
            # Microsoft Azure AD requires scope parameter on token refresh
            return requests.post(
                oauth_config.token_url,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                    "scope": oauth_config.scope,
                },
                timeout=10,
            )
        elif kind == "stripe":
            # Stripe Apps OAuth: secret as HTTP Basic username, no client_id/client_secret in body.
            return requests.post(
                oauth_config.token_url,
                auth=HTTPBasicAuth(client_secret, ""),
                data={"refresh_token": refresh_token, "grant_type": "refresh_token"},
                timeout=10,
            )
        else:
            token_url = oauth_config.token_url
            # Salesforce sandbox integrations are stored under the production kind (the sandbox
            # is only a token-exchange fallback in the OAuth callback), so the static prod
            # token URL would refuse a sandbox-issued refresh_token. Refresh at the org's
            # own instance host instead. Validate the host before sending client_secret +
            # refresh_token so a stray write to config can't exfiltrate the fleet-wide
            # Salesforce app secret; fall back to the hardcoded prod URL on rejection.
            if kind in SALESFORCE_OAUTH_KINDS:
                allowed_host = _salesforce_instance_host(self.integration.config.get("instance_url"))
                if allowed_host:
                    token_url = f"{allowed_host}/services/oauth2/token"

            return requests.post(
                token_url,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
                timeout=10,
                allow_redirects=False,
            )

    def _parse_token_refresh_response(self, res: requests.Response) -> dict:
        try:
            config = res.json()
        except ValueError:
            # e.g. an HTML error page from a proxy/5xx - still a failed refresh, not an exception
            return {}
        # TikTok Business API nests the refreshed tokens under `data`, same as the token exchange.
        # Lift them to the top level so the generic access_token/refresh_token/expires_in handling reads them.
        if self.integration.kind == "tiktok-ads" and isinstance(config.get("data"), dict):
            config = {**config, **config["data"]}
        return config

    def _record_terminal_unreadable_secret(self) -> None:
        logger.error(
            "integration_refresh_secret_unreadable",
            integration_id=self.integration.pk,
            team_id=self.integration.team_id,
            kind=self.integration.kind,
        )
        self.integration.errors = common.ERROR_TOKEN_REFRESH_FAILED
        attempt = refresh_tracking.record_refresh_failure(
            self.integration, reason=refresh_tracking.REFRESH_FAILURE_REASON_UNREADABLE_SECRET
        )
        refresh_tracking.oauth_refresh_counter.labels(
            kind=self.integration.kind,
            result="failed",
            reason=refresh_tracking.REFRESH_FAILURE_REASON_UNREADABLE_SECRET,
            attempt=attempt,
        ).inc()
        # `sensitive_config` is deliberately excluded: saving it would re-encrypt the ciphertext
        # this integration already can't read, adding another layer to the stored value.
        self.integration.save(update_fields=["errors", "config"])

    def refresh_access_token(self):
        """
        Refresh the access token for the integration if necessary
        """
        region = self.integration.config.get("region") if self.integration.kind == "posthog" else None
        oauth_config = self.oauth_config_for_kind(self.integration.kind, region)

        # Clear out previous token refreshing errors, as they'll be re-set below if another error occurs
        self.integration.errors = ""

        res: requests.Response | None = None
        config: dict = {}
        used_fallback = False
        try:
            res = self._post_token_refresh(oauth_config, oauth_config.client_id, oauth_config.client_secret)
            config = self._parse_token_refresh_response(res)
        except model.UndecryptedIntegrationSecretError:
            # The stored refresh token can't be read, so there is nothing to refresh with and no
            # later attempt can change that. Go terminal immediately: the sweep stops retrying,
            # and the UI shows the reconnect prompt.
            self._record_terminal_unreadable_secret()
            return
        except requests.RequestException as e:
            # A network error (timeout, connection reset) is a failed refresh, not a crash. Without
            # this the Celery sweep task errors out before recording the failure, so the backoff and
            # the TOKEN_REFRESH_FAILED reconnect state are never persisted.
            logger.warning(f"Network error on primary credentials for {self}", error=str(e))

        # A rotated or migrated OAuth app leaves users with refresh tokens only the previous
        # credentials can refresh. Retry with the fallback pair — including when the primary hit a
        # network error — so they keep working until they reconnect.
        if (
            res is None or res.status_code != 200 or not config.get("access_token")
        ) and oauth_config.client_secret_fallback:
            try:
                res = self._post_token_refresh(
                    oauth_config,
                    oauth_config.client_id_fallback or oauth_config.client_id,
                    oauth_config.client_secret_fallback,
                )
                config = self._parse_token_refresh_response(res)
                used_fallback = True
            except requests.RequestException as e:
                logger.warning(f"Network error on fallback credentials for {self}", error=str(e))
                res = None
                config = {}

        if res is None or res.status_code != 200 or not config.get("access_token"):
            logger.warning(
                f"Failed to refresh token for {self}", response=res.text if res is not None else "network error"
            )
            self.integration.errors = common.ERROR_TOKEN_REFRESH_FAILED
            reason = (
                refresh_tracking.oauth_refresh_failure_reason(res.status_code, config, kind=self.integration.kind)
                if res is not None
                else refresh_tracking.REFRESH_FAILURE_REASON_NETWORK
            )
            attempt = refresh_tracking.record_refresh_failure(self.integration, reason=reason)
            refresh_tracking.oauth_refresh_counter.labels(
                kind=self.integration.kind, result="failed", reason=reason, attempt=attempt
            ).inc()
            # A failed refresh leaves `sensitive_config` untouched, so writing it back only risks
            # harm: `ignore_decrypt_errors` hands back raw ciphertext for a secret that couldn't be
            # decrypted, and saving re-encrypts it, permanently adding a layer to the stored value.
            self.integration.save(update_fields=["errors", "config"])
            return
        else:
            logger.info(f"Refreshed access token for {self}")
            refresh_tracking.record_refresh_success(self.integration)
            refresh_tracking.record_oauth_client_used(self.integration, used_fallback=used_fallback)
            self.integration.sensitive_config["access_token"] = config["access_token"]

            # Some providers (e.g. Atlassian/Jira) rotate refresh tokens — each
            # refresh response includes a new refresh_token and the old one is
            # invalidated.  Always store the latest one to avoid "invalid refresh
            # token" errors on subsequent refreshes.
            if config.get("refresh_token"):
                self.integration.sensitive_config["refresh_token"] = config["refresh_token"]

            # Handle case where Salesforce/Stripe doesn't provide expires_in in refresh response
            expires_in = config.get("expires_in")
            if not expires_in and self.integration.kind in SALESFORCE_OAUTH_KINDS:
                expires_in = 3600
            if not expires_in and self.integration.kind == "stripe":
                expires_in = 3600

            self.integration.config["expires_in"] = expires_in
            self.integration.config["refreshed_at"] = int(time.time())
            reload_integrations_on_workers(self.integration.team_id, [self.integration.id])
            refresh_tracking.oauth_refresh_counter.labels(
                kind=self.integration.kind,
                result="success_fallback" if used_fallback else "success",
                reason="",
                attempt="",
            ).inc()

        self.integration.save()
