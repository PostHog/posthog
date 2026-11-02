"""Generic OAuth connect/refresh dispatcher shared by every generic-OAuth integration kind."""

import json
import time
import base64
import hashlib
import secrets
from datetime import timedelta
from typing import Any, NoReturn
from urllib.parse import parse_qs, urlencode, urlparse

from django.conf import settings
from django.core.cache import cache

import requests
import structlog
from requests.auth import HTTPBasicAuth
from rest_framework.exceptions import ValidationError

from posthog.cache_utils import cache_for
from posthog.credentials_service.callers import CredentialsCaller
from posthog.credentials_service.instance_settings import get_many_or_instance_settings
from posthog.credentials_service.settings_fallback import get_many_or_settings
from posthog.dataclasses import frozen
from posthog.egress.slack.observability import record_slack_api_response
from posthog.integrations.contracts import IntegrationRecord
from posthog.models.user import User
from posthog.plugins.plugin_server_api import reload_integrations_on_workers
from posthog.schema_enums import SlackIntegrationScope
from posthog.scopes import get_oauth_scopes_supported

from . import apple_ads, common, model, refresh_tracking

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
        graph_error = body.get("error")
        if isinstance(graph_error, dict):
            # Meta's Graph API nests the error in an object whose trace id and codes mean nothing to the customer.
            message = graph_error.get("message")
            return str(message) if message else None
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


_INVALID_GRANT_MESSAGE = (
    "This authorization is no longer valid. Start the connection again and approve access without waiting in between."
)

_STRIPE_MODE_MISMATCH_MESSAGE = (
    "Stripe approved this connection in test mode or a sandbox, but PostHog can only connect live mode Stripe accounts. "
    "Starting the connection again won't fix this. To sync your live data, change Authentication type to "
    "Restricted API key and use a key you create in live mode."
)


_CLIENT_CREDENTIALS_REJECTED_MESSAGE = (
    "This connection failed because of a problem on PostHog's side, and nothing in your account needs to change. "
    "Contact support so we can fix it."
)


def _oauth_error_field(res: requests.Response, field: str) -> str | None:
    try:
        body = res.json()
    except Exception:
        return None
    value = body.get(field) if isinstance(body, dict) else None
    return value if isinstance(value, str) else None


def _oauth_error_code(res: requests.Response) -> str | None:
    return _oauth_error_field(res, "error")


def _is_client_credentials_rejected(res: requests.Response) -> bool:
    # The provider refused PostHog's client id or secret, so starting the connection again fails the same way.
    if _oauth_error_code(res) == "invalid_client":
        return True
    try:
        body = res.json()
    except Exception:
        return False
    graph_error = body.get("error") if isinstance(body, dict) else None
    message = graph_error.get("message") if isinstance(graph_error, dict) else None
    return isinstance(message, str) and "validating client secret" in message.lower()


def _is_stripe_mode_mismatch(kind: str, res: requests.Response) -> bool:
    # The install link that issued the code fixes its mode, and Stripe redeems it only with the secret
    # key of that mode. A retry gets a code from the same link, so it fails the same way.
    if kind != "stripe":
        return False
    description = _oauth_error_field(res, "error_description") or ""
    return "authorization code only supports returning" in description


def _raise_oauth_validation_error(kind: str, res: requests.Response) -> NoReturn:
    """Raise a ValidationError describing a failed OAuth token exchange.

    DRF turns ValidationError into a 400 with a populated `detail`, so the frontend toast renders
    a useful message instead of the generic "Something went wrong" fallback that follows from a
    bare Exception (which surfaces as a 500 with no detail).
    """
    if _oauth_error_code(res) == "invalid_grant":
        if _is_stripe_mode_mismatch(kind, res):
            raise ValidationError(_STRIPE_MODE_MISMATCH_MESSAGE)
        # The code expired, was already exchanged, or was issued for another account. The
        # provider's description can echo the code itself, so it stays in the logs.
        raise ValidationError(_INVALID_GRANT_MESSAGE)
    if _is_client_credentials_rejected(res):
        raise ValidationError(_CLIENT_CREDENTIALS_REJECTED_MESSAGE)
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


# Apple Ads: where the authorization code is exchanged. Apple's service provider OAuth guide names
# a different path for the refresh grant, `/auth/token`, which is the Sign in with Apple endpoint
# rather than a sibling of the `/auth/oauth2/v2/authorize` endpoint this flow starts at.
# `_post_token_refresh` tries this one first and falls back to that one, so whichever Apple honors
# keeps working.
APPLE_ADS_TOKEN_URL = "https://appleid.apple.com/auth/oauth2/token"
APPLE_ADS_REFRESH_TOKEN_FALLBACK_URL = "https://appleid.apple.com/auth/token"
# Lists every ad account the granting user can reach, and the organization each sits under. Apple
# documents it as the call to make once per access token, and it is the only identity Apple exposes
# for a service provider grant.
APPLE_ADS_ACL_URL = "https://api.ads.apple.com/v1/acls"


@frozen
class OauthConfig:
    """The static part of a provider's OAuth setup.

    It holds no client credentials: this is cached for five minutes, and a cached secret would
    outlive a rotation. Get those from `OauthIntegration.client_credentials_for_kind` at use time.
    """

    authorize_url: str
    token_url: str
    scope: str
    id_path: str
    name_path: str
    token_info_url: str | None = None
    token_info_graphql_query: str | None = None
    token_info_config_fields: list[str] | None = None
    additional_authorize_params: dict[str, str] | None = None
    # When true, the authorize/token-exchange flow uses PKCE (RFC 7636, S256)
    pkce: bool = False
    # When set, disconnecting the integration also revokes the grant at the provider
    token_revoke_url: str | None = None
    # When true, authorize_url hex-encodes the state for a provider that does not return it verbatim.
    # The frontend callback decodes it before it reads the token.
    opaque_state: bool = False


