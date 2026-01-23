from django.db.models import F
from django.db.models.functions import Greatest
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

import structlog

from posthog.models.comment import Comment

from .cache import invalidate_messages_cache, invalidate_tickets_cache
from .models import Ticket

logger = structlog.get_logger(__name__)


@receiver(post_save, sender=Comment)
def update_ticket_on_message(sender, instance: Comment, created: bool, **kwargs):
    """
    Update ticket stats when a message is created or soft-deleted.
    - Increment message_count, update last_message_at/text on create
    - Increment unread_customer_count for team messages
    - Handle soft-delete by decrementing count and recalculating last_message
    - Invalidate widget cache for polling endpoints
    """
    if instance.scope != "conversations_ticket":
        return

    if not instance.item_id:
        return

    if created:
        # New message: update denormalized stats
        author_type = instance.item_context.get("author_type") if isinstance(instance.item_context, dict) else None
        is_team_message = instance.created_by and author_type != "customer"

        update_fields = {
            "message_count": F("message_count") + 1,
            "last_message_at": instance.created_at,
            "last_message_text": (instance.content or "")[:500],  # Truncate to 500 chars
        }

        if is_team_message:
            update_fields["unread_customer_count"] = F("unread_customer_count") + 1

        Ticket.objects.filter(id=instance.item_id, team=instance.team).update(**update_fields)

        # Invalidate widget cache so polling sees new messages
        invalidate_messages_cache(instance.team_id, instance.item_id)
        # Also invalidate tickets list cache (last_message changed)
        try:
            ticket = Ticket.objects.filter(id=instance.item_id, team=instance.team).values("widget_session_id").first()
            if ticket:
                invalidate_tickets_cache(instance.team_id, ticket["widget_session_id"])
        except Exception:
            logger.warning(
                "conversations_ticket_cache_invalidate_failed",
                ticket_id=instance.item_id,
                exc_info=True,
            )


@receiver(pre_save, sender=Comment)
def handle_comment_soft_delete(sender, instance: Comment, **kwargs):
    """
    When a comment is soft-deleted, update the ticket's message stats.
    We use pre_save to detect the change from deleted=False to deleted=True.
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
        author_type = instance.item_context.get("author_type") if isinstance(instance.item_context, dict) else None
        is_team_message = instance.created_by and author_type != "customer"

        # Use Greatest to prevent negative counts from race conditions or data inconsistencies
        update_fields = {"message_count": Greatest(F("message_count") - 1, 0)}
        if is_team_message:
            update_fields["unread_customer_count"] = Greatest(F("unread_customer_count") - 1, 0)

        Ticket.objects.filter(id=instance.item_id, team=instance.team).update(**update_fields)

        # Recalculate last_message from remaining messages
        last_comment = (
            Comment.objects.filter(
                team=instance.team,
                scope="conversations_ticket",
                item_id=instance.item_id,
                deleted=False,
            )
            .exclude(pk=instance.pk)  # Exclude the one being deleted
            .order_by("-created_at")
            .first()
        )

        if last_comment:
            Ticket.objects.filter(id=instance.item_id, team=instance.team).update(
                last_message_at=last_comment.created_at,
                last_message_text=(last_comment.content or "")[:500],
            )
        else:
            Ticket.objects.filter(id=instance.item_id, team=instance.team).update(
                last_message_at=None,
                last_message_text=None,
            )

        # Invalidate widget cache
        invalidate_messages_cache(instance.team_id, instance.item_id)
        try:
            ticket = Ticket.objects.filter(id=instance.item_id, team=instance.team).values("widget_session_id").first()
            if ticket:
                invalidate_tickets_cache(instance.team_id, ticket["widget_session_id"])
        except Exception:
            logger.warning(
                "conversations_ticket_cache_invalidate_failed",
                ticket_id=instance.item_id,
                exc_info=True,
            )
