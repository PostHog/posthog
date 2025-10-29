import hmac
import json
import time
import base64
import socket
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal, Optional
from urllib.parse import urlencode

if TYPE_CHECKING:
    import aiohttp

from django.conf import settings
from django.db import models

import jwt
import requests
import structlog
from disposable_email_domains import blocklist as disposable_email_domains_list
from free_email_domains import whitelist as free_email_domains_list
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import service_account
from prometheus_client import Counter
from requests.auth import HTTPBasicAuth
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient

from posthog.cache_utils import cache_for
from posthog.exceptions_capture import capture_exception
from posthog.helpers.encrypted_fields import EncryptedJSONField
from posthog.models.instance_setting import get_instance_settings
from posthog.models.user import User
from posthog.plugins.plugin_server_api import reload_integrations_on_workers
from posthog.sync import database_sync_to_async

from products.workflows.backend.providers import MailjetProvider, SESProvider, TwilioProvider

logger = structlog.get_logger(__name__)

oauth_refresh_counter = Counter(
    "integration_oauth_refresh", "Number of times an oauth refresh has been attempted", labelnames=["kind", "result"]
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
        SLACK = "slack"
        SALESFORCE = "salesforce"
        HUBSPOT = "hubspot"
        GOOGLE_PUBSUB = "google-pubsub"
        GOOGLE_CLOUD_STORAGE = "google-cloud-storage"
        GOOGLE_ADS = "google-ads"
        GOOGLE_SHEETS = "google-sheets"
        SNAPCHAT = "snapchat"
        LINKEDIN_ADS = "linkedin-ads"
        REDDIT_ADS = "reddit-ads"
        TIKTOK_ADS = "tiktok-ads"
        INTERCOM = "intercom"
        EMAIL = "email"
        LINEAR = "linear"
        GITHUB = "github"
        GITLAB = "gitlab"
        META_ADS = "meta-ads"
        TWILIO = "twilio"
        CLICKUP = "clickup"
        VERCEL = "vercel"
        DATABRICKS = "databricks"

    team = models.ForeignKey("Team", on_delete=models.CASCADE)

    # The integration type identifier
    kind = models.CharField(max_length=20, choices=IntegrationKind.choices)
    # The ID of the integration in the external system
    integration_id = models.TextField(null=True, blank=True)
    # Any config that COULD be passed to the frontend
    config = models.JSONField(default=dict)
    sensitive_config = EncryptedJSONField(
        default=dict,
        ignore_decrypt_errors=True,  # allows us to load previously unencrypted data
    )

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


class OauthIntegration:
    supported_kinds = [
        "slack",
        "salesforce",
        "hubspot",
        "google-ads",
        "google-sheets",
        "snapchat",
        "linkedin-ads",
        "reddit-ads",
        "tiktok-ads",
        "meta-ads",
        "intercom",
        "linear",
        "clickup",
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
                scope="channels:read,groups:read,chat:write,chat:write.customize",
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

            return OauthConfig(
                authorize_url="https://www.linkedin.com/oauth/v2/authorization",
                token_info_url="https://api.linkedin.com/v2/userinfo",
                token_info_config_fields=["sub", "email"],
                token_url="https://www.linkedin.com/oauth/v2/accessToken",
                client_id=settings.LINKEDIN_APP_CLIENT_ID,
                client_secret=settings.LINKEDIN_APP_CLIENT_SECRET,
                scope="r_ads rw_conversions r_ads_reporting openid profile email",
                id_path="sub",
                name_path="email",
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

        raise NotImplementedError(f"Oauth config for kind {kind} not implemented")

    @classmethod
    def redirect_uri(cls, kind: str) -> str:
        # The redirect uri is fixed but should always be https and include the "next" parameter for the frontend to redirect
        return f"{settings.SITE_URL.replace('http://', 'https://')}/integrations/{kind}/callback"

    @classmethod
    def authorize_url(cls, kind: str, token: str, next="") -> str:
        oauth_config = cls.oauth_config_for_kind(kind)

        if kind == "tiktok-ads":
            # TikTok uses different parameter names
            query_params = {
                "app_id": oauth_config.client_id,
                "redirect_uri": cls.redirect_uri(kind),
                "state": urlencode({"next": next, "token": token}),
            }
        else:
            query_params = {
                "client_id": oauth_config.client_id,
                "scope": oauth_config.scope,
                "redirect_uri": cls.redirect_uri(kind),
                "response_type": "code",
                "state": urlencode({"next": next, "token": token}),
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
        else:
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
                logger.error(f"Oauth error for {kind}", response=res.text)
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
                if oauth_config.token_info_config_fields:
                    for field in oauth_config.token_info_config_fields:
                        config[field] = dot_get(data, field)

        integration_id = dot_get(config, oauth_config.id_path)

        # Reddit access token is a JWT, extract user ID from it
        if kind == "reddit-ads" and not integration_id:
            try:
                access_token = config.get("access_token")
                if access_token:
                    # Split JWT and get payload (middle part)
                    parts = access_token.split(".")
                    if len(parts) >= 2:
                        payload = parts[1]
                        # Decode JWT payload (handle missing padding)
                        decoded = base64.urlsafe_b64decode(payload + "===")
                        jwt_data = json.loads(decoded)

                        # Extract user ID from JWT (lid = login ID)
                        reddit_user_id = jwt_data.get("lid", jwt_data.get("aid"))
                        if reddit_user_id:
                            config["reddit_user_id"] = reddit_user_id
                            integration_id = reddit_user_id
            except Exception as e:
                logger.exception("Failed to decode Reddit JWT", error=str(e))

        if isinstance(integration_id, int):
            integration_id = str(integration_id)
        elif isinstance(integration_id, list) and len(integration_id) > 0:
            integration_id = ",".join(str(item) for item in integration_id)

        if not isinstance(integration_id, str):
            raise Exception("Oauth error")

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
        if integration.kind != "slack":
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
    def validate_request(cls, request: Request):
        """
        Based on https://api.slack.com/authentication/verifying-requests-from-slack
        """
        slack_config = cls.slack_config()
        slack_signature = request.headers.get("X-SLACK-SIGNATURE")
        slack_time = request.headers.get("X-SLACK-REQUEST-TIMESTAMP")

        if not slack_config["SLACK_APP_SIGNING_SECRET"] or not slack_signature or not slack_time:
            raise SlackIntegrationError("Invalid")

        # Check the token is not older than 5mins
        try:
            if time.time() - float(slack_time) > 300:
                raise SlackIntegrationError("Expired")
        except ValueError:
            raise SlackIntegrationError("Invalid")

        sig_basestring = f"v0:{slack_time}:{request.body.decode('utf-8')}"

        my_signature = (
            "v0="
            + hmac.new(
                slack_config["SLACK_APP_SIGNING_SECRET"].encode("utf-8"),
                sig_basestring.encode("utf-8"),
                digestmod=hashlib.sha256,
            ).hexdigest()
        )

        if not hmac.compare_digest(my_signature, slack_signature):
            raise SlackIntegrationError("Invalid")

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
            json={"query": "SELECT conversion_action.id, conversion_action.name FROM conversion_action"},
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.integration.sensitive_config['access_token']}",
                "developer-token": settings.GOOGLE_ADS_DEVELOPER_TOKEN,
                **({"login-customer-id": parent_id} if parent_id else {}),
            },
        )

        if response.status_code != 200:
            capture_exception(
                Exception(f"GoogleAdsIntegration: Failed to list ads conversion actions: {response.text}")
            )
            raise Exception(f"There was an internal error")

        return response.json()

    # Google Ads manager accounts can have access to other accounts (including other manager accounts).
    # Filter out duplicates where a user has direct access and access through a manager account, while prioritizing direct access.
    def list_google_ads_accessible_accounts(self) -> list[dict[str, str]]:
        response = requests.request(
            "GET",
            f"https://googleads.googleapis.com/v21/customers:listAccessibleCustomers",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.integration.sensitive_config['access_token']}",
                "developer-token": settings.GOOGLE_ADS_DEVELOPER_TOKEN,
            },
        )

        if response.status_code != 200:
            capture_exception(Exception(f"GoogleAdsIntegration: Failed to list accessible accounts: {response.text}"))
            raise Exception(f"There was an internal error")

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
                    "access_token": credentials.token,
                },
                "sensitive_config": key_info,
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

        credentials = service_account.Credentials.from_service_account_info(
            self.integration.sensitive_config, scopes=[scope]
        )

        try:
            credentials.refresh(GoogleRequest())
        except Exception:
            raise ValidationError(f"Failed to authenticate with provided service account key")

        self.integration.config = {
            "expires_in": credentials.expiry.timestamp() - int(time.time()),
            "refreshed_at": int(time.time()),
            "access_token": credentials.token,
        }
        self.integration.save()
        reload_integrations_on_workers(self.integration.team_id, [self.integration.id])

        logger.info(f"Refreshed access token for {self}")


