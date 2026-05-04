import hmac
import json
import time
import base64
import socket
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal, NamedTuple, NoReturn, Optional
from urllib.parse import urlencode

from products.workflows.backend.providers import MAILDEV_MOCK_DNS_RECORDS

if TYPE_CHECKING:
    import aiohttp

from django.conf import settings
from django.db import models
from django.http import HttpRequest
from django.utils import timezone

import requests
import structlog
from disposable_email_domains import blocklist as disposable_email_domains_list
from free_email_domains import whitelist as free_email_domains_list
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import service_account
from prometheus_client import Counter
from requests.auth import HTTPBasicAuth
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient
from stripe import StripeClient

from posthog.cache_utils import cache_for
from posthog.exceptions_capture import capture_exception
from posthog.helpers.encrypted_fields import EncryptedJSONField
from posthog.models.github_integration_base import GitHubIntegrationBase, GitHubIntegrationError
from posthog.models.instance_setting import get_instance_settings
from posthog.models.oauth import OAuthAccessToken, OAuthApplication, OAuthRefreshToken
from posthog.models.user import User
from posthog.models.utils import generate_random_oauth_access_token, generate_random_oauth_refresh_token
from posthog.plugins.plugin_server_api import reload_integrations_on_workers
from posthog.rbac.decorators import field_access_control
from posthog.security.url_validation import is_url_allowed
from posthog.sync import database_sync_to_async
from posthog.utils import get_instance_region

from products.workflows.backend.providers import SESProvider, TwilioProvider

logger = structlog.get_logger(__name__)


def _decode_jwt_payload(token: str) -> dict | None:
    """
    Decode JWT payload without signature verification.

    Used to extract claims from OAuth tokens (id_token, access_token) where
    we trust the token source (received directly from provider over HTTPS).

    Returns None if JWT doesn't have enough parts. Raises on decode errors
    so callers can log exceptions with full traceback.
    """
    parts = token.split(".")
    if len(parts) < 2:
        return None
    payload = parts[1]
    # Handle missing base64 padding
    decoded = base64.urlsafe_b64decode(payload + "===")
    return json.loads(decoded)


oauth_refresh_counter = Counter(
    "integration_oauth_refresh", "Number of times an oauth refresh has been attempted", labelnames=["kind", "result"]
)

GITHUB_API_VERSION = "2022-11-28"

PRIVATE_CHANNEL_WITHOUT_ACCESS = "PRIVATE_CHANNEL_WITHOUT_ACCESS"


def dot_get(d: Any, path: str, default: Any = None) -> Any:
    if path in d and d[path] is not None:
        return d[path]
    for key in path.split("."):
        if not isinstance(d, dict):
            return default
        d = d.get(key, default)
    return d


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


ERROR_TOKEN_REFRESH_FAILED = "TOKEN_REFRESH_FAILED"


class Integration(models.Model):
    class IntegrationKind(models.TextChoices):
        APPLE_PUSH = "apns"
        AZURE_BLOB = "azure-blob"
        BING_ADS = "bing-ads"
        CLICKUP = "clickup"
        CUSTOMERIO_APP = "customerio-app"
        CUSTOMERIO_TRACK = "customerio-track"
        CUSTOMERIO_WEBHOOK = "customerio-webhook"
        DATABRICKS = "databricks"
        EMAIL = "email"
        FIREBASE = "firebase"
        GITHUB = "github"
        GITLAB = "gitlab"
        GOOGLE_ADS = "google-ads"
        GOOGLE_CLOUD_SERVICE_ACCOUNT = "google-cloud-service-account"
        GOOGLE_CLOUD_STORAGE = "google-cloud-storage"
        GOOGLE_PUBSUB = "google-pubsub"
        GOOGLE_SHEETS = "google-sheets"
        HUBSPOT = "hubspot"
        INTERCOM = "intercom"
        JIRA = "jira"
        LINEAR = "linear"
        LINKEDIN_ADS = "linkedin-ads"
        META_ADS = "meta-ads"
        PINTEREST_ADS = "pinterest-ads"
        POSTGRESQL = "postgresql"
        REDDIT_ADS = "reddit-ads"
        SALESFORCE = "salesforce"
        SLACK = "slack"
        SLACK_POSTHOG_CODE = "slack-posthog-code"
        SNAPCHAT = "snapchat"
        STRIPE = "stripe"
        TIKTOK_ADS = "tiktok-ads"
        TWILIO = "twilio"
        VERCEL = "vercel"

    team = models.ForeignKey("Team", on_delete=models.CASCADE)

    # The integration type identifier
    kind = field_access_control(models.CharField(max_length=32, choices=IntegrationKind), "project", "admin")
    # The ID of the integration in the external system
    integration_id = field_access_control(models.TextField(null=True, blank=True), "project", "admin")
    # Any config that COULD be passed to the frontend
    config = field_access_control(models.JSONField(default=dict), "project", "admin")
    sensitive_config = field_access_control(
        EncryptedJSONField(
            default=dict,
            ignore_decrypt_errors=True,  # allows us to load previously unencrypted data
        ),
        "project",
        "admin",
    )
    repository_cache = models.JSONField(default=list, blank=True)
    repository_cache_updated_at = models.DateTimeField(null=True, blank=True)

    errors = models.TextField()

    # Meta
    created_at = models.DateTimeField(auto_now_add=True, blank=True)
    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "kind", "integration_id"], name="posthog_integration_kind_id_unique"
            )
        ]

    @property
    def display_name(self) -> str:
        if self.kind in OauthIntegration.supported_kinds:
            oauth_config = OauthIntegration.oauth_config_for_kind(self.kind)
            return dot_get(self.config, oauth_config.name_path, self.integration_id)
        if self.kind in GoogleCloudIntegration.supported_kinds:
            return self.integration_id or "unknown ID"
        if self.kind == "github":
            return dot_get(self.config, "account.name", self.integration_id)
        if self.kind == "databricks":
            return self.integration_id or "unknown ID"
        if self.kind == "gitlab":
            return self.integration_id or "unknown ID"
        if self.kind == "email":
            return self.config.get("email", self.integration_id)
        if self.kind == "apns":
            return self.config.get("bundle_id", self.integration_id)

        return f"ID: {self.integration_id}"

    @property
    def access_token(self) -> str | None:
        return self.sensitive_config.get("access_token")

    @property
    def refresh_token(self) -> str | None:
        return self.sensitive_config.get("refresh_token")


def defer_repository_cache_fields(queryset: models.QuerySet[Integration]) -> models.QuerySet[Integration]:
    return queryset.defer("repository_cache", "repository_cache_updated_at")


@database_sync_to_async
def aget_integration_by_id(integration_id: str, team_id: int) -> Integration | None:
    return Integration.objects.get(id=integration_id, team_id=team_id)


@dataclass
class OauthConfig:
    authorize_url: str
    token_url: str
    client_id: str
    client_secret: str
    scope: str
    id_path: str
    name_path: str
    token_info_url: str | None = None
    token_info_graphql_query: str | None = None
    token_info_config_fields: list[str] | None = None
    additional_authorize_params: dict[str, str] | None = None


POSTHOG_SLACK_SCOPE = ",".join(
    [
        "channels:read",
        "groups:read",
        "chat:write",
        "chat:write.customize",
        *(
            [  # New scopes that came with the update adding PostHog AI integration with Slack
                "app_mentions:read",
                "channels:history",
                "groups:history",
                "links:read",
                "links:write",
                "reactions:read",
                "reactions:write",
                "team:read",
                "users:read",
                "users:read.email",
            ]
            if settings.DEBUG or settings.CLOUD_DEPLOYMENT == "DEV"
            else []
        ),
    ]
)


