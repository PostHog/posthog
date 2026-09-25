from typing import TYPE_CHECKING
from uuid import uuid4

from django.db import transaction

from posthog.models import Team, User
from posthog.models.comment import Comment

from products.conversations.backend.models import (
    Channel,
    EmailChannel,
    EmailChannelConnectionStatus,
    EmailChannelKind,
    Status,
    Ticket,
)

if TYPE_CHECKING:
    from products.conversations.backend.facade.types import DesktopFeedbackContext


class FeedbackTicketUnavailable(Exception):
    pass


def create_desktop_feedback_ticket(
    *,
    team_id: int,
    user_id: int,
    content: str,
    context: "DesktopFeedbackContext",
    image_urls: list[str],
    app_logs: str | None,
) -> str:
    team = Team.objects.get(pk=team_id)
    user = User.objects.get(pk=user_id)
    if not team.conversations_enabled or not (team.conversations_settings or {}).get("email_enabled"):
        raise FeedbackTicketUnavailable("Feedback email replies are not enabled")
    if not user.email or not user.is_email_verified:
        raise FeedbackTicketUnavailable("A verified account email is required for feedback replies")
    email_channel = EmailChannel.objects.filter(
        team=team,
        kind=EmailChannelKind.SUPPORT,
        connection_status=EmailChannelConnectionStatus.ACTIVE,
        is_default=True,
        domain_verified=True,
    ).first()
    if email_channel is None:
        raise FeedbackTicketUnavailable("Feedback email replies are not configured")

    session_context = {
        "feedback_source": context.feedback_source,
        "feedback_view": context.feedback_view,
        "source_product": "desktop",
    }
    optional_context = {
        "feedback_type": context.feedback_type,
        "feedback_task_id": context.feedback_task_id,
        "feedback_folder_id": context.feedback_folder_id,
        "app_version": context.app_version,
        "$session_id": context.session_id,
    }
    session_context.update({key: value for key, value in optional_context.items() if value})

    with transaction.atomic():
        ticket = Ticket.objects.create_with_number(
            team=team,
            channel_source=Channel.EMAIL,
            distinct_id=str(user.uuid),
            widget_session_id=str(uuid4()),
            status=Status.NEW,
            email_config=email_channel,
            email_from=user.email,
            email_subject="PostHog Desktop feedback",
            anonymous_traits={"email": user.email, "name": user.get_full_name()},
            identity_verified=True,
            session_id=context.session_id,
            session_context=session_context,
            unread_team_count=1,
        )
        Comment.objects.create(
            team=team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content=content,
            rich_content={
                "type": "doc",
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": content}]},
                    *[{"type": "image", "attrs": {"src": url}} for url in image_urls],
                ],
            },
            item_context={"author_type": "customer", "distinct_id": str(user.uuid), "is_private": False},
        )
        if app_logs:
            Comment.objects.create(
                team=team,
                scope="conversations_ticket",
                item_id=str(ticket.id),
                content="Desktop app logs\n\n" + app_logs,
                item_context={"author_type": "customer", "is_private": True},
            )
    return str(ticket.id)