class LinkedInAdsIntegration:
    integration: Integration

    def __init__(self, integration: Integration) -> None:
        if integration.kind != "linkedin-ads":
            raise Exception("LinkedInAdsIntegration init called with Integration with wrong 'kind'")

        self.integration = integration

    @property
    def client(self) -> WebClient:
        return WebClient(self.integration.sensitive_config["access_token"])

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

        return response.json()


class ClickUpIntegration:
    integration: Integration

    def __init__(self, integration: Integration) -> None:
        if integration.kind != "clickup":
            raise Exception("ClickUpIntegration init called with Integration with wrong 'kind'")

        self.integration = integration

    def list_clickup_spaces(self, workspace_id):
        response = requests.request(
            "GET",
            f"https://api.clickup.com/api/v2/team/{workspace_id}/space",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.integration.sensitive_config['access_token']}",
            },
        )

        if response.status_code != 200:
            capture_exception(Exception(f"ClickUpIntegration: Failed to list spaces: {response.text}"))
            raise Exception(f"There was an internal error")

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

        if response.status_code != 200:
            capture_exception(Exception(f"ClickUpIntegration: Failed to list lists: {response.text}"))
            raise Exception(f"There was an internal error")

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

        if response.status_code != 200:
            capture_exception(Exception(f"ClickUpIntegration: Failed to list folders: {response.text}"))
            raise Exception(f"There was an internal error")

        return response.json()

    def list_clickup_workspaces(self) -> dict:
        response = requests.request(
            "GET",
            "https://api.clickup.com/api/v2/team",
            headers={"Authorization": f"Bearer {self.integration.sensitive_config['access_token']}"},
        )

        if response.status_code != 200:
            capture_exception(Exception(f"ClickUpIntegration: Failed to list workspaces: {response.text}"))
            raise Exception(f"There was an internal error")

        return response.json()


