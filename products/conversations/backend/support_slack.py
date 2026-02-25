import hmac
import time
import hashlib
from typing import TYPE_CHECKING, cast

from django.db import transaction
from django.http import HttpRequest

from rest_framework.request import Request

from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.instance_setting import get_instance_settings
from posthog.models.integration import SlackIntegrationError
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.utils import mask_key_value

from products.conversations.backend.models import TeamConversationsSlackConfig

if TYPE_CHECKING:
    from posthog.models.team.team import Team
    from posthog.models.user import User

SUPPORT_SLACK_MAX_IMAGE_BYTES = 4 * 1024 * 1024
SUPPORT_SLACK_ALLOWED_HOST_SUFFIXES = ("slack.com", "slack-edge.com", "slack-files.com")


def get_support_slack_settings() -> dict:
    return get_instance_settings(
        [
            "SUPPORT_SLACK_SIGNING_SECRET",
        ]
    )


def get_support_slack_bot_token(team: "Team") -> str:
    config = get_or_create_team_extension(team, TeamConversationsSlackConfig)
    return str(config.slack_bot_token or "")


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


def save_supporthog_slack_token(
    *,
    team: "Team",
    user: "User",
    is_impersonated_session: bool,
    bot_token: str,
    slack_team_id: str,
) -> None:
    config = get_or_create_team_extension(team, TeamConversationsSlackConfig)
    old_token = config.slack_bot_token

    settings = team.conversations_settings or {}
    old_slack_team_id = settings.get("slack_team_id")
    settings["slack_team_id"] = slack_team_id
    settings["slack_enabled"] = True
    team.conversations_settings = settings

    with transaction.atomic():
        config.slack_bot_token = bot_token
        config.save(update_fields=["slack_bot_token"])
        team.save(update_fields=["conversations_settings"])

    log_activity(
        organization_id=team.organization_id,
        team_id=team.pk,
        user=cast("User", user),
        was_impersonated=is_impersonated_session,
        scope="Team",
        item_id=team.pk,
        activity="updated",
        detail=Detail(
            name=str(team.name),
            changes=[
                Change(
                    type="Team",
                    action="created" if old_token is None else "changed",
                    field="support_slack_bot_token",
                    before=mask_key_value(old_token) if old_token else None,
                    after=mask_key_value(bot_token),
                ),
                Change(
                    type="Team",
                    action="created" if old_slack_team_id is None else "changed",
                    field="conversations_settings.slack_team_id",
                    before=old_slack_team_id,
                    after=slack_team_id,
                ),
            ],
        ),
    )


def clear_supporthog_slack_token(
    *,
    team: "Team",
    user: "User",
    is_impersonated_session: bool,
) -> None:
    config = get_or_create_team_extension(team, TeamConversationsSlackConfig)
    old_token = config.slack_bot_token
    if old_token is None:
        return

    settings = team.conversations_settings or {}
    settings["slack_enabled"] = False
    team.conversations_settings = settings

    with transaction.atomic():
        config.slack_bot_token = None
        config.save(update_fields=["slack_bot_token"])
        team.save(update_fields=["conversations_settings"])

    log_activity(
        organization_id=team.organization_id,
        team_id=team.pk,
        user=cast("User", user),
        was_impersonated=is_impersonated_session,
        scope="Team",
        item_id=team.pk,
        activity="updated",
        detail=Detail(
            name=str(team.name),
            changes=[
                Change(
                    type="Team",
                    action="deleted",
                    field="support_slack_bot_token",
                    before=mask_key_value(old_token),
                    after=None,
                ),
            ],
        ),
    )