# Slack accepts comma-separated scopes on the OAuth authorize URL. The canonical list is the
# StrEnum declared in posthog/schema.py (generated from the SlackIntegrationScope enum in
# frontend/src/types.ts via `hogli build:schema`), so widening it on either side stays in sync.
#
# Every scope here is approved for the public Cloud app, so the same list is requested on every
# instance. Staging a scope Slack hasn't approved needs a DEV/local-only branch again — see the
# note by SlackIntegrationScope in frontend/src/types.ts.
POSTHOG_SLACK_SCOPE = ",".join(scope.value for scope in SlackIntegrationScope)


def _apple_ads_acl_accounts(access_token: str) -> list[dict[str, Any]]:
    """Ad accounts an Apple Ads access token can read, flattened one row per account.

    Apple nests each account under `adAccount` and lists the granting user's roles beside it:
    ``{"result": {"acls": [{"adAccount": {"id", "name", "orgId", ...}, "roles": [...]}]}}``.
    Returns an empty list rather than raising when Apple rejects the call, so the caller decides
    what a grant with no readable account means.
    """
    try:
        res = requests.get(
            APPLE_ADS_ACL_URL,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            timeout=10,
            # This call carries the access token; a 30x must not resend it to another origin.
            allow_redirects=False,
        )
    except requests.RequestException as e:
        logger.warning("apple_ads_acl_request_failed", error=str(e))
        return []

    if res.status_code != 200:
        logger.warning("apple_ads_acl_request_rejected", status_code=res.status_code, response=res.text[:500])
        return []

    try:
        payload = res.json()
    except ValueError:
        return []

    result = payload.get("result") if isinstance(payload, dict) else None
    entries = result.get("acls") if isinstance(result, dict) else None
    if not isinstance(entries, list):
        return []

    accounts: list[dict[str, Any]] = []
    for entry in entries:
        account = entry.get("adAccount") if isinstance(entry, dict) else None
        if isinstance(account, dict) and account.get("id") is not None:
            accounts.append({**account, "roles": entry.get("roles") or []})
    return accounts


def _apple_ads_account_name(accounts: list[dict[str, Any]]) -> str:
    """Label for the connected Apple Ads grant, named after the organizations it reaches."""
    org_names: list[str] = []
    for account in accounts:
        name = account.get("orgName") or account.get("parentOrgName")
        if name and name not in org_names:
            org_names.append(str(name))
    if org_names:
        return ", ".join(org_names)
    first = accounts[0]
    return str(first.get("name") or f"Apple Ads account {first['id']}")


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

# Kinds that authorize through another kind's connected app. The provider allows only the callback
# URL that the app was registered with, so a path built from the borrowing kind is rejected with
# redirect_uri_mismatch before the user can grant anything.
OAUTH_REDIRECT_URI_ALIASES: dict[str, str] = {"pardot": "salesforce"}


def resolve_aliased_oauth_kind(path_kind: str, state: str) -> str:
    """Return the kind a callback belongs to, given the kind its callback path names.

    An aliased kind returns on the app owner's path, so the path segment names the wrong
    integration and `authorize_url` puts the real kind in the state. Only a state kind that the
    alias table maps back to `path_kind` is promoted, so a caller cannot name an unrelated
    integration through this — and a caller that wants the aliased kind can already ask for it
    directly.
    """
    state_kind = parse_qs(state).get("kind", [""])[0]
    if state_kind and OAUTH_REDIRECT_URI_ALIASES.get(state_kind) == path_kind:
        return state_kind
    return path_kind


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


@frozen
class _PosthogConnectTarget:
    region: str
    base_url: str
    # Names of the credentials, not their values: they resolve at use time, never in a cache.
    client_id_key: str
    client_secret_key: str


def _posthog_connect_target(region: str | None) -> _PosthogConnectTarget:
    """Resolve the base URL and the client credential names for a remote target cell.

    Raises NotImplementedError for an unknown or unconfigured region so the connect/refresh
    paths fail closed (surfaced to the user as a reconnect error) rather than silently hitting
    the wrong cell. The client credentials are checked where they are resolved, in
    `OauthIntegration.client_credentials_for_kind`.
    """
    normalized = (region or "").upper()
    if normalized == "DEV" and not _POSTHOG_CONNECT_ALLOW_DEV:
        # Defense in depth: even if a `DEV` region row somehow reaches here in production, refuse to
        # resolve it so the backend never POSTs a token exchange to the dev base URL.
        raise NotImplementedError("PostHog connect DEV region is only available in dev/test")
    targets = {
        "US": (
            settings.POSTHOG_CONNECT_BASE_URL_US,
            "POSTHOG_CONNECT_OAUTH_CLIENT_ID_US",
            "POSTHOG_CONNECT_OAUTH_CLIENT_SECRET_US",
        ),
        "EU": (
            settings.POSTHOG_CONNECT_BASE_URL_EU,
            "POSTHOG_CONNECT_OAUTH_CLIENT_ID_EU",
            "POSTHOG_CONNECT_OAUTH_CLIENT_SECRET_EU",
        ),
        "DEV": (
            settings.POSTHOG_CONNECT_BASE_URL_DEV,
            "POSTHOG_CONNECT_OAUTH_CLIENT_ID_DEV",
            "POSTHOG_CONNECT_OAUTH_CLIENT_SECRET_DEV",
        ),
    }
    if normalized not in targets:
        raise NotImplementedError(f"PostHog connect OAuth not supported for region {region!r}")
    base_url, client_id_key, client_secret_key = targets[normalized]
    if not base_url:
        raise NotImplementedError(f"PostHog connect app not configured for region {normalized}")
    return _PosthogConnectTarget(
        region=normalized,
        base_url=base_url.rstrip("/"),
        client_id_key=client_id_key,
        client_secret_key=client_secret_key,
    )


