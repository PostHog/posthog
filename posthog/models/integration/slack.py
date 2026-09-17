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

import structlog
from opentelemetry import trace
from prometheus_client import Counter
from rest_framework.request import Request
from slack_sdk.errors import SlackApiError

from posthog.cache_utils import cache_for
from posthog.egress.slack.client import SlackWebClient as WebClient
from posthog.models.instance_setting import get_instance_settings

from . import model

tracer = trace.get_tracer(__name__)
logger = structlog.get_logger(__name__)

slack_listing_truncated_counter = Counter(
    "slack_listing_truncated",
    "Slack listings that hit a safety cap and dropped the remainder, by listing kind",
    labelnames=["kind"],
)


PRIVATE_CHANNEL_WITHOUT_ACCESS = "PRIVATE_CHANNEL_WITHOUT_ACCESS"


class SlackIntegrationError(Exception):
    pass


class SlackMembershipUnknown(SlackIntegrationError):
    """A membership check ran out of budget or hit a rate limit before it could answer.

    Distinct from "not a member": the caller must not turn this into an empty result, because a
    channel that resolves to nothing reads to the user as "the app is not in that channel".
    """


def _is_rate_limited(error: SlackApiError) -> bool:
    response = getattr(error, "response", None)
    if response is None:
        return False
    return bool(response.get("error") == "ratelimited")


SLACK_INTEGRATION_KINDS: tuple[str, ...] = ("slack",)

SLACK_CHANNELS_PAGE_SIZE = 1000

# Slack returns fewer items than the requested limit whenever it likes, so a page count is not an
# item count. A listing stops on whichever cap it reaches first. On short pages that is the request
# count, well short of the item cap, and the request count stays low because the listing runs
# inside a request a person waits on, where a few hundred sequential calls to a rate-limited Slack
# endpoint fail on latency before they finish. _record_truncation logs the items collected and the
# requests made, so the log says which cap stopped the listing.
SLACK_LISTING_MAX_ITEMS = 50000

SLACK_LISTING_MAX_REQUESTS = 100

# conversations.members returns at most 1000 ids per call, whatever limit is asked for.
SLACK_MEMBERS_PAGE_SIZE = 1000