class EmailIntegration:
    integration: Integration

    def __init__(self, integration: Integration) -> None:
        if integration.kind != "email":
            raise Exception("EmailIntegration init called with Integration with wrong 'kind'")
        self.integration = integration

    @property
    def mailjet_provider(self) -> MailjetProvider:
        return MailjetProvider()

    @property
    def ses_provider(self) -> SESProvider:
        return SESProvider()

    @classmethod
    def create_native_integration(cls, config: dict, team_id: int, created_by: User | None = None) -> Integration:
        email_address: str = config["email"]
        name: str = config["name"]
        domain: str = email_address.split("@")[1]
        provider: str = config.get("provider", "mailjet")  # Default to mailjet for backward compatibility

        if domain in free_email_domains_list or domain in disposable_email_domains_list:
            raise ValidationError(f"Email domain {domain} is not supported. Please use a custom domain.")

        # Check if any other integration already exists in a different team with the same domain
        if Integration.objects.filter(kind="email", config__domain=domain).exclude(team_id=team_id).exists():
            raise ValidationError(
                f"An email integration with domain {domain} already exists in another project. Try a different domain or contact support if you believe this is a mistake."
            )

        # Create domain in the appropriate provider
        if provider == "ses":
            ses = SESProvider()
            ses.create_email_domain(domain, team_id=team_id)
        elif provider == "mailjet":
            mailjet = MailjetProvider()
            mailjet.create_email_domain(domain, team_id=team_id)
        elif provider == "maildev" and settings.DEBUG:
            pass
        else:
            raise ValueError(f"Invalid provider: must be either 'ses' or 'mailjet'")

        integration, created = Integration.objects.update_or_create(
            team_id=team_id,
            kind="email",
            integration_id=email_address,
            defaults={
                "config": {
                    "email": email_address,
                    "domain": domain,
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

    @classmethod
    def integration_from_keys(
        cls, api_key: str, secret_key: str, team_id: int, created_by: User | None = None
    ) -> Integration:
        integration, created = Integration.objects.update_or_create(
            team_id=team_id,
            kind="email",
            integration_id=api_key,
            defaults={
                "config": {
                    "api_key": api_key,
                    "vendor": "mailjet",
                },
                "sensitive_config": {
                    "secret_key": secret_key,
                },
                "created_by": created_by,
            },
        )
        if integration.errors:
            integration.errors = ""
            integration.save()

        return integration

    def verify(self):
        domain = self.integration.config.get("domain")
        provider = self.integration.config.get("provider", "mailjet")

        # Use the appropriate provider for verification
        if provider == "ses":
            verification_result = self.ses_provider.verify_email_domain(domain, team_id=self.integration.team_id)
        elif provider == "mailjet":
            verification_result = self.mailjet_provider.verify_email_domain(domain)
        elif provider == "maildev":
            verification_result = {
                "status": "success",
                "dnsRecords": [],
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

    def __init__(self, integration: Integration) -> None:
        if integration.kind != "github":
            raise Exception("GitHubIntegration init called with Integration with wrong 'kind'")
        self.integration = integration

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
        response = self.client_request(f"installations/{self.integration.integration_id}/access_tokens", method="POST")
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
            reload_integrations_on_workers(self.integration.team_id, [self.integration.id])
            oauth_refresh_counter.labels(self.integration.kind, "success").inc()
            self.integration.save()

    def organization(self) -> str:
        return dot_get(self.integration.config, "account.name")

    def list_repositories(self, page: int = 1) -> list[str]:
        # Proactively refresh token if it's close to expiring to avoid intermittent 401s
        try:
            if self.access_token_expired():
                self.refresh_access_token()
        except Exception:
            logger.warning("GitHubIntegration: token refresh pre-check failed", exc_info=True)

        def fetch() -> requests.Response:
            access_token = self.integration.sensitive_config.get("access_token")
            return requests.get(
                f"https://api.github.com/installation/repositories?page={page}&per_page=100",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {access_token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )

        response = fetch()

        # If unauthorized, try a single refresh and retry
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
                "GitHubIntegration: list_repositories non-JSON response",
                status_code=response.status_code,
            )
            return []

        repositories = body.get("repositories")
        if response.status_code == 200 and isinstance(repositories, list):
            names: list[str] = [
                repo["name"] for repo in repositories if isinstance(repo, dict) and isinstance(repo.get("name"), str)
            ]
            return names

        logger.warning(
            "GitHubIntegration: failed to list repositories",
            status_code=response.status_code,
            error=body if isinstance(body, dict) else None,
        )
        return []

    def create_issue(self, config: dict[str, str]):
        title: str = config.pop("title")
        body: str = config.pop("body")
        repository: str = config.pop("repository")

        org = self.organization()
        access_token = self.integration.sensitive_config["access_token"]

        response = requests.post(
            f"https://api.github.com/repos/{org}/{repository}/issues",
            json={"title": title, "body": body},
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
        org = self.organization()
        access_token = self.integration.sensitive_config["access_token"]

        response = requests.get(
            f"https://api.github.com/repos/{org}/{repository}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {access_token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

        if response.status_code == 200:
            repo_data = response.json()
            return repo_data.get("default_branch", "main")
        else:
            return "main"

    def create_branch(self, repository: str, branch_name: str, base_branch: str | None = None) -> dict[str, Any]:
        """Create a new branch from a base branch."""
        org = self.organization()
        access_token = self.integration.sensitive_config["access_token"]

        # Get the SHA of the base branch (default to repository's default branch)
        if not base_branch:
            base_branch = self.get_default_branch(repository)

        # Get the SHA of the base branch
        ref_response = requests.get(
            f"https://api.github.com/repos/{org}/{repository}/git/ref/heads/{base_branch}",
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
        response = requests.post(
            f"https://api.github.com/repos/{org}/{repository}/git/refs",
            json={
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
            get_response = requests.get(
                f"https://api.github.com/repos/{org}/{repository}/contents/{file_path}",
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

        response = requests.put(
            f"https://api.github.com/repos/{org}/{repository}/contents/{file_path}",
            json=data,
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

        response = requests.post(
            f"https://api.github.com/repos/{org}/{repository}/pulls",
            json={
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

        response = requests.get(
            f"https://api.github.com/repos/{org}/{repository}/branches/{branch_name}",
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
        response = requests.get(
            f"https://api.github.com/repos/{org}/{repository}/pulls",
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


class GitLabIntegration:
    integration: Integration

    @staticmethod
    def get(hostname: str, endpoint: str, project_access_token: str) -> dict:
        response = requests.get(
            f"{hostname}/api/v4/{endpoint}",
            headers={"PRIVATE-TOKEN": project_access_token},
        )

        return response.json()

    @staticmethod
    def post(hostname: str, endpoint: str, project_access_token: str, json: dict) -> dict:
        response = requests.post(
            f"{hostname}/api/v4/{endpoint}",
            json=json,
            headers={"PRIVATE-TOKEN": project_access_token},
        )

        return response.json()

    @classmethod
    def create_integration(self, hostname, project_id, project_access_token, team_id, user) -> Integration:
        project = self.get(hostname, f"projects/{project_id}", project_access_token)

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
