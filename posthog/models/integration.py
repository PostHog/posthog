import hmac
import json
import time
import base64
import socket
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal, NamedTuple, Optional, cast
from urllib.parse import urlencode, urlparse

from products.workflows.backend.providers import MAILDEV_MOCK_DNS_RECORDS

if TYPE_CHECKING:
    import aiohttp

from django.conf import settings
from django.core.cache import cache
from django.db import models
from django.http import HttpRequest
from django.utils import timezone

import jwt
import requests
import structlog
from disposable_email_domains import blocklist as disposable_email_domains_list
from free_email_domains import whitelist as free_email_domains_list
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import service_account
from prometheus_client import Counter, Gauge
from requests.auth import HTTPBasicAuth
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient
from stripe import StripeClient

from posthog.cache_utils import cache_for
from posthog.exceptions_capture import capture_exception
from posthog.helpers.encrypted_fields import EncryptedJSONField
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

github_api_request_counter = Counter(
    "github_integration_api_requests",
    "Number of GitHub API requests made through a GitHub integration.",
    labelnames=["integration_id", "method", "endpoint", "status_code"],
)
github_api_rate_limit_remaining_gauge = Gauge(
    "github_integration_api_rate_limit_remaining",
    "Most recently observed GitHub API rate limit remaining count by integration and resource.",
    labelnames=["integration_id", "resource"],
)
github_api_rate_limit_limit_gauge = Gauge(
    "github_integration_api_rate_limit_limit",
    "Most recently observed GitHub API rate limit limit by integration and resource.",
    labelnames=["integration_id", "resource"],
)
github_api_rate_limit_reset_timestamp_gauge = Gauge(
    "github_integration_api_rate_limit_reset_timestamp_seconds",
    "Most recently observed GitHub API rate limit reset timestamp by integration and resource.",
    labelnames=["integration_id", "resource"],
)
github_cache_access_counter = Counter(
    "github_integration_cache_accesses",
    "Number of GitHub integration cache accesses by cache type, repository, and result.",
    labelnames=["integration_id", "cache", "repository", "result"],
)

PRIVATE_CHANNEL_WITHOUT_ACCESS = "PRIVATE_CHANNEL_WITHOUT_ACCESS"


def dot_get(d: Any, path: str, default: Any = None) -> Any:
    if path in d and d[path] is not None:
        return d[path]
    for key in path.split("."):
        if not isinstance(d, dict):
            return default
        d = d.get(key, default)
    return d


ERROR_TOKEN_REFRESH_FAILED = "TOKEN_REFRESH_FAILED"


