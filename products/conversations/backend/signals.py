from email.utils import make_msgid
from typing import Any, cast

from django.db import transaction
from django.db.models import F, Q
from django.db.models.functions import Greatest
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

import structlog

from posthog.event_usage import report_team_action, report_user_action
from posthog.exceptions_capture import capture_exception
from posthog.models import User
from posthog.models.comment import Comment
from posthog.models.instance_setting import get_instance_setting

from .cache import invalidate_messages_cache, invalidate_tickets_cache
from .events import capture_message_received, capture_message_sent, capture_ticket_created
from .models import EmailOutboxMessage, Ticket
from .models.constants import Channel
from .tasks import (
    post_reply_to_github,
    post_reply_to_slack,
    post_reply_to_teams,
    post_reply_to_teams_via_graph,
    send_email_reply,
)
from .teams import parse_teams_root_message_id, resolve_shared_channel_team_id

logger = structlog.get_logger(__name__)


def _is_private_message(item_context: dict | None) -> bool:
    """Check if a message is marked as private."""
    if not isinstance(item_context, dict):
        return False
    return item_context.get("is_private", False) is True


def _get_comment_created_by_id(comment: Comment) -> int | None:
    created_by_id = getattr(comment, "created_by_id", None)
    return created_by_id if isinstance(created_by_id, int) else None


def _is_outbound_reply(item_context: dict | None, created_by_id: int | None) -> bool:
    """True for messages that should be delivered to the customer's channel.

    This includes human team replies (has created_by, non-customer, non-private) and
    public AI replies (author_type == "AI" with is_private == False).
    """
    if not isinstance(item_context, dict):
        return False
    if _is_private_message(item_context):
        return False
    author_type = item_context.get("author_type")
    if created_by_id and author_type != "customer":
        return True
    if author_type == "AI":
        return True
    return False


AI_BOT_DISPLAY_NAME = "AI assistant"


@receiver(post_save, sender=Ticket)
def emit_ticket_created_event(sender, instance: Ticket, created: bool, **kwargs):
    """
    Fire `$conversation_ticket_created` for every newly created ticket, regardless of
    channel (widget, email, slack, teams, ...). Workflow triggers depend on this event
    being emitted uniformly for all sources.

    Deferred via `transaction.on_commit` so we don't emit phantom events for tickets
    rolled back by the email duplicate-race `IntegrityError` in `email_events.py` (or
    any future caller that wraps creation in `transaction.atomic`).

    Note: `Ticket.objects.bulk_create` does NOT trigger this signal. All current callers
    use `Ticket.objects.create_with_number`; keep it that way or fire the event
    explicitly.
    """
    if not created:
        return

    # All callers use `create_with_number(team=team_obj, ...)`, so `instance.team` is
    # already populated and `capture_ticket_created` won't trigger an extra FK lookup.
    def do_emit():
        try:
            capture_ticket_created(instance)
        except Exception as e:
            capture_exception(e, {"ticket_id": str(instance.id)})

    transaction.on_commit(do_emit)