# A membership check runs inside a request a person is waiting on, so it gets a much tighter budget
# than a listing. Ten calls covers every channel short of the largest Slack allows.
SLACK_MEMBERS_MAX_REQUESTS = 10


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

    def _is_channel_member(self, channel_id: str, authed_user: str | None) -> bool:
        """Slack caps conversations.members at 1000 ids per call whatever limit is asked for, so a
        member past the first page needs the cursor followed rather than a bigger limit."""
        cursor = None
        requests = 0
        seen = 0

        while requests < SLACK_MEMBERS_MAX_REQUESTS:
            requests += 1
            try:
                res = self.client.conversations_members(
                    channel=channel_id, limit=SLACK_MEMBERS_PAGE_SIZE, cursor=cursor
                )
            except SlackApiError as e:
                if not _is_rate_limited(e):
                    raise
                self._record_truncation("channel_members_rate_limited", collected=seen, requests=requests)
                raise SlackMembershipUnknown() from e
            members = res["members"]
            seen += len(members)
            if authed_user in members:
                return True
            cursor = (res.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                return False

        self._record_truncation("channel_members", collected=seen, requests=requests)
        raise SlackMembershipUnknown()

    def get_channel_by_id(
        self, channel_id: str, should_include_private_channels: bool = False, authed_user: str | None = None
    ) -> dict | None:
        try:
            response = self.client.conversations_info(channel=channel_id, include_num_members=True)
            channel = response["channel"]

            try:
                is_member = self._is_channel_member(channel_id, authed_user)
            except SlackMembershipUnknown:
                # The scan could not finish, so membership is unproven rather than disproven. Return
                # the channel: the picker shows it and flags that the app may not be in it, which is
                # recoverable, while hiding it is the silent empty result this change exists to stop.
                is_member = True
            if not is_member:
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

    def list_users(self) -> list[dict]:
        """Human workspace members the bot can DM, as raw Slack member payloads."""
        users: list[dict] = []
        cursor = None
        requests = 0
        fetched = 0

        while requests < SLACK_LISTING_MAX_REQUESTS:
            requests += 1
            try:
                res = self.client.users_list(limit=SLACK_CHANNELS_PAGE_SIZE, cursor=cursor)
            except SlackApiError as e:
                if not _is_rate_limited(e):
                    raise
                self._record_truncation("users_rate_limited", collected=fetched, requests=requests)
                return users
            fetched += len(res["members"])
            users.extend(
                member
                for member in res["members"]
                if self._belongs_to_workspace(member) and self._is_dmable_user(member)
            )
            cursor = (res.get("response_metadata") or {}).get("next_cursor")
            # Cap on members fetched, not members kept, so a workspace full of bots and guests
            # cannot page forever.
            if not cursor or fetched >= SLACK_LISTING_MAX_ITEMS:
                break

        if cursor:
            self._record_truncation("users", collected=fetched, requests=requests)

        return users

    def get_user_by_id(self, user_id: str) -> dict | None:
        try:
            response = self.client.users_info(user=user_id)
            member = response["user"]
            if not self._belongs_to_workspace(member):
                return None
            return member if self._is_dmable_user(member) else None
        except SlackApiError as e:
            # user_not_visible is terminal too: the token can't see the member, so retrying the
            # same lookup can never succeed.
            if e.response["error"] in ("user_not_found", "user_not_visible"):
                return None
            raise

    def _belongs_to_workspace(self, member: dict) -> bool:
        # Slack also surfaces Connect externals the bot shares a channel with (users.info always,
        # users.list depending on workspace shape), so reject members whose home workspace isn't
        # this integration's: internal scout/DM output must never be routable outside the
        # connected workspace. Enterprise Grid members may carry another primary team_id while
        # still belonging to this workspace via enterprise_user.teams.
        member_team_id = member.get("team_id")
        enterprise_teams = (member.get("enterprise_user") or {}).get("teams") or []
        return not member.get("is_stranger") and (
            member_team_id is None
            or member_team_id == self.integration.integration_id
            or self.integration.integration_id in enterprise_teams
        )

    @staticmethod
    def _is_dmable_user(member: dict) -> bool:
        # Guests (single/multi-channel, often external people) are excluded like bots: DM surfaces
        # deliver internal content, matching the slack_app onboarding and unfurl eligibility rules.
        return (
            not member.get("deleted")
            and not member.get("is_bot")
            and not member.get("is_restricted")
            and not member.get("is_ultra_restricted")
            and member.get("id") != "USLACKBOT"
        )

    def _list_channels_by_type(
        self,
        type: Literal["public_channel", "private_channel"],
        should_include_private_channels: bool = False,
        authed_user: str | None = None,
    ) -> list[dict]:
        channels: list[dict] = []
        cursor = None
        requests = 0

        while requests < SLACK_LISTING_MAX_REQUESTS:
            requests += 1
            try:
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
            except SlackApiError as e:
                # These endpoints are rate limited per workspace and the client does not retry, so a
                # long walk can run into a 429 part way. Keep the pages already collected: a short
                # list is what the caller got before this change, while raising here would replace it
                # with no channels at all, and nothing is cached to fall back on.
                if not _is_rate_limited(e):
                    raise
                self._record_truncation(f"channels_{type}_rate_limited", collected=len(channels), requests=requests)
                return channels

            if type != "public_channel":
                for channel in res["channels"]:
                    if channel["is_private"] and not should_include_private_channels:
                        channel["name"] = PRIVATE_CHANNEL_WITHOUT_ACCESS
                        channel["is_private_without_access"] = True

            channels.extend(res["channels"])
            cursor = (res.get("response_metadata") or {}).get("next_cursor")
            if not cursor or len(channels) >= SLACK_LISTING_MAX_ITEMS:
                break

        if cursor:
            self._record_truncation(f"channels_{type}", collected=len(channels), requests=requests)

        return channels

    def _record_truncation(self, kind: str, *, collected: int, requests: int) -> None:
        """A cap stopped a listing with more to fetch, so the caller is holding a partial list.

        Nothing downstream can tell a partial list from a complete one, and a channel missing from
        it reads to the user as "the app is not in that channel". Leave a trail so the next report
        is answerable from our own data.
        """
        slack_listing_truncated_counter.labels(kind=kind).inc()
        logger.warning(
            "slack_listing_truncated",
            kind=kind,
            integration_id=self.integration.id,
            team_id=self.integration.team_id,
            collected=collected,
            requests=requests,
        )

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
