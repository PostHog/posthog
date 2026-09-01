"""Temporal activities for Zendesk historical ticket import."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from temporalio import activity, workflow

# The package __init__ imports this module inside the Temporal workflow sandbox, but these
# Django/HogQL/model imports are non-deterministic and trip sandbox restrictions (e.g. the
# ORM query-expression names walk django.core.checks.translation -> gettext). Only the
# activity sync helpers touch them at runtime, so pass them through the sandbox unmodified.
with workflow.unsafe.imports_passed_through():
    from django.db import transaction
    from django.db.models import F, Max
    from django.utils import timezone
    from django.utils.dateparse import parse_datetime
    from django.utils.html import strip_tags

    from posthog.dataclasses import frozen
    from posthog.models import Tag, Team
    from posthog.models.comment import Comment
    from posthog.models.tag import tagify
    from posthog.models.tagged_item import TaggedItem
    from posthog.sync import database_sync_to_async
    from posthog.temporal.common.heartbeat import Heartbeater

    from products.conversations.backend.models import EmailChannel, EmailChannelKind, Ticket, ZendeskImportJob
    from products.conversations.backend.models.constants import Status
    from products.conversations.backend.services.attachments import (
        CONVERSATIONS_MAX_IMAGE_BYTES,
        build_content_with_images,
        save_file_to_uploaded_media,
    )
    from products.conversations.backend.temporal.zendesk_import.client import (
        ZendeskAttachmentTooLargeError,
        ZendeskCredentials,
        ZendeskImportClient,
    )
    from products.conversations.backend.temporal.zendesk_import.mappers import (
        default_channel_source,
        map_zendesk_author_type,
        map_zendesk_priority,
        map_zendesk_status,
    )

logger = structlog.get_logger(__name__)


@dataclass
class EnumerateTicketsInput:
    job_id: str
    cursor: str | None = None


@dataclass
class EnumerateTicketsOutput:
    ticket_ids: list[int]
    next_cursor: str | None
    end_of_stream: bool


@dataclass
class ImportBatchInput:
    job_id: str
    team_id: int
    ticket_ids: list[int]
    dry_run: bool = False
    # Fallback EmailChannel (UUID str) for tickets whose Zendesk `recipient` doesn't match a
    # configured support address (e.g. a *.zendesk.com recipient) or is absent. None = leave the
    # ticket's email_config null in those cases.
    default_email_channel_id: str | None = None


@dataclass
class ImportBatchOutput:
    imported: int
    skipped: int
    failed: int


@dataclass
class UpdateJobStatusInput:
    job_id: str
    status: str
    latest_error: str | None = None


@dataclass
class UpdateJobProgressInput:
    job_id: str
    processed_delta: int = 0
    imported_delta: int = 0
    skipped_delta: int = 0
    failed_delta: int = 0
    total_delta: int = 0
    export_cursor: str | None = None


def _parse_zendesk_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone=UTC)
    return parsed


def _credentials_from_job(job: ZendeskImportJob) -> ZendeskCredentials:
    inputs = job.job_inputs or {}
    subdomain = str(inputs.get("subdomain") or "")
    email_address = str(inputs.get("email_address") or "")
    api_token = str(inputs.get("api_token") or "")
    if not subdomain or not email_address or not api_token:
        raise ValueError("Zendesk import job is missing credentials")
    return ZendeskCredentials(subdomain=subdomain, email_address=email_address, api_token=api_token)


def _strip_nul(value: str) -> str:
    """Remove NUL (0x00) bytes, which Postgres text/jsonb columns reject outright.

    Zendesk ticket bodies occasionally carry stray NULs (bad email encodings, copy-paste
    artifacts). One such byte anywhere in a batch aborts the entire bulk_create with a
    DataError and exhausts the activity's retries, so scrub it from every stored string.
    """
    return value.replace("\x00", "") if "\x00" in value else value


def _comment_body(comment: dict[str, Any]) -> str:
    body = (comment.get("body") or "").strip()
    if body:
        return _strip_nul(body)
    html_body = comment.get("html_body") or ""
    return _strip_nul(strip_tags(html_body).strip())


def _comment_is_private(comment: Comment) -> bool:
    """True for internal notes, which must never surface in customer-facing denormalized stats."""
    ctx = comment.item_context
    return isinstance(ctx, dict) and ctx.get("is_private") is True


def _process_attachments(
    client: ZendeskImportClient,
    team: Team,
    comment: dict[str, Any],
    content: str,
    rich_content: dict[str, Any] | None,
) -> tuple[str, dict[str, Any] | None]:
    images: list[dict[str, Any]] = []
    file_links: list[str] = []
    for attachment in comment.get("attachments") or []:
        content_url = attachment.get("content_url")
        file_name = attachment.get("file_name") or "attachment"
        content_type = attachment.get("content_type") or "application/octet-stream"
        if not content_url:
            continue
        try:
            raw = client.download_attachment(content_url, max_bytes=CONVERSATIONS_MAX_IMAGE_BYTES)
        except ZendeskAttachmentTooLargeError:
            logger.warning(
                "zendesk_import_attachment_too_large",
                team_id=team.id,
                file_name=file_name,
                max_bytes=CONVERSATIONS_MAX_IMAGE_BYTES,
            )
            continue
        except Exception as exc:
            logger.warning(
                "zendesk_import_attachment_download_failed",
                team_id=team.id,
                file_name=file_name,
                error=str(exc),
            )
            continue
        is_image = content_type.startswith("image/")
        media_url = save_file_to_uploaded_media(
            team,
            file_name,
            content_type,
            raw,
            validate_images=is_image,
        )
        if not media_url:
            continue
        if is_image:
            images.append({"url": media_url, "name": file_name})
        else:
            file_links.append(f"[{file_name}]({media_url})")
    if file_links:
        suffix = "\n".join(file_links)
        content = f"{content}\n\n{suffix}" if content else suffix
    return build_content_with_images(content, rich_content, images)


@frozen
class _TicketPartition:
    """The requested ticket ids split into ones to import and ones a previous run already imported."""

    existing_ids: set[int]
    to_import: list[int]
    skipped: int


@frozen
class _ZendeskThread:
    """One raw Zendesk ticket payload with the comment payloads fetched for it."""

    ticket: dict[str, Any]
    comments: list[dict[str, Any]]


@frozen
class _FetchedThreads:
    """Phase 1 outcome: the threads fetched, every comment author seen across them, and the fetch failures."""

    threads: list[_ZendeskThread]
    comment_author_ids: set[int]
    failed: int


@frozen
class _CommentAuthor:
    name: str
    email: str


@frozen(eq=False)
class _BuiltComment:
    comment: Comment
    author_type: str
    is_private: bool


@frozen(eq=False)
class _BuiltComments:
    comments: list[Comment]
    customer_message_count: int
    agent_reply_count: int


@frozen(eq=False)
class _BuiltTicket:
    """One ticket built in Phase 2, ready for the Phase 3 transaction.

    `ticket` and `comments` are the exact model instances persisted, so after bulk_create
    sets their ids Phase 3 reads those ids back off the same objects.
    """

    ticket: Ticket
    comments: list[Comment]
    tag_names: list[str]
    customer_message_count: int
    agent_reply_count: int
    created_at: datetime | None
    updated_at: datetime | None


def _resolve_email_channels(
    team_id: int, default_email_channel_id: str | None
) -> tuple[dict[str, EmailChannel], EmailChannel | None]:
    # Map the team's support addresses so each ticket's Zendesk `recipient` (the address the
    # customer originally emailed) resolves to the matching EmailChannel. Unmatched/absent
    # recipients fall back to the caller-selected default channel, if any. Bounded to
    # MAX_EMAIL_CONFIGS_PER_TEAM rows, so a single query up front is cheap.
    email_channels = list(EmailChannel.objects.filter(team_id=team_id, kind=EmailChannelKind.SUPPORT))
    by_addr = {(c.from_email or "").strip().lower(): c for c in email_channels}
    default_channel = None
    if default_email_channel_id:
        default_channel = next((c for c in email_channels if str(c.id) == default_email_channel_id), None)
    return by_addr, default_channel


def _partition_new_tickets(team_id: int, ticket_ids: list[int]) -> _TicketPartition:
    existing_ids = {
        tid
        for tid in Ticket.objects.filter(team_id=team_id)
        .filter(zendesk_ticket_id__in=ticket_ids)
        .values_list("zendesk_ticket_id", flat=True)
        if tid is not None
    }
    to_import = [tid for tid in ticket_ids if tid not in existing_ids]
    return _TicketPartition(existing_ids=existing_ids, to_import=to_import, skipped=len(ticket_ids) - len(to_import))


def _backfill_missing_email_channel(team_id: int, existing_ids: set[int], default_email_channel: EmailChannel) -> None:
    # Re-import backfill: tickets a previous run imported without an email channel (no default
    # was provided at the time) adopt this run's default. Tickets that already resolved a
    # channel — their own recipient match or an earlier default — keep it. QuerySet.update()
    # bypasses the signal receivers (see the Phase 3 comment below) and doesn't bump the
    # historical updated_at.
    backfilled = Ticket.objects.filter(
        team_id=team_id,
        zendesk_ticket_id__in=existing_ids,
        email_config__isnull=True,
    ).update(email_config=default_email_channel)
    if backfilled:
        logger.info("zendesk_import_backfilled_email_channel", team_id=team_id, backfilled=backfilled)


def _fetch_tickets_and_users(client: ZendeskImportClient, to_import: list[int]) -> tuple[list[dict[str, Any]], dict]:
    zendesk_tickets = client.fetch_tickets(to_import)
    requester_ids = [int(t["requester_id"]) for t in zendesk_tickets if t.get("requester_id") is not None]
    return zendesk_tickets, client.fetch_users(requester_ids)


def _fetch_ticket_comments(
    client: ZendeskImportClient, zendesk_tickets: list[dict[str, Any]], team: Team
) -> _FetchedThreads:
    """Phase 1: fetch each ticket's comments OUTSIDE the transaction (network I/O)."""
    threads: list[_ZendeskThread] = []
    comment_author_ids: set[int] = set()
    failed = 0
    for zendesk_ticket in zendesk_tickets:
        zendesk_id = int(zendesk_ticket["id"])
        try:
            comments = client.fetch_comments(zendesk_id)
            for zd_comment in comments:
                author_id = zd_comment.get("author_id")
                if author_id is not None:
                    comment_author_ids.add(int(author_id))
            threads.append(_ZendeskThread(ticket=zendesk_ticket, comments=comments))
        except Exception as exc:
            failed += 1
            logger.exception(
                "zendesk_import_ticket_fetch_failed",
                team_id=team.id,
                zendesk_ticket_id=zendesk_id,
                error=str(exc),
            )
    return _FetchedThreads(threads=threads, comment_author_ids=comment_author_ids, failed=failed)


