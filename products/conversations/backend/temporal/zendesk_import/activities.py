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

    from posthog.models import Team
    from posthog.models.comment import Comment
    from posthog.sync import database_sync_to_async
    from posthog.temporal.common.heartbeat import Heartbeater

    from products.conversations.backend.models import EmailChannel, Ticket, ZendeskImportJob
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


def _import_ticket_batch_sync(input: ImportBatchInput) -> ImportBatchOutput:
    job = ZendeskImportJob.objects.for_team(input.team_id).get(id=input.job_id)
    team = Team.objects.get(id=input.team_id)
    credentials = _credentials_from_job(job)
    client = ZendeskImportClient(credentials)

    existing_ids = set(
        Ticket.objects.filter(team_id=input.team_id)
        .filter(zendesk_ticket_id__in=input.ticket_ids)
        .values_list("zendesk_ticket_id", flat=True)
    )
    to_import = [tid for tid in input.ticket_ids if tid not in existing_ids]
    skipped = len(input.ticket_ids) - len(to_import)
    if not to_import:
        return ImportBatchOutput(imported=0, skipped=skipped, failed=0)

    if input.dry_run:
        logger.info("zendesk_import_dry_run_batch", team_id=team.id, would_import=len(to_import), skipped=skipped)
        return ImportBatchOutput(imported=len(to_import), skipped=skipped, failed=0)

    zendesk_tickets = client.fetch_tickets(to_import)
    requester_ids = [int(t["requester_id"]) for t in zendesk_tickets if t.get("requester_id") is not None]
    users_by_id = client.fetch_users(requester_ids)

    imported = 0
    failed = 0

    # Map the team's support addresses so each ticket's Zendesk `recipient` (the address the
    # customer originally emailed) resolves to the matching EmailChannel. Unmatched/absent
    # recipients fall back to the caller-selected default channel, if any. Bounded to
    # MAX_EMAIL_CONFIGS_PER_TEAM rows, so a single query up front is cheap.
    email_channels = list(EmailChannel.objects.filter(team_id=team.id))
    email_channels_by_addr = {(c.from_email or "").strip().lower(): c for c in email_channels}
    default_email_channel = None
    if input.default_email_channel_id:
        default_email_channel = next((c for c in email_channels if str(c.id) == input.default_email_channel_id), None)

    # Phase 1: Fetch all comments + attachments OUTSIDE the transaction (network I/O).
    ticket_data: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    comment_author_ids: set[int] = set()
    for zendesk_ticket in zendesk_tickets:
        zendesk_id = int(zendesk_ticket["id"])
        try:
            comments = client.fetch_comments(zendesk_id)
            for zd_comment in comments:
                author_id = zd_comment.get("author_id")
                if author_id is not None:
                    comment_author_ids.add(int(author_id))
            ticket_data.append((zendesk_ticket, comments))
        except Exception as exc:
            failed += 1
            logger.exception(
                "zendesk_import_ticket_fetch_failed",
                team_id=team.id,
                zendesk_ticket_id=zendesk_id,
                error=str(exc),
            )

    if not ticket_data:
        return ImportBatchOutput(imported=0, skipped=skipped, failed=failed)

    # Batch-resolve every comment author's role in one shot (so classification uses the real
    # role for each participant, not a per-thread heuristic). Deactivated agents still resolve;
    # only hard-deleted users won't, and those fall back to the customer-side id check below.
    missing_author_ids = [aid for aid in comment_author_ids if aid not in users_by_id]
    if missing_author_ids:
        users_by_id.update(client.fetch_users(missing_author_ids))

    # Phase 2: Process each ticket (attachments involve network I/O, so outside atomic).
    tickets_to_create: list[Ticket] = []
    ticket_comments_map: list[tuple[int, list[Comment], int, int]] = []
    # Maps index in tickets_to_create → index in ticket_data
    ticket_create_to_data_idx: list[int] = []

    for idx, (zendesk_ticket, comments) in enumerate(ticket_data):
        zendesk_id = int(zendesk_ticket["id"])
        try:
            requester = users_by_id.get(int(zendesk_ticket.get("requester_id") or 0), {})
            requester_email = _strip_nul(
                (requester.get("email") or f"zendesk-user-{zendesk_ticket.get('requester_id')}").strip()
            )
            requester_name = _strip_nul((requester.get("name") or "").strip())
            # Access identity: use the Zendesk requester email verbatim. This gates verified-widget
            # ticket history (widget.py checks ticket.distinct_id ∈ the caller's person distinct_ids),
            # and person distinct_ids are set only by the app's own identify()/alias() calls. We must
            # NOT resolve this via a person lookup on `properties.email`: that field is attacker-
            # settable analytics data, so seeding a profile with a victim's email would rebind the
            # victim's imported tickets to the attacker's distinct_id (identity poisoning).
            distinct_id = requester_email

            # Populate anonymous_traits so the customer renders as their name/email instead of
            # "Anonymous user" when no PostHog person matched — same shape as the other import
            # paths (Slack/email/GitHub). The email is from the authenticated Zendesk API, not
            # public widget input, so it's trustworthy for restore-by-email.
            anonymous_traits: dict[str, str] = {}
            if requester_name:
                anonymous_traits["name"] = requester_name
            if "@" in requester_email:
                anonymous_traits["email"] = requester_email

            # Zendesk `recipient` is the original support address the customer emailed. Match it to
            # a configured EmailChannel; otherwise fall back to the caller-selected default (or null).
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
            create_idx = len(tickets_to_create)
            tickets_to_create.append(ticket)
            ticket_create_to_data_idx.append(idx)

            comments_to_create: list[Comment] = []
            customer_message_count = 0
            agent_reply_count = 0

            # Customer-side participants: the requester plus any CCs/collaborators. Used only as a
            # fallback when an author's role can't be resolved (hard-deleted users) so a deleted
            # end-user still counts as a customer and a deleted agent counts as staff.
            customer_side_ids: set[int] = set()
            if zendesk_ticket.get("requester_id") is not None:
                customer_side_ids.add(int(zendesk_ticket["requester_id"]))
            for cc_id in (zendesk_ticket.get("collaborator_ids") or []) + (zendesk_ticket.get("email_cc_ids") or []):
                if cc_id is not None:
                    customer_side_ids.add(int(cc_id))

            for zd_comment in comments:
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
                    continue

                # Mirror signals.update_ticket_on_message: private/internal notes are dropped from
                # every denormalized widget stat (message_count, last_message_*, unread counts).
                # Counting them here would leak note text into last_message_text and inflate the
                # customer's unread badge on the verified widget.
                if is_private:
                    pass
                elif author_type == "customer":
                    customer_message_count += 1
                else:
                    agent_reply_count += 1

                # Persist each comment's own author identity so the thread shows the actual
                # commenter (a second requester, an agent, etc.) instead of every message
                # inheriting the ticket-level requester from anonymous_traits.
                author_name = _strip_nul((author.get("name") or "").strip())
                author_email = _strip_nul((author.get("email") or "").strip())
                # A staff author whose Zendesk user no longer resolves (deleted ex-agent) has no
                # name/email — recover it from the comment's own sender (`via.source.from`), which
                # survives user deletion, so the reply doesn't render as "Anonymous user".
                if author_type == "support" and not author_name and not author_email:
                    via_from = ((zd_comment.get("via") or {}).get("source") or {}).get("from") or {}
                    author_name = _strip_nul((via_from.get("name") or "").strip())
                    author_email = _strip_nul((via_from.get("address") or "").strip())
                item_context: dict[str, Any] = {
                    "author_type": author_type,
                    "is_private": is_private,
                    "from_zendesk": True,
                    "zendesk_comment_id": zd_comment.get("id"),
                }
                if author_name:
                    item_context["author_name"] = author_name
                if author_email:
                    item_context["author_email"] = author_email

                comment_created_at = _parse_zendesk_datetime(zd_comment.get("created_at"))
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
                comment_obj._zendesk_created_at = comment_created_at  # type: ignore[attr-defined]
                comments_to_create.append(comment_obj)

            ticket_comments_map.append((create_idx, comments_to_create, customer_message_count, agent_reply_count))
        except Exception as exc:
            failed += 1
            logger.exception(
                "zendesk_import_ticket_failed",
                team_id=team.id,
                zendesk_ticket_id=zendesk_id,
                error=str(exc),
            )

    if not tickets_to_create:
        return ImportBatchOutput(imported=0, skipped=skipped, failed=failed)

    # Phase 3: Persist tickets + comments in a single transaction (no network I/O).
    # Ticket numbers are assigned under the same lock that guards bulk_create, so
    # concurrent batch activities can't collide on unique_ticket_number_per_team.
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
        for offset, ticket_to_number in enumerate(tickets_to_create):
            ticket_to_number.ticket_number = max_num + 1 + offset
        created_tickets = Ticket.objects.bulk_create(tickets_to_create)

        # Apply historical timestamps
        ticket_ts_updates: list[Ticket] = []
        for i, ticket_obj in enumerate(created_tickets):
            data_idx = ticket_create_to_data_idx[i]
            zendesk_ticket = ticket_data[data_idx][0]
            created_at = _parse_zendesk_datetime(zendesk_ticket.get("created_at"))
            updated_at_ts = _parse_zendesk_datetime(zendesk_ticket.get("updated_at"))
            if created_at or updated_at_ts:
                ticket_obj.created_at = created_at or timezone.now()
                ticket_obj.updated_at = updated_at_ts or timezone.now()
                ticket_ts_updates.append(ticket_obj)
        if ticket_ts_updates:
            Ticket.objects.bulk_update(ticket_ts_updates, ["created_at", "updated_at"])

        # Set item_id on comments now that tickets have IDs, then bulk_create
        all_comments: list[Comment] = []
        # (ticket, public customer messages, public agent replies) — private notes are excluded
        # from every denormalized counter to match the live signal path.
        ticket_counter_updates: list[tuple[Ticket, int, int]] = []
        for idx, comments_list, cust_count, agent_count in ticket_comments_map:
            if idx >= len(created_tickets):
                continue
            ticket_obj = created_tickets[idx]
            for c in comments_list:
                c.item_id = str(ticket_obj.id)
            all_comments.extend(comments_list)
            if comments_list:
                ticket_counter_updates.append((ticket_obj, cust_count, agent_count))

        if all_comments:
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

        # Update denormalized counters per ticket. All of these back the customer-facing widget
        # (message_count, last_message_*, unread badge), so they must exclude private notes — see
        # the counting loop above and signals.update_ticket_on_message.
        for ticket_obj, cust_count, agent_count in ticket_counter_updates:
            update_fields_dict: dict[str, Any] = {
                "message_count": F("message_count") + cust_count + agent_count,
            }
            # last_message_* is shown to the customer, so use the latest non-private comment.
            # Comments are appended in Zendesk chronological order, so reverse-scan for the
            # newest visible one.
            ticket_comments = [c for c in all_comments if c.item_id == str(ticket_obj.id)]
            last_visible = next((c for c in reversed(ticket_comments) if not _comment_is_private(c)), None)
            if last_visible is not None:
                update_fields_dict["last_message_at"] = last_visible.created_at
                update_fields_dict["last_message_text"] = (last_visible.content or "")[:500]
            if cust_count:
                update_fields_dict["unread_team_count"] = F("unread_team_count") + cust_count
            if agent_count:
                update_fields_dict["unread_customer_count"] = F("unread_customer_count") + agent_count
            Ticket.objects.filter(team_id=team.id, id=ticket_obj.id).update(**update_fields_dict)

        imported = len(created_tickets)

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
