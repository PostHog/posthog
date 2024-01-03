import hashlib
import hmac
import time
from datetime import timedelta
from typing import Dict, List, Literal

from django.db import models
from rest_framework.request import Request
from slack_sdk import WebClient

from posthog.cache_utils import cache_for
from posthog.models.instance_setting import get_instance_settings
from posthog.models.user import User


class Integration(models.Model):
    class IntegrationKind(models.TextChoices):
        SLACK = "slack"

    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)

    # The integration type identifier
    kind: models.CharField = models.CharField(max_length=10, choices=IntegrationKind.choices)
    # Any config that COULD be passed to the frontend
    config: models.JSONField = models.JSONField(default=dict)
    # Any sensitive config that SHOULD NOT be passed to the frontend
    sensitive_config: models.JSONField = models.JSONField(default=dict)

    errors: models.TextField = models.TextField()

    # Meta
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, blank=True)
    created_by: models.ForeignKey = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)


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

    def list_channels(self) -> List[Dict]:
        # NOTE: Annoyingly the Slack API has no search so we have to load all channels...
        # We load public and private channels separately as when mixed, the Slack API pagination is buggy
        public_channels = self._list_channels_by_type("public_channel")
        private_channels = self._list_channels_by_type("private_channel")
        channels = public_channels + private_channels

        return sorted(channels, key=lambda x: x["name"])

    def _list_channels_by_type(self, type: Literal["public_channel", "private_channel"]) -> List[Dict]:
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
    def integration_from_slack_response(cls, team_id: str, created_by: User, params: Dict[str, str]) -> Integration:
        client = WebClient()
        slack_config = cls.slack_config()

        res = client.oauth_v2_access(
            client_id=slack_config["SLACK_APP_CLIENT_ID"],
            client_secret=slack_config["SLACK_APP_CLIENT_SECRET"],
            code=params["code"],
            redirect_uri=params["redirect_uri"],
        )

        if not res.get("ok", False):
            raise Exception("Slack error")

        config = {
            "app_id": res.get("app_id"),  # Like  "A03KWE2FJJ2",
            "authed_user": res.get("authed_user"),  # Like {"id": "U03DCBD92JX"},
            "scope": res.get("scope"),  # Like "incoming-webhook,channels:read,chat:write",
            "token_type": res.get("token_type"),  # Like "bot",
            "bot_user_id": res.get("bot_user_id"),  # Like "U03LFNLTARX",
            "team": res.get("team"),  # Like {"id": "TSS5W8YQZ", "name": "PostHog"},
            "enterprise": res.get("enterprise"),
            "is_enterprise_install": res.get("is_enterprise_install"),
        }

        sensitive_config = {"access_token": res.get("access_token")}

        integration, created = Integration.objects.update_or_create(
            team_id=team_id,
            kind="slack",
            defaults={
                "config": config,
                "sensitive_config": sensitive_config,
                "created_by": created_by,
            },
        )

        return integration

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
