"""What happens once a pattern opens or a person decides on it.

Every side effect here runs after the row is committed and is safe to call twice: the notification
carries an idempotency key, the Slack post checks the pattern's own record of having been posted,
and the events are plain captures. Detection never waits on any of it.
"""

from __future__ import annotations

from typing import Literal

import structlog

from posthog.models import Team, User
from posthog.settings import SITE_URL

from products.annotations.backend.facade.api import create_project_annotation
from products.conversations.backend.events import capture_pattern_detected, capture_pattern_resolved
from products.conversations.backend.models import TicketPattern
from products.conversations.backend.slack import get_slack_client
from products.conversations.backend.support_slack import get_support_slack_bot_token
from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    Priority,
    SourceType,
    TargetType,
    create_notification,
)

logger = structlog.get_logger(__name__)

SLACK_POSTED_KEY = "slack_posted"
NOTIFICATION_TITLE_LIMIT = 100


def patterns_url(team: Team) -> str:
    return f"/project/{team.id}/support/patterns"


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _headline(pattern: TicketPattern) -> str:
    return f"{_plural(pattern.ticket_count, 'ticket')} from {_plural(pattern.requester_count, 'customer')} about {pattern.topic}"


def deliver_opened(pattern: TicketPattern) -> None:
    """Fire the one-time side effects for a freshly opened pattern."""
    capture_pattern_detected(pattern)
    _notify(pattern)
    _post_to_slack(pattern)


def deliver_resolved(pattern: TicketPattern, resolution: Literal["confirmed", "dismissed", "auto"]) -> None:
    capture_pattern_resolved(pattern, resolution)


def _notify(pattern: TicketPattern) -> None:
    team = pattern.team
    settings = team.conversations_settings or {}
    role_id = settings.get("pattern_notify_role_id")
    # A team target resolves to the whole organization, which is too wide for a support alert, so
    # a team that has not named a role gets the in-product surfaces and Slack only.
    if not role_id:
        return
    create_notification(
        NotificationData(
            team_id=team.id,
            notification_type=NotificationType.SUPPORT_PATTERN_DETECTED,
            priority=Priority.NORMAL,
            title=f"Possible emerging issue: {pattern.topic}"[:NOTIFICATION_TITLE_LIMIT],
            body=_headline(pattern),
            target_type=TargetType.ROLE,
            target_id=str(role_id),
            resource_type="ticket",
            resource_id=str(pattern.id),
            source_type=SourceType.TICKET,
            source_id=str(pattern.id),
            source_url=patterns_url(team),
            idempotency_key=f"conversations-pattern:{pattern.id}",
        )
    )


def _post_to_slack(pattern: TicketPattern) -> None:
    team = pattern.team
    settings = team.conversations_settings or {}
    channel = settings.get("slack_alert_channel_id")
    if not isinstance(channel, str) or not channel or not get_support_slack_bot_token(team):
        return
    if pattern.evidence.get(SLACK_POSTED_KEY):
        return
    text = f"Possible emerging issue in support: {_headline(pattern)}.\nReview it at {SITE_URL}{patterns_url(team)}"
    try:
        get_slack_client(team).chat_postMessage(channel=channel, text=text, unfurl_links=False)
    except Exception:
        logger.warning("ticket_patterns: slack post failed", team_id=team.id, pattern_id=str(pattern.id))
        return
    TicketPattern.objects.for_team(team.id).filter(pk=pattern.pk).update(
        evidence={**pattern.evidence, SLACK_POSTED_KEY: True}
    )


def annotate_confirmation(pattern: TicketPattern, user: User) -> None:
    """Mark the incident on every insight chart, at the moment the first ticket arrived."""
    create_project_annotation(
        pattern.team_id,
        user.id,
        content=f"Support pattern confirmed: {pattern.title}",
        date_marker=pattern.first_ticket_at or pattern.opened_at,
    )