class OauthIntegration:
    supported_kinds = [
        "slack",
        "slack-posthog-code",
        "salesforce",
        "hubspot",
        "google-ads",
        "google-sheets",
        "snapchat",
        "linkedin-ads",
        "reddit-ads",
        "tiktok-ads",
        "bing-ads",
        "meta-ads",
        "intercom",
        "linear",
        "clickup",
        "jira",
        "pinterest-ads",
        "stripe",
    ]
    integration: Integration

    def __str__(self) -> str:
        return f"OauthIntegration(integration={self.integration.id}, kind={self.integration.kind}, team={self.integration.team_id})"

    def __init__(self, integration: Integration) -> None:
        self.integration = integration

    @classmethod
    @cache_for(timedelta(minutes=5))
    def oauth_config_for_kind(cls, kind: str, is_sandbox: bool = False) -> OauthConfig:
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
        elif kind == "slack-posthog-code":
            if not settings.SLACK_POSTHOG_CODE_CLIENT_ID or not settings.SLACK_POSTHOG_CODE_CLIENT_SECRET:
                raise NotImplementedError("PostHog Code Slack app not configured")

            return OauthConfig(
                authorize_url="https://slack.com/oauth/v2/authorize",
                token_url="https://slack.com/api/oauth.v2.access",
                client_id=settings.SLACK_POSTHOG_CODE_CLIENT_ID,
                client_secret=settings.SLACK_POSTHOG_CODE_CLIENT_SECRET,
                scope="app_mentions:read,channels:read,groups:read,channels:history,groups:history,chat:write,reactions:write,users:read,users:read.email",
                id_path="team.id",
                name_path="team.name",
            )
        elif kind == "salesforce":
            if not settings.SALESFORCE_CONSUMER_KEY or not settings.SALESFORCE_CONSUMER_SECRET:
                raise NotImplementedError("Salesforce app not configured")

            return OauthConfig(
                authorize_url="https://login.salesforce.com/services/oauth2/authorize",
                token_url="https://login.salesforce.com/services/oauth2/token",
                client_id=settings.SALESFORCE_CONSUMER_KEY,
                client_secret=settings.SALESFORCE_CONSUMER_SECRET,
                scope="full refresh_token",
                id_path="instance_url",
                name_path="instance_url",
            )
        elif kind == "salesforce-sandbox":
            if not settings.SALESFORCE_CONSUMER_KEY or not settings.SALESFORCE_CONSUMER_SECRET:
                raise NotImplementedError("Salesforce app not configured")

            return OauthConfig(
                authorize_url="https://test.salesforce.com/services/oauth2/authorize",
                token_url="https://test.salesforce.com/services/oauth2/token",
                client_id=settings.SALESFORCE_CONSUMER_KEY,
                client_secret=settings.SALESFORCE_CONSUMER_SECRET,
                scope="full refresh_token",
                id_path="instance_url",
                name_path="instance_url",
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
                    # NOTE: these scopes are only available on certain hubspot plans and as such are optional
                    "optional_scope": "analytics.behavioral_events.send behavioral_events.event_definitions.read_write"
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
                authorize_url=f"https://www.facebook.com/{MetaAdsIntegration.api_version}/dialog/oauth",
                token_url=f"https://graph.facebook.com/{MetaAdsIntegration.api_version}/oauth/access_token",
                token_info_url=f"https://graph.facebook.com/{MetaAdsIntegration.api_version}/me",
                token_info_config_fields=["id", "name", "email"],
                client_id=settings.META_ADS_APP_CLIENT_ID,
                client_secret=settings.META_ADS_APP_CLIENT_SECRET,
                scope="ads_read",
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
                name_path="reddit_user_id",  # Same as ID for Reddit
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
                token_info_config_fields=["id", "username"],
                client_id=settings.PINTEREST_ADS_CLIENT_ID,
                client_secret=settings.PINTEREST_ADS_CLIENT_SECRET,
                scope="ads:read user_accounts:read",
                id_path="id",
                name_path="username",
            )
        elif kind == "stripe":
            if not settings.STRIPE_APP_CLIENT_ID or not settings.STRIPE_APP_SECRET_KEY:
                raise NotImplementedError("Stripe app not configured")

            # Stripe issues separate client_id and secret for live vs sandbox installs of the
            # same app. Sandbox-issued OAuth codes can only be redeemed with the sandbox secret;
            # using the live secret returns "Authorization code provided does not belong to you".
            if is_sandbox:
                if not settings.STRIPE_APP_SANDBOX_CLIENT_ID or not settings.STRIPE_APP_SANDBOX_SECRET_KEY:
                    raise NotImplementedError("Stripe sandbox not configured")
                client_id = settings.STRIPE_APP_SANDBOX_CLIENT_ID
                client_secret = settings.STRIPE_APP_SANDBOX_SECRET_KEY
            else:
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

        raise NotImplementedError(f"Oauth config for kind {kind} not implemented")

    @classmethod
    def redirect_uri(cls, kind: str) -> str:
        # The redirect uri is fixed but should always be https and include the "next" parameter for the frontend to redirect
        # slack-posthog-code piggybacks on the approved /integrations/slack/callback redirect URI
        # because the approved production Slack app is still under review for the new path.
        # The real kind is carried in OAuth state so the callback still creates a slack-posthog-code integration.
        path_kind = "slack" if kind == "slack-posthog-code" else kind
        if settings.DEBUG and settings.NGROK_URL:
            return f"{settings.NGROK_URL}/integrations/{path_kind}/callback"
        return f"{settings.SITE_URL.replace('http://', 'https://')}/integrations/{path_kind}/callback"

    @classmethod
    def authorize_url(cls, kind: str, token: str, next: str = "", is_sandbox: bool = False) -> str:
        oauth_config = cls.oauth_config_for_kind(kind, is_sandbox=is_sandbox)

        state_payload: dict[str, str] = {"next": next, "token": token}
        if kind == "slack-posthog-code":
            state_payload["kind"] = kind

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
                "scope": oauth_config.scope,
                "redirect_uri": cls.redirect_uri(kind),
                "response_type": "code",
                "state": urlencode(state_payload),
                **(oauth_config.additional_authorize_params or {}),
            }

        return f"{oauth_config.authorize_url}?{urlencode(query_params)}"

    @classmethod
    def integration_from_oauth_response(
        cls, kind: str, team_id: int, created_by: User, params: dict[str, str]
    ) -> Integration:
        oauth_config = cls.oauth_config_for_kind(kind)

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
            )
            # Marketplace-initiated installs land on /integrations/stripe/confirm-install
            # without any signal indicating live vs sandbox. If the live secret rejected
            # the code as "does not belong to you", it was minted by the sandbox app -
            # retry with the sandbox secret. Both sandbox client_id and secret must be
            # configured: oauth_config_for_kind requires both, so guard on both here to
            # avoid raising NotImplementedError over the original OAuth error.
            if (
                res.status_code == 400
                and settings.STRIPE_APP_SANDBOX_CLIENT_ID
                and settings.STRIPE_APP_SANDBOX_SECRET_KEY
                and "does not belong to you" in (res.text or "")
            ):
                sandbox_oauth_config = cls.oauth_config_for_kind("stripe", is_sandbox=True)
                res = requests.post(
                    sandbox_oauth_config.token_url,
                    auth=HTTPBasicAuth(sandbox_oauth_config.client_secret, ""),
                    data={
                        "code": params["code"],
                        "grant_type": "authorization_code",
                    },
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
                },
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
                    },
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
                )
            else:
                token_info_res = requests.get(
                    oauth_config.token_info_url.replace(":access_token", config["access_token"]),
                    headers={"Authorization": f"Bearer {config['access_token']}"},
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
                        config[field] = dot_get(data, field)
            else:
                logger.error(
                    f"OAuth token_info request failed for {kind}",
                    token_info_url=oauth_config.token_info_url,
                    status_code=token_info_res.status_code,
                    response=token_info_res.text[:500],
                )

        integration_id = dot_get(config, oauth_config.id_path)

        # Bing Ads id_token is a JWT, extract user ID from it
        if kind == "bing-ads" and not integration_id:
            try:
                id_token = config.get("id_token")
                if id_token:
                    jwt_data = _decode_jwt_payload(id_token)
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
                    jwt_data = _decode_jwt_payload(access_token)
                    if jwt_data:
                        # Extract user ID from JWT (lid = login ID)
                        reddit_user_id = jwt_data.get("lid", jwt_data.get("aid"))
                        if reddit_user_id:
                            config["reddit_user_id"] = reddit_user_id
                            integration_id = reddit_user_id
            except Exception as e:
                logger.exception("Failed to decode Reddit JWT", error=str(e))

        # LinkedIn id_token is a JWT, extract user ID and email from it
        # This avoids calling /v2/userinfo which has intermittent REVOKED_ACCESS_TOKEN errors
        if kind == "linkedin-ads" and not integration_id:
            try:
                id_token = config.get("id_token")
                if id_token:
                    jwt_data = _decode_jwt_payload(id_token)
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

        sensitive_config: dict = {
            "access_token": config.pop("access_token"),
            # NOTE: We don't actually use the refresh and id tokens (typically they aren't even provided for this sort of service auth)
            # but we ensure they are popped and stored in sensitive config to avoid accidental exposure
            "refresh_token": config.pop("refresh_token", None),
            "id_token": config.pop("id_token", None),
        }

        # Handle case where Salesforce doesn't provide expires_in in initial response
        if not config.get("expires_in") and kind == "salesforce":
            # Default to 1 hour for Salesforce if not provided (conservative)
            config["expires_in"] = 3600

        config["refreshed_at"] = int(time.time())

        integration, created = Integration.objects.update_or_create(
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

        return integration

    def access_token_expired(self, time_threshold: timedelta | None = None) -> bool:
        # Not all integrations have refresh tokens or expiries, so we just return False if we can't check

        refresh_token = self.integration.sensitive_config.get("refresh_token")
        expires_in = self.integration.config.get("expires_in")
        refreshed_at = self.integration.config.get("refreshed_at")

        if not refresh_token:
            return False

        if not expires_in and self.integration.kind == "salesforce":
            # Salesforce tokens typically last 2-4 hours, we'll assume 1 hour (3600 seconds) to be conservative
            expires_in = 3600

        if not expires_in or not refreshed_at:
            return False

        # To be really safe we refresh if its half way through the expiry
        time_threshold = time_threshold or timedelta(seconds=expires_in / 2)

        return time.time() > refreshed_at + expires_in - time_threshold.total_seconds()

    def refresh_access_token(self):
        """
        Refresh the access token for the integration if necessary
        """
        oauth_config = self.oauth_config_for_kind(self.integration.kind)

        # Clear out previous token refreshing errors, as they'll be re-set below if another error occurs
        self.integration.errors = ""

        # Reddit uses HTTP Basic Auth for token refresh
        if self.integration.kind == "reddit-ads":
            res = requests.post(
                oauth_config.token_url,
                auth=HTTPBasicAuth(oauth_config.client_id, oauth_config.client_secret),
                data={
                    "refresh_token": self.integration.sensitive_config["refresh_token"],
                    "grant_type": "refresh_token",
                },
                # If I use a standard User-Agent, it will throw a 429 too many requests error
                headers={"User-Agent": "PostHog/1.0 by PostHogTeam"},
            )
        # Pinterest uses HTTP Basic Auth for token refresh
        elif self.integration.kind == "pinterest-ads":
            res = requests.post(
                oauth_config.token_url,
                auth=HTTPBasicAuth(oauth_config.client_id, oauth_config.client_secret),
                data={
                    "refresh_token": self.integration.sensitive_config["refresh_token"],
                    "grant_type": "refresh_token",
                },
            )
        elif self.integration.kind == "tiktok-ads":
            res = requests.post(
                "https://open.tiktokapis.com/v2/oauth/token/",
                data={
                    "client_key": oauth_config.client_id,  # TikTok uses client_key instead of client_id
                    "client_secret": oauth_config.client_secret,
                    "refresh_token": self.integration.sensitive_config["refresh_token"],
                    "grant_type": "refresh_token",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        elif self.integration.kind == "bing-ads":
            # Microsoft Azure AD requires scope parameter on token refresh
            res = requests.post(
                oauth_config.token_url,
                data={
                    "client_id": oauth_config.client_id,
                    "client_secret": oauth_config.client_secret,
                    "refresh_token": self.integration.sensitive_config["refresh_token"],
                    "grant_type": "refresh_token",
                    "scope": oauth_config.scope,
                },
            )
        elif self.integration.kind == "stripe":
            # Stripe Apps OAuth: secret as HTTP Basic username, no client_id/client_secret in body.
            res = requests.post(
                oauth_config.token_url,
                auth=HTTPBasicAuth(oauth_config.client_secret, ""),
                data={
                    "refresh_token": self.integration.sensitive_config["refresh_token"],
                    "grant_type": "refresh_token",
                },
            )
        else:
            res = requests.post(
                oauth_config.token_url,
                data={
                    "client_id": oauth_config.client_id,
                    "client_secret": oauth_config.client_secret,
                    "refresh_token": self.integration.sensitive_config["refresh_token"],
                    "grant_type": "refresh_token",
                },
            )

        config: dict = res.json()

        if res.status_code != 200 or not config.get("access_token"):
            logger.warning(f"Failed to refresh token for {self}", response=res.text)
            self.integration.errors = ERROR_TOKEN_REFRESH_FAILED
            oauth_refresh_counter.labels(self.integration.kind, "failed").inc()
        else:
            logger.info(f"Refreshed access token for {self}")
            self.integration.sensitive_config["access_token"] = config["access_token"]

            # Some providers (e.g. Atlassian/Jira) rotate refresh tokens — each
            # refresh response includes a new refresh_token and the old one is
            # invalidated.  Always store the latest one to avoid "invalid refresh
            # token" errors on subsequent refreshes.
            if config.get("refresh_token"):
                self.integration.sensitive_config["refresh_token"] = config["refresh_token"]

            # Handle case where Salesforce doesn't provide expires_in in refresh response
            expires_in = config.get("expires_in")
            if not expires_in and self.integration.kind == "salesforce":
                # Default to 1 hour for Salesforce if not provided (conservative)
                expires_in = 3600

            self.integration.config["expires_in"] = expires_in
            self.integration.config["refreshed_at"] = int(time.time())
            reload_integrations_on_workers(self.integration.team_id, [self.integration.id])
            oauth_refresh_counter.labels(self.integration.kind, "success").inc()

        self.integration.save()


class SlackIntegrationError(Exception):
    pass


SLACK_INTEGRATION_KINDS: tuple[str, ...] = ("slack", "slack-posthog-code")


class SlackIntegration:
    integration: Integration

    def __init__(self, integration: Integration) -> None:
        if integration.kind not in SLACK_INTEGRATION_KINDS:
            raise Exception("SlackIntegration init called with Integration with wrong 'kind'")

        self.integration = integration

    @property
    def client(self) -> WebClient:
        return WebClient(self.integration.sensitive_config["access_token"])

    def async_client(self, session: Optional["aiohttp.ClientSession"] = None) -> AsyncWebClient:
        return AsyncWebClient(self.integration.sensitive_config["access_token"], session=session)

    def list_channels(self, should_include_private_channels: bool, authed_user: str) -> list[dict]:
        # NOTE: Annoyingly the Slack API has no search so we have to load all channels...
        # We load public and private channels separately as when mixed, the Slack API pagination is buggy
        public_channels = self._list_channels_by_type("public_channel")
        private_channels = self._list_channels_by_type("private_channel", should_include_private_channels, authed_user)
        channels = public_channels + private_channels

        return sorted(channels, key=lambda x: x["name"])

    def get_channel_by_id(
        self, channel_id: str, should_include_private_channels: bool = False, authed_user: str | None = None
    ) -> dict | None:
        try:
            response = self.client.conversations_info(channel=channel_id, include_num_members=True)
            channel = response["channel"]
            members_response = self.client.conversations_members(channel=channel_id, limit=channel["num_members"] + 1)
            isMember = authed_user in members_response["members"]

            if not isMember:
                return None

            isPrivateWithoutAccess = channel["is_private"] and not should_include_private_channels

            return {
                "id": channel["id"],
                "name": PRIVATE_CHANNEL_WITHOUT_ACCESS if isPrivateWithoutAccess else channel["name"],
                "is_private": channel["is_private"],
                "is_member": channel.get("is_member", True),
                "is_ext_shared": channel["is_ext_shared"],
                "is_private_without_access": isPrivateWithoutAccess,
            }
        except SlackApiError as e:
            if e.response["error"] == "channel_not_found":
                return None
            raise

    def _list_channels_by_type(
        self,
        type: Literal["public_channel", "private_channel"],
        should_include_private_channels: bool = False,
        authed_user: str | None = None,
    ) -> list[dict]:
        max_page = 50
        channels = []
        cursor = None

        while max_page > 0:
            max_page -= 1
            if type == "public_channel":
                res = self.client.conversations_list(exclude_archived=True, types=type, limit=200, cursor=cursor)
            else:
                res = self.client.users_conversations(
                    exclude_archived=True, types=type, limit=200, cursor=cursor, user=authed_user
                )

                for channel in res["channels"]:
                    if channel["is_private"] and not should_include_private_channels:
                        channel["name"] = PRIVATE_CHANNEL_WITHOUT_ACCESS
                        channel["is_private_without_access"] = True

            channels.extend(res["channels"])
            cursor = res["response_metadata"]["next_cursor"]
            if not cursor:
                break

        return channels

    @classmethod
    def validate_request(cls, request: HttpRequest | Request):
        slack_config = cls.slack_config()
        validate_slack_request(request, slack_config["SLACK_APP_SIGNING_SECRET"])

    @classmethod
    @cache_for(timedelta(minutes=5))
    def slack_config(cls):
        config = get_instance_settings(
            [
                "SLACK_APP_CLIENT_ID",
                "SLACK_APP_CLIENT_SECRET",
                "SLACK_APP_SIGNING_SECRET",
            ]
        )

        return config

    @classmethod
    def posthog_code_slack_config(cls) -> dict[str, str]:
        return {
            "SLACK_POSTHOG_CODE_CLIENT_ID": settings.SLACK_POSTHOG_CODE_CLIENT_ID,
            "SLACK_POSTHOG_CODE_CLIENT_SECRET": settings.SLACK_POSTHOG_CODE_CLIENT_SECRET,
            "SLACK_POSTHOG_CODE_SIGNING_SECRET": settings.SLACK_POSTHOG_CODE_SIGNING_SECRET,
        }


def validate_slack_request(request: HttpRequest | Request, signing_secret: str) -> None:
    """
    Validate a Slack request using HMAC-SHA256 signature verification.
    Based on https://api.slack.com/authentication/verifying-requests-from-slack
    """
    slack_signature = request.headers.get("X-SLACK-SIGNATURE")
    slack_time = request.headers.get("X-SLACK-REQUEST-TIMESTAMP")

    if not signing_secret or not slack_signature or not slack_time:
        raise SlackIntegrationError("Invalid")

    try:
        if time.time() - float(slack_time) > 300:
            raise SlackIntegrationError("Expired")
    except ValueError:
        raise SlackIntegrationError("Invalid")

    sig_basestring = f"v0:{slack_time}:{request.body.decode('utf-8')}"

    my_signature = (
        "v0="
        + hmac.new(
            signing_secret.encode("utf-8"),
            sig_basestring.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()
    )

    if not hmac.compare_digest(my_signature, slack_signature):
        raise SlackIntegrationError("Invalid")


class GoogleAdsIntegration:
    integration: Integration

    def __init__(self, integration: Integration) -> None:
        if integration.kind != "google-ads":
            raise Exception("GoogleAdsIntegration init called with Integration with wrong 'kind'")

        self.integration = integration

    @property
    def client(self) -> WebClient:
        return WebClient(self.integration.sensitive_config["access_token"])

    def list_google_ads_conversion_actions(self, customer_id, parent_id=None) -> list[dict]:
        response = requests.request(
            "POST",
            f"https://googleads.googleapis.com/v21/customers/{customer_id}/googleAds:searchStream",
            json={
                "query": "SELECT conversion_action.id, conversion_action.name FROM conversion_action WHERE conversion_action.status != 'REMOVED'"
            },
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.integration.sensitive_config['access_token']}",
                "developer-token": settings.GOOGLE_ADS_DEVELOPER_TOKEN,
                **({"login-customer-id": parent_id} if parent_id else {}),
            },
        )

        if response.status_code == 401:
            logger.warning(
                "GoogleAdsIntegration: Auth error listing conversion actions",
                status_code=response.status_code,
                integration_id=self.integration.id,
            )
            self.integration.errors = ERROR_TOKEN_REFRESH_FAILED
            self.integration.save(update_fields=["errors"])
            raise ValidationError(
                "This integration's authentication is no longer valid. "
                "Please reconnect or disconnect this integration and connect a different account."
            )

        if response.status_code == 403:
            raise ValidationError(
                "This integration does not have permission to access this resource. "
                "Please check the account permissions on the provider side."
            )

        if response.status_code != 200:
            capture_exception(
                Exception(f"GoogleAdsIntegration: Failed to list ads conversion actions: {response.text}")
            )
            raise Exception("There was an internal error")

        return response.json()

    # Google Ads manager accounts can have access to other accounts (including other manager accounts).
    # Filter out duplicates where a user has direct access and access through a manager account, while prioritizing direct access.
    def list_google_ads_accessible_accounts(self) -> list[dict[str, str]]:
        response = requests.request(
            "GET",
            "https://googleads.googleapis.com/v21/customers:listAccessibleCustomers",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.integration.sensitive_config['access_token']}",
                "developer-token": settings.GOOGLE_ADS_DEVELOPER_TOKEN,
            },
        )

        if response.status_code == 401:
            logger.warning(
                "GoogleAdsIntegration: Auth error listing accessible accounts",
                status_code=response.status_code,
                integration_id=self.integration.id,
            )
            self.integration.errors = ERROR_TOKEN_REFRESH_FAILED
            self.integration.save(update_fields=["errors"])
            raise ValidationError(
                "This integration's authentication is no longer valid. "
                "Please reconnect or disconnect this integration and connect a different account."
            )

        if response.status_code == 403:
            raise ValidationError(
                "This integration does not have permission to access this resource. "
                "Please check the account permissions on the provider side."
            )

        if response.status_code != 200:
            capture_exception(Exception(f"GoogleAdsIntegration: Failed to list accessible accounts: {response.text}"))
            raise Exception("There was an internal error")

        accessible_accounts = response.json()
        all_accounts: list[dict[str, str]] = []

        def dfs(account_id, accounts=None, parent_id=None) -> list[dict]:
            if accounts is None:
                accounts = []
            response = requests.request(
                "POST",
                f"https://googleads.googleapis.com/v21/customers/{account_id}/googleAds:searchStream",
                json={
                    "query": "SELECT customer_client.descriptive_name, customer_client.client_customer, customer_client.level, customer_client.manager, customer_client.status FROM customer_client WHERE customer_client.level <= 5"
                },
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.integration.sensitive_config['access_token']}",
                    "developer-token": settings.GOOGLE_ADS_DEVELOPER_TOKEN,
                    **({"login-customer-id": parent_id} if parent_id else {}),
                },
            )

            if response.status_code != 200:
                return accounts

            data = response.json()

            for nested_account in data[0]["results"]:
                if any(
                    account["id"] == nested_account["customerClient"]["clientCustomer"].split("/")[1]
                    and account["level"] > nested_account["customerClient"]["level"]
                    for account in accounts
                ):
                    accounts = [
                        account
                        for account in accounts
                        if account["id"] != nested_account["customerClient"]["clientCustomer"].split("/")[1]
                    ]
                elif any(
                    account["id"] == nested_account["customerClient"]["clientCustomer"].split("/")[1]
                    and account["level"] < nested_account["customerClient"]["level"]
                    for account in accounts
                ):
                    continue
                if nested_account["customerClient"].get("status") != "ENABLED":
                    continue
                accounts.append(
                    {
                        "parent_id": parent_id,
                        "id": nested_account["customerClient"].get("clientCustomer").split("/")[1],
                        "level": nested_account["customerClient"].get("level"),
                        "name": nested_account["customerClient"].get("descriptiveName", "Google Ads account"),
                    }
                )

            return accounts

        for account in accessible_accounts["resourceNames"]:
            all_accounts = dfs(account.split("/")[1], all_accounts, account.split("/")[1])

        return all_accounts