def _resolve_missing_authors(client: ZendeskImportClient, comment_author_ids: set[int], users_by_id: dict) -> None:
    # Batch-resolve every comment author's role in one shot (so classification uses the real
    # role for each participant, not a per-thread heuristic). Deactivated agents still resolve;
    # only hard-deleted users won't, and those fall back to the customer-side id check below.
    missing_author_ids = [aid for aid in comment_author_ids if aid not in users_by_id]
    if missing_author_ids:
        users_by_id.update(client.fetch_users(missing_author_ids))


def _customer_side_ids(zendesk_ticket: dict[str, Any]) -> set[int]:
    # Customer-side participants: the requester plus any CCs/collaborators. Used only as a
    # fallback when an author's role can't be resolved (hard-deleted users) so a deleted
    # end-user still counts as a customer and a deleted agent counts as staff.
    ids: set[int] = set()
    if zendesk_ticket.get("requester_id") is not None:
        ids.add(int(zendesk_ticket["requester_id"]))
    for cc_id in (zendesk_ticket.get("collaborator_ids") or []) + (zendesk_ticket.get("email_cc_ids") or []):
        if cc_id is not None:
            ids.add(int(cc_id))
    return ids


def _resolve_comment_author(zd_comment: dict[str, Any], author: dict, author_type: str) -> _CommentAuthor:
    author_name = _strip_nul((author.get("name") or "").strip())
    author_email = _strip_nul((author.get("email") or "").strip())
    # A staff author whose Zendesk user no longer resolves (deleted ex-agent) has no name/email —
    # recover it from the comment's own sender (`via.source.from`), which survives user deletion,
    # so the reply doesn't render as "Anonymous user".
    if author_type == "support" and not author_name and not author_email:
        via_from = ((zd_comment.get("via") or {}).get("source") or {}).get("from") or {}
        author_name = _strip_nul((via_from.get("name") or "").strip())
        author_email = _strip_nul((via_from.get("address") or "").strip())
    return _CommentAuthor(name=author_name, email=author_email)


