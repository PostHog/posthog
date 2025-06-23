from dataclasses import dataclass
import hashlib
import hmac
import time
from datetime import timedelta
from typing import Any, Literal, Optional
from urllib.parse import urlencode

from django.db import models
from prometheus_client import Counter
import requests
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from posthog.exceptions_capture import capture_exception
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from google.oauth2 import service_account
from google.auth.transport.requests import Request as GoogleRequest

from django.conf import settings
from posthog.cache_utils import cache_for
from posthog.helpers.encrypted_fields import EncryptedJSONField
from posthog.models.instance_setting import get_instance_settings
from posthog.models.user import User
from products.messaging.backend.providers.mailjet import MailjetProvider
import structlog

from posthog.plugins.plugin_server_api import reload_integrations_on_workers
from posthog.warehouse.util import database_sync_to_async

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
        SNAPCHAT = "snapchat"
        LINKEDIN_ADS = "linkedin-ads"
        INTERCOM = "intercom"
        EMAIL = "email"
        LINEAR = "linear"

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

        return f"ID: {self.integration_id}"

    @property
    def access_token(self) -> Optional[str]:
        return self.sensitive_config.get("access_token")

    @property
    def refresh_token(self) -> Optional[str]:
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
    token_info_url: Optional[str] = None
    token_info_graphql_query: Optional[str] = None
    token_info_config_fields: Optional[list[str]] = None
    additional_authorize_params: Optional[dict[str, str]] = None


class OauthIntegration:
    supported_kinds = [
        "slack",
        "salesforce",
        "hubspot",
        "google-ads",
        "snapchat",
        "linkedin-ads",
        "intercom",
        "linear",
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
                scope="r_ads rw_conversions openid profile email",
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
                token_info_graphql_query="{ viewer { organization { id name } } }",
                token_info_config_fields=["data.viewer.organization.id", "data.viewer.organization.name"],
                client_id=settings.LINEAR_APP_CLIENT_ID,
                client_secret=settings.LINEAR_APP_CLIENT_SECRET,
                scope="read issues:create",
                id_path="data.viewer.organization.id",
                name_path="data.viewer.organization.name",
            )

        raise NotImplementedError(f"Oauth config for kind {kind} not implemented")

    @classmethod
    def redirect_uri(cls, kind: str) -> str:
        # The redirect uri is fixed but should always be https and include the "next" parameter for the frontend to redirect
        return f"{settings.SITE_URL.replace('http://', 'https://')}/integrations/{kind}/callback"

    @classmethod
    def authorize_url(cls, kind: str, token: str, next="") -> str:
        oauth_config = cls.oauth_config_for_kind(kind)

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

        if res.status_code != 200 or not config.get("access_token"):
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

        if isinstance(integration_id, int):
            integration_id = str(integration_id)

        if not isinstance(integration_id, str):
            raise Exception("Oauth error")

        sensitive_config: dict = {
            "access_token": config.pop("access_token"),
            # NOTE: We don't actually use the refresh and id tokens (typically they aren't even provided for this sort of service auth)
            # but we ensure they are popped and stored in sensitive config to avoid accidental exposure
            "refresh_token": config.pop("refresh_token", None),
            "id_token": config.pop("id_token", None),
        }

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

    def access_token_expired(self, time_threshold: Optional[timedelta] = None) -> bool:
        # Not all integrations have refresh tokens or expiries, so we just return False if we can't check

        refresh_token = self.integration.sensitive_config.get("refresh_token")
        expires_in = self.integration.config.get("expires_in")
        refreshed_at = self.integration.config.get("refreshed_at")
        if not refresh_token or not expires_in or not refreshed_at:
            return False

        # To be really safe we refresh if its half way through the expiry
        time_threshold = time_threshold or timedelta(seconds=expires_in / 2)

        return time.time() > refreshed_at + expires_in - time_threshold.total_seconds()

    def refresh_access_token(self):
        """
        Refresh the access token for the integration if necessary
        """

        oauth_config = self.oauth_config_for_kind(self.integration.kind)

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
            self.integration.config["expires_in"] = config.get("expires_in")
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

    def list_channels(self, should_include_private_channels: bool, authed_user: str) -> list[dict]:
        # NOTE: Annoyingly the Slack API has no search so we have to load all channels...
        # We load public and private channels separately as when mixed, the Slack API pagination is buggy
        public_channels = self._list_channels_by_type("public_channel")
        private_channels = self._list_channels_by_type("private_channel", should_include_private_channels, authed_user)
        channels = public_channels + private_channels

        return sorted(channels, key=lambda x: x["name"])

    def get_channel_by_id(
        self, channel_id: str, should_include_private_channels: bool = False, authed_user: str | None = None
    ) -> Optional[dict]:
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
            f"https://googleads.googleapis.com/v18/customers/{customer_id}/googleAds:searchStream",
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
            f"https://googleads.googleapis.com/v18/customers:listAccessibleCustomers",
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
                f"https://googleads.googleapis.com/v18/customers/{account_id}/googleAds:searchStream",
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
        cls, kind: str, key_info: dict, team_id: int, created_by: Optional[User] = None
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

    def access_token_expired(self, time_threshold: Optional[timedelta] = None) -> bool:
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
        credentials = service_account.Credentials.from_service_account_info(
            self.integration.sensitive_config, scopes=["https://www.googleapis.com/auth/pubsub"]
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
                "LinkedIn-Version": "202409",
            },
        )

        return response.json()

    def list_linkedin_ads_accounts(self) -> dict:
        response = requests.request(
            "GET",
            "https://api.linkedin.com/v2/adAccountsV2?q=search",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.integration.sensitive_config['access_token']}",
                "LinkedIn-Version": "202409",
            },
        )

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

    @classmethod
    def integration_from_domain(cls, domain: str, team_id: int, created_by: Optional[User] = None) -> Integration:
        mailjet = MailjetProvider()
        mailjet.create_email_domain(domain, team_id=team_id)

        integration, created = Integration.objects.update_or_create(
            team_id=team_id,
            kind="email",
            integration_id=domain,
            defaults={
                "config": {
                    "domain": domain,
                    "mailjet_verified": False,
                    "aws_ses_verified": False,
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
        cls, api_key: str, secret_key: str, team_id: int, created_by: Optional[User] = None
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

        verification_result = self.mailjet_provider.verify_email_domain(domain, team_id=self.integration.team_id)

        if verification_result.get("status") == "success":
            updated_config = {"mailjet_verified": True}

            # Merge the new config with existing config
            updated_config = {**self.integration.config, **updated_config}
            self.integration.config = updated_config
            self.integration.save()

        return verification_result


class LinearIntegration:
    integration: Integration

    def __init__(self, integration: Integration) -> None:
        if integration.kind != "linear":
            raise Exception("LinearIntegration init called with Integration with wrong 'kind'")

        self.integration = integration

    def list_teams(self) -> list[dict]:
        query = f"{{ teams {{ nodes {{ id name }} }} }}"

        response = requests.post(
            "https://api.linear.app/graphql",
            headers={"Authorization": f"Bearer {self.integration.sensitive_config['access_token']}"},
            json={"query": query},
        )

        teams = dot_get(response.json(), "data.teams.nodes")
        return teams