def is_unique_service_account_by_organization_id(service_account_email: str, organization_id: str) -> bool:
    """Check if the service account is only in one organization.

    This is used as a security measure to block multiple organizations from
    impersonating the same service account.

    In the future we may lift this restriction, but initially we want to make sure about
    service account ownership with this check. This complements other runtime checks in
    batch exports; see `verify_impersonated_service_account_ownership` in
    `bigquery_batch_export.py`.
    """
    same_service_account_integrations = (
        Integration.objects.select_related("team__organization")
        .filter(kind="google-cloud-service-account", config__service_account_email=service_account_email)
        # If private key is present, then we are not impersonating
        .exclude(sensitive_config__has_key="private_key")
    )
    for integration in same_service_account_integrations:
        if str(integration.team.organization.id) != organization_id:
            return False

    return True


class GoogleCloudServiceAccountIntegration:
    integration: Integration

    def __init__(self, integration: Integration) -> None:
        self.integration = integration

    @classmethod
    def integration_from_service_account(
        cls,
        team_id: int,
        organization_id: str,
        service_account_email: str,
        project_id: str,
        private_key: str | None = None,
        private_key_id: str | None = None,
        token_uri: str | None = None,
        created_by: User | None = None,
    ) -> Integration:
        if private_key is None:
            if not is_unique_service_account_by_organization_id(service_account_email, organization_id):
                raise ValidationError("Cannot create Google Cloud service account integration: Invalid service account")

        sensitive_config = {}
        is_impersonated = True
        if isinstance(private_key, str) and isinstance(private_key_id, str) and isinstance(token_uri, str):
            sensitive_config["private_key"] = private_key
            sensitive_config["private_key_id"] = private_key_id
            sensitive_config["token_uri"] = token_uri

            is_impersonated = False

        variant = "impersonated" if is_impersonated else "key-file"

        integration, _ = Integration.objects.update_or_create(
            team_id=team_id,
            kind=Integration.IntegrationKind.GOOGLE_CLOUD_SERVICE_ACCOUNT.value,
            # Including team_id to allow teams from the same organization to use the
            # same service account. Otherwise different teams would overwrite each other.
            integration_id=f"{service_account_email}-{team_id}-{variant}",
            defaults={
                "config": {
                    "project_id": project_id,
                    "service_account_email": service_account_email,
                },
                "sensitive_config": sensitive_config,
                "created_by": created_by,
            },
        )

        if integration.errors:
            integration.errors = ""
            integration.save()

        return integration

    def has_key(self) -> bool:
        """Return if this integration has a key associated with a service account.

        If not, then it is a service account we are meant to impersonate.
        """
        keys = ("private_key", "private_key_id")
        return all(key in self.integration.sensitive_config for key in keys) and all(
            self.integration.sensitive_config[key] for key in keys
        )

    @property
    def project_id(self) -> str:
        return self.integration.config["project_id"]

    @property
    def service_account_email(self) -> str:
        return self.integration.config["service_account_email"]

    @property
    def service_account_info(self) -> dict[str, str]:
        return {
            "private_key": self.integration.sensitive_config["private_key"],
            "private_key_id": self.integration.sensitive_config["private_key_id"],
            "token_uri": self.integration.sensitive_config["token_uri"],
            "client_email": self.service_account_email,
            "project_id": self.project_id,
        }