def _build_comment(
    client: ZendeskImportClient,
    team: Team,
    zd_comment: dict[str, Any],
    users_by_id: dict,
    customer_side_ids: set[int],
) -> _BuiltComment | None:
    """Build one Comment. A comment with no body and no rich content is dropped (returns None)."""
    author_id = zd_comment.get("author_id")
    author = users_by_id.get(int(author_id), {}) if author_id is not None else {}

    is_public = bool(zd_comment.get("public", True))
    is_customer_side = author_id is not None and int(author_id) in customer_side_ids
    author_type, is_private = map_zendesk_author_type(
        role=author.get("role"), is_public=is_public, is_customer_side=is_customer_side
    )
    body = _comment_body(zd_comment)
    rich_content: dict[str, Any] | None = None
    body, rich_content = _process_attachments(client, team, zd_comment, body, rich_content)
    if not body and not rich_content:
        return None

    # Persist each comment's own author identity so the thread shows the actual commenter (a
    # second requester, an agent, etc.) instead of every message inheriting the ticket-level
    # requester from anonymous_traits.
    comment_author = _resolve_comment_author(zd_comment, author, author_type)
    item_context: dict[str, Any] = {
        "author_type": author_type,
        "is_private": is_private,
        "from_zendesk": True,
        "zendesk_comment_id": zd_comment.get("id"),
    }
    if comment_author.name:
        item_context["author_name"] = comment_author.name
    if comment_author.email:
        item_context["author_email"] = comment_author.email

    comment_obj = Comment(
        team=team,
        scope="conversations_ticket",
        item_id="",  # placeholder — set after ticket gets an ID
        content=_strip_nul(body),
        rich_content=rich_content,
        item_context=item_context,
    )
    # auto_now_add clobbers created_at during bulk_create, so stash the
    # historical value on a shadow attr and re-apply it via bulk_update.
    comment_obj._zendesk_created_at = _parse_zendesk_datetime(zd_comment.get("created_at"))  # type: ignore[attr-defined]
    return _BuiltComment(comment=comment_obj, author_type=author_type, is_private=is_private)