def posthog_connect_base_url(region: str | None) -> str:
    """Public base URL of a remote target cell (e.g. https://eu.posthog.com), for callers that
    need to reach its API with a `posthog` integration token. Raises for unknown/unconfigured regions."""
    return _posthog_connect_target(region).base_url


CREDENTIALS_CALLER = CredentialsCaller.INTEGRATIONS


@frozen
class _ClientCredentialKeys:
    # Names in the credentials service, and the Django settings that hold them until they move.
    client_id: str
    client_secret: str
    not_configured: str


_SALESFORCE_CLIENT_KEYS = _ClientCredentialKeys(
    client_id="SALESFORCE_CONSUMER_KEY",
    client_secret="SALESFORCE_CONSUMER_SECRET",
    not_configured="Salesforce app not configured",
)

# Every kind whose client credentials are a plain id/secret pair. `posthog` (per region), `slack`
# (instance settings) and `apple-ads` (a signed secret) resolve in their own branches.
OAUTH_CLIENT_CREDENTIAL_KEYS: dict[str, _ClientCredentialKeys] = {
    "salesforce": _SALESFORCE_CLIENT_KEYS,
    "salesforce-sandbox": _SALESFORCE_CLIENT_KEYS,
    "pardot": _SALESFORCE_CLIENT_KEYS,
    "hubspot": _ClientCredentialKeys(
        client_id="HUBSPOT_APP_CLIENT_ID",
        client_secret="HUBSPOT_APP_CLIENT_SECRET",
        not_configured="Hubspot app not configured",
    ),
    "google-ads": _ClientCredentialKeys(
        client_id="GOOGLE_ADS_APP_CLIENT_ID",
        client_secret="GOOGLE_ADS_APP_CLIENT_SECRET",
        not_configured="Google Ads app not configured",
    ),
    "google-analytics": _ClientCredentialKeys(
        client_id="GOOGLE_ANALYTICS_APP_CLIENT_ID",
        client_secret="GOOGLE_ANALYTICS_APP_CLIENT_SECRET",
        not_configured="Google Analytics app not configured",
    ),
    "google-calendar": _ClientCredentialKeys(
        client_id="GOOGLE_CALENDAR_APP_CLIENT_ID",
        client_secret="GOOGLE_CALENDAR_APP_CLIENT_SECRET",
        not_configured="Google Calendar app not configured",
    ),
    "google-search-console": _ClientCredentialKeys(
        client_id="GOOGLE_SEARCH_CONSOLE_APP_CLIENT_ID",
        client_secret="GOOGLE_SEARCH_CONSOLE_APP_CLIENT_SECRET",
        not_configured="Google Search Console app not configured",
    ),
    "google-sheets": _ClientCredentialKeys(
        client_id="SOCIAL_AUTH_GOOGLE_OAUTH2_KEY",
        client_secret="SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET",
        not_configured="Google Sheets app not configured",
    ),
    "youtube-analytics": _ClientCredentialKeys(
        client_id="YOUTUBE_ANALYTICS_APP_CLIENT_ID",
        client_secret="YOUTUBE_ANALYTICS_APP_CLIENT_SECRET",
        not_configured="YouTube Analytics app not configured",
    ),
    "snapchat": _ClientCredentialKeys(
        client_id="SNAPCHAT_APP_CLIENT_ID",
        client_secret="SNAPCHAT_APP_CLIENT_SECRET",
        not_configured="Snapchat app not configured",
    ),
    "linkedin-ads": _ClientCredentialKeys(
        client_id="LINKEDIN_APP_CLIENT_ID",
        client_secret="LINKEDIN_APP_CLIENT_SECRET",
        not_configured="LinkedIn Ads app not configured",
    ),
    "bing-ads": _ClientCredentialKeys(
        client_id="BING_ADS_CLIENT_ID",
        client_secret="BING_ADS_CLIENT_SECRET",
        not_configured="Bing Ads app not configured",
    ),
    "intercom": _ClientCredentialKeys(
        client_id="INTERCOM_APP_CLIENT_ID",
        client_secret="INTERCOM_APP_CLIENT_SECRET",
        not_configured="Intercom app not configured",
    ),
    "helpscout": _ClientCredentialKeys(
        client_id="HELPSCOUT_APP_CLIENT_ID",
        client_secret="HELPSCOUT_APP_CLIENT_SECRET",
        not_configured="Help Scout app not configured",
    ),
    "linear": _ClientCredentialKeys(
        client_id="LINEAR_APP_CLIENT_ID",
        client_secret="LINEAR_APP_CLIENT_SECRET",
        not_configured="Linear app not configured",
    ),
    "meta-ads": _ClientCredentialKeys(
        client_id="META_ADS_APP_CLIENT_ID",
        client_secret="META_ADS_APP_CLIENT_SECRET",
        not_configured="Meta Ads app not configured",
    ),
    "instagram": _ClientCredentialKeys(
        client_id="INSTAGRAM_APP_CLIENT_ID",
        client_secret="INSTAGRAM_APP_CLIENT_SECRET",
        not_configured="Instagram app not configured",
    ),
    "reddit-ads": _ClientCredentialKeys(
        client_id="REDDIT_ADS_CLIENT_ID",
        client_secret="REDDIT_ADS_CLIENT_SECRET",
        not_configured="Reddit Ads app not configured",
    ),
    "tiktok-ads": _ClientCredentialKeys(
        client_id="TIKTOK_ADS_CLIENT_ID",
        client_secret="TIKTOK_ADS_CLIENT_SECRET",
        not_configured="TikTok Ads app not configured",
    ),
    "clickup": _ClientCredentialKeys(
        client_id="CLICKUP_APP_CLIENT_ID",
        client_secret="CLICKUP_APP_CLIENT_SECRET",
        not_configured="ClickUp app not configured",
    ),
    "jira": _ClientCredentialKeys(
        client_id="ATLASSIAN_APP_CLIENT_ID",
        client_secret="ATLASSIAN_APP_CLIENT_SECRET",
        not_configured="Atlassian/Jira app not configured",
    ),
    "pinterest-ads": _ClientCredentialKeys(
        client_id="PINTEREST_ADS_CLIENT_ID",
        client_secret="PINTEREST_ADS_CLIENT_SECRET",
        not_configured="Pinterest Ads app not configured",
    ),
    "stripe": _ClientCredentialKeys(
        client_id="STRIPE_APP_CLIENT_ID",
        client_secret="STRIPE_APP_SECRET_KEY",
        not_configured="Stripe app not configured",
    ),
    "resend": _ClientCredentialKeys(
        client_id="RESEND_APP_CLIENT_ID",
        client_secret="RESEND_APP_CLIENT_SECRET",
        not_configured="Resend app not configured",
    ),
}