class GoogleCloudIntegration:
    supported_kinds = ["google-pubsub", "google-cloud-storage"]
    integration: Integration

    def __init__(self, integration: Integration) -> None:
        self.integration = integration

    @classmethod
    def integration_from_key(
        cls, kind: str, key_info: dict, team_id: int, created_by: User | None = None
    ) -> Integration:
        if kind == "google-pubsub":
            scope = "https://www.googleapis.com/auth/pubsub"
        elif kind == "google-cloud-storage":
            scope = "https://www.googleapis.com/auth/devstorage.read_write"
        else:
            raise NotImplementedError(f"Google Cloud integration kind {kind} not implemented")

        try:
            credentials = service_account.Credentials.from_service_account_info(key_info, scopes=[scope])
            credentials.refresh(GoogleRequest())
        except Exception:
            raise ValidationError(f"Failed to authenticate with provided service account key")

        integration, created = Integration.objects.update_or_create(
            team_id=team_id,
            kind=kind,
            integration_id=credentials.service_account_email,
            defaults={
                "config": {
                    "expires_in": credentials.expiry.timestamp() - int(time.time()),
                    "refreshed_at": int(time.time()),
                },
                "sensitive_config": {
                    "key_info": key_info,
                    "access_token": credentials.token,
                },
                "created_by": created_by,
            },
        )

        if integration.errors:
            integration.errors = ""
            integration.save()

        return integration

    def access_token_expired(self, time_threshold: timedelta | None = None) -> bool:
        expires_in = self.integration.config.get("expires_in")
        refreshed_at = self.integration.config.get("refreshed_at")
        if not expires_in or not refreshed_at:
            return False

        # To be really safe we refresh if its half way through the expiry
        time_threshold = time_threshold or timedelta(seconds=expires_in / 2)

        return time.time() > refreshed_at + expires_in - time_threshold.total_seconds()

    def refresh_access_token(self):
        """
        Refresh the access token for the integration if necessary
        """
        if self.integration.kind == "google-pubsub":
            scope = "https://www.googleapis.com/auth/pubsub"
        elif self.integration.kind == "google-cloud-storage":
            scope = "https://www.googleapis.com/auth/devstorage.read_write"
        else:
            raise NotImplementedError(f"Google Cloud integration kind {self.integration.kind} not implemented")

        key_info = self.integration.sensitive_config.get("key_info", self.integration.sensitive_config)
        credentials = service_account.Credentials.from_service_account_info(key_info, scopes=[scope])

        try:
            credentials.refresh(GoogleRequest())
        except Exception:
            raise ValidationError(f"Failed to authenticate with provided service account key")

        self.integration.config = {
            "expires_in": credentials.expiry.timestamp() - int(time.time()),
            "refreshed_at": int(time.time()),
        }
        # Migrate pre-migration integrations where sensitive_config contains the
        # keyfile directly (not nested under "key_info"). Without this, setting
        # access_token pollutes the keyfile dict and breaks subsequent refreshes.
        if "key_info" not in self.integration.sensitive_config:
            self.integration.sensitive_config = {
                "key_info": self.integration.sensitive_config,
                "access_token": credentials.token,
            }
        else:
            self.integration.sensitive_config["access_token"] = credentials.token
        self.integration.save()
        reload_integrations_on_workers(self.integration.team_id, [self.integration.id])

        logger.info(f"Refreshed access token for {self}")

    def get_access_token(self) -> str:
        if self.access_token_expired():
            self.refresh_access_token()
        # Fall back to config for pre-migration integrations
        return self.integration.sensitive_config.get("access_token") or self.integration.config.get("access_token", "")


class FirebaseIntegration:
    integration: Integration

    def __init__(self, integration: Integration) -> None:
        if integration.kind != "firebase":
            raise Exception("FirebaseIntegration init called with Integration with wrong 'kind'")
        self.integration = integration

    @classmethod
    def integration_from_key(cls, key_info: dict, team_id: int, created_by: User | None = None) -> "Integration":
        scope = "https://www.googleapis.com/auth/firebase.messaging"

        try:
            credentials = service_account.Credentials.from_service_account_info(key_info, scopes=[scope])
            credentials.refresh(GoogleRequest())
        except Exception:
            raise ValidationError("Failed to authenticate with provided Firebase service account key")

        project_id = key_info.get("project_id")
        if not project_id:
            raise ValidationError("Service account key must contain a project_id")

        integration, created = Integration.objects.update_or_create(
            team_id=team_id,
            kind="firebase",
            integration_id=project_id,
            defaults={
                "config": {
                    "project_id": project_id,
                    "expires_in": credentials.expiry.timestamp() - int(time.time()),
                    "refreshed_at": int(time.time()),
                },
                "sensitive_config": {
                    "key_info": key_info,
                    "access_token": credentials.token,
                },
                "created_by": created_by,
            },
        )

        if integration.errors:
            integration.errors = ""
            integration.save()

        return integration

    @property
    def project_id(self) -> str:
        return self.integration.config.get("project_id", "")

    def access_token_expired(self, time_threshold: timedelta | None = None) -> bool:
        expires_in = self.integration.config.get("expires_in")
        refreshed_at = self.integration.config.get("refreshed_at")
        if not expires_in or not refreshed_at:
            return False

        # To be really safe we refresh if its half way through the expiry
        time_threshold = time_threshold or timedelta(seconds=expires_in / 2)
        return time.time() > refreshed_at + expires_in - time_threshold.total_seconds()

    def refresh_access_token(self) -> None:
        scope = "https://www.googleapis.com/auth/firebase.messaging"
        key_info = self.integration.sensitive_config.get("key_info", {})

        credentials = service_account.Credentials.from_service_account_info(key_info, scopes=[scope])

        try:
            credentials.refresh(GoogleRequest())
        except Exception:
            raise ValidationError("Failed to authenticate with provided Firebase service account key")

        self.integration.config["expires_in"] = credentials.expiry.timestamp() - int(time.time())
        self.integration.config["refreshed_at"] = int(time.time())
        self.integration.sensitive_config["access_token"] = credentials.token
        self.integration.save()
        reload_integrations_on_workers(self.integration.team_id, [self.integration.id])

        logger.info(f"Refreshed access token for FirebaseIntegration {self.integration.id}")

    def get_access_token(self) -> str:
        if self.access_token_expired():
            self.refresh_access_token()
        return self.integration.sensitive_config.get("access_token", "")


class ApplePushIntegration:
    """
    Integration for Apple Push Notification Service (APNS).

    config stores:
      - team_id: Apple Developer Team ID
      - bundle_id: App bundle identifier (e.g. com.example.app)
      - key_id: The Key ID for the .p8 signing key

    sensitive_config stores:
      - signing_key: The .p8 signing key contents
    """

    integration: Integration

    def __init__(self, integration: Integration) -> None:
        if integration.kind != "apns":
            raise Exception("ApplePushIntegration init called with Integration with wrong 'kind'")
        self.integration = integration

    @classmethod
    def integration_from_key(
        cls,
        signing_key: str,
        key_id: str,
        team_id_apple: str,
        bundle_id: str,
        team_id: int,
        created_by: User | None = None,
    ) -> "Integration":
        if not all([signing_key, key_id, team_id_apple, bundle_id]):
            raise ValidationError("All APNS fields are required: signing_key, key_id, team_id_apple, bundle_id")

        integration, created = Integration.objects.update_or_create(
            team_id=team_id,
            kind="apns",
            integration_id=f"{team_id_apple}.{bundle_id}",
            defaults={
                "config": {
                    "team_id": team_id_apple,
                    "bundle_id": bundle_id,
                    "key_id": key_id,
                },
                "sensitive_config": {
                    "signing_key": signing_key,
                },
            },
        )

        if created and created_by is not None:
            integration.created_by = created_by
            integration.save(update_fields=["created_by"])

        if integration.errors:
            integration.errors = ""
            integration.save(update_fields=["errors"])

        return integration

    @property
    def team_id_apple(self) -> str:
        return self.integration.config.get("team_id", "")

    @property
    def bundle_id(self) -> str:
        return self.integration.config.get("bundle_id", "")

    @property
    def key_id(self) -> str:
        return self.integration.config.get("key_id", "")

    @property
    def signing_key(self) -> str:
        return self.integration.sensitive_config.get("signing_key", "")


class LinkedInAdsIntegration:
    integration: Integration

    def __init__(self, integration: Integration) -> None:
        if integration.kind != "linkedin-ads":
            raise Exception("LinkedInAdsIntegration init called with Integration with wrong 'kind'")

        self.integration = integration

    @property
    def client(self) -> WebClient:
        return WebClient(self.integration.sensitive_config["access_token"])

    def _check_auth_error(self, response: requests.Response, context: str) -> None:
        if response.status_code == 401:
            logger.warning(
                f"LinkedInAdsIntegration: Auth error {context}",
                status_code=response.status_code,
                integration_id=self.integration.id,
            )
            self.integration.errors = ERROR_TOKEN_REFRESH_FAILED
            self.integration.save(update_fields=["errors"])
            raise ValidationError(
                "This integration's authentication is no longer valid. "
                "Please reconnect or disconnect this integration and connect a different account."
            )
        if response.status_code == 403:
            raise ValidationError(
                "This integration does not have permission to access this resource. "
                "Please check the account permissions on the provider side."
            )

    def list_linkedin_ads_conversion_rules(self, account_id):
        response = requests.request(
            "GET",
            f"https://api.linkedin.com/rest/conversions?q=account&account=urn%3Ali%3AsponsoredAccount%3A{account_id}&fields=conversionMethod%2Cenabled%2Ctype%2Cname%2Cid%2Ccampaigns%2CattributionType",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.integration.sensitive_config['access_token']}",
                "LinkedIn-Version": "202508",
            },
        )

        self._check_auth_error(response, "listing conversion rules")
        return response.json()

    def list_linkedin_ads_accounts(self) -> dict:
        response = requests.request(
            "GET",
            "https://api.linkedin.com/rest/adAccounts?q=search",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.integration.sensitive_config['access_token']}",
                "LinkedIn-Version": "202508",
            },
        )

        self._check_auth_error(response, "listing ad accounts")
        return response.json()


