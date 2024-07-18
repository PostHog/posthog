from dataclasses import dataclass
import hashlib
import hmac
import time
from datetime import timedelta
from typing import Any, Literal
from urllib.parse import urlencode

from django.db import models
import requests
from rest_framework.request import Request
from slack_sdk import WebClient

from django.conf import settings
from posthog.cache_utils import cache_for
from posthog.models.instance_setting import get_instance_settings
from posthog.models.user import User


class Integration(models.Model):
    class IntegrationKind(models.TextChoices):
        SLACK = "slack"
        SALESFORCE = "salesforce"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "kind", "integration_id"], name="posthog_integration_kind_id_unique"
            )
        ]

    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)

    # The integration type identifier
    kind: models.CharField = models.CharField(max_length=10, choices=IntegrationKind.choices)
    # The ID of the integration in the external system
    integration_id: models.TextField = models.TextField(null=True, blank=True)
    # Any config that COULD be passed to the frontend
    config: models.JSONField = models.JSONField(default=dict)
    # Any sensitive config that SHOULD NOT be passed to the frontend
    sensitive_config: models.JSONField = models.JSONField(default=dict)

    errors: models.TextField = models.TextField()

    # Meta
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, blank=True)
    created_by: models.ForeignKey = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)


@dataclass
class OauthConfig:
    authorize_url: str
    token_url: str
    client_id: str
    client_secret: str
    scope: str
    id_path: str


class OauthIntegration:
    supported_kinds = ["slack", "salesforce"]
    integration: Integration
    kind: str

    def __init__(self, integration: Integration, kind: str) -> None:
        self.integration = integration
        self.kind = kind

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
            )
        elif kind == "salesforce":
            if not settings.SALESFORCE_CONSUMER_KEY or not settings.SALESFORCE_CONSUMER_SECRET:
                raise NotImplementedError("Salesforce app not configured")

            return OauthConfig(
                authorize_url="https://login.salesforce.com/services/oauth2/authorize",
                token_url="https://login.salesforce.com/services/oauth2/token",
                client_id=settings.SALESFORCE_CONSUMER_KEY,
                client_secret=settings.SALESFORCE_CONSUMER_SECRET,
                scope="full",
                id_path="instance_url",
            )

        raise NotImplementedError(f"Oauth config for kind {kind} not implemented")

    @classmethod
    def redirect_uri(cls, kind: str) -> str:
        # The redirect uri is fixed but should always be https and include the "next" parameter for the frontend to redirect
        return f"{settings.SITE_URL.replace('http://', 'https://')}/integrations/{kind}/callback"

    @classmethod
    def authorize_url(cls, kind: str, next="") -> str:
        oauth_config = cls.oauth_config_for_kind(kind)

        query_params = {
            "client_id": oauth_config.client_id,
            "scope": oauth_config.scope,
            "redirect_uri": cls.redirect_uri(kind),
            "response_type": "code",
            "state": urlencode({"next": next}),
        }

        return f"{oauth_config.authorize_url}?{urlencode(query_params)}"

    @classmethod
    def integration_from_oauth_response(
        cls, kind: str, team_id: str, created_by: User, params: dict[str, str]
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
            raise Exception("Oauth error")

        integration_id: Any = config

        for key in oauth_config.id_path.split("."):
            integration_id = integration_id.get(key)

        if not isinstance(integration_id, str):
            raise Exception("Oauth error")

        sensitive_config: dict = {
            "access_token": config.pop("access_token"),
            # NOTE: We don't actually use the refresh and id tokens (typically they aren't even provided for this sort of service auth)
            # but we ensure they are popped and stored in sensitive config to avoid accidental exposure
            "refresh_token": config.pop("refresh_token", None),
            "id_token": config.pop("id_token", None),
        }

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

        return integration


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

    def list_channels(self) -> list[dict]:
        # NOTE: Annoyingly the Slack API has no search so we have to load all channels...
        # We load public and private channels separately as when mixed, the Slack API pagination is buggy
        public_channels = self._list_channels_by_type("public_channel")
        private_channels = self._list_channels_by_type("private_channel")
        channels = public_channels + private_channels

        return sorted(channels, key=lambda x: x["name"])

    def _list_channels_by_type(self, type: Literal["public_channel", "private_channel"]) -> list[dict]:
        max_page = 10
        channels = []
        cursor = None

        while max_page > 0:
            max_page -= 1
            res = self.client.conversations_list(exclude_archived=True, types=type, limit=200, cursor=cursor)

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
