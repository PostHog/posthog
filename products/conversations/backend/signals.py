from typing import Any, cast

from django.db import transaction
from django.db.models import F, Q
from django.db.models.functions import Greatest
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models.comment import Comment

from .events import capture_message_received, capture_message_sent
from .models import Ticket
from .models.constants import Channel
from .tasks import post_reply_to_slack

logger = structlog.get_logger(__name__)


def _is_private_message(item_context: dict | None) -> bool:
    """Check if a message is marked as private."""
    if not isinstance(item_context, dict):
        return False
    return item_context.get("is_private", False) is True


def _get_comment_created_by_id(comment: Comment) -> int | None:
    created_by_id = getattr(comment, "created_by_id", None)
    return created_by_id if isinstance(created_by_id, int) else None


@receiver(post_save, sender=Comment)
def update_ticket_on_message(sender, instance: Comment, created: bool, **kwargs):
    """
    Update ticket stats when a new message is created.
    - Increment message_count, update last_message_at/text (only for non-private messages)
    - Increment unread_customer_count for team messages (only for non-private messages)

    Private messages are excluded from denormalized stats to prevent leaking
    to widget via last_message_text and to keep message_count accurate for customers.

    Uses transaction.on_commit() to defer work and avoid blocking the request.
    Cache invalidation not needed - short TTLs handle staleness.
    """
    if instance.scope != "conversations_ticket":
        return

    if not instance.item_id:
        return

    if not created:
        return

    # Capture values for closure (avoid referencing instance in deferred callback)
    team_id = instance.team_id
    item_id = instance.item_id
    comment_id = str(instance.id)
    created_at = instance.created_at
    content = instance.content
    item_context = instance.item_context
    created_by_id = _get_comment_created_by_id(instance)

    def do_update():
        # Private messages don't update denormalized stats (to avoid leaking to widget)
        if _is_private_message(item_context):
            return

        # New message: update denormalized stats
        author_type = item_context.get("author_type") if isinstance(item_context, dict) else None
        is_team_message = created_by_id and author_type != "customer"

        update_fields = {
            "message_count": F("message_count") + 1,
            "last_message_at": created_at,
            "last_message_text": (content or "")[:500],  # Truncate to 500 chars
        }

        if is_team_message:
            update_fields["unread_customer_count"] = F("unread_customer_count") + 1

        Ticket.objects.filter(id=item_id, team_id=team_id).update(**update_fields)

        # Emit analytics events for workflow triggers
        try:
            ticket = Ticket.objects.select_related("team").get(id=item_id, team_id=team_id)
            if is_team_message:
                capture_message_sent(ticket, comment_id, content or "", created_by_id)
            else:
                capture_message_received(ticket, comment_id, content or "")
        except Ticket.DoesNotExist:
            pass
        except Exception as e:
            # Don't let analytics failures break message creation
            capture_exception(e, {"ticket_id": item_id})

    transaction.on_commit(do_update)


