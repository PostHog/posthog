from django.db.models import F
from django.db.models.signals import post_save
from django.dispatch import receiver

from posthog.models.comment import Comment

from .models import Ticket


@receiver(post_save, sender=Comment)
def increment_unread_on_team_message(sender, instance: Comment, created: bool, **kwargs):
    """
    When a team member sends a message to a conversation ticket,
    increment unread_customer_count so the widget shows a badge.
    """
    if not created:
        return

    # Only for conversations tickets
    if instance.scope != "conversations_ticket":
        return

    # Only for messages from team members (has created_by = logged in user)
    if not instance.created_by:
        return

    # Check author_type to be sure (customer messages shouldn't have created_by anyway)
    author_type = instance.item_context.get("author_type") if instance.item_context else None
    if author_type == "customer":
        return

    # Increment unread count for customer
    Ticket.objects.filter(id=instance.item_id, team=instance.team).update(
        unread_customer_count=F("unread_customer_count") + 1
    )
