"""Source-agnostic persistence for historical ticket imports (Zendesk, Intercom)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from temporalio import workflow

# The temporal package __init__ imports the import activities inside the workflow sandbox, which
# pulls this module in too. Pass the Django/model imports through the sandbox unmodified — only
# the activity sync helpers touch them at runtime.
with workflow.unsafe.imports_passed_through():
    from django.db import transaction
    from django.db.models import F
    from django.utils import timezone

    from posthog.dataclasses import frozen
    from posthog.models import Tag, Team
    from posthog.models.comment import Comment
    from posthog.models.tagged_item import TaggedItem

    from products.conversations.backend.models import EmailChannel, EmailChannelKind, Ticket
    from products.conversations.backend.models.constants import Status

_HISTORICAL_CREATED_AT_ATTR = "_import_historical_created_at"


def strip_nul(value: str) -> str:
    """Remove NUL (0x00) bytes, which Postgres text/jsonb columns reject outright.

    Imported ticket bodies occasionally carry stray NULs (bad email encodings, copy-paste
    artifacts). One such byte anywhere in a batch aborts the entire bulk_create with a
    DataError and exhausts the activity's retries, so scrub it from every stored string.
    """
    return value.replace("\x00", "") if "\x00" in value else value


def comment_is_private(comment: Comment) -> bool:
    """True for internal notes, which must never surface in customer-facing denormalized stats."""
    ctx = comment.item_context
    return isinstance(ctx, dict) and ctx.get("is_private") is True


def set_historical_created_at(comment: Comment, created_at: datetime | None) -> None:
    # auto_now_add clobbers created_at during bulk_create, so stash the historical value on a
    # shadow attr and re-apply it via bulk_update after the insert.
    setattr(comment, _HISTORICAL_CREATED_AT_ATTR, created_at)


@frozen(eq=False)
class BuiltTicket:
    """One ticket built from a source payload, ready for the persist transaction.

    `ticket` and `comments` are the exact model instances persisted, so after bulk_create
    sets their ids the later steps read those ids back off the same objects.
    """

    ticket: Ticket
    comments: list[Comment]
    tag_names: list[str]
    customer_message_count: int
    agent_reply_count: int
    created_at: datetime | None
    updated_at: datetime | None


def resolve_email_channels(
    team_id: int, default_email_channel_id: str | None
) -> tuple[dict[str, EmailChannel], EmailChannel | None]:
    # Map the team's support addresses so each imported ticket's original recipient (the address
    # the customer emailed) resolves to the matching EmailChannel. Unmatched/absent recipients fall
    # back to the caller-selected default channel, if any. Bounded to MAX_EMAIL_CONFIGS_PER_TEAM
    # rows, so a single query up front is cheap.
    email_channels = list(EmailChannel.objects.filter(team_id=team_id, kind=EmailChannelKind.SUPPORT))
    by_addr = {(c.from_email or "").strip().lower(): c for c in email_channels}
    default_channel = None
    if default_email_channel_id:
        default_channel = next((c for c in email_channels if str(c.id) == default_email_channel_id), None)
    return by_addr, default_channel


def resolve_tags(team_id: int, built: list[BuiltTicket]) -> dict[str, Tag]:
    # Resolve Tag rows before the ticket transaction to keep its lock window narrow. get_or_create
    # matches the live tagging path (set_tags_on_object); a Tag row left behind by a failed batch
    # is harmless — it's reused on retry.
    all_tag_names = {name for b in built for name in b.tag_names}
    return {name: Tag.objects.get_or_create(name=name, team_id=team_id)[0] for name in all_tag_names}


def _apply_ticket_timestamps(built: list[BuiltTicket]) -> None:
    updates: list[Ticket] = []
    for b in built:
        if b.created_at or b.updated_at:
            b.ticket.created_at = b.created_at or timezone.now()
            b.ticket.updated_at = b.updated_at or timezone.now()
            updates.append(b.ticket)
    if updates:
        Ticket.objects.bulk_update(updates, ["created_at", "updated_at"])


def _link_ticket_tags(built: list[BuiltTicket], tags_by_name: dict[str, Tag]) -> None:
    # bulk_create skips TaggedItem.save()/full_clean() on purpose — the same no-signals rule as
    # the ticket/comment writes here.
    tagged_items = [TaggedItem.for_content_object(tags_by_name[name], b.ticket) for b in built for name in b.tag_names]
    if tagged_items:
        TaggedItem.objects.bulk_create(tagged_items, ignore_conflicts=True)


def _create_ticket_comments(built: list[BuiltTicket]) -> None:
    all_comments: list[Comment] = []
    for b in built:
        for c in b.comments:
            c.item_id = str(b.ticket.id)
        all_comments.extend(b.comments)
    if not all_comments:
        return
    created_comments = Comment.objects.bulk_create(all_comments)
    # bulk_create's auto_now_add overwrote created_at, so re-apply the stashed
    # historical timestamps for comments that had one.
    comment_ts_updates: list[Comment] = []
    for c in created_comments:
        historical = getattr(c, _HISTORICAL_CREATED_AT_ATTR, None)
        if historical is not None:
            c.created_at = historical
            comment_ts_updates.append(c)
    if comment_ts_updates:
        Comment.objects.bulk_update(comment_ts_updates, ["created_at"])


def _apply_denormalized_counters(team: Team, built: list[BuiltTicket]) -> None:
    # All of these back the customer-facing widget (message_count, last_message_*, unread badge),
    # so they must exclude private notes — see signals.update_ticket_on_message.
    for b in built:
        if not b.comments:
            continue
        ticket_obj = b.ticket
        cust_count = b.customer_message_count
        agent_count = b.agent_reply_count
        update_fields_dict: dict[str, Any] = {
            "message_count": F("message_count") + cust_count + agent_count,
        }
        # last_message_* is shown to the customer, so use the latest non-private comment. Comments
        # are appended in source chronological order, so reverse-scan for the newest visible one.
        last_visible = next((c for c in reversed(b.comments) if not comment_is_private(c)), None)
        if last_visible is not None:
            update_fields_dict["last_message_at"] = last_visible.created_at
            update_fields_dict["last_message_text"] = (last_visible.content or "")[:500]
        # Only still-active imported tickets should surface unread badges. Pending/on-hold/resolved
        # tickets are done or parked, so lighting up the agent inbox (unread_team_count) or the
        # customer widget (unread_customer_count) with years-old activity is pure alert fatigue —
        # import them read.
        is_active = ticket_obj.status in (Status.NEW, Status.OPEN)
        if is_active and cust_count:
            update_fields_dict["unread_team_count"] = F("unread_team_count") + cust_count
        if is_active and agent_count:
            update_fields_dict["unread_customer_count"] = F("unread_customer_count") + agent_count
        Ticket.objects.filter(team_id=team.id, id=ticket_obj.id).update(**update_fields_dict)


def persist_ticket_batch(team: Team, built: list[BuiltTicket], tags_by_name: dict[str, Tag]) -> int:
    # Persist tickets + comments in a single transaction (no network I/O). Ticket numbers are
    # assigned under the same advisory lock as create_with_number, so live creates and concurrent
    # batch activities can't collide on unique_ticket_number_per_team.
    #
    # IMPORTANT: persist historical rows with bulk_create/bulk_update ONLY. These bypass the
    # post_save/pre_save receivers in products/conversations/backend/signals.py, which is what
    # keeps a backfill silent: those receivers emit the $conversation_* analytics events that
    # power hogflow triggers (New ticket created, Ticket message sent/received, ...) AND enqueue
    # outbound Slack/email/Teams/GitHub replies. Switching any write here to create_with_number(),
    # Comment.objects.create(), or .save() would fire those signals for every imported row —
    # triggering workflows and re-sending replies to real customers for years-old tickets. Don't.
    with transaction.atomic():
        Ticket.all_objects.lock_ticket_number_allocation(team.id)
        max_num = Ticket.all_objects.highest_used_ticket_number(team.id)
        tickets_to_create = [b.ticket for b in built]
        for offset, ticket_to_number in enumerate(tickets_to_create):
            ticket_to_number.ticket_number = max_num + 1 + offset
        # bulk_create sets each object's id in place, so built[i].ticket now carries its new id.
        Ticket.objects.bulk_create(tickets_to_create)

        _apply_ticket_timestamps(built)
        _link_ticket_tags(built, tags_by_name)
        _create_ticket_comments(built)
        _apply_denormalized_counters(team, built)
        return len(tickets_to_create)