@receiver(pre_save, sender=Comment)
def handle_comment_soft_delete(sender, instance: Comment, **kwargs):
    """
    When a comment is soft-deleted, update the ticket's message stats.
    We use pre_save to detect the change from deleted=False to deleted=True.

    Private messages don't affect denormalized stats, so soft-deleting them
    only requires recalculating last_message if it happens to match.

    Uses transaction.on_commit() to defer work and avoid blocking the request.
    Cache invalidation not needed - short TTLs handle staleness.
    """
    if instance.scope != "conversations_ticket":
        return

    if not instance.item_id:
        return

    if not instance.pk:
        return  # New instance, not a soft-delete

    try:
        old_instance = Comment.objects.get(pk=instance.pk)
    except Comment.DoesNotExist:
        return

    # Detect soft-delete: was not deleted, now is deleted
    if not old_instance.deleted and instance.deleted:
        # Capture values for closure (avoid referencing instance in deferred callback)
        team_id = instance.team_id
        item_id = instance.item_id
        comment_pk = instance.pk
        item_context = instance.item_context
        created_by_id = _get_comment_created_by_id(instance)

        def do_soft_delete_update():
            is_private = _is_private_message(item_context)

            # Only decrement counts if this wasn't a private message
            # (private messages weren't counted in the first place)
            if not is_private:
                author_type = item_context.get("author_type") if isinstance(item_context, dict) else None
                is_team_message = created_by_id and author_type != "customer"

                # Use Greatest to prevent negative counts from race conditions or data inconsistencies
                update_fields = {"message_count": Greatest(F("message_count") - 1, 0)}
                if is_team_message:
                    update_fields["unread_customer_count"] = Greatest(F("unread_customer_count") - 1, 0)

                Ticket.objects.filter(id=item_id, team_id=team_id).update(**update_fields)

            # Recalculate last_message from remaining non-private messages
            # Use exclude + isnull to match _is_private_message() identity check:
            # - Exclude only exact boolean True
            # - Include everything else (False, None, missing key, weird values)
            # The isnull handles SQL NULL semantics where ~Q alone would exclude missing keys
            last_comment = (
                Comment.objects.filter(
                    team_id=team_id,
                    scope="conversations_ticket",
                    item_id=item_id,
                    deleted=False,
                )
                .filter(~Q(item_context__is_private=True) | Q(item_context__is_private__isnull=True))
                .exclude(pk=comment_pk)  # Exclude the one being deleted
                .order_by("-created_at")
                .first()
            )

            if last_comment:
                Ticket.objects.filter(id=item_id, team_id=team_id).update(
                    last_message_at=last_comment.created_at,
                    last_message_text=(last_comment.content or "")[:500],
                )
            else:
                Ticket.objects.filter(id=item_id, team_id=team_id).update(
                    last_message_at=None,
                    last_message_text=None,
                )

        transaction.on_commit(do_soft_delete_update)


@receiver(post_save, sender=Comment)
def post_slack_reply_on_team_message(sender, instance: Comment, created: bool, **kwargs):
    """
    When a team member replies to a Slack-sourced ticket, post the reply
    back to the Slack thread via a Celery task.

    Only triggers for:
    - Newly created comments (not edits)
    - Non-private messages
    - Messages with a created_by (team member, not customer)
    - Tickets with channel_source="slack" and valid slack thread info
    """
    if instance.scope != "conversations_ticket":
        return

    if not instance.item_id or not created:
        return

    item_context = instance.item_context
    if _is_private_message(item_context):
        return

    # Only team messages (has created_by, not customer-authored)
    created_by_id = _get_comment_created_by_id(instance)
    if not created_by_id:
        return

    author_type = item_context.get("author_type") if isinstance(item_context, dict) else None
    if author_type == "customer":
        return

    # Capture values for the deferred callback
    team_id = instance.team_id
    item_id = instance.item_id
    content = instance.content or ""
    rich_content = instance.rich_content
    created_by = instance.created_by

    def do_post_to_slack():
        try:
            ticket = Ticket.objects.filter(
                id=item_id,
                team_id=team_id,
                channel_source=Channel.SLACK,
            ).first()

            if not ticket or not ticket.slack_channel_id or not ticket.slack_thread_ts:
                return

            team = ticket.team
            settings_dict = team.conversations_settings or {}
            if not settings_dict.get("slack_enabled"):
                return

            author_name = ""
            if created_by:
                author_name = f"{created_by.first_name} {created_by.last_name}".strip() or created_by.email

            cast(Any, post_reply_to_slack).delay(
                ticket_id=str(ticket.id),
                team_id=team_id,
                content=content,
                rich_content=rich_content,
                author_name=author_name,
                slack_channel_id=ticket.slack_channel_id,
                slack_thread_ts=ticket.slack_thread_ts,
            )
        except Exception:
            logger.exception("slack_reply_signal_failed", item_id=item_id)

    transaction.on_commit(do_post_to_slack)