class Integration(models.Model):
    class IntegrationKind(models.TextChoices):
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
    def oauth_config_for_kind(cls, kind: str) -> OauthConfig:
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

            authorize_url = (
                settings.STRIPE_APP_OVERRIDE_AUTHORIZE_URL or "https://marketplace.stripe.com/oauth/v2/authorize"
            )
            return OauthConfig(
                authorize_url=authorize_url,
                token_url="https://api.stripe.com/v1/oauth/token",
                client_id=settings.STRIPE_APP_CLIENT_ID,
                client_secret=settings.STRIPE_APP_SECRET_KEY,
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
    def authorize_url(cls, kind: str, token: str, next="") -> str:
        oauth_config = cls.oauth_config_for_kind(kind)

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

        config: dict = res.json()

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

                config = res.json()

                if res.status_code != 200 or not config.get("access_token"):
                    logger.error(f"Oauth error for {kind}", response=res.text)
                    raise Exception(f"Oauth error for {kind}. Status code = {res.status_code}")
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
                raise Exception(f"Oauth error. Status code = {res.status_code}")

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


class SlackIntegration:
    integration: Integration

    def __init__(self, integration: Integration) -> None:
        if integration.kind not in ("slack", "slack-posthog-code"):
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


@dataclass(frozen=True)
class GitHubCommitAuthor:
    login: str
    name: str | None
    commit_url: str


# Default branches change rarely; a multi-hour TTL is plenty to avoid hitting
# GitHub on every paginated branch request while keeping the window in which a
# renamed default branch stays stale tolerably short.
GITHUB_DEFAULT_BRANCH_CACHE_TTL_SECONDS = 60 * 60 * 6
GITHUB_REPOSITORY_CACHE_TTL_SECONDS = 60 * 60
GITHUB_REPOSITORY_REFRESH_COOLDOWN_SECONDS = 30
GITHUB_BRANCH_CACHE_TTL_SECONDS = 60 * 10
GITHUB_BRANCH_CACHE_TIMEOUT_SECONDS = 60 * 60 * 24


@dataclass(frozen=True)
class GitHubUserAuthorization:
    """Outcome of a successful GitHub App user authorization code exchange."""

    gh_id: int
    gh_login: str
    access_token: str
    refresh_token: str | None
    access_token_expires_in: int | None
    refresh_token_expires_in: int | None


class GitHubIntegrationError(Exception):
    pass


class GitHubIntegration:
    integration: Integration

    @classmethod
    def client_request(cls, endpoint: str, method: str = "GET") -> requests.Response:
        github_app_client_id = settings.GITHUB_APP_CLIENT_ID
        github_app_private_key = settings.GITHUB_APP_PRIVATE_KEY

        if not github_app_client_id:
            raise ValidationError("GITHUB_APP_CLIENT_ID is not configured")

        if not github_app_private_key:
            raise ValidationError("GITHUB_APP_PRIVATE_KEY is not configured")

        github_app_private_key = github_app_private_key.replace("\\n", "\n").strip()

        try:
            jwt_token = jwt.encode(
                {
                    "iat": int(time.time()) - 300,  # 5 minutes in the past
                    "exp": int(time.time()) + 300,  # 5 minutes in the future
                    "iss": github_app_client_id,
                },
                github_app_private_key,
                algorithm="RS256",
            )
        except Exception:
            logger.error("Failed to encode JWT token", exc_info=True)
            raise ValidationError(
                "Failed to create GitHub App JWT token. Please check your GITHUB_APP_PRIVATE_KEY format."
            )

        return requests.request(
            method,
            f"https://api.github.com/app/{endpoint}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {jwt_token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

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
    def github_user_from_code(cls, code: str) -> "GitHubUserAuthorization | None":
        """Exchange an OAuth code from the GitHub App user authorization flow.

        Returns a :class:`GitHubUserAuthorization` with the user's id/login plus the
        user-to-server access/refresh tokens and their expirations, or ``None`` if
        the exchange fails or the response lacks an id/login.
        """
        client_id = settings.GITHUB_APP_CLIENT_ID
        client_secret = settings.GITHUB_APP_CLIENT_SECRET
        if not client_id or not client_secret:
            logger.warning("GitHubIntegration: GITHUB_APP_CLIENT_ID/SECRET not configured, cannot exchange code")
            return None

        try:
            token_response = requests.post(
                "https://github.com/login/oauth/access_token",
                json={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                },
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
        except Exception:
            logger.warning("GitHubIntegration: failed to exchange code for github user", exc_info=True)
            return None

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

    @staticmethod
    def _rate_limit_header(headers: Mapping[str, str] | None, name: str) -> float | None:
        if headers is None:
            return None
        value = headers.get(name)
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _record_github_api_response(self, response: requests.Response, method: str, endpoint: str) -> None:
        integration_id = str(self.integration.id)
        status_code = str(response.status_code)
        github_api_request_counter.labels(integration_id, method, endpoint, status_code).inc()

        headers = response.headers if isinstance(response.headers, Mapping) else None
        resource = headers.get("X-RateLimit-Resource", "unknown") if headers is not None else "unknown"
        remaining = self._rate_limit_header(headers, "X-RateLimit-Remaining")
        limit = self._rate_limit_header(headers, "X-RateLimit-Limit")
        reset_at = self._rate_limit_header(headers, "X-RateLimit-Reset")

        if remaining is not None:
            github_api_rate_limit_remaining_gauge.labels(integration_id, resource).set(remaining)
        if limit is not None:
            github_api_rate_limit_limit_gauge.labels(integration_id, resource).set(limit)
        if reset_at is not None:
            github_api_rate_limit_reset_timestamp_gauge.labels(integration_id, resource).set(reset_at)

    def _record_github_api_exception(self, method: str, endpoint: str) -> None:
        github_api_request_counter.labels(str(self.integration.id), method, endpoint, "exception").inc()

    def _record_github_cache_access(
        self, cache_type: Literal["repositories", "branches"], result: Literal["hit", "miss"], repository: str
    ) -> None:
        github_cache_access_counter.labels(str(self.integration.id), cache_type, repository.casefold(), result).inc()

    def _github_api_get(
        self,
        url: str,
        *,
        endpoint: str,
        headers: dict[str, str],
        params: dict[str, str | int] | None = None,
        timeout: int | None = None,
    ) -> requests.Response:
        try:
            response = requests.get(url, headers=headers, params=params, timeout=timeout)
        except requests.RequestException:
            self._record_github_api_exception("GET", endpoint)
            raise
        self._record_github_api_response(response, "GET", endpoint)
        return response

    def _github_api_post(
        self,
        url: str,
        *,
        endpoint: str,
        headers: dict[str, str],
        json_body: Mapping[str, object] | None = None,
    ) -> requests.Response:
        try:
            response = requests.post(url, json=json_body, headers=headers)
        except requests.RequestException:
            self._record_github_api_exception("POST", endpoint)
            raise
        self._record_github_api_response(response, "POST", endpoint)
        return response

    def _github_api_put(
        self,
        url: str,
        *,
        endpoint: str,
        headers: dict[str, str],
        json_body: Mapping[str, object],
    ) -> requests.Response:
        try:
            response = requests.put(url, json=json_body, headers=headers)
        except requests.RequestException:
            self._record_github_api_exception("PUT", endpoint)
            raise
        self._record_github_api_response(response, "PUT", endpoint)
        return response

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
        endpoint = "/app/installations/{installation_id}/access_tokens"
        try:
            response = self.client_request(
                f"installations/{self.integration.integration_id}/access_tokens", method="POST"
            )
        except requests.RequestException:
            self._record_github_api_exception("POST", endpoint)
            raise
        self._record_github_api_response(response, "POST", endpoint)
        config = response.json()

        if response.status_code != status.HTTP_201_CREATED or not config.get("token"):
            logger.warning(f"Failed to refresh token for {self}", response=response.text)
            self.integration.errors = ERROR_TOKEN_REFRESH_FAILED
            oauth_refresh_counter.labels(self.integration.kind, "failed").inc()
            self.integration.save()
            raise Exception(f"Failed to refresh token for {self}: {response.text}")
        else:
            logger.info(f"Refreshed access token for {self}")
            expires_in = datetime.fromisoformat(config["expires_at"]).timestamp() - int(time.time())
            self.integration.config["expires_in"] = expires_in
            self.integration.config["refreshed_at"] = int(time.time())
            self.integration.sensitive_config["access_token"] = config["token"]
            self.integration.errors = ""
            reload_integrations_on_workers(self.integration.team_id, [self.integration.id])
            oauth_refresh_counter.labels(self.integration.kind, "success").inc()
            self.integration.save()

    def organization(self) -> str:
        return dot_get(self.integration.config, "account.name")

    def _installation_authenticated_get(
        self, url: str, *, endpoint: str, timeout: int = 10
    ) -> requests.Response | None:
        """GET with installation token; refreshes on expiry or 401."""
        try:
            if self.access_token_expired():
                self.refresh_access_token()
        except Exception:
            logger.warning("GitHubIntegration: token refresh pre-check failed", exc_info=True)

        def fetch() -> requests.Response:
            access_token = self.integration.sensitive_config.get("access_token")
            return self._github_api_get(
                url,
                endpoint=endpoint,
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {access_token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=timeout,
            )

        try:
            response = fetch()
            if response.status_code == 401:
                try:
                    self.refresh_access_token()
                except Exception:
                    logger.warning("GitHubIntegration: token refresh after 401 failed", exc_info=True)
                    return None
                response = fetch()
            return response
        except Exception:
            logger.warning("GitHubIntegration: installation GET failed", url=url, exc_info=True)
            return None

    def installation_can_access_repository(self, repository: str) -> bool:
        """Whether this installation token can access the repo (``GET /repos/{owner}/{repo}`` returns 200)."""
        response = self._installation_authenticated_get(
            f"https://api.github.com/repos/{repository}", endpoint="/repos/{owner}/{repo}"
        )
        if response is None:
            return False
        return response.status_code == 200

    def get_commit_author_info(self, repository: str, sha: str) -> GitHubCommitAuthor | None:
        """Resolve a commit SHA to author metadata via the GitHub API."""
        response = self._installation_authenticated_get(
            f"https://api.github.com/repos/{repository}/commits/{sha}", endpoint="/repos/{owner}/{repo}/commits/{sha}"
        )
        if response is None:
            return None
        if response.status_code != 200:
            logger.info(
                "GitHub API non-200 for commit lookup",
                status_code=response.status_code,
                sha_prefix=sha[:8],
                repository=repository,
            )
            return None
        try:
            data = response.json()
        except Exception:
            logger.warning(
                "GitHubIntegration: failed to parse commit JSON",
                repository=repository,
                sha_prefix=sha[:8],
                exc_info=True,
            )
            return None
        author = data.get("author")
        if not author or not author.get("login"):
            return None
        git_author = data.get("commit", {}).get("author", {})
        name = git_author.get("name") or author.get("login")
        commit_url = data.get("html_url", f"https://github.com/{repository}/commit/{sha}")
        return GitHubCommitAuthor(login=author["login"], name=name, commit_url=commit_url)

    def list_repositories(self, *, limit: int = 100, offset: int = 0) -> tuple[list[dict], bool]:
        """List installation repositories via the GitHub API.

        Fetches only the GitHub pages needed to satisfy the requested
        ``[offset, offset+limit)`` window. Returns a tuple of
        ``(repositories, has_more)`` where *has_more* indicates whether
        additional repositories exist beyond the returned window.
        """
        GITHUB_PER_PAGE = 100

        try:
            if self.access_token_expired():
                self.refresh_access_token()
        except Exception:
            logger.warning("GitHubIntegration: token refresh pre-check failed", exc_info=True)

        def fetch(page: int) -> requests.Response:
            access_token = self.integration.sensitive_config.get("access_token")
            return self._github_api_get(
                f"https://api.github.com/installation/repositories?page={page}&per_page={GITHUB_PER_PAGE}",
                endpoint="/installation/repositories",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {access_token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )

        def extract_repos(body: dict) -> list[dict]:
            repositories = body.get("repositories")
            if not isinstance(repositories, list):
                logger.warning(
                    "GitHubIntegration: list_repositories invalid payload",
                    integration_id=self.integration.id,
                    payload_keys=sorted(body.keys()),
                )
                raise GitHubIntegrationError("GitHubIntegration: list_repositories invalid payload")
            return [
                {
                    "id": repo["id"],
                    "name": repo["name"],
                    "full_name": repo["full_name"],
                }
                for repo in repositories
                if isinstance(repo, dict)
                and isinstance(repo.get("id"), int)
                and isinstance(repo.get("name"), str)
                and isinstance(repo.get("full_name"), str)
            ]

        def raise_repository_error(message: str, *, status_code: int | None = None, exc_info: bool = False) -> None:
            logger.warning(
                message,
                integration_id=self.integration.id,
                status_code=status_code,
                exc_info=exc_info,
            )
            raise GitHubIntegrationError(message)

        # Work out which GitHub pages cover the requested window.
        first_page = offset // GITHUB_PER_PAGE + 1
        skip = offset % GITHUB_PER_PAGE
        needed = skip + limit

        # Fetch the first required page with 401-retry and transient-error retry.
        transient_status_codes = {502, 503, 504}
        current_page = first_page

        for attempt in range(2):
            try:
                response = fetch(current_page)
            except requests.RequestException:
                raise_repository_error("GitHubIntegration: list_repositories network error", exc_info=True)

            if response.status_code == 401:
                try:
                    self.refresh_access_token()
                except Exception:
                    raise_repository_error("GitHubIntegration: token refresh after 401 failed", exc_info=True)
                try:
                    response = fetch(current_page)
                except requests.RequestException:
                    raise_repository_error("GitHubIntegration: list_repositories network error on retry", exc_info=True)

            try:
                body = response.json()
            except Exception:
                if response.status_code in transient_status_codes and attempt == 0:
                    logger.info(
                        "GitHubIntegration: list_repositories retrying transient non-JSON response",
                        status_code=response.status_code,
                    )
                    continue
                logger.warning(
                    "GitHubIntegration: list_repositories non-JSON response",
                    integration_id=self.integration.id,
                    status_code=response.status_code,
                )
                raise GitHubIntegrationError("GitHubIntegration: list_repositories non-JSON response")

            if response.status_code == 200 and isinstance(body, dict):
                page_repos = extract_repos(body)
                all_fetched = page_repos
                has_next_page = len(page_repos) == GITHUB_PER_PAGE
                break

            if response.status_code in transient_status_codes and attempt == 0:
                logger.info(
                    "GitHubIntegration: list_repositories retrying transient error",
                    status_code=response.status_code,
                    error=body if isinstance(body, dict) else None,
                )
                continue

            logger.warning(
                "GitHubIntegration: failed to list repositories",
                integration_id=self.integration.id,
                status_code=response.status_code,
                error=body if isinstance(body, dict) else None,
            )
            raise GitHubIntegrationError("GitHubIntegration: failed to list repositories")
        else:
            raise GitHubIntegrationError("GitHubIntegration: failed to list repositories after retries")

        # Fetch subsequent pages until we have enough items.
        while len(all_fetched) < needed and has_next_page:
            current_page += 1
            try:
                response = fetch(current_page)
            except requests.RequestException:
                logger.warning(
                    "GitHubIntegration: list_repositories network error on page",
                    integration_id=self.integration.id,
                    page=current_page,
                    exc_info=True,
                )
                raise GitHubIntegrationError("GitHubIntegration: list_repositories network error on page")
            try:
                body = response.json()
            except Exception:
                logger.warning(
                    "GitHubIntegration: list_repositories non-JSON response on page",
                    integration_id=self.integration.id,
                    page=current_page,
                    status_code=response.status_code,
                )
                raise GitHubIntegrationError("GitHubIntegration: list_repositories non-JSON response on page")
            if response.status_code != 200 or not isinstance(body, dict):
                logger.warning(
                    "GitHubIntegration: failed to list repositories on page",
                    integration_id=self.integration.id,
                    page=current_page,
                    status_code=response.status_code,
                    error=body if isinstance(body, dict) else None,
                )
                raise GitHubIntegrationError("GitHubIntegration: failed to list repositories on page")
            page_repos = extract_repos(body)
            all_fetched.extend(page_repos)
            has_next_page = len(page_repos) == GITHUB_PER_PAGE

        result = all_fetched[skip : skip + limit]
        has_more = has_next_page or (skip + limit < len(all_fetched))

        return result, has_more

    def list_all_repositories(self) -> list[dict]:
        """Fetch all accessible repositories, paginating through GitHub's API."""
        all_repositories: list[dict] = []
        offset = 0
        page_size = 100

        while True:
            repositories, has_more = self.list_repositories(limit=page_size, offset=offset)
            all_repositories.extend(repositories)

            if not has_more or not repositories:
                return all_repositories

            offset += len(repositories)

    def _get_repository_cache(self) -> list[dict] | None:
        cached = self.integration.repository_cache
        if not isinstance(cached, list):
            return None

        repositories: list[dict] = []
        for repo in cached:
            if (
                isinstance(repo, dict)
                and isinstance(repo.get("id"), int)
                and isinstance(repo.get("name"), str)
                and isinstance(repo.get("full_name"), str)
            ):
                repositories.append(
                    {
                        "id": repo["id"],
                        "name": repo["name"],
                        "full_name": repo["full_name"],
                    }
                )

        return repositories

    def repository_cache_is_stale(self) -> bool:
        updated_at = self.integration.repository_cache_updated_at
        if updated_at is None:
            return True

        return (timezone.now() - updated_at).total_seconds() >= GITHUB_REPOSITORY_CACHE_TTL_SECONDS

    def sync_repository_cache(self, min_refresh_interval_seconds: int | None = None) -> list[dict]:
        cached_repositories = self._get_repository_cache()
        updated_at = self.integration.repository_cache_updated_at
        if (
            min_refresh_interval_seconds is not None
            and cached_repositories is not None
            and updated_at is not None
            and (timezone.now() - updated_at).total_seconds() < min_refresh_interval_seconds
        ):
            return cached_repositories

        repositories = self.list_all_repositories()
        refreshed_at = timezone.now()
        update_fields = ["repository_cache_updated_at"]
        if repositories != cached_repositories:
            self.integration.repository_cache = repositories
            update_fields.insert(0, "repository_cache")
        self.integration.repository_cache_updated_at = refreshed_at
        self.integration.save(update_fields=update_fields)
        return repositories

    def _filter_cached_repositories(self, repositories: list[dict], search: str) -> list[dict]:
        search_query = search.strip().casefold()
        if not search_query:
            return repositories

        return [
            repository for repository in repositories if search_query in str(repository.get("full_name", "")).casefold()
        ]

    def list_cached_repositories(
        self, *, search: str = "", limit: int = 100, offset: int = 0
    ) -> tuple[list[dict], bool]:
        cached_repositories = self._get_repository_cache()
        updated_at = self.integration.repository_cache_updated_at
        has_cached_snapshot = updated_at is not None
        cache_is_stale = self.repository_cache_is_stale()
        should_refresh = cached_repositories is None or cache_is_stale
        self._record_github_cache_access("repositories", "miss" if should_refresh else "hit", "__all__")

        if should_refresh:
            try:
                cached_repositories = self.sync_repository_cache()
            except Exception:
                logger.warning(
                    "GitHubIntegration: failed to refresh repository cache",
                    integration_id=self.integration.id,
                    exc_info=True,
                )
                if not has_cached_snapshot:
                    raise

        if cached_repositories is None:
            cached_repositories = []

        filtered_repositories = self._filter_cached_repositories(cached_repositories, search)
        result = filtered_repositories[offset : offset + limit]
        has_more = offset + limit < len(filtered_repositories)
        return result, has_more

    def list_all_cached_repositories(self, max_repos: int | None = None) -> list[dict]:
        cached_repositories = self._get_repository_cache()
        updated_at = self.integration.repository_cache_updated_at
        has_cached_snapshot = updated_at is not None
        cache_is_stale = self.repository_cache_is_stale()
        should_refresh = cached_repositories is None or cache_is_stale
        self._record_github_cache_access("repositories", "miss" if should_refresh else "hit", "__all__")

        if should_refresh:
            try:
                cached_repositories = self.sync_repository_cache()
            except Exception:
                logger.warning(
                    "GitHubIntegration: failed to refresh repository cache",
                    integration_id=self.integration.id,
                    exc_info=True,
                )
                if not has_cached_snapshot:
                    raise

        if cached_repositories is None:
            cached_repositories = []

        if max_repos is not None:
            return cached_repositories[:max_repos]

        return cached_repositories

    @database_sync_to_async
    def list_cached_repositories_async(
        self, *, search: str = "", limit: int = 100, offset: int = 0
    ) -> tuple[list[dict], bool]:
        return self.list_cached_repositories(search=search, limit=limit, offset=offset)

    @database_sync_to_async
    def list_all_cached_repositories_async(self, max_repos: int | None = None) -> list[dict]:
        return self.list_all_cached_repositories(max_repos=max_repos)

    def _get_branch_cache_key(self, repo: str) -> str:
        return f"github_integration:branches:{self.integration.id}:{repo.lower()}"

    def _get_branch_cache(self, repo: str) -> dict[str, Any] | None:
        cached = cache.get(self._get_branch_cache_key(repo))
        if not isinstance(cached, dict):
            return None

        branches = cached.get("branches")
        default_branch = cached.get("default_branch")
        updated_at = cached.get("updated_at")
        if not isinstance(branches, list) or not all(isinstance(branch, str) for branch in branches):
            return None
        if default_branch is not None and not isinstance(default_branch, str):
            return None
        if not isinstance(updated_at, (int, float)):
            return None

        return {
            "branches": branches,
            "default_branch": default_branch,
            "updated_at": updated_at,
        }

    def branch_cache_is_stale(self, repo: str) -> bool:
        cached = self._get_branch_cache(repo)
        if cached is None:
            return True

        return time.time() - float(cached["updated_at"]) >= GITHUB_BRANCH_CACHE_TTL_SECONDS

    def list_all_branches(self, repo: str) -> list[str]:
        """Fetch all branches for a repository, paginating through GitHub's API."""
        all_branches: list[str] = []
        offset = 0
        page_size = 100

        while True:
            branches, has_more = self.list_branches(repo, limit=page_size, offset=offset)
            all_branches.extend(branches)

            if not has_more or not branches:
                return all_branches

            offset += len(branches)

    def sync_branch_cache(self, repo: str) -> tuple[list[str], str | None]:
        branches = self.list_all_branches(repo)
        cached = self._get_branch_cache(repo)
        cached_default_branch = None if cached is None else cast(str | None, cached["default_branch"])

        default_branch: str | None
        try:
            default_branch = self.get_default_branch(repo)
        except Exception:
            logger.warning(
                "GitHubIntegration: failed to refresh default branch",
                integration_id=self.integration.id,
                repo=repo,
                exc_info=True,
            )
            default_branch = cached_default_branch if cached_default_branch in branches else None

        if default_branch and default_branch in branches:
            branches = [branch for branch in branches if branch != default_branch]
            branches.insert(0, default_branch)

        cache.set(
            self._get_branch_cache_key(repo),
            {
                "branches": branches,
                "default_branch": default_branch,
                "updated_at": time.time(),
            },
            timeout=GITHUB_BRANCH_CACHE_TIMEOUT_SECONDS,
        )

        return branches, default_branch

    def list_cached_branches(
        self, repo: str, *, search: str = "", limit: int = 100, offset: int = 0
    ) -> tuple[list[str], str | None, bool]:
        cached = self._get_branch_cache(repo)
        should_refresh = cached is None or self.branch_cache_is_stale(repo)
        self._record_github_cache_access("branches", "miss" if should_refresh else "hit", repo)

        if should_refresh:
            try:
                branches, default_branch = self.sync_branch_cache(repo)
                cached = {
                    "branches": branches,
                    "default_branch": default_branch,
                }
            except Exception:
                logger.warning(
                    "GitHubIntegration: failed to refresh branch cache",
                    integration_id=self.integration.id,
                    repo=repo,
                    exc_info=True,
                )
                if cached is None:
                    raise

        assert cached is not None
        branches = cast(list[str], cached["branches"])
        default_branch = cast(str | None, cached["default_branch"])

        normalized_search = search.strip().casefold()
        filtered_branches = (
            [branch for branch in branches if normalized_search in branch.casefold()] if normalized_search else branches
        )

        result = filtered_branches[offset : offset + limit]
        has_more = offset + limit < len(filtered_branches)
        return result, default_branch, has_more

    def get_top_starred_repository(self) -> str | None:
        """Get the repository with the most stars from the GitHub integration.

        Returns the full repository name in format 'org/repo', or None if no repos available.
        """
        try:
            if self.access_token_expired():
                self.refresh_access_token()
        except Exception:
            logger.warning("GitHubIntegration: token refresh pre-check failed", exc_info=True)

        def fetch(page: int = 1) -> requests.Response:
            access_token = self.integration.sensitive_config.get("access_token")
            return self._github_api_get(
                f"https://api.github.com/installation/repositories?page={page}&per_page=100",
                endpoint="/installation/repositories",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {access_token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )

        response = fetch()

        if response.status_code == 401:
            try:
                self.refresh_access_token()
            except Exception:
                logger.warning("GitHubIntegration: token refresh after 401 failed", exc_info=True)
            else:
                response = fetch()

        try:
            body = response.json()
        except Exception:
            logger.warning(
                "GitHubIntegration: get_top_starred_repository non-JSON response",
                status_code=response.status_code,
            )
            return None

        repositories = body.get("repositories")
        if response.status_code != 200 or not isinstance(repositories, list) or not repositories:
            return None

        top_repo = max(repositories, key=lambda r: r.get("stargazers_count", 0) if isinstance(r, dict) else 0)
        if not isinstance(top_repo, dict):
            return None

        full_name = top_repo.get("full_name")
        if isinstance(full_name, str):
            return full_name.lower()

        return None

    def list_branches(self, repo: str, *, limit: int = 100, offset: int = 0) -> tuple[list[str], bool]:
        """List branches for a given repository via the GitHub API.

        Fetches only the GitHub pages needed to satisfy the requested
        ``[offset, offset+limit)`` window. Returns a tuple of
        ``(branch_names, has_more)`` where *has_more* indicates whether
        additional branches exist beyond the returned window.
        """
        GITHUB_PER_PAGE = 100

        try:
            if self.access_token_expired():
                self.refresh_access_token()
        except Exception:
            logger.warning("GitHubIntegration: token refresh pre-check failed", exc_info=True)

        def fetch(page: int) -> requests.Response:
            access_token = self.integration.sensitive_config.get("access_token")
            return self._github_api_get(
                f"https://api.github.com/repos/{repo}/branches?per_page={GITHUB_PER_PAGE}&page={page}",
                endpoint="/repos/{owner}/{repo}/branches",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {access_token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=10,
            )

        def extract_names(data: list) -> list[str]:
            return [
                branch["name"] for branch in data if isinstance(branch, dict) and isinstance(branch.get("name"), str)
            ]

        # Work out which GitHub pages cover the requested window.
        first_page = offset // GITHUB_PER_PAGE + 1
        skip = offset % GITHUB_PER_PAGE
        needed = skip + limit

        # Fetch the first required page (with 401-retry logic).
        current_page = first_page
        try:
            response = fetch(current_page)
        except requests.RequestException:
            logger.warning("GitHubIntegration: list_branches network error", repo=repo, exc_info=True)
            return [], False

        if response.status_code == 401:
            try:
                self.refresh_access_token()
            except Exception:
                logger.warning("GitHubIntegration: token refresh after 401 failed", exc_info=True)
                return [], False
            try:
                response = fetch(current_page)
            except requests.RequestException:
                logger.warning("GitHubIntegration: list_branches network error on retry", repo=repo, exc_info=True)
                return [], False

        if response.status_code != 200:
            logger.warning(
                "GitHubIntegration: failed to list branches",
                status_code=response.status_code,
                repo=repo,
            )
            return [], False

        try:
            body = response.json()
        except Exception:
            logger.warning(
                "GitHubIntegration: list_branches non-JSON response",
                status_code=response.status_code,
            )
            return [], False

        if not isinstance(body, list):
            return [], False

        all_fetched = extract_names(body)
        has_next_page = 'rel="next"' in response.headers.get("Link", "")

        # Fetch subsequent pages until we have enough items.
        while len(all_fetched) < needed and has_next_page:
            current_page += 1
            try:
                response = fetch(current_page)
            except requests.RequestException:
                break
            if response.status_code != 200:
                logger.warning(
                    "GitHubIntegration.list_branches pagination stopped",
                    status_code=response.status_code,
                    page=current_page,
                    repo=repo,
                )
                break
            try:
                body = response.json()
            except Exception:
                break
            if not isinstance(body, list):
                break
            all_fetched.extend(extract_names(body))
            has_next_page = 'rel="next"' in response.headers.get("Link", "")

        result = all_fetched[skip : skip + limit]
        has_more = has_next_page or (skip + limit < len(all_fetched))

        return result, has_more

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
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

        issue = response.json()

        return {"number": issue["number"], "repository": repository}

    def get_default_branch(self, repository: str) -> str:
        """Get the default branch for a repository."""
        repo_path = repository if "/" in repository else f"{self.organization()}/{repository}"
        cache_key = f"github_integration:default_branch:{self.integration.id}:{repo_path}"

        cached = cache.get(cache_key)
        if isinstance(cached, str):
            return cached

        access_token = self.integration.sensitive_config.get("access_token")
        if not access_token:
            raise ValueError("GitHub access token not configured")

        response = self._github_api_get(
            f"https://api.github.com/repos/{repo_path}",
            endpoint="/repos/{owner}/{repo}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {access_token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=10,
        )

        if response.status_code == 200:
            repo_data = response.json()
            default_branch = repo_data.get("default_branch", "main")
            cache.set(cache_key, default_branch, timeout=60 * 60 * 24)
            return default_branch
        else:
            raise Exception(f"Failed to get default branch: HTTP {response.status_code}")

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
                "X-GitHub-Api-Version": "2022-11-28",
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
                "X-GitHub-Api-Version": "2022-11-28",
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
                    "X-GitHub-Api-Version": "2022-11-28",
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
                "X-GitHub-Api-Version": "2022-11-28",
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
                "X-GitHub-Api-Version": "2022-11-28",
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
                "X-GitHub-Api-Version": "2022-11-28",
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
                "X-GitHub-Api-Version": "2022-11-28",
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

    @staticmethod
    def parse_pull_request_url(pr_url: str) -> tuple[str, str, int] | None:
        """Parse a GitHub pull request URL into ``(owner, repo, pr_number)``.

        Returns ``None`` if the URL does not look like a GitHub PR URL.
        """
        try:
            parsed = urlparse(pr_url)
        except Exception:
            return None
        if parsed.netloc not in {"github.com", "www.github.com"}:
            return None
        parts = [p for p in parsed.path.split("/") if p]
        # Expected path: /{owner}/{repo}/pull/{number}[/...]
        if len(parts) < 4 or parts[2] != "pull":
            return None
        owner, repo, _, pr_number_str = parts[:4]
        try:
            pr_number = int(pr_number_str)
        except ValueError:
            return None
        return owner, repo, pr_number

    def get_pull_request(self, repository: str, pr_number: int) -> dict[str, Any]:
        """Fetch a pull request by repository (``owner/repo`` or just ``repo``) and PR number."""
        repo_path = repository if "/" in repository else f"{self.organization()}/{repository}"

        response = self._installation_authenticated_get(
            f"https://api.github.com/repos/{repo_path}/pulls/{pr_number}",
            endpoint="/repos/{owner}/{repo}/pulls/{pull_number}",
        )
        if response is None:
            return {"success": False, "error": "Network error fetching pull request"}
        if response.status_code != 200:
            return {
                "success": False,
                "error": f"Failed to fetch pull request: {response.text}",
                "status_code": response.status_code,
            }
        try:
            pr = response.json()
        except Exception:
            logger.warning(
                "GitHubIntegration: get_pull_request non-JSON response",
                repository=repo_path,
                pr_number=pr_number,
            )
            return {"success": False, "error": "Failed to parse pull request JSON"}

        head = pr.get("head") or {}
        base = pr.get("base") or {}
        user = pr.get("user") or {}

        return {
            "success": True,
            "number": pr.get("number"),
            "title": pr.get("title"),
            "body": pr.get("body"),
            "url": pr.get("html_url"),
            "state": pr.get("state"),
            "merged": pr.get("merged", False),
            "draft": pr.get("draft", False),
            "head_branch": head.get("ref"),
            "base_branch": base.get("ref"),
            "head_sha": head.get("sha"),
            "base_sha": base.get("sha"),
            "repository": repo_path,
            "author": user.get("login"),
            "created_at": pr.get("created_at"),
            "updated_at": pr.get("updated_at"),
            "merged_at": pr.get("merged_at"),
            "closed_at": pr.get("closed_at"),
            "comments": pr.get("comments", 0),
            "review_comments": pr.get("review_comments", 0),
            "commits": pr.get("commits", 0),
            "additions": pr.get("additions", 0),
            "deletions": pr.get("deletions", 0),
            "changed_files": pr.get("changed_files", 0),
        }

    def get_pull_request_from_url(self, pr_url: str) -> dict[str, Any]:
        """Fetch a pull request by its HTML URL (e.g. ``https://github.com/owner/repo/pull/123``)."""
        parsed = self.parse_pull_request_url(pr_url)
        if parsed is None:
            return {"success": False, "error": f"Invalid GitHub pull request URL: {pr_url}"}
        owner, repo, pr_number = parsed
        return self.get_pull_request(f"{owner}/{repo}", pr_number)


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
