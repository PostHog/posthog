import hmac
import time
import hashlib
from typing import TYPE_CHECKING

from django.http import HttpRequest

from rest_framework.request import Request

from posthog.models.instance_setting import get_instance_settings
from posthog.models.integration import SlackIntegrationError

if TYPE_CHECKING:
    from posthog.models.team.team import Team

SUPPORT_SLACK_MAX_IMAGE_BYTES = 4 * 1024 * 1024
SUPPORT_SLACK_ALLOWED_HOST_SUFFIXES = ("slack.com", "slack-edge.com", "slack-files.com")


def get_support_slack_settings() -> dict:
    return get_instance_settings(
        [
            "SUPPORT_SLACK_SIGNING_SECRET",
        ]
    )


def get_support_slack_bot_token(team: "Team") -> str:
    team_settings = team.conversations_settings or {}
    team_token = team_settings.get("slack_bot_token")
    return str(team_token or "")


def validate_support_request(request: HttpRequest | Request) -> None:
    """
    Validate Support Slack bot requests.
    Based on https://api.slack.com/authentication/verifying-requests-from-slack
    """
    support_settings = get_support_slack_settings()
    signing_secret = str(support_settings.get("SUPPORT_SLACK_SIGNING_SECRET") or "")
    slack_signature = request.headers.get("X-SLACK-SIGNATURE")
    slack_time = request.headers.get("X-SLACK-REQUEST-TIMESTAMP")

    if not signing_secret or not slack_signature or not slack_time:
        raise SlackIntegrationError("Invalid")

    try:
        timestamp_diff = time.time() - float(slack_time)
        # Reject requests older than 5 minutes OR from the future (with 60s tolerance for clock skew)
        if timestamp_diff > 300 or timestamp_diff < -60:
            raise SlackIntegrationError("Expired")
    except ValueError:
        raise SlackIntegrationError("Invalid")

    sig_basestring = f"v0:{slack_time}:{request.body.decode('utf-8')}"
    expected_signature = (
        "v0="
        + hmac.new(
            signing_secret.encode("utf-8"),
            sig_basestring.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()
    )

    if not hmac.compare_digest(expected_signature, slack_signature):
        raise SlackIntegrationError("Invalid")