@receiver(post_save, sender=Comment)
def update_ticket_on_message(sender, instance: Comment, created: bool, **kwargs):
    """
    Update ticket stats when a new message is created.
    - Increment message_count, update last_message_at/text (only for non-private messages)
    - Increment unread_customer_count for team messages (only for non-private messages)

    Private messages are excluded from denormalized stats to prevent leaking
    to widget via last_message_text and to keep message_count accurate for customers.

    Uses transaction.on_commit() to defer work and avoid blocking the request.
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
        is_team_message = (created_by_id and author_type != "customer") or (
            author_type == "AI" and not _is_private_message(item_context)
        )

        update_fields = {
            "message_count": F("message_count") + 1,
            "last_message_at": created_at,
            "last_message_text": (content or "")[:500],  # Truncate to 500 chars
            "updated_at": created_at,
        }

        if is_team_message:
            update_fields["unread_customer_count"] = F("unread_customer_count") + 1

        Ticket.objects.filter(id=item_id, team_id=team_id).update(**update_fields)

        # Emit analytics events and invalidate cache
        try:
            ticket = Ticket.objects.select_related("team").get(id=item_id, team_id=team_id)
            # Invalidate widget caches so list and messages reflect the new message
            if ticket.widget_session_id:
                invalidate_tickets_cache(team_id, ticket.widget_session_id)
            invalidate_messages_cache(team_id, item_id)

            # Customer-facing analytics (to customer's project)
            if is_team_message:
                author = User.objects.filter(id=created_by_id).first() if created_by_id else None
                capture_message_sent(ticket, comment_id, content or "", author=author)
            else:
                author = None
                capture_message_received(ticket, comment_id, content or "")

            # Internal analytics (PostHog tracking its own usage)
            props = {"channel_source": ticket.channel_source}
            if is_team_message:
                if author:
                    report_user_action(author, "support message sent", props, team=ticket.team)
                else:
                    report_team_action(ticket.team, "support message sent", props)
            else:
                report_team_action(ticket.team, "support message received", props)
            # Send email notification on first customer message (i.e. new ticket)
            if ticket.message_count == 1 and not is_team_message:
                try:
                    conversations_settings = ticket.team.conversations_settings or {}
                    if conversations_settings.get("notification_recipients"):
                        # posthog.tasks.__init__ eagerly imports every task module; this signal
                        # module is wired at django.setup(), so import the task lazily.
                        from posthog.tasks.email import send_new_ticket_notification  # noqa: PLC0415

                        send_new_ticket_notification.delay(
                            ticket_id=item_id,
                            team_id=team_id,
                            first_message_content=(content or "")[:500],
                        )
                except Exception as e:
                    capture_exception(e, {"ticket_id": item_id})
        except Ticket.DoesNotExist:
            pass
        except Exception as e:
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
    When a team member or AI bot replies to a Slack-sourced ticket, post the reply
    back to the Slack thread via a Celery task.

    Only triggers for:
    - Newly created comments (not edits)
    - Outbound replies (human team or public AI)
    - Tickets with channel_source="slack" and valid slack thread info
    """
    if instance.scope != "conversations_ticket":
        return

    if not instance.item_id or not created:
        return

    item_context = instance.item_context
    created_by_id = _get_comment_created_by_id(instance)

    if not _is_outbound_reply(item_context, created_by_id):
        return

    # Don't echo messages that originated from Slack back to Slack
    if isinstance(item_context, dict) and item_context.get("from_slack"):
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
            author_email = ""
            if created_by:
                author_name = f"{created_by.first_name} {created_by.last_name}".strip() or created_by.email
                author_email = created_by.email
            else:
                author_name = settings_dict.get("slack_bot_display_name") or AI_BOT_DISPLAY_NAME

            cast(Any, post_reply_to_slack).delay(
                ticket_id=str(ticket.id),
                team_id=team_id,
                content=content,
                rich_content=rich_content,
                author_name=author_name,
                author_email=author_email,
                slack_channel_id=ticket.slack_channel_id,
                slack_thread_ts=ticket.slack_thread_ts,
            )
        except Exception:
            logger.exception("slack_reply_signal_failed", item_id=item_id)

    transaction.on_commit(do_post_to_slack)


@receiver(post_save, sender=Comment)
def send_email_reply_on_team_message(sender, instance: Comment, created: bool, **kwargs):
    """
    When a team member or AI bot replies to an email-sourced ticket, send the reply
    back to the customer via email through a Celery task.

    Only triggers for:
    - Newly created comments (not edits)
    - Outbound replies (human team or public AI)
    - Tickets with channel_source="email"
    """
    if instance.scope != "conversations_ticket":
        return

    if not instance.item_id or not created:
        return

    item_context = instance.item_context
    created_by_id = _get_comment_created_by_id(instance)

    if not _is_outbound_reply(item_context, created_by_id):
        return

    # Don't echo messages that originated from email back via email
    if isinstance(item_context, dict) and item_context.get("from_email"):
        return

    team_id = instance.team_id
    item_id = instance.item_id
    comment = instance

    # Resolve the ticket + email config now (synchronously, in the comment's transaction)
    # so the durable outbox row commits atomically with the reply. If Celery/the broker
    # is down, the row still exists and flush_pending_email_replies will send it.
    ticket = (
        Ticket.objects.select_related("team", "email_config")
        .filter(id=item_id, team_id=team_id, channel_source=Channel.EMAIL)
        .first()
    )
    if not ticket:
        return

    # Deliverability verdicts (team email_enabled, customer address, channel config) are NOT
    # checked here: every customer-facing reply on an email ticket gets an outbox row, and
    # _process_outbox_row fails undeliverable ones with a reason. Skipping row creation instead
    # would leave the reply looking sent in the agent UI, with no record of why nothing went out.

    config = ticket.email_config
    inbound_domain = get_instance_setting("CONVERSATIONS_EMAIL_INBOUND_DOMAIN") or (config.domain if config else None)
    message_id = make_msgid(domain=inbound_domain) if inbound_domain else make_msgid()

    # One outbox row per reply comment; get_or_create keeps the signal idempotent.
    outbox, _ = EmailOutboxMessage.objects.get_or_create(
        comment=comment,
        defaults={
            "team_id": team_id,
            "ticket": ticket,
            "message_id": message_id,
        },
    )

    outbox_id = str(outbox.id)

    def enqueue_immediate_send():
        # Low-latency happy path; the periodic sweeper is the durability backstop.
        try:
            cast(Any, send_email_reply).delay(outbox_id=outbox_id)
        except Exception:
            logger.exception("email_reply_signal_failed", item_id=item_id)

    transaction.on_commit(enqueue_immediate_send)