class ClickUpIntegration:
    integration: Integration

    def __init__(self, integration: Integration) -> None:
        if integration.kind != "clickup":
            raise Exception("ClickUpIntegration init called with Integration with wrong 'kind'")

        self.integration = integration

    def _check_auth_error(self, response: requests.Response, context: str) -> None:
        if response.status_code == 401:
            logger.warning(
                f"ClickUpIntegration: Auth error {context}",
                status_code=response.status_code,
                integration_id=self.integration.id,
            )
            self.integration.errors = ERROR_TOKEN_REFRESH_FAILED
            self.integration.save(update_fields=["errors"])
            raise ValidationError(
                "This integration's authentication is no longer valid. "
                "Please reconnect or disconnect this integration and connect a different account."
            )
        if response.status_code == 403:
            raise ValidationError(
                "This integration does not have permission to access this resource. "
                "Please check the account permissions on the provider side."
            )

    def list_clickup_spaces(self, workspace_id):
        response = requests.request(
            "GET",
            f"https://api.clickup.com/api/v2/team/{workspace_id}/space",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.integration.sensitive_config['access_token']}",
            },
        )

        self._check_auth_error(response, "listing spaces")
        if response.status_code != 200:
            capture_exception(Exception(f"ClickUpIntegration: Failed to list spaces: {response.text}"))
            raise Exception("There was an internal error")

        return response.json()

    def list_clickup_folderless_lists(self, space_id):
        response = requests.request(
            "GET",
            f"https://api.clickup.com/api/v2/space/{space_id}/list",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.integration.sensitive_config['access_token']}",
            },
        )

        self._check_auth_error(response, "listing lists")
        if response.status_code != 200:
            capture_exception(Exception(f"ClickUpIntegration: Failed to list lists: {response.text}"))
            raise Exception("There was an internal error")

        return response.json()

    def list_clickup_folders(self, space_id):
        response = requests.request(
            "GET",
            f"https://api.clickup.com/api/v2/space/{space_id}/folder",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.integration.sensitive_config['access_token']}",
            },
        )

        self._check_auth_error(response, "listing folders")
        if response.status_code != 200:
            capture_exception(Exception(f"ClickUpIntegration: Failed to list folders: {response.text}"))
            raise Exception("There was an internal error")

        return response.json()

    def list_clickup_workspaces(self) -> dict:
        response = requests.request(
            "GET",
            "https://api.clickup.com/api/v2/team",
            headers={"Authorization": f"Bearer {self.integration.sensitive_config['access_token']}"},
        )

        self._check_auth_error(response, "listing workspaces")
        if response.status_code != 200:
            capture_exception(Exception(f"ClickUpIntegration: Failed to list workspaces: {response.text}"))
            raise Exception("There was an internal error")

        return response.json()


class EmailIntegration:
    integration: Integration

    def __init__(self, integration: Integration) -> None:
        if integration.kind != "email":
            raise Exception("EmailIntegration init called with Integration with wrong 'kind'")
        self.integration = integration

    @property
    def ses_provider(self) -> SESProvider:
        return SESProvider()

    @classmethod
    def create_native_integration(
        cls, config: dict, team_id: int, organization_id: str, created_by: User | None = None
    ) -> Integration:
        email_address: str = config["email"]
        name: str = config["name"]
        domain: str = email_address.split("@")[1]
        mail_from_subdomain: str = config.get("mail_from_subdomain", "feedback")
        provider: str = config.get("provider", "ses")

        if domain in free_email_domains_list or domain in disposable_email_domains_list:
            raise ValidationError(f"Email domain {domain} is not supported. Please use a custom domain.")

        # Check if any other integration already exists in a different team with the same domain,
        # if so, ensure this team is part of the same organization. If not, we block creation.
        same_domain_integrations = Integration.objects.filter(kind="email", config__domain=domain)
        for integration in same_domain_integrations:
            if str(integration.team.organization.id) != str(organization_id):
                raise ValidationError(
                    f"An email integration with domain {domain} already exists in another organization. Try a different domain or contact support if you believe this is a mistake."
                )

        # Create domain in the appropriate provider
        if provider == "ses":
            ses = SESProvider()
            ses.create_email_domain(domain, mail_from_subdomain=mail_from_subdomain, team_id=team_id)
        elif provider == "maildev" and settings.DEBUG:
            pass
        else:
            raise ValueError(f"Invalid provider: must be 'ses'")

        integration, created = Integration.objects.update_or_create(
            team_id=team_id,
            kind="email",
            integration_id=email_address,
            defaults={
                "config": {
                    "email": email_address,
                    "domain": domain,
                    "mail_from_subdomain": mail_from_subdomain,
                    "name": name,
                    "provider": provider,
                    "verified": True if provider == "maildev" else False,
                },
                "created_by": created_by,
            },
        )

        if integration.errors:
            integration.errors = ""
            integration.save()

        return integration

    def update_native_integration(self, config: dict, team_id: int) -> Integration:
        provider = self.integration.config.get("provider")
        domain = self.integration.config.get("domain")
        # Only name and mail_from_subdomain can be updated
        name: str = config.get("name", self.integration.config.get("name"))
        mail_from_subdomain: str = config.get(
            "mail_from_subdomain", self.integration.config.get("mail_from_subdomain", "feedback")
        )

        # Update domain in the appropriate provider
        if provider == "ses":
            ses = SESProvider()
            ses.update_mail_from_subdomain(domain, mail_from_subdomain=mail_from_subdomain)
        elif provider == "maildev" and settings.DEBUG:
            pass
        else:
            raise ValueError(f"Invalid provider: must be 'ses'")

        self.integration.config.update(
            {
                "name": name,
                "mail_from_subdomain": mail_from_subdomain,
            }
        )
        self.integration.save()

        return self.integration

    def verify(self):
        domain = self.integration.config.get("domain")
        provider = self.integration.config.get("provider", "ses")
        mail_from_subdomain = self.integration.config.get("mail_from_subdomain", "feedback")

        # Use the appropriate provider for verification
        if provider == "ses":
            verification_result = self.ses_provider.verify_email_domain(
                domain, mail_from_subdomain=mail_from_subdomain, team_id=self.integration.team_id
            )
        elif provider == "maildev":
            verification_result = {
                "status": "success",
                "dnsRecords": MAILDEV_MOCK_DNS_RECORDS,
            }
        else:
            raise ValueError(f"Invalid provider: {provider}")

        if verification_result.get("status") == "success":
            # We can validate all other integrations with the same domain and provider
            all_integrations_for_domain = Integration.objects.filter(
                team_id=self.integration.team_id,
                kind="email",
                config__domain=domain,
                config__provider=provider,
            )
            for integration in all_integrations_for_domain:
                integration.config["verified"] = True
                integration.save()

            reload_integrations_on_workers(
                self.integration.team_id, [integration.id for integration in all_integrations_for_domain]
            )

        return verification_result


class LinearIntegration:
    integration: Integration

    def __init__(self, integration: Integration) -> None:
        if integration.kind != "linear":
            raise Exception("LinearIntegration init called with Integration with wrong 'kind'")

        self.integration = integration

    def url_key(self) -> str:
        return dot_get(self.integration.config, "data.viewer.organization.urlKey")

    def list_teams(self) -> list[dict]:
        body = self.query(f"{{ teams {{ nodes {{ id name }} }} }}")
        teams = dot_get(body, "data.teams.nodes")
        return teams

    def create_issue(self, team_id: str, posthog_issue_id: str, config: dict[str, str]):
        title: str = json.dumps(config.pop("title"))
        description: str = json.dumps(config.pop("description"))
        linear_team_id = config.pop("team_id")

        issue_create_query = f'mutation IssueCreate {{ issueCreate(input: {{ title: {title}, description: {description}, teamId: "{linear_team_id}" }}) {{ success issue {{ identifier }} }} }}'
        body = self.query(issue_create_query)
        linear_issue_id = dot_get(body, "data.issueCreate.issue.identifier")

        attachment_url = f"{settings.SITE_URL}/project/{team_id}/error_tracking/{posthog_issue_id}"
        link_attachment_query = f'mutation AttachmentCreate {{ attachmentCreate(input: {{ issueId: "{linear_issue_id}", title: "PostHog issue", url: "{attachment_url}" }}) {{ success }} }}'
        self.query(link_attachment_query)

        return {"id": linear_issue_id}

    def query(self, query):
        response = requests.post(
            "https://api.linear.app/graphql",
            headers={"Authorization": f"Bearer {self.integration.sensitive_config['access_token']}"},
            json={"query": query},
        )
        return response.json()