def _build_comments(
    client: ZendeskImportClient,
    team: Team,
    comments: list[dict[str, Any]],
    users_by_id: dict,
    customer_side_ids: set[int],
) -> _BuiltComments:
    """Build a ticket's comments and count its public customer/agent messages."""
    built: list[Comment] = []
    customer_message_count = 0
    agent_reply_count = 0
    for zd_comment in comments:
        built_comment = _build_comment(client, team, zd_comment, users_by_id, customer_side_ids)
        if built_comment is None:
            continue
        # Mirror signals.update_ticket_on_message: private/internal notes are dropped from every
        # denormalized widget stat (message_count, last_message_*, unread counts). Counting them
        # would leak note text into last_message_text and inflate the customer's unread badge.
        if built_comment.is_private:
            pass
        elif built_comment.author_type == "customer":
            customer_message_count += 1
        else:
            agent_reply_count += 1
        built.append(built_comment.comment)
    return _BuiltComments(
        comments=built, customer_message_count=customer_message_count, agent_reply_count=agent_reply_count
    )


def _build_ticket(
    client: ZendeskImportClient,
    team: Team,
    thread: _ZendeskThread,
    users_by_id: dict,
    email_channels_by_addr: dict[str, EmailChannel],
    default_email_channel: EmailChannel | None,
) -> _BuiltTicket:
    zendesk_ticket = thread.ticket
    zendesk_id = int(zendesk_ticket["id"])
    requester = users_by_id.get(int(zendesk_ticket.get("requester_id") or 0), {})
    requester_email = _strip_nul(
        (requester.get("email") or f"zendesk-user-{zendesk_ticket.get('requester_id')}").strip()
    )
    requester_name = _strip_nul((requester.get("name") or "").strip())
    # Access identity: use the Zendesk requester email verbatim. This gates verified-widget ticket
    # history (widget.py checks ticket.distinct_id ∈ the caller's person distinct_ids), and person
    # distinct_ids are set only by the app's own identify()/alias() calls. We must NOT resolve this
    # via a person lookup on `properties.email`: that field is attacker-settable analytics data, so
    # seeding a profile with a victim's email would rebind the victim's imported tickets to the
    # attacker's distinct_id (identity poisoning).
    distinct_id = requester_email

    # Populate anonymous_traits so the customer renders as their name/email instead of "Anonymous
    # user" when no PostHog person matched — same shape as the other import paths (Slack/email/
    # GitHub). The email is from the authenticated Zendesk API, not public widget input, so it's
    # trustworthy for restore-by-email.
    anonymous_traits: dict[str, str] = {}
    if requester_name:
        anonymous_traits["name"] = requester_name
    if "@" in requester_email:
        anonymous_traits["email"] = requester_email

    # Zendesk `recipient` is the original support address the customer emailed. Match it to a
    # configured EmailChannel; otherwise fall back to the caller-selected default (or null).
    recipient = (zendesk_ticket.get("recipient") or "").strip().lower()
    email_config = email_channels_by_addr.get(recipient) or default_email_channel

    ticket = Ticket(
        team=team,
        channel_source=default_channel_source(),
        widget_session_id=str(uuid.uuid4()),
        distinct_id=distinct_id,
        status=map_zendesk_status(zendesk_ticket.get("status")),
        priority=map_zendesk_priority(zendesk_ticket.get("priority")),
        email_subject=_strip_nul(zendesk_ticket.get("subject") or "")[:500] or None,
        email_from=requester_email if "@" in requester_email else None,
        email_config=email_config,
        anonymous_traits=anonymous_traits,
        zendesk_ticket_id=zendesk_id,
    )

    # Zendesk tags are plain strings on the ticket payload; PostHog tags are per-team Tag rows,
    # so normalize the same way the live tagging API does (tagify).
    zendesk_tags = {tagify(_strip_nul(str(t)))[:255] for t in (zendesk_ticket.get("tags") or [])}
    tag_names = sorted(t for t in zendesk_tags if t)

    built_comments = _build_comments(client, team, thread.comments, users_by_id, _customer_side_ids(zendesk_ticket))
    return _BuiltTicket(
        ticket=ticket,
        comments=built_comments.comments,
        tag_names=tag_names,
        customer_message_count=built_comments.customer_message_count,
        agent_reply_count=built_comments.agent_reply_count,
        created_at=_parse_zendesk_datetime(zendesk_ticket.get("created_at")),
        updated_at=_parse_zendesk_datetime(zendesk_ticket.get("updated_at")),
    )