# Legacy OAuth client credentials kept alive during an app or secret rotation. Refreshes fall back
# to these when the primary credentials fail, so tokens issued by a since-migrated app keep working
# until users reconnect. A fallback is used only when its secret is set; an unset id reuses the
# primary one.
OAUTH_CLIENT_FALLBACK_KEYS: dict[str, tuple[str, str]] = {
    "bing-ads": ("BING_ADS_CLIENT_ID_FALLBACK", "BING_ADS_CLIENT_SECRET_FALLBACK"),
}

SLACK_APP_CLIENT_CREDENTIAL_KEYS = ["SLACK_APP_CLIENT_ID", "SLACK_APP_CLIENT_SECRET"]


class OauthIntegration:
    supported_kinds = [
        "slack",
        "posthog",
        "salesforce",
        "hubspot",
        "apple-ads",
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
        "helpscout",
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

    def __init__(self, integration: IntegrationRecord) -> None:
        self.integration = model.integration_model(integration)

    @classmethod
    @cache_for(timedelta(minutes=5))
    def oauth_config_for_kind(cls, kind: str, region: str | None = None) -> OauthConfig:
        # `region` only applies to the `posthog` remote kind, whose endpoints depend on the
        # target cell. cache_for keys on all args, so each (kind, region) pair caches separately;
        # every other kind is called without region and keeps its single cached entry.
        return cls._build_oauth_config(kind, region)

    @classmethod
    def client_credentials_for_kind(cls, kind: str, region: str | None = None) -> common.OauthClientCredentials:
        """PostHog's OAuth client id and secret for `kind`, read from the credentials service.

        Not cached, on purpose: a rotation must land on the next call, and the service can only tell
        when an old value is safe to retire if every use reads it again. So call this only where the
        credentials are sent, never where only the static config is needed.

        Raises NotImplementedError when either value is unset, as the static config used to.
        """
        if kind == POSTHOG_CONNECT_KIND:
            target = _posthog_connect_target(region)
            values = get_many_or_settings([target.client_id_key, target.client_secret_key], CREDENTIALS_CALLER)
            client_id, client_secret = values[target.client_id_key], values[target.client_secret_key]
            not_configured = f"PostHog connect app not configured for region {target.region}"
        elif kind == "slack":
            values = get_many_or_instance_settings(SLACK_APP_CLIENT_CREDENTIAL_KEYS, CREDENTIALS_CALLER)
            client_id, client_secret = values["SLACK_APP_CLIENT_ID"], values["SLACK_APP_CLIENT_SECRET"]
            not_configured = "Slack app not configured"
        elif kind == "apple-ads":
            try:
                return apple_ads.service_provider_client_credentials()
            except apple_ads.AppleAdsOauthNotConfigured:
                raise NotImplementedError("Apple Ads service provider app not configured")
        elif kind in OAUTH_CLIENT_CREDENTIAL_KEYS:
            keys = OAUTH_CLIENT_CREDENTIAL_KEYS[kind]
            values = get_many_or_settings([keys.client_id, keys.client_secret], CREDENTIALS_CALLER)
            client_id, client_secret = values[keys.client_id], values[keys.client_secret]
            not_configured = keys.not_configured
        else:
            raise NotImplementedError(f"Oauth config for kind {kind} not implemented")

        if not client_id or not client_secret:
            raise NotImplementedError(not_configured)
        return common.OauthClientCredentials(client_id=client_id, client_secret=client_secret)

    @classmethod
    def fallback_client_credentials_for_kind(
        cls, kind: str, primary: common.OauthClientCredentials
    ) -> common.OauthClientCredentials | None:
        """The legacy credentials of a rotated app, or None when `kind` has none configured.

        Read only after the primary credentials fail, so a kind with no fallback costs no reads.
        """
        keys = OAUTH_CLIENT_FALLBACK_KEYS.get(kind)
        if keys is None:
            return None
        client_id_key, client_secret_key = keys
        values = get_many_or_settings([client_id_key, client_secret_key], CREDENTIALS_CALLER)
        if not values[client_secret_key]:
            return None
        return common.OauthClientCredentials(
            client_id=values[client_id_key] or primary.client_id, client_secret=values[client_secret_key]
        )

    @classmethod
    def _build_oauth_config(cls, kind: str, region: str | None = None) -> OauthConfig:
        if kind == "posthog":
            base_url = _posthog_connect_target(region).base_url
            return OauthConfig(
                authorize_url=f"{base_url}/oauth/authorize",
                token_url=f"{base_url}/oauth/token",
                token_info_url=f"{base_url}/oauth/userinfo",
                token_info_config_fields=["sub", "email"],
                token_revoke_url=f"{base_url}/oauth/revoke",
                # Default only; authorize_url overrides with the user-selected scopes (plus the
                # identity scopes). Token exchange/refresh don't send scope, so this is unused there.
                scope=" ".join([*POSTHOG_CONNECT_DEFAULT_SCOPES, *POSTHOG_CONNECT_IDENTITY_SCOPES]),
                id_path="sub",
                name_path="email",
                pkce=True,
            )
        if kind == "slack":
            return OauthConfig(
                authorize_url="https://slack.com/oauth/v2/authorize",
                token_url="https://slack.com/api/oauth.v2.access",
                scope=POSTHOG_SLACK_SCOPE,
                id_path="team.id",
                name_path="team.name",
            )
        elif kind == "salesforce":
            return OauthConfig(
                authorize_url="https://login.salesforce.com/services/oauth2/authorize",
                token_url="https://login.salesforce.com/services/oauth2/token",
                token_revoke_url="https://login.salesforce.com/services/oauth2/revoke",
                scope="full refresh_token",
                id_path="instance_url",
                name_path="instance_url",
                pkce=True,
            )
        elif kind == "salesforce-sandbox":
            return OauthConfig(
                authorize_url="https://test.salesforce.com/services/oauth2/authorize",
                token_url="https://test.salesforce.com/services/oauth2/token",
                token_revoke_url="https://test.salesforce.com/services/oauth2/revoke",
                scope="full refresh_token",
                id_path="instance_url",
                name_path="instance_url",
                pkce=True,
            )
        elif kind == "pardot":
            # Account Engagement (formerly Pardot) authorizes against Salesforce, so this reuses the
            # Salesforce connected app rather than registering a second one. It needs its own kind
            # because `pardot_api` is not covered by the `full` scope the `salesforce` kind requests:
            # a Salesforce integration authorized for the CRM cannot call the Account Engagement API,
            # and a token scoped for Account Engagement should not appear in the CRM picker.
            return OauthConfig(
                authorize_url="https://login.salesforce.com/services/oauth2/authorize",
                token_url="https://login.salesforce.com/services/oauth2/token",
                token_revoke_url="https://login.salesforce.com/services/oauth2/revoke",
                scope="pardot_api refresh_token",
                id_path="instance_url",
                name_path="instance_url",
                pkce=True,
            )
        elif kind == "hubspot":
            return OauthConfig(
                authorize_url="https://app.hubspot.com/oauth/authorize",
                token_url="https://api.hubapi.com/oauth/v1/token",
                token_info_url="https://api.hubapi.com/oauth/v1/access-tokens/:access_token",
                token_info_config_fields=["hub_id", "hub_domain", "user", "user_id", "scopes"],
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
            return OauthConfig(
                authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
                # forces the consent screen, otherwise we won't receive a refresh token
                additional_authorize_params={"access_type": "offline", "prompt": "consent"},
                token_info_url="https://openidconnect.googleapis.com/v1/userinfo",
                token_info_config_fields=["sub", "email"],
                token_url="https://oauth2.googleapis.com/token",
                scope="https://www.googleapis.com/auth/adwords https://www.googleapis.com/auth/userinfo.email",
                id_path="sub",
                name_path="email",
            )
        elif kind == "google-analytics":
            return OauthConfig(
                authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
                # forces the consent screen, otherwise we won't receive a refresh token
                additional_authorize_params={"access_type": "offline", "prompt": "consent"},
                token_info_url="https://openidconnect.googleapis.com/v1/userinfo",
                token_info_config_fields=["sub", "email"],
                token_url="https://oauth2.googleapis.com/token",
                scope="https://www.googleapis.com/auth/analytics.readonly https://www.googleapis.com/auth/userinfo.email",
                id_path="sub",
                name_path="email",
            )
        elif kind == "google-calendar":
            return OauthConfig(
                authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
                # forces the consent screen, otherwise we won't receive a refresh token
                additional_authorize_params={"access_type": "offline", "prompt": "consent"},
                token_info_url="https://openidconnect.googleapis.com/v1/userinfo",
                token_info_config_fields=["sub", "email"],
                token_url="https://oauth2.googleapis.com/token",
                scope="https://www.googleapis.com/auth/calendar.readonly https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/userinfo.email",
                id_path="sub",
                name_path="email",
            )
        elif kind == "google-search-console":
            return OauthConfig(
                authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
                additional_authorize_params={"access_type": "offline", "prompt": "consent"},
                token_info_url="https://openidconnect.googleapis.com/v1/userinfo",
                token_info_config_fields=["sub", "email"],
                token_url="https://oauth2.googleapis.com/token",
                scope="https://www.googleapis.com/auth/webmasters.readonly https://www.googleapis.com/auth/userinfo.email",
                id_path="sub",
                name_path="email",
            )
        elif kind == "google-sheets":
            return OauthConfig(
                authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
                # forces the consent screen, otherwise we won't receive a refresh token
                additional_authorize_params={"access_type": "offline", "prompt": "consent"},
                token_info_url="https://openidconnect.googleapis.com/v1/userinfo",
                token_info_config_fields=["sub", "email"],
                token_url="https://oauth2.googleapis.com/token",
                scope="https://www.googleapis.com/auth/spreadsheets https://www.googleapis.com/auth/userinfo.email",
                id_path="sub",
                name_path="email",
            )
        elif kind == "youtube-analytics":
            return OauthConfig(
                authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
                # forces the consent screen, otherwise we won't receive a refresh token
                additional_authorize_params={"access_type": "offline", "prompt": "consent"},
                token_info_url="https://openidconnect.googleapis.com/v1/userinfo",
                token_info_config_fields=["sub", "email"],
                token_url="https://oauth2.googleapis.com/token",
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
            return OauthConfig(
                authorize_url="https://accounts.snapchat.com/accounts/oauth2/auth",
                token_url="https://accounts.snapchat.com/accounts/oauth2/token",
                token_info_url="https://adsapi.snapchat.com/v1/me",
                token_info_config_fields=["me.id", "me.email"],
                scope="snapchat-offline-conversions-api snapchat-marketing-api",
                id_path="me.id",
                name_path="me.email",
            )
        elif kind == "linkedin-ads":
            # Note: We extract user info from id_token JWT instead of calling token_info_url
            # because LinkedIn's /v2/userinfo endpoint has intermittent issues returning
            # REVOKED_ACCESS_TOKEN errors for valid tokens. See JWT extraction below.
            return OauthConfig(
                authorize_url="https://www.linkedin.com/oauth/v2/authorization",
                token_url="https://www.linkedin.com/oauth/v2/accessToken",
                scope="r_ads rw_conversions r_ads_reporting openid profile email",
                id_path="sub",
                name_path="email",
            )
        elif kind == "bing-ads":
            return OauthConfig(
                authorize_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
                token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
                scope="https://ads.microsoft.com/msads.manage offline_access openid profile",
                id_path="id",
                name_path="userPrincipalName",
            )
        elif kind == "intercom":
            return OauthConfig(
                authorize_url="https://app.intercom.com/oauth",
                token_url="https://api.intercom.io/auth/eagle/token",
                token_info_url="https://api.intercom.io/me",
                token_info_config_fields=["id", "email", "app.region"],
                scope="",
                id_path="id",
                name_path="email",
            )
        elif kind == "helpscout":
            return OauthConfig(
                authorize_url="https://secure.helpscout.net/authentication/authorizeClientApplication",
                token_url="https://api.helpscout.net/v2/oauth2/token",
                token_info_url="https://api.helpscout.net/v2/users/me",
                # Help Scout grants the authorizing user's full Mailbox API access and takes no
                # scope parameter on the authorize URL.
                scope="",
                id_path="id",
                name_path="email",
                token_info_config_fields=["id", "email"],
                # Help Scout decodes the state one extra time and drops everything after the first `&`, so the
                # token and team_id never come back. A hex string has no characters that it can change.
                opaque_state=True,
            )
        elif kind == "linear":
            return OauthConfig(
                authorize_url="https://linear.app/oauth/authorize",
                # Linear skips its approval screen once the app is authorized, and that screen holds
                # the only workspace switcher, so without `prompt=consent` a person with more than
                # one workspace can never connect anything but the first one.
                additional_authorize_params={"actor": "application", "prompt": "consent"},
                token_url="https://api.linear.app/oauth/token",
                token_info_url="https://api.linear.app/graphql",
                token_info_graphql_query="{ viewer { organization { id name urlKey } } }",
                token_info_config_fields=[
                    "data.viewer.organization.id",
                    "data.viewer.organization.name",
                    "data.viewer.organization.urlKey",
                ],
                scope="read issues:create",
                id_path="data.viewer.organization.id",
                name_path="data.viewer.organization.name",
            )
        elif kind == "meta-ads":
            return OauthConfig(
                authorize_url=f"https://www.facebook.com/{common.META_GRAPH_API_VERSION}/dialog/oauth",
                token_url=f"https://graph.facebook.com/{common.META_GRAPH_API_VERSION}/oauth/access_token",
                token_info_url=f"https://graph.facebook.com/{common.META_GRAPH_API_VERSION}/me",
                token_info_config_fields=["id", "name", "email"],
                scope="ads_read",
                id_path="id",
                name_path="name",
            )
        elif kind == "instagram":
            # Same Facebook Login endpoints as Meta Ads, and the credentials may even be the same
            # Meta app, but the two grants request different scopes so they stay separate kinds.
            # The token response carries no account identifier, so id/name come from `/me`.
            return OauthConfig(
                authorize_url=f"https://www.facebook.com/{common.META_GRAPH_API_VERSION}/dialog/oauth",
                token_url=f"https://graph.facebook.com/{common.META_GRAPH_API_VERSION}/oauth/access_token",
                token_info_url=f"https://graph.facebook.com/{common.META_GRAPH_API_VERSION}/me",
                token_info_config_fields=["id", "name"],
                scope=INSTAGRAM_OAUTH_SCOPE,
                id_path="id",
                name_path="name",
            )
        elif kind == "reddit-ads":
            return OauthConfig(
                authorize_url="https://www.reddit.com/api/v1/authorize",
                token_url="https://www.reddit.com/api/v1/access_token",
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
            return OauthConfig(
                authorize_url="https://business-api.tiktok.com/portal/auth",
                token_url="https://business-api.tiktok.com/open_api/v1.3/oauth2/access_token/",
                scope="",
                id_path="data.advertiser_ids",
                name_path="data.advertiser_ids",
            )
        elif kind == "clickup":
            return OauthConfig(
                authorize_url="https://app.clickup.com/api",
                token_url="https://api.clickup.com/api/v2/oauth/token",
                token_info_url="https://api.clickup.com/api/v2/user",
                token_info_config_fields=["user.id", "user.email"],
                scope="",
                id_path="user.id",
                name_path="user.email",
            )
        elif kind == "jira":
            return OauthConfig(
                authorize_url="https://auth.atlassian.com/authorize",
                additional_authorize_params={"audience": "api.atlassian.com", "prompt": "consent"},
                token_url="https://auth.atlassian.com/oauth/token",
                token_info_url="https://api.atlassian.com/oauth/token/accessible-resources",
                token_info_config_fields=[],  # Handled specially in integration_from_oauth_response
                scope="read:jira-work write:jira-work read:jira-user offline_access",
                id_path="cloud_id",
                name_path="site_name",
            )
        elif kind == "pinterest-ads":
            return OauthConfig(
                authorize_url="https://www.pinterest.com/oauth/",
                token_url="https://api.pinterest.com/v5/oauth/token",
                token_info_url="https://api.pinterest.com/v5/user_account",
                token_info_config_fields=["id", "username", "business_name"],
                scope="ads:read user_accounts:read",
                id_path="id",
                name_path="username",
            )
        elif kind == "stripe":
            authorize_url = (
                settings.STRIPE_APP_OVERRIDE_AUTHORIZE_URL or "https://marketplace.stripe.com/oauth/v2/authorize"
            )
            return OauthConfig(
                authorize_url=authorize_url,
                token_url="https://api.stripe.com/v1/oauth/token",
                scope="",
                id_path="stripe_user_id",
                name_path="account_name",
            )
        elif kind == "resend":
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
                scope="full_access",
                pkce=True,
                id_path="resend_account_id",
                name_path="resend_account_name",
            )

        elif kind == "apple-ads":
            # Apple's service provider flow, where a PostHog registration acts on behalf of an
            # Apple Ads user who grants access. The first-party flow the warehouse source also
            # supports is a different thing: it uses the customer's own key pair with
            # `client_credentials` and the `searchadsorg` scope, and never reaches this code.
            #
            # The client secret is signed, not stored: Apple issues no static secret, so
            # `client_credentials_for_kind` mints a fresh ES256 assertion on every call.
            #
            # The token response carries no account identifier, so id/name come from Apple's ACL
            # endpoint below (see the apple-ads branch in integration_from_oauth_response).
            return OauthConfig(
                authorize_url="https://appleid.apple.com/auth/oauth2/v2/authorize",
                token_url=APPLE_ADS_TOKEN_URL,
                scope="searchads",
                id_path="apple_ads_account_id",
                name_path="apple_ads_account_name",
            )

        raise NotImplementedError(f"Oauth config for kind {kind} not implemented")

    @classmethod
    def redirect_uri(cls, kind: str) -> str:
        # The redirect uri is fixed but should always be https and include the "next" parameter for the frontend to redirect
        path_kind = OAUTH_REDIRECT_URI_ALIASES.get(kind, kind)
        if settings.DEBUG and settings.NGROK_URL:
            return f"{settings.NGROK_URL}/integrations/{path_kind}/callback"
        return f"{settings.SITE_URL.replace('http://', 'https://')}/integrations/{path_kind}/callback"

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
        # Only the id goes into the URL, but resolving the pair keeps the "not configured" check on
        # the secret too, so an unusable app fails here instead of after the user has consented.
        client = cls.client_credentials_for_kind(kind, region)

        # Carry the initiating team through the OAuth round-trip. The fixed callback URL is not
        # project-scoped, so without this the SPA re-resolves to the user's default team on
        # reload and the integration lands on the wrong project.
        state_payload: dict[str, str] = {"next": next, "token": token}
        if team_id is not None:
            state_payload["team_id"] = str(team_id)
        if kind in OAUTH_REDIRECT_URI_ALIASES:
            # The callback lands on the aliased kind's path, so its URL segment names the wrong
            # integration. The callback handler reads the real kind from here instead.
            state_payload["kind"] = kind

        scope = oauth_config.scope
        if kind == "posthog":
            # The target cell is the authorization server, so the callback (which runs on the
            # connecting cell) needs to know which region to exchange the code against — carry it
            # in state. Always append the identity scopes so /oauth/userinfo can name the account.
            state_payload["region"] = (region or "").upper()
            requested = list(scopes) if scopes else list(POSTHOG_CONNECT_DEFAULT_SCOPES)
            scope = " ".join(dict.fromkeys([*requested, *POSTHOG_CONNECT_IDENTITY_SCOPES]))

        state = urlencode(state_payload)
        if oauth_config.opaque_state:
            state = state.encode().hex()

        if kind == "tiktok-ads":
            # TikTok uses different parameter names
            query_params = {
                "app_id": client.client_id,
                "redirect_uri": cls.redirect_uri(kind),
                "state": state,
            }
        else:
            query_params = {
                "client_id": client.client_id,
                "scope": scope,
                "redirect_uri": cls.redirect_uri(kind),
                "response_type": "code",
                "state": state,
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
        client = cls.client_credentials_for_kind(kind, region)

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
                auth=HTTPBasicAuth(client.client_id, client.client_secret),
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
                auth=HTTPBasicAuth(client.client_id, client.client_secret),
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
                    "app_id": client.client_id,
                    "secret": client.client_secret,
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
                auth=HTTPBasicAuth(client.client_secret, ""),
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
                    "client_id": client.client_id,
                    "client_secret": client.client_secret,
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
            if kind in SALESFORCE_OAUTH_KINDS:
                oauth_config = cls.oauth_config_for_kind("salesforce-sandbox")
                client = cls.client_credentials_for_kind("salesforce-sandbox")
                res = requests.post(
                    oauth_config.token_url,
                    data={
                        "client_id": client.client_id,
                        "client_secret": client.client_secret,
                        "code": params["code"],
                        "redirect_uri": OauthIntegration.redirect_uri(kind),
                        "grant_type": "authorization_code",
                        **({"code_verifier": code_verifier} if code_verifier else {}),
                    },
                    timeout=10,
                    # Same guard as the first exchange: a 30x must not resend the secret and code.
                    allow_redirects=False,
                )

                try:
                    config = res.json()
                except ValueError:
                    config = {}

                if res.status_code != 200 or not config.get("access_token"):
                    logger.error(
                        f"Oauth error for {kind}",
                        response=res.text,
                        status_code=res.status_code,
                        client_id=client.client_id,
                        redirect_uri=OauthIntegration.redirect_uri(kind),
                        code_prefix=str(params.get("code", ""))[:12],
                        exchange_host="sandbox",
                    )
                    _raise_oauth_validation_error(kind, res)
            else:
                # Include request context so on-call can compare what we sent against what
                # the merchant authorized with in Stripe. Code prefix only, full grant is
                # short-lived but still a credential during its TTL. Never log client_secret.
                logger.error(
                    f"Oauth error for {kind}",
                    response=res.text,
                    status_code=res.status_code,
                    client_id=client.client_id,
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

        # Apple's token response carries no account identifier. Apple documents the ACL endpoint as
        # the call to make once per access token, so it names the grant and checks that it can read
        # something. The granting user may reach several ad accounts across organizations. A hash
        # of the opaque grant token keeps separate grants from overwriting one another, while the
        # account is picked per source afterwards.
        if kind == "apple-ads" and not integration_id:
            accounts = _apple_ads_acl_accounts(config["access_token"])
            if not accounts:
                raise ValidationError(
                    "This Apple Ads user cannot read any ad account. Ask an account admin to grant "
                    "access in Apple Ads, then connect again."
                )
            org_ids = sorted({str(account["orgId"]) for account in accounts if account.get("orgId") is not None})
            config["apple_ads_account_name"] = _apple_ads_account_name(accounts)
            config["apple_ads_org_ids"] = org_ids
            grant_token = config.get("refresh_token") or config["access_token"]
            integration_id = f"grant:{hashlib.sha256(grant_token.encode()).hexdigest()}"

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

                stripe_client = StripeClient(client.client_secret)
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
            client = self.client_credentials_for_kind(self.integration.kind, region)
            data["client_id"] = client.client_id
            data["client_secret"] = client.client_secret
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

    def _post_token_refresh(
        self, oauth_config: OauthConfig, client: common.OauthClientCredentials
    ) -> requests.Response:
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
                auth=HTTPBasicAuth(client.client_id, client.client_secret),
                data={"refresh_token": refresh_token, "grant_type": "refresh_token"},
                # If I use a standard User-Agent, it will throw a 429 too many requests error
                headers={"User-Agent": "PostHog/1.0 by PostHogTeam"},
                timeout=10,
            )
        # Pinterest uses HTTP Basic Auth for token refresh
        elif kind == "pinterest-ads":
            return requests.post(
                oauth_config.token_url,
                auth=HTTPBasicAuth(client.client_id, client.client_secret),
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
                    "app_id": client.client_id,
                    "secret": client.client_secret,
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
                    "client_id": client.client_id,
                    "client_secret": client.client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                    "scope": oauth_config.scope,
                },
                timeout=10,
            )
        elif kind == "stripe":
            # Stripe Apps OAuth: secret as HTTP Basic username, no client_id/client_secret in body.
            # Stripe rolls the refresh token on every exchange. If the response is lost after
            # Stripe committed the roll, the stored token is dead and only a reconnect recovers.
            # A key derived from the token makes the next attempt replay Stripe's saved response.
            return requests.post(
                oauth_config.token_url,
                auth=HTTPBasicAuth(client.client_secret, ""),
                data={"refresh_token": refresh_token, "grant_type": "refresh_token"},
                headers={"Idempotency-Key": hashlib.sha256(refresh_token.encode()).hexdigest()},
                timeout=10,
            )
        elif kind == "apple-ads":
            # Apple's guide names `/auth/token` for the refresh grant while the exchange it pairs
            # with uses `/auth/oauth2/token`. Try the exchange endpoint first, then the documented
            # one, so a wrong guess in either direction costs one extra request on failure instead
            # of a dead integration. Drop the fallback once Apple's behavior is confirmed.
            body = {
                "client_id": client.client_id,
                "client_secret": client.client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            }
            res = requests.post(oauth_config.token_url, data=body, timeout=10, allow_redirects=False)
            if res.status_code == 200:
                return res
            return requests.post(APPLE_ADS_REFRESH_TOKEN_FALLBACK_URL, data=body, timeout=10, allow_redirects=False)
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
                    "client_id": client.client_id,
                    "client_secret": client.client_secret,
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
        # Resolved before anything changes on the integration: a credentials service failure is
        # never this integration's fault, so it must not leave the integration marked as failed.
        client = self.client_credentials_for_kind(self.integration.kind, region)

        # Clear out previous token refreshing errors, as they'll be re-set below if another error occurs
        self.integration.errors = ""

        res: requests.Response | None = None
        config: dict = {}
        used_fallback = False
        try:
            res = self._post_token_refresh(oauth_config, client)
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
        fallback_client = (
            self.fallback_client_credentials_for_kind(self.integration.kind, client)
            if res is None or res.status_code != 200 or not config.get("access_token")
            else None
        )
        if fallback_client is not None:
            try:
                res = self._post_token_refresh(oauth_config, fallback_client)
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