class JiraIntegration:
    integration: Integration

    def __init__(self, integration: Integration) -> None:
        if integration.kind != "jira":
            raise Exception("JiraIntegration init called with Integration with wrong 'kind'")

        self.integration = integration

    def cloud_id(self) -> str | None:
        """Get the Atlassian cloud ID from the integration config"""
        return dot_get(self.integration.config, "cloud_id")

    def site_name(self) -> str | None:
        """Get the Jira site name from the integration config"""
        return dot_get(self.integration.config, "site_name")

    def site_url(self) -> str:
        """Get the Jira site URL from the integration config"""
        return dot_get(self.integration.config, "site_url", "")

    def access_token_expired(self, time_threshold: timedelta | None = None) -> bool:
        """Check if the Atlassian access token has expired or is close to expiring"""
        refresh_token = self.integration.sensitive_config.get("refresh_token")
        expires_in = self.integration.config.get("expires_in")
        refreshed_at = self.integration.config.get("refreshed_at")

        if not refresh_token:
            return False

        if not expires_in or not refreshed_at:
            return False

        # To be safe we refresh if it's halfway through the expiry
        time_threshold = time_threshold or timedelta(seconds=expires_in / 2)

        return time.time() > refreshed_at + expires_in - time_threshold.total_seconds()

    def refresh_access_token(self) -> None:
        """Refresh the Atlassian access token using the refresh token"""
        oauth_integration = OauthIntegration(self.integration)
        oauth_integration.refresh_access_token()

    def _ensure_token_valid(self) -> None:
        """Proactively refresh token if it's close to expiring to avoid intermittent 401s"""
        try:
            if self.access_token_expired():
                self.refresh_access_token()
        except Exception:
            logger.warning("JiraIntegration: token refresh pre-check failed", exc_info=True)

    def list_projects(self) -> list[dict]:
        """List all Jira projects accessible to the user"""
        cloud_id = self.cloud_id()
        if not cloud_id:
            raise ValidationError("Jira integration missing cloud_id - the integration may not be properly configured")

        self._ensure_token_valid()

        response = requests.get(
            f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/project/search",
            headers={
                "Authorization": f"Bearer {self.integration.sensitive_config['access_token']}",
                "Accept": "application/json",
            },
        )
        body = response.json()
        projects = body.get("values", [])
        return [{"id": p["id"], "key": p["key"], "name": p["name"]} for p in projects]

    def create_issue(self, config: dict[str, str]) -> dict[str, str]:
        """Create a Jira issue and return the issue key"""
        cloud_id = self.cloud_id()
        if not cloud_id:
            raise ValidationError("Jira integration missing cloud_id - the integration may not be properly configured")

        self._ensure_token_valid()

        title = config.get("title")
        description = config.get("description")
        project_key = config.get("project_key")

        # Jira uses Atlassian Document Format (ADF) for description
        payload = {
            "fields": {
                "project": {"key": project_key},
                "summary": title,
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": description}],
                        }
                    ],
                },
                "issuetype": {"name": "Task"},
            }
        }

        response = requests.post(
            f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/issue",
            headers={
                "Authorization": f"Bearer {self.integration.sensitive_config['access_token']}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json=payload,
        )

        issue = response.json()
        return {"key": issue.get("key", ""), "id": issue.get("id", "")}


# Default branches change rarely; a multi-hour TTL is plenty to avoid hitting
# GitHub on every paginated branch request while keeping the window in which a
# renamed default branch stays stale tolerably short.
GITHUB_DEFAULT_BRANCH_CACHE_TTL_SECONDS = 60 * 60 * 6
GITHUB_REPOSITORY_REFRESH_COOLDOWN_SECONDS = 30


@dataclass(frozen=True)
class GitHubUserAuthorization:
    """Outcome of a successful GitHub App user authorization code exchange."""

    gh_id: int
    gh_login: str
    access_token: str
    refresh_token: str | None
    access_token_expires_in: int | None
    refresh_token_expires_in: int | None


class GitHubRateLimitError(GitHubIntegrationError):
    """GitHub API rate limit exhausted for this installation."""

    def __init__(self, message: str, reset_at: int | None = None, retry_after: int | None = None):
        super().__init__(message)
        self.reset_at = reset_at
        self.retry_after = retry_after


def raise_if_github_rate_limited(response: requests.Response) -> None:
    """Raise GitHubRateLimitError when the response signals a GitHub rate limit.

    Handles both primary (403 + body) and secondary (429) rate limit formats.
    Safe to call unconditionally after every GitHub API response.
    """
    if response.status_code == 429:
        is_rate_limited = True
    elif response.status_code == 403:
        try:
            body = response.text
        except Exception:
            body = ""
        is_rate_limited = "rate limit" in body.lower()
    else:
        return

    if not is_rate_limited:
        return

    def _int_header(name: str) -> int | None:
        val = response.headers.get(name)
        if not val:
            return None
        try:
            return int(val)
        except (ValueError, TypeError):
            return None

    reset_at = _int_header("x-ratelimit-reset")
    retry_after = _int_header("retry-after")
    if retry_after is None and reset_at is not None:
        retry_after = max(1, reset_at - int(time.time()))

    raise GitHubRateLimitError(
        f"GitHub API rate limit exceeded (resets at {reset_at})",
        reset_at=reset_at,
        retry_after=retry_after,
    )


@dataclass(frozen=True)
class GitHubInstallationAccess:
    """Installation-level access token response for a GitHub App installation."""

    installation_id: str
    installation_info: dict[str, Any]
    access_token: str
    token_expires_at: str  # ISO datetime returned by GitHub, e.g. "2024-01-01T14:00:00Z"
    repository_selection: str


class GitHubIntegration(GitHubIntegrationBase):
    integration: Integration

    @classmethod
    def integration_from_installation_id(
        cls, installation_id: str, team_id: int, created_by: User | None = None
    ) -> Integration:
        installation_info = cls.client_request(f"installations/{installation_id}").json()
        access_token = cls.client_request(f"installations/{installation_id}/access_tokens", method="POST").json()

        config = {
            "installation_id": installation_id,
            "expires_in": datetime.fromisoformat(access_token["expires_at"]).timestamp() - int(time.time()),
            "refreshed_at": int(time.time()),
            "repository_selection": access_token["repository_selection"],
            "account": {
                "type": dot_get(installation_info, "account.type", None),
                "name": dot_get(installation_info, "account.login", installation_id),
            },
        }

        sensitive_config = {"access_token": access_token["token"]}

        integration, created = Integration.objects.update_or_create(
            team_id=team_id,
            kind="github",
            integration_id=installation_id,
            defaults={
                "config": config,
                "sensitive_config": sensitive_config,
                "created_by": created_by,
            },
        )

        if integration.errors:
            integration.errors = ""
            integration.save()

        return integration

    @classmethod
    def github_login_from_code(cls, code: str) -> str | None:
        result = cls.github_user_from_code(code)
        return result.gh_login if result else None

    @classmethod
    def github_user_from_code(cls, code: str, *, redirect_uri: str | None = None) -> "GitHubUserAuthorization | None":
        """Exchange an OAuth code from the GitHub App user authorization flow.

        Pass ``redirect_uri`` when the user was sent to ``/login/oauth/authorize`` with
        the same redirect URI (required by GitHub for the token exchange in that flow).

        Returns a :class:`GitHubUserAuthorization` with the user's id/login plus the
        user-to-server access/refresh tokens and their expirations, or ``None`` if
        the exchange fails or the response lacks an id/login.
        """
        client_id = settings.GITHUB_APP_CLIENT_ID
        client_secret = settings.GITHUB_APP_CLIENT_SECRET
        if not client_id or not client_secret:
            logger.warning("GitHubIntegration: GITHUB_APP_CLIENT_ID/SECRET not configured, cannot exchange code")
            return None

        token_body: dict[str, str] = {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
        }
        if redirect_uri is not None:
            token_body["redirect_uri"] = redirect_uri

        token_response = requests.post(
            "https://github.com/login/oauth/access_token",
            json=token_body,
            headers={"Accept": "application/json"},
            timeout=10,
        )
        token_data = token_response.json()
        access_token = token_data.get("access_token")
        if not access_token:
            logger.warning(
                "GitHubIntegration: code exchange returned no access_token",
                status_code=token_response.status_code,
                error=token_data.get("error"),
                error_description=token_data.get("error_description"),
                error_uri=token_data.get("error_uri"),
            )
            return None

        user_response = requests.get(
            "https://api.github.com/user",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {access_token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=10,
        )
        if user_response.status_code != 200:
            logger.warning("GitHubIntegration: /user request failed", status_code=user_response.status_code)
            return None

        payload = user_response.json()
        gh_id = payload.get("id")
        gh_login = payload.get("login")
        if gh_id is None or not gh_login:
            return None
        access_expires_in = token_data.get("expires_in")
        refresh_expires_in = token_data.get("refresh_token_expires_in")
        return GitHubUserAuthorization(
            gh_id=int(gh_id),
            gh_login=str(gh_login),
            access_token=str(access_token),
            refresh_token=token_data.get("refresh_token") or None,
            access_token_expires_in=int(access_expires_in) if access_expires_in is not None else None,
            refresh_token_expires_in=int(refresh_expires_in) if refresh_expires_in is not None else None,
        )

    @classmethod
    def first_for_team_repository(cls, team_id: int, repository: str) -> "GitHubIntegration | None":
        """First GitHub integration for the team whose installation can access ``repository`` (``owner/name``)."""
        for integration in Integration.objects.filter(team_id=team_id, kind="github").order_by("id"):
            github = cls(integration)
            if github.installation_can_access_repository(repository):
                return github
        return None

    def __init__(self, integration: Integration) -> None:
        if integration.kind != "github":
            raise Exception("GitHubIntegration init called with Integration with wrong 'kind'")
        self.integration = integration

    def _on_token_refresh_failed(self, response: requests.Response) -> None:
        logger.warning(f"Failed to refresh token for {self}", response=response.text)
        self.integration.errors = ERROR_TOKEN_REFRESH_FAILED
        oauth_refresh_counter.labels(self.integration.kind, "failed").inc()
        self.integration.save()

    def get_access_token(self) -> str:
        """Return a valid installation access token, refreshing it if expired."""
        if self.access_token_expired():
            self.refresh_access_token()
        token = self.integration.sensitive_config.get("access_token")
        if not token:
            raise GitHubIntegrationError("Access token unavailable after refresh")
        return token

    def _on_token_refreshed(self) -> None:
        logger.info(f"Refreshed access token for {self}")
        self.integration.errors = ""
        reload_integrations_on_workers(self.integration.team_id, [self.integration.id])
        oauth_refresh_counter.labels(self.integration.kind, "success").inc()

    @database_sync_to_async
    def list_cached_repositories_async(
        self, *, search: str = "", limit: int = 100, offset: int = 0
    ) -> tuple[list[dict], bool]:
        return self.list_cached_repositories(search=search, limit=limit, offset=offset)

    @database_sync_to_async
    def list_all_cached_repositories_async(self, max_repos: int | None = None) -> list[dict]:
        return self.list_all_cached_repositories(max_repos=max_repos)

    def create_issue(self, config: dict[str, str]):
        title: str = config.pop("title")
        body: str = config.pop("body")
        repository: str = config.pop("repository")

        org = self.organization()
        access_token = self.integration.sensitive_config["access_token"]

        response = self._github_api_post(
            f"https://api.github.com/repos/{org}/{repository}/issues",
            endpoint="/repos/{owner}/{repo}/issues",
            json_body={"title": title, "body": body},
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {access_token}",
                "X-GitHub-Api-Version": GITHUB_API_VERSION,
            },
        )

        issue = response.json()

        return {"number": issue["number"], "repository": repository}

    def create_branch(self, repository: str, branch_name: str, base_branch: str | None = None) -> dict[str, Any]:
        """Create a new branch from a base branch."""
        org = self.organization()
        access_token = self.integration.sensitive_config["access_token"]

        # Get the SHA of the base branch (default to repository's default branch)
        if not base_branch:
            base_branch = self.get_default_branch(repository)

        # Get the SHA of the base branch
        ref_response = self._github_api_get(
            f"https://api.github.com/repos/{org}/{repository}/git/ref/heads/{base_branch}",
            endpoint="/repos/{owner}/{repo}/git/ref/heads/{branch}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {access_token}",
                "X-GitHub-Api-Version": GITHUB_API_VERSION,
            },
        )

        if ref_response.status_code != 200:
            return {
                "success": False,
                "error": f"Failed to get base branch {base_branch}: {ref_response.text}",
            }

        base_sha = ref_response.json()["object"]["sha"]

        # Create the new branch
        response = self._github_api_post(
            f"https://api.github.com/repos/{org}/{repository}/git/refs",
            endpoint="/repos/{owner}/{repo}/git/refs",
            json_body={
                "ref": f"refs/heads/{branch_name}",
                "sha": base_sha,
            },
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {access_token}",
                "X-GitHub-Api-Version": GITHUB_API_VERSION,
            },
        )

        if response.status_code == 201:
            branch_data = response.json()
            return {
                "success": True,
                "branch_name": branch_name,
                "sha": branch_data["object"]["sha"],
                "ref": branch_data["ref"],
            }
        else:
            return {
                "success": False,
                "error": f"Failed to create branch: {response.text}",
                "status_code": response.status_code,
            }

    def update_file(
        self, repository: str, file_path: str, content: str, commit_message: str, branch: str, sha: str | None = None
    ) -> dict[str, Any]:
        """Create or update a file in the repository."""
        org = self.organization()
        access_token = self.integration.sensitive_config["access_token"]

        # If no SHA provided, try to get existing file's SHA
        if not sha:
            get_response = self._github_api_get(
                f"https://api.github.com/repos/{org}/{repository}/contents/{file_path}",
                endpoint="/repos/{owner}/{repo}/contents/{path}",
                params={"ref": branch},
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {access_token}",
                    "X-GitHub-Api-Version": GITHUB_API_VERSION,
                },
            )
            if get_response.status_code == 200:
                sha = get_response.json()["sha"]

        encoded_content = base64.b64encode(content.encode("utf-8")).decode("utf-8")

        data = {
            "message": commit_message,
            "content": encoded_content,
            "branch": branch,
        }

        if sha:
            data["sha"] = sha

        response = self._github_api_put(
            f"https://api.github.com/repos/{org}/{repository}/contents/{file_path}",
            endpoint="/repos/{owner}/{repo}/contents/{path}",
            json_body=data,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {access_token}",
                "X-GitHub-Api-Version": GITHUB_API_VERSION,
            },
        )

        if response.status_code in [200, 201]:
            commit_data = response.json()
            return {
                "success": True,
                "commit_sha": commit_data["commit"]["sha"],
                "file_sha": commit_data["content"]["sha"],
                "html_url": commit_data["commit"]["html_url"],
            }
        else:
            return {
                "success": False,
                "error": f"Failed to update file: {response.text}",
                "status_code": response.status_code,
            }

    def create_pull_request(
        self, repository: str, title: str, body: str, head_branch: str, base_branch: str | None = None
    ) -> dict[str, Any]:
        """Create a pull request."""
        org = self.organization()
        access_token = self.integration.sensitive_config["access_token"]

        if not base_branch:
            base_branch = self.get_default_branch(repository)

        response = self._github_api_post(
            f"https://api.github.com/repos/{org}/{repository}/pulls",
            endpoint="/repos/{owner}/{repo}/pulls",
            json_body={
                "title": title,
                "body": body,
                "head": head_branch,
                "base": base_branch,
            },
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {access_token}",
                "X-GitHub-Api-Version": GITHUB_API_VERSION,
            },
        )

        if response.status_code == 201:
            pr_data = response.json()
            return {
                "success": True,
                "pr_number": pr_data["number"],
                "pr_url": pr_data["html_url"],
                "pr_id": pr_data["id"],
                "state": pr_data["state"],
            }
        else:
            return {
                "success": False,
                "error": f"Failed to create pull request: {response.text}",
                "status_code": response.status_code,
            }

    def get_branch_info(self, repository: str, branch_name: str) -> dict[str, Any]:
        """Get information about a specific branch."""
        org = self.organization()
        access_token = self.integration.sensitive_config["access_token"]

        response = self._github_api_get(
            f"https://api.github.com/repos/{org}/{repository}/branches/{branch_name}",
            endpoint="/repos/{owner}/{repo}/branches/{branch}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {access_token}",
                "X-GitHub-Api-Version": GITHUB_API_VERSION,
            },
        )

        if response.status_code == 200:
            branch_data = response.json()
            return {
                "success": True,
                "exists": True,
                "branch_name": branch_data["name"],
                "commit_sha": branch_data["commit"]["sha"],
                "protected": branch_data.get("protected", False),
            }
        elif response.status_code == 404:
            return {
                "success": True,
                "exists": False,
                "branch_name": branch_name,
            }
        else:
            return {
                "success": False,
                "error": f"Failed to get branch info: {response.text}",
                "status_code": response.status_code,
            }

    def list_pull_requests(self, repository: str, state: str = "open") -> dict[str, Any]:
        """List pull requests for a repository."""
        org = self.organization()
        access_token = self.integration.sensitive_config["access_token"]

        params: dict[str, str | int] = {"state": state, "per_page": 100}
        response = self._github_api_get(
            f"https://api.github.com/repos/{org}/{repository}/pulls",
            endpoint="/repos/{owner}/{repo}/pulls",
            params=params,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {access_token}",
                "X-GitHub-Api-Version": GITHUB_API_VERSION,
            },
        )

        if response.status_code == 200:
            prs = response.json()
            return {
                "success": True,
                "pull_requests": [
                    {
                        "number": pr["number"],
                        "title": pr["title"],
                        "url": pr["html_url"],
                        "state": pr["state"],
                        "head_branch": pr["head"]["ref"],
                        "base_branch": pr["base"]["ref"],
                        "created_at": pr["created_at"],
                        "updated_at": pr["updated_at"],
                    }
                    for pr in prs
                ],
            }
        else:
            return {
                "success": False,
                "error": f"Failed to list pull requests: {response.text}",
                "status_code": response.status_code,
            }