def _build_tickets(
    client: ZendeskImportClient,
    team: Team,
    threads: list[_ZendeskThread],
    users_by_id: dict,
    email_channels_by_addr: dict[str, EmailChannel],
    default_email_channel: EmailChannel | None,
) -> tuple[list[_BuiltTicket], int]:
    """Phase 2: build each ticket + its comments (attachments involve network I/O, so outside atomic)."""
    built: list[_BuiltTicket] = []
    failed = 0
    for thread in threads:
        try:
            built.append(
                _build_ticket(client, team, thread, users_by_id, email_channels_by_addr, default_email_channel)
            )
        except Exception as exc:
            failed += 1
            logger.exception(
                "zendesk_import_ticket_failed",
                team_id=team.id,
                zendesk_ticket_id=int(thread.ticket["id"]),
                error=str(exc),
            )
    return built, failed


def _apply_ticket_timestamps(built: list[_BuiltTicket]) -> None:
    updates: list[Ticket] = []
    for b in built:
        if b.created_at or b.updated_at:
            b.ticket.created_at = b.created_at or timezone.now()
            b.ticket.updated_at = b.updated_at or timezone.now()
            updates.append(b.ticket)
    if updates:
        Ticket.objects.bulk_update(updates, ["created_at", "updated_at"])


