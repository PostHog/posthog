from django.db import transaction
from django.db.models import F
from django.db.models.functions import Greatest
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

import structlog

from posthog.models.comment import Comment

from .models import Ticket

logger = structlog.get_logger(__name__)


@receiver(post_save, sender=Comment)
def update_ticket_on_message(sender, instance: Comment, created: bool, **kwargs):
    """
    Update ticket stats when a new message is created.
    - Increment message_count, update last_message_at/text
    - Increment unread_customer_count for team messages

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
    created_at = instance.created_at
    content = instance.content
    item_context = instance.item_context
    created_by_id = instance.created_by_id

    def do_update():
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

    transaction.on_commit(do_update)


@receiver(pre_save, sender=Comment)
def handle_comment_soft_delete(sender, instance: Comment, **kwargs):
    """
    When a comment is soft-deleted, update the ticket's message stats.
    We use pre_save to detect the change from deleted=False to deleted=True.

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
        created_by_id = instance.created_by_id

        def do_soft_delete_update():
            author_type = item_context.get("author_type") if isinstance(item_context, dict) else None
            is_team_message = created_by_id and author_type != "customer"

            # Use Greatest to prevent negative counts from race conditions or data inconsistencies
            update_fields = {"message_count": Greatest(F("message_count") - 1, 0)}
            if is_team_message:
                update_fields["unread_customer_count"] = Greatest(F("unread_customer_count") - 1, 0)

            Ticket.objects.filter(id=item_id, team_id=team_id).update(**update_fields)

            # Recalculate last_message from remaining messages
            last_comment = (
                Comment.objects.filter(
                    team_id=team_id,
                    scope="conversations_ticket",
                    item_id=item_id,
                    deleted=False,
                )
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