class GitLabIntegrationError(Exception):
    pass


class GitLabIntegration:
    integration: Integration

    @staticmethod
    def get(hostname: str, endpoint: str, project_access_token: str) -> dict:
        url = f"{hostname}/api/v4/{endpoint}"
        allowed, error = is_url_allowed(url)
        if not allowed:
            raise GitLabIntegrationError(f"Invalid GitLab hostname: {error}")

        response = requests.get(
            url,
            headers={"PRIVATE-TOKEN": project_access_token},
            # disallow redirects to prevent SSRF on redirected host
            allow_redirects=False,
        )

        return response.json()

    @staticmethod
    def post(hostname: str, endpoint: str, project_access_token: str, json: dict) -> dict:
        url = f"{hostname}/api/v4/{endpoint}"
        allowed, error = is_url_allowed(url)
        if not allowed:
            raise GitLabIntegrationError(f"Invalid GitLab hostname: {error}")

        response = requests.post(
            url,
            json=json,
            headers={"PRIVATE-TOKEN": project_access_token},
            # disallow redirects to prevent SSRF on redirected host
            allow_redirects=False,
        )

        return response.json()

    @classmethod
    def create_integration(cls, hostname, project_id, project_access_token, team_id, user) -> Integration:
        project = cls.get(hostname, f"projects/{project_id}", project_access_token)

        integration = Integration.objects.create(
            team_id=team_id,
            kind=Integration.IntegrationKind.GITLAB,
            integration_id=project.get("name_with_namespace"),
            config={
                "hostname": hostname,
                "path_with_namespace": project.get("path_with_namespace"),
                "project_id": project.get("id"),
            },
            sensitive_config={"access_token": project_access_token},
            created_by=user,
        )

        return integration

    def __init__(self, integration: Integration) -> None:
        if integration.kind != "gitlab":
            raise Exception("GitLabIntegration init called with Integration with wrong 'kind'")
        self.integration = integration

    @property
    def project_path(self) -> str:
        return dot_get(self.integration.config, "path_with_namespace")

    @property
    def hostname(self) -> str:
        return dot_get(self.integration.config, "hostname")

    def create_issue(self, config: dict[str, str]):
        title: str = config.pop("title")
        description: str = config.pop("body")

        hostname = self.integration.config.get("hostname")
        project_id = self.integration.config.get("project_id")
        access_token = self.integration.sensitive_config.get("access_token")

        issue = GitLabIntegration.post(
            hostname,
            f"projects/{project_id}/issues",
            access_token,
            {
                "title": title,
                "description": description,
                "labels": "posthog",
            },
        )

        return {"issue_id": issue["iid"]}


class MetaAdsIntegration:
    integration: Integration
    api_version: str = "v23.0"

    def __init__(self, integration: Integration) -> None:
        if integration.kind != "meta-ads":
            raise Exception("MetaAdsIntegration init called with Integration with wrong 'kind'")
        self.integration = integration

    def refresh_access_token(self):
        oauth_config = OauthIntegration.oauth_config_for_kind(self.integration.kind)

        # check if refresh is necessary (less than 7 days)
        if self.integration.config.get("expires_in") and self.integration.config.get("refreshed_at"):
            if (
                time.time()
                > self.integration.config.get("refreshed_at") + self.integration.config.get("expires_in") - 604800
            ):
                return

        res = requests.post(
            oauth_config.token_url,
            data={
                "client_id": oauth_config.client_id,
                "client_secret": oauth_config.client_secret,
                "fb_exchange_token": self.integration.sensitive_config["access_token"],
                "grant_type": "fb_exchange_token",
                "set_token_expires_in_60_days": True,
            },
        )

        config: dict = res.json()

        if res.status_code != 200 or not config.get("access_token"):
            logger.warning(f"Failed to refresh token for {self}", response=res.text)
            self.integration.errors = ERROR_TOKEN_REFRESH_FAILED
            oauth_refresh_counter.labels(self.integration.kind, "failed").inc()
        else:
            logger.info(f"Refreshed access token for {self}")
            self.integration.sensitive_config["access_token"] = config["access_token"]
            self.integration.errors = ""
            self.integration.config["expires_in"] = config.get("expires_in")
            self.integration.config["refreshed_at"] = int(time.time())
            # not used in CDP yet
            # reload_integrations_on_workers(self.integration.team_id, [self.integration.id])
            oauth_refresh_counter.labels(self.integration.kind, "success").inc()
        self.integration.save()


class TwilioIntegration:
    integration: Integration
    twilio_provider: TwilioProvider

    def __init__(self, integration: Integration) -> None:
        if integration.kind != "twilio":
            raise Exception("TwilioIntegration init called with Integration with wrong 'kind'")
        self.integration = integration
        self.twilio_provider = TwilioProvider(
            account_sid=self.integration.config["account_sid"],
            auth_token=self.integration.sensitive_config["auth_token"],
        )

    def list_twilio_phone_numbers(self) -> list[dict]:
        twilio_phone_numbers = self.twilio_provider.get_phone_numbers()

        if not twilio_phone_numbers:
            raise Exception(f"There was an internal error")

        return twilio_phone_numbers

    def integration_from_keys(self) -> Integration:
        account_info = self.twilio_provider.get_account_info()

        if not account_info.get("sid"):
            raise ValidationError({"account_info": "Failed to get account info"})

        integration, created = Integration.objects.update_or_create(
            team_id=self.integration.team_id,
            kind="twilio",
            integration_id=account_info["sid"],
            defaults={
                "config": {
                    "account_sid": account_info["sid"],
                },
                "sensitive_config": {
                    "auth_token": self.integration.sensitive_config["auth_token"],
                },
                "created_by": self.integration.created_by,
            },
        )
        if integration.errors:
            integration.errors = ""
            integration.save()

        return integration


class DatabricksIntegrationError(Exception):
    """Error raised when the Databricks integration is not valid."""

    pass