def _link_ticket_tags(built: list[_BuiltTicket], tags_by_name: dict[str, Tag]) -> None:
    # bulk_create skips TaggedItem.save()/full_clean() on purpose — the same no-signals rule as
    # the ticket/comment writes here.
    tagged_items = [TaggedItem(tag=tags_by_name[name], ticket=b.ticket) for b in built for name in b.tag_names]
    if tagged_items:
        TaggedItem.objects.bulk_create(tagged_items, ignore_conflicts=True)


def _create_ticket_comments(built: list[_BuiltTicket]) -> None:
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
        historical = getattr(c, "_zendesk_created_at", None)
        if historical is not None:
            c.created_at = historical
            comment_ts_updates.append(c)
    if comment_ts_updates:
        Comment.objects.bulk_update(comment_ts_updates, ["created_at"])


def _apply_denormalized_counters(team: Team, built: list[_BuiltTicket]) -> None:
    # All of these back the customer-facing widget (message_count, last_message_*, unread badge),
    # so they must exclude private notes — see _build_comments and signals.update_ticket_on_message.
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
        # are appended in Zendesk chronological order, so reverse-scan for the newest visible one.
        last_visible = next((c for c in reversed(b.comments) if not _comment_is_private(c)), None)
        if last_visible is not None:
            update_fields_dict["last_message_at"] = last_visible.created_at
            update_fields_dict["last_message_text"] = (last_visible.content or "")[:500]
        # Only still-active imported tickets should surface unread badges. Pending/on-hold/resolved
        # (Zendesk solved+closed) tickets are done or parked, so lighting up the agent inbox
        # (unread_team_count) or the customer widget (unread_customer_count) with years-old activity
        # is pure alert fatigue — import them read.
        is_active = ticket_obj.status in (Status.NEW, Status.OPEN)
        if is_active and cust_count:
            update_fields_dict["unread_team_count"] = F("unread_team_count") + cust_count
        if is_active and agent_count:
            update_fields_dict["unread_customer_count"] = F("unread_customer_count") + agent_count
        Ticket.objects.filter(team_id=team.id, id=ticket_obj.id).update(**update_fields_dict)


def _persist_ticket_batch(team: Team, built: list[_BuiltTicket], tags_by_name: dict[str, Tag]) -> int:
    # Phase 3: Persist tickets + comments in a single transaction (no network I/O). Ticket numbers
    # are assigned under the same lock that guards bulk_create, so concurrent batch activities can't
    # collide on unique_ticket_number_per_team.
    #
    # IMPORTANT: persist historical rows with bulk_create/bulk_update ONLY. These bypass the
    # post_save/pre_save receivers in products/conversations/backend/signals.py, which is what
    # keeps a backfill silent: those receivers emit the $conversation_* analytics events that
    # power hogflow triggers (New ticket created, Ticket message sent/received, ...) AND enqueue
    # outbound Slack/email/Teams/GitHub replies. Switching any write here to create_with_number(),
    # Comment.objects.create(), or .save() would fire those signals for every imported row —
    # triggering workflows and re-sending replies to real customers for years-old tickets. Don't.
    with transaction.atomic():
        Team.objects.select_for_update().get(id=team.id)
        max_num = Ticket.objects.filter(team_id=team.id).aggregate(Max("ticket_number"))["ticket_number__max"] or 0
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


