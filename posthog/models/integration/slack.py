"""Slack integration: connected-workspace API calls and request-signature verification."""

import hmac
import time
import hashlib
from collections.abc import Iterable
from datetime import timedelta
from typing import TYPE_CHECKING, Literal, Optional

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    import aiohttp
    from slack_sdk.web.async_client import AsyncWebClient

from django.http import HttpRequest

from opentelemetry import trace
from rest_framework.request import Request
from slack_sdk.errors import SlackApiError

from posthog.cache_utils import cache_for
from posthog.egress.slack.client import SlackWebClient as WebClient
from posthog.models.instance_setting import get_instance_settings

from . import model

tracer = trace.get_tracer(__name__)


PRIVATE_CHANNEL_WITHOUT_ACCESS = "PRIVATE_CHANNEL_WITHOUT_ACCESS"


class SlackIntegrationError(Exception):
    pass


SLACK_INTEGRATION_KINDS: tuple[str, ...] = ("slack",)

SLACK_CHANNELS_PAGE_SIZE = 1000

SLACK_CHANNELS_MAX_PAGES = 10


class SlackIntegration:
    integration: model.Integration

    def __init__(self, integration: model.Integration) -> None:
        if integration.kind not in SLACK_INTEGRATION_KINDS:
            raise Exception("SlackIntegration init called with Integration with wrong 'kind'")

        self.integration = integration

    @property
    def client(self) -> WebClient:
        return WebClient(
            self.integration.sensitive_config["access_token"],
            source="integration",
            workspace_id=self.integration.integration_id,
            app_id="posthog",
        )

    def async_client(self, session: Optional["aiohttp.ClientSession"] = None) -> "AsyncWebClient":
        # slack_sdk's async client imports aiohttp at module scope; this is a models module,
        # so a top-level import would put aiohttp on the django.setup() path
        from posthog.egress.slack.async_client import SlackAsyncWebClient  # noqa: PLC0415

        return SlackAsyncWebClient(
            self.integration.sensitive_config["access_token"],
            source="integration",
            workspace_id=self.integration.integration_id,
            app_id="posthog",
            session=session,
        )

    def granted_scopes(self) -> frozenset[str]:
        """OAuth scopes Slack granted this install, stored on Integration.config["scope"]."""
        raw = self.integration.config.get("scope") or ""
        return frozenset(scope.strip() for scope in raw.split(",") if scope.strip())

    def missing_scopes(self, required: Iterable[str]) -> frozenset[str]:
        return frozenset(required) - self.granted_scopes()

    def list_channels(self, should_include_private_channels: bool, authed_user: str) -> list[dict]:
        # NOTE: Annoyingly the Slack API has no search so we have to load all channels...
        # We load public and private channels separately as when mixed, the Slack API pagination is buggy
        public_channels = self._list_channels_by_type("public_channel")
        private_channels = self._list_channels_by_type("private_channel", should_include_private_channels, authed_user)
        channels = public_channels + private_channels

        return sorted(channels, key=lambda x: x["name"])

    def list_public_channels(self) -> list[dict]:
        """Every public channel, without paging the private half.

        ``list_channels`` also pages ``users_conversations`` and masks the name of every private
        channel the caller cannot see, so a caller that matches on name pays for a listing where
        those entries all collapse onto one unusable name. Background jobs want this one: they
        have no request user to pass as ``authed_user``, so the private half can only ever be
        masked for them.
        """
        return sorted(self._list_channels_by_type("public_channel"), key=lambda x: x["name"])

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
        max_page = SLACK_CHANNELS_MAX_PAGES
        channels = []
        cursor = None

        while max_page > 0:
            max_page -= 1
            if type == "public_channel":
                res = self.client.conversations_list(
                    exclude_archived=True, types=type, limit=SLACK_CHANNELS_PAGE_SIZE, cursor=cursor
                )
            else:
                res = self.client.users_conversations(
                    exclude_archived=True,
                    types=type,
                    limit=SLACK_CHANNELS_PAGE_SIZE,
                    cursor=cursor,
                    user=authed_user,
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
        # Span only fires on cache miss (cache_for is process-local in-memory).
        # If preflight.slack_config_main is fast in production traces, this span
        # will be absent; if it appears, it tells us the DB hit was slow.
        with tracer.start_as_current_span("slack_integration.slack_config_db"):
            config = get_instance_settings(
                [
                    "SLACK_APP_CLIENT_ID",
                    "SLACK_APP_CLIENT_SECRET",
                    "SLACK_APP_SIGNING_SECRET",
                ]
            )

        return config


@frozen
class SlackRequestSignature:
    signature: str
    timestamp: str


def sign_slack_request(body: bytes, signing_secret: str) -> SlackRequestSignature:
    """Sign a body with the Slack HMAC-SHA256 scheme.

    Used by both prod (PostHog→PostHog cross-region calls that reuse the Slack signing scheme)
    and tests. The matching verifier is `validate_slack_request` below.
    """
    ts = str(int(time.time()))
    sig_basestring = f"v0:{ts}:{body.decode('utf-8')}".encode()
    signature = "v0=" + hmac.new(signing_secret.encode("utf-8"), sig_basestring, digestmod=hashlib.sha256).hexdigest()
    return SlackRequestSignature(signature=signature, timestamp=ts)


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
