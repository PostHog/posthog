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
    TargetType,
    create_notification,
)

logger = structlog.get_logger(__name__)

SLACK_POSTED_KEY = "slack_posted"
SLACK_TS_KEY = "slack_ts"
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


def deliver_resolved(
    pattern: TicketPattern, resolution: Literal["confirmed", "dismissed", "auto"], user: User | None = None
) -> None:
    capture_pattern_resolved(pattern, resolution)
    _post_decision_to_slack(pattern, resolution, user)


def annotation_on_confirm_enabled(team: Team) -> bool:
    return (team.conversations_settings or {}).get("pattern_annotate_on_confirm", True) is not False


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
            # No source_type: the menu turns one into a path from source_id, and a ticket source
            # would send the click to a ticket that does not exist. A pattern is not a ticket.
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
        response = get_slack_client(team).chat_postMessage(channel=channel, text=text, unfurl_links=False)
    except Exception:
        logger.warning("ticket_patterns: slack post failed", team_id=team.id, pattern_id=str(pattern.id))
        return
    # The message id lets the decision land as a thread reply under the alert, so the channel
    # reads as one story per pattern rather than two unrelated posts.
    ts = response.get("ts") if hasattr(response, "get") else None
    TicketPattern.objects.for_team(team.id).filter(pk=pattern.pk).update(
        evidence={**pattern.evidence, SLACK_POSTED_KEY: True, **({SLACK_TS_KEY: ts} if isinstance(ts, str) else {})}
    )


_DECISION_TEXT = {
    "confirmed": "Confirmed as an incident",
    "dismissed": "Marked not an issue",
    "auto": "Quiet for two windows, closed automatically",
}


def _post_decision_to_slack(pattern: TicketPattern, resolution: str, user: User | None) -> None:
    """Tell the channel how the alert ended, in the alert's own thread when there is one.

    Only an alert that was posted gets a follow-up. A team with Slack configured after the pattern
    opened has nothing in the channel to update, and a fresh top-level post for a decision would
    read as a new alert.
    """
    team = pattern.team
    channel = (team.conversations_settings or {}).get("slack_alert_channel_id")
    ts = pattern.evidence.get(SLACK_TS_KEY)
    if not isinstance(channel, str) or not channel or not ts or not get_support_slack_bot_token(team):
        return
    label = _DECISION_TEXT.get(resolution)
    if not label:
        return
    who = f" by {user.first_name or user.email}" if user else ""
    text = f"{label}{who}: {_headline(pattern)}."
    try:
        get_slack_client(team).chat_postMessage(channel=channel, text=text, thread_ts=ts, unfurl_links=False)
    except Exception:
        logger.warning("ticket_patterns: slack decision post failed", team_id=team.id, pattern_id=str(pattern.id))


def annotate_confirmation(pattern: TicketPattern, user: User) -> None:
    """Mark the incident on every insight chart, at the moment the first ticket arrived."""
    create_project_annotation(
        pattern.team_id,
        user.id,
        content=f"Support pattern confirmed: {pattern.title}",
        date_marker=pattern.first_ticket_at or pattern.opened_at,
    )