class DatabricksIntegration:
    """A Databricks integration.

    The recommended way to connect to Databricks is via OAuth machine-to-machine (M2M) authentication.
    See: https://docs.databricks.com/aws/en/dev-tools/python-sql-connector#oauth-machine-to-machine-m2m-authentication

    This works quite differently to regular user-to-machine OAuth as it does not require a real-time user sign in and
    consent flow: Instead, the user creates a service principal and provided us with the client ID and client secret to authenticate.

    Attributes:
        integration: The integration object.
        server_hostname: the Server Hostname value for user's all-purpose compute or SQL warehouse.
        client_id: the service principal's UUID or Application ID value.
        client_secret: the Secret value for the service principal's OAuth secret.
    """

    integration: Integration
    server_hostname: str
    client_id: str
    client_secret: str

    def __init__(self, integration: Integration) -> None:
        if integration.kind != Integration.IntegrationKind.DATABRICKS.value:
            raise DatabricksIntegrationError("Integration provided is not a Databricks integration")
        self.integration = integration

        try:
            self.server_hostname = self.integration.config["server_hostname"]
            self.client_id = self.integration.sensitive_config["client_id"]
            self.client_secret = self.integration.sensitive_config["client_secret"]
        except KeyError as e:
            raise DatabricksIntegrationError(f"Databricks integration is not valid: {str(e)} missing")

    @classmethod
    def integration_from_config(
        cls, team_id: int, server_hostname: str, client_id: str, client_secret: str, created_by: User | None = None
    ) -> Integration:
        # first, validate the host
        cls.validate_host(server_hostname)

        config = {
            "server_hostname": server_hostname,
        }
        sensitive_config = {
            "client_id": client_id,
            "client_secret": client_secret,
        }
        integration, _ = Integration.objects.update_or_create(
            team_id=team_id,
            kind=Integration.IntegrationKind.DATABRICKS.value,
            integration_id=server_hostname,  # Use server_hostname as unique identifier
            defaults={
                "config": config,
                "sensitive_config": sensitive_config,
                "created_by": created_by,
            },
        )
        if integration.errors:
            integration.errors = ""
            integration.save()

        return integration

    @staticmethod
    def validate_host(server_hostname: str):
        """Validate the Databricks host.

        This is a quick check to ensure the host is valid and that we can connect to it (testing connectivity to a SQL
        warehouse requires a warehouse http_path in addition to these parameters so it not possible to perform a full
        test here)
        """
        # we expect a hostname, not a full URL
        if server_hostname.startswith("http"):
            raise DatabricksIntegrationError(
                f"Databricks integration is not valid: 'server_hostname' should not be a full URL"
            )
        # TCP connectivity check
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3.0)
            # we only support https
            port = 443
            sock.connect((server_hostname, port))
            sock.close()
        except OSError:
            raise DatabricksIntegrationError(
                f"Databricks integration error: could not connect to hostname '{server_hostname}'"
            )
        except Exception:
            raise DatabricksIntegrationError(
                f"Databricks integration error: could not connect to hostname '{server_hostname}'"
            )


class AzureBlobIntegrationError(Exception):
    pass


class AzureBlobIntegration:
    """Wraps Integration model to provide encrypted credential storage for Azure Blob Storage.

    Attributes:
        integration: The underlying Integration model instance.
        connection_string: The decrypted Azure Storage connection string.
    """

    integration: Integration
    connection_string: str

    def __init__(self, integration: Integration) -> None:
        if integration.kind != Integration.IntegrationKind.AZURE_BLOB.value:
            raise AzureBlobIntegrationError(
                f"Integration provided is not an Azure Blob integration (got kind='{integration.kind}')"
            )
        self.integration = integration

        try:
            self.connection_string = self.integration.sensitive_config["connection_string"]
        except KeyError:
            raise AzureBlobIntegrationError("Azure Blob integration is missing required field: 'connection_string'")

    @classmethod
    def integration_from_config(
        cls,
        team_id: int,
        connection_string: str,
        created_by: "User | None" = None,
    ) -> Integration:
        account_name = cls._extract_account_name(connection_string)
        if not account_name:
            raise AzureBlobIntegrationError(
                "Could not extract AccountName from connection string. "
                "Ensure it contains 'AccountName=<your-account-name>;'"
            )

        config: dict[str, str] = {}
        sensitive_config = {
            "connection_string": connection_string,
        }

        integration, created = Integration.objects.update_or_create(
            team_id=team_id,
            kind=Integration.IntegrationKind.AZURE_BLOB.value,
            integration_id=account_name,
            defaults={
                "config": config,
                "sensitive_config": sensitive_config,
                "created_by": created_by,
            },
        )

        if integration.errors:
            integration.errors = ""
            integration.save()

        return integration

    @staticmethod
    def _extract_account_name(connection_string: str) -> str | None:
        for part in connection_string.split(";"):
            part = part.strip()
            if part.startswith("AccountName="):
                return part.split("=", 1)[1]
        return None


class StripeIntegration:
    integration: Integration

    # These are the scopes we'll give Stripe when creating a local OAuth App
    # and sending them access
    SCOPES = " ".join(
        [
            "customer_journey:read",
            "query:read",
            "conversation:read",
            "conversation:write",
            "experiment:read",
            "feature_flag:read",
            "insight:read",
            "organization:read",
            "person:read",
            "project:read",
            "ticket:read",
            "ticket:write",
            "user:read",
            "hog_flow:read",
            "hog_flow:write",
        ]
    )

    def __init__(self, integration: Integration) -> None:
        if integration.kind != "stripe":
            raise ValueError(f"Expected stripe integration, got {integration.kind}")
        self.integration = integration

    def write_posthog_secrets(self, team_id: int, created_by: "User") -> None:
        """Write PostHog OAuth tokens to Stripe's Secret Store so the Stripe App can call PostHog APIs."""

        oauth_app = self._get_posthog_oauth_app()
        if not oauth_app:
            logger.warning("PostHog OAuth app not found, cannot write secrets to Stripe")
            return

        access_token_value = generate_random_oauth_access_token(None)
        access_token = OAuthAccessToken.objects.create(
            application=oauth_app,
            token=access_token_value,
            user=created_by,
            expires=timezone.now() + timedelta(days=14),
            scope=self.SCOPES,
            scoped_teams=[team_id],
        )

        refresh_token_value = generate_random_oauth_refresh_token(None)
        OAuthRefreshToken.objects.create(
            application=oauth_app,
            token=refresh_token_value,
            user=created_by,
            access_token=access_token,
            scoped_teams=[team_id],
        )

        stripe_user_id = self.integration.integration_id
        if not stripe_user_id:
            raise ValueError("Missing stripe_user_id on integration")

        region = get_instance_region() or "us"

        secrets = {
            "posthog_region": region.lower(),
            "posthog_access_token": access_token_value,
            "posthog_refresh_token": refresh_token_value,
            "posthog_project_id": str(team_id),
            "posthog_oauth_client_id": oauth_app.client_id,
        }

        client = StripeClient(settings.STRIPE_APP_SECRET_KEY)

        for name, payload in secrets.items():
            try:
                client.apps.secrets.create(
                    params={
                        "scope": {"type": "account"},
                        "name": name,
                        "payload": payload,
                    },
                    options={"stripe_account": stripe_user_id},
                )
            except Exception as e:
                capture_exception(e)
                logger.warning(
                    "Failed to write secret to Stripe",
                    secret_name=name,
                    stripe_user_id=stripe_user_id,
                    error=str(e),
                )

    def clear_posthog_secrets(self) -> None:
        """Best-effort clear of PostHog secrets from Stripe and revoke local OAuth tokens."""
        stripe_user_id = self.integration.integration_id
        if not stripe_user_id:
            raise ValueError("Missing stripe_user_id on integration")

        client = StripeClient(settings.STRIPE_APP_SECRET_KEY)

        for name in (
            "posthog_region",
            "posthog_access_token",
            "posthog_refresh_token",
            "posthog_project_id",
            "posthog_oauth_client_id",
        ):
            try:
                client.apps.secrets.delete_where(
                    params={
                        "scope": {"type": "account"},
                        "name": name,
                    },
                    options={"stripe_account": stripe_user_id},
                )
            except Exception as e:
                capture_exception(e)
                logger.warning(
                    "Failed to clear secret from Stripe",
                    secret_name=name,
                    stripe_user_id=stripe_user_id,
                    error=str(e),
                )

        self._destroy_posthog_oauth_tokens()

    def _destroy_posthog_oauth_tokens(self) -> None:
        """Delete the local OAuth access and refresh tokens created for this Stripe integration."""
        oauth_app = self._get_posthog_oauth_app()
        if not oauth_app:
            return

        team_id = self.integration.team_id
        access_tokens = OAuthAccessToken.objects.filter(
            application=oauth_app,
            scoped_teams__contains=[team_id],
        )
        # Delete refresh tokens first since their FK to access_token is SET_NULL
        OAuthRefreshToken.objects.filter(access_token__in=access_tokens).delete()
        access_tokens.delete()

    def _get_posthog_oauth_app(self):
        if settings.STRIPE_POSTHOG_OAUTH_CLIENT_ID:
            return OAuthApplication.objects.filter(client_id=settings.STRIPE_POSTHOG_OAUTH_CLIENT_ID).first()

        return None


class Credentials(NamedTuple):
    """PostgreSQL credentials."""

    user: str
    password: str


class Authority(NamedTuple):
    """PostgreSQL authority parameters."""

    host: str
    port: int


MISSING_CERT_PATH = "/tmp/posthog/batch-exports/MISSING.crt"


class TLS(NamedTuple):
    """PostgreSQL TLS parameters.

    NOTE: If a root CA file exists in the default '~/.postgresql/root.crt' path libpq
    treats `sslmode='require'` as `sslmode='verify-ca'`.

    **This is not what we want**

    If a user has not provided a root certificate (by setting `ssl_root_cert` to the
    cert's contents) or asked to use the system store explicitly (by setting
    `ssl_root_cert='system'`, in version >=16), then whatever is present in the default
    path should not be used.

    This could be a problem if, for example, another application or library or
    dependency bundled in the same container ships with a default cert.

    For this reason we require `ssl_root_cert` to not be `None` (as that would translate
    to the default path), and it defaults to an application-scoped path under `/tmp/`.
    """

    ssl_mode: Literal["prefer", "require", "verify-ca", "verify-full"]
    ssl_root_cert: str | Literal["system"] = MISSING_CERT_PATH


class PostgreSQLIntegration:
    integration: Integration

    def __init__(self, integration: Integration) -> None:
        self.integration = integration

    @classmethod
    def integration_from_config(
        cls,
        team_id: int,
        host: str,
        port: int,
        user: str,
        password: str,
        ssl_mode: Literal["prefer", "require", "verify-ca", "verify-full"] = "require",
        ssl_root_cert: str | Literal["system"] | None = None,
        created_by: User | None = None,
    ) -> Integration:
        integration, _ = Integration.objects.update_or_create(
            team_id=team_id,
            kind=Integration.IntegrationKind.POSTGRESQL,
            integration_id=f"{team_id}-{host}-{port}-{user}",
            defaults={
                "config": {
                    "host": host,
                    "port": port,
                    "user": user,
                    "ssl_mode": ssl_mode,
                    "ssl_root_cert": ssl_root_cert,
                },
                "sensitive_config": {
                    "password": password,
                },
                "created_by": created_by,
            },
        )

        if integration.errors:
            integration.errors = ""
            integration.save()

        return integration

    def authority(self) -> Authority:
        return Authority(self.integration.config["host"], self.integration.config["port"])

    def credentials(self) -> Credentials:
        return Credentials(self.integration.config["user"], self.integration.sensitive_config["password"])

    def tls(self) -> TLS:
        if (ssl_root_cert := self.integration.config.get("ssl_root_cert", None)) is not None:
            return TLS(
                ssl_mode=self.integration.config["ssl_mode"],
                ssl_root_cert=ssl_root_cert,
            )
        else:
            # Preserve the default ssl_root_cert if one was not provided
            return TLS(ssl_mode=self.integration.config["ssl_mode"])