@receiver(post_save, sender=Comment)
def post_teams_reply_on_team_message(sender, instance: Comment, created: bool, **kwargs):
    """
    When a team member or AI bot replies to a Teams-sourced ticket, post the reply
    back to the Teams conversation via a Celery task.

    Only triggers for:
    - Newly created comments (not edits)
    - Outbound replies (human team or public AI)
    - Tickets with channel_source="teams" and valid teams thread info
    - Messages not originating from Teams (to avoid echo)
    """
    if instance.scope != "conversations_ticket":
        return

    if not instance.item_id or not created:
        return

    item_context = instance.item_context
    created_by_id = _get_comment_created_by_id(instance)

    if not _is_outbound_reply(item_context, created_by_id):
        return

    # Don't echo messages that originated from Teams back to Teams
    if isinstance(item_context, dict) and item_context.get("from_teams"):
        return

    team_id = instance.team_id
    item_id = instance.item_id
    content = instance.content or ""
    rich_content = instance.rich_content
    created_by = instance.created_by

    def do_post_to_teams():
        try:
            ticket = Ticket.objects.filter(
                id=item_id,
                team_id=team_id,
                channel_source=Channel.TEAMS,
            ).first()

            if not ticket or not ticket.teams_conversation_id:
                return

            team = ticket.team
            settings_dict = team.conversations_settings or {}
            if not settings_dict.get("teams_enabled"):
                return

            author_name = ""
            if created_by:
                author_name = f"{created_by.first_name} {created_by.last_name}".strip() or created_by.email
            else:
                author_name = AI_BOT_DISPLAY_NAME

            # Shared channels are written to via Graph (the bot connector can't post
            # there); standard channels keep using the bot connector reply path.
            shared_team_id = resolve_shared_channel_team_id(team, ticket.teams_channel_id)
            if shared_team_id:
                root_message_id = parse_teams_root_message_id(ticket.teams_conversation_id)
                if not root_message_id:
                    return
                cast(Any, post_reply_to_teams_via_graph).delay(
                    ticket_id=str(ticket.id),
                    team_id=team_id,
                    teams_team_id=shared_team_id,
                    channel_id=ticket.teams_channel_id,
                    root_message_id=root_message_id,
                    content=content,
                    rich_content=rich_content,
                    author_name=author_name,
                )
            elif ticket.teams_service_url:
                cast(Any, post_reply_to_teams).delay(
                    ticket_id=str(ticket.id),
                    team_id=team_id,
                    content=content,
                    rich_content=rich_content,
                    author_name=author_name,
                    teams_service_url=ticket.teams_service_url,
                    teams_conversation_id=ticket.teams_conversation_id,
                )
        except Exception:
            logger.exception("teams_reply_signal_failed", item_id=item_id)

    transaction.on_commit(do_post_to_teams)


@receiver(post_save, sender=Comment)
def post_github_reply_on_team_message(sender, instance: Comment, created: bool, **kwargs):
    """
    When a team member or AI bot replies to a GitHub-sourced ticket, post the reply
    back to the GitHub issue via a Celery task.

    Only triggers for:
    - Newly created comments (not edits)
    - Outbound replies (human team or public AI)
    - Tickets with channel_source="github" and valid github issue info
    - Messages not originating from GitHub (to avoid echo)
    """
    if instance.scope != "conversations_ticket":
        return

    if not instance.item_id or not created:
        return

    item_context = instance.item_context
    created_by_id = _get_comment_created_by_id(instance)

    if not _is_outbound_reply(item_context, created_by_id):
        return

    if isinstance(item_context, dict) and item_context.get("from_github"):
        return

    team_id = instance.team_id
    item_id = instance.item_id
    content = instance.content or ""
    rich_content = instance.rich_content
    created_by = instance.created_by

    def do_post_to_github():
        try:
            ticket = Ticket.objects.filter(
                id=item_id,
                team_id=team_id,
                channel_source=Channel.GITHUB,
            ).first()

            if not ticket or not ticket.github_repo or not ticket.github_issue_number:
                return

            team = ticket.team
            settings_dict = team.conversations_settings or {}
            if not settings_dict.get("github_enabled"):
                return

            author_name = ""
            if created_by:
                author_name = f"{created_by.first_name} {created_by.last_name}".strip() or created_by.email
            else:
                author_name = AI_BOT_DISPLAY_NAME

            cast(Any, post_reply_to_github).delay(
                ticket_id=str(ticket.id),
                team_id=team_id,
                content=content,
                rich_content=rich_content,
                author_name=author_name,
            )
        except Exception:
            logger.exception("github_reply_signal_failed", item_id=item_id)

    transaction.on_commit(do_post_to_github)