def _import_ticket_batch_sync(input: ImportBatchInput) -> ImportBatchOutput:
    job = ZendeskImportJob.objects.for_team(input.team_id).get(id=input.job_id)
    team = Team.objects.get(id=input.team_id)
    client = ZendeskImportClient(_credentials_from_job(job))
    email_channels_by_addr, default_email_channel = _resolve_email_channels(team.id, input.default_email_channel_id)

    partition = _partition_new_tickets(input.team_id, input.ticket_ids)
    skipped = partition.skipped

    if partition.existing_ids and default_email_channel is not None and not input.dry_run:
        _backfill_missing_email_channel(input.team_id, partition.existing_ids, default_email_channel)

    if not partition.to_import:
        return ImportBatchOutput(imported=0, skipped=skipped, failed=0)

    would_import = len(partition.to_import)
    if input.dry_run:
        logger.info("zendesk_import_dry_run_batch", team_id=team.id, would_import=would_import, skipped=skipped)
        return ImportBatchOutput(imported=would_import, skipped=skipped, failed=0)

    zendesk_tickets, users_by_id = _fetch_tickets_and_users(client, partition.to_import)

    fetched = _fetch_ticket_comments(client, zendesk_tickets, team)
    failed = fetched.failed
    if not fetched.threads:
        return ImportBatchOutput(imported=0, skipped=skipped, failed=failed)

    _resolve_missing_authors(client, fetched.comment_author_ids, users_by_id)

    built, build_failed = _build_tickets(
        client, team, fetched.threads, users_by_id, email_channels_by_addr, default_email_channel
    )
    failed += build_failed
    if not built:
        return ImportBatchOutput(imported=0, skipped=skipped, failed=failed)

    # Resolve Tag rows before the ticket transaction to keep its lock window narrow. get_or_create
    # matches the live tagging path (set_tags_on_object); a Tag row left behind by a failed batch
    # is harmless — it's reused on retry.
    all_tag_names = {name for b in built for name in b.tag_names}
    tags_by_name = {name: Tag.objects.get_or_create(name=name, team_id=team.id)[0] for name in all_tag_names}

    imported = _persist_ticket_batch(team, built, tags_by_name)
    return ImportBatchOutput(imported=imported, skipped=skipped, failed=failed)


@activity.defn
async def zendesk_import_enumerate_tickets_activity(input: EnumerateTicketsInput) -> EnumerateTicketsOutput:
    async with Heartbeater():
        return await database_sync_to_async(_enumerate_tickets_sync, thread_sensitive=False)(input)


def _enumerate_tickets_sync(input: EnumerateTicketsInput) -> EnumerateTicketsOutput:
    job = ZendeskImportJob.objects.unscoped().get(id=input.job_id)
    client = ZendeskImportClient(_credentials_from_job(job))
    ticket_ids, next_cursor, end_of_stream = client.list_ticket_ids_page(cursor=input.cursor)
    return EnumerateTicketsOutput(ticket_ids=ticket_ids, next_cursor=next_cursor, end_of_stream=end_of_stream)


@activity.defn
async def zendesk_import_batch_activity(input: ImportBatchInput) -> ImportBatchOutput:
    async with Heartbeater():
        return await database_sync_to_async(_import_ticket_batch_sync, thread_sensitive=False)(input)


def _update_job_status_sync(input: UpdateJobStatusInput) -> None:
    job = ZendeskImportJob.objects.unscoped().get(id=input.job_id)
    update_fields = ["status", "updated_at"]
    job.status = input.status
    if input.latest_error is not None:
        job.latest_error = input.latest_error
        update_fields.append("latest_error")
    if input.status == ZendeskImportJob.Status.RUNNING and job.started_at is None:
        job.started_at = timezone.now()
        update_fields.append("started_at")
    if input.status in (ZendeskImportJob.Status.COMPLETED, ZendeskImportJob.Status.FAILED):
        job.finished_at = timezone.now()
        update_fields.append("finished_at")
    # Narrow update_fields so this write can't clobber counters / cursor
    # that in-flight batch children may update concurrently (e.g. on FAILED).
    job.save(update_fields=update_fields)


def _update_job_progress_sync(input: UpdateJobProgressInput) -> None:
    updates: dict[str, Any] = {
        "processed_tickets": F("processed_tickets") + input.processed_delta,
        "imported_tickets": F("imported_tickets") + input.imported_delta,
        "skipped_tickets": F("skipped_tickets") + input.skipped_delta,
        "failed_tickets": F("failed_tickets") + input.failed_delta,
        "total_tickets": F("total_tickets") + input.total_delta,
    }
    if input.export_cursor is not None:
        updates["export_cursor"] = input.export_cursor
    ZendeskImportJob.objects.unscoped().filter(id=input.job_id).update(**updates)


@activity.defn
async def zendesk_import_update_job_status_activity(input: UpdateJobStatusInput) -> None:
    async with Heartbeater():
        await database_sync_to_async(_update_job_status_sync, thread_sensitive=False)(input)


@activity.defn
async def zendesk_import_update_job_progress_activity(input: UpdateJobProgressInput) -> None:
    async with Heartbeater():
        await database_sync_to_async(_update_job_progress_sync, thread_sensitive=False)(input)
