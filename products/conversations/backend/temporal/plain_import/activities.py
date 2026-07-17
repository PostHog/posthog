"""Temporal activities for Plain historical thread import."""

from __future__ import annotations

import uuid
import mimetypes
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from temporalio import activity, workflow

with workflow.unsafe.imports_passed_through():
    from django.db import transaction
    from django.db.models import F, Max
    from django.utils import timezone
    from django.utils.dateparse import parse_datetime

    from posthog.models import Tag, Team
    from posthog.models.comment import Comment
    from posthog.models.tag import tagify
    from posthog.models.tagged_item import TaggedItem
    from posthog.sync import database_sync_to_async
    from posthog.temporal.common.client import async_connect
    from posthog.temporal.common.heartbeat import Heartbeater

    from products.conversations.backend.models import EmailChannel, PlainImportJob, Ticket
    from products.conversations.backend.models.constants import Channel, Status
    from products.conversations.backend.services.attachments import (
        CONVERSATIONS_MAX_IMAGE_BYTES,
        build_content_with_images,
        save_file_to_uploaded_media,
    )
    from products.conversations.backend.temporal.plain_import.client import (
        PlainAttachmentTooLargeError,
        PlainCredentials,
        PlainImportClient,
    )
    from products.conversations.backend.temporal.plain_import.mappers import (
        extract_entry_attachments,
        extract_entry_author,
        extract_entry_body,
        map_plain_author_type,
        map_plain_channel_source,
        map_plain_priority,
        map_plain_status,
    )

logger = structlog.get_logger(__name__)


@dataclass
class EnumerateThreadsInput:
    job_id: str
    cursor: str | None = None


@dataclass
class EnumerateThreadsOutput:
    thread_ids: list[str]
    next_cursor: str | None
    end_of_stream: bool


@dataclass
class ImportBatchInput:
    job_id: str
    team_id: int
    thread_ids: list[str]
    dry_run: bool = False
    # Fallback EmailChannel (UUID str) for email-sourced threads. None = leave email_config null.
    default_email_channel_id: str | None = None


@dataclass
class ImportBatchOutput:
    imported: int
    skipped: int
    failed: int


@dataclass
class AwaitBatchInput:
    child_id: str
    thread_count: int


@dataclass
class UpdateJobStatusInput:
    job_id: str
    status: str
    latest_error: str | None = None


@dataclass
class UpdateJobProgressInput:
    # Absolute cumulative counts, not deltas. The coordinator owns these counters and tracks running
    # totals (carried across continue-as-new via the *_offset inputs), so it can write the absolute
    # value each time. This makes the write idempotent: a Temporal activity retry that lands after
    # the DB commit but before completion is acknowledged just re-sets the same value instead of
    # re-adding a delta and inflating the totals. None means "leave this counter untouched".
    job_id: str
    processed: int | None = None
    imported: int | None = None
    skipped: int | None = None
    failed: int | None = None
    total: int | None = None
    export_cursor: str | None = None


def _parse_plain_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone=UTC)
    return parsed


def _credentials_from_job(job: PlainImportJob) -> PlainCredentials:
    inputs = job.job_inputs or {}
    api_key = str(inputs.get("api_key") or "")
    region = str(inputs.get("region") or "")
    if not api_key or not region:
        raise ValueError("Plain import job is missing credentials")
    return PlainCredentials(api_key=api_key, region=region)


def _strip_nul(value: str) -> str:
    return value.replace("\x00", "") if "\x00" in value else value


def _comment_is_private(comment: Comment) -> bool:
    ctx = comment.item_context
    return isinstance(ctx, dict) and ctx.get("is_private") is True


def _guess_content_type(file_name: str, file_extension: str | None) -> str:
    if file_extension:
        guessed, _ = mimetypes.guess_type(f"file.{file_extension.lstrip('.')}")
        if guessed:
            return guessed
    guessed, _ = mimetypes.guess_type(file_name)
    return guessed or "application/octet-stream"


def _process_attachments(
    client: PlainImportClient,
    team: Team,
    entry: dict[str, Any],
    content: str,
    rich_content: dict[str, Any] | None,
) -> tuple[str, dict[str, Any] | None]:
    images: list[dict[str, Any]] = []
    file_links: list[str] = []
    for attachment in extract_entry_attachments(entry):
        attachment_id = str(attachment["id"])
        file_name = attachment.get("fileName") or "attachment"
        content_type = (attachment.get("fileMimeType") or "").strip() or _guess_content_type(
            file_name, attachment.get("fileExtension")
        )
        try:
            raw = client.download_attachment(attachment_id, max_bytes=CONVERSATIONS_MAX_IMAGE_BYTES)
        except PlainAttachmentTooLargeError:
            logger.warning(
                "plain_import_attachment_too_large",
                team_id=team.id,
                file_name=file_name,
                max_bytes=CONVERSATIONS_MAX_IMAGE_BYTES,
            )
            continue
        except Exception as exc:
            logger.warning(
                "plain_import_attachment_download_failed",
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


def _import_thread_batch_sync(input: ImportBatchInput) -> ImportBatchOutput:
    job = PlainImportJob.objects.for_team(input.team_id).get(id=input.job_id)
    team = Team.objects.get(id=input.team_id)
    credentials = _credentials_from_job(job)
    client = PlainImportClient(credentials)

    default_email_channel = None
    if input.default_email_channel_id:
        default_email_channel = EmailChannel.objects.filter(team_id=team.id, id=input.default_email_channel_id).first()

    existing_ids = set(
        Ticket.objects.filter(team_id=input.team_id)
        .filter(plain_thread_id__in=input.thread_ids)
        .values_list("plain_thread_id", flat=True)
    )
    to_import = [tid for tid in input.thread_ids if tid not in existing_ids]
    skipped = len(input.thread_ids) - len(to_import)

    # Re-import backfill: tickets a previous run imported without an email channel adopt this
    # run's default when they are email-sourced (channel_source=email).
    if existing_ids and default_email_channel is not None and not input.dry_run:
        backfilled = Ticket.objects.filter(
            team_id=input.team_id,
            plain_thread_id__in=existing_ids,
            email_config__isnull=True,
            channel_source=Channel.EMAIL,
        ).update(email_config=default_email_channel)
        if backfilled:
            logger.info("plain_import_backfilled_email_channel", team_id=team.id, backfilled=backfilled)

    if not to_import:
        return ImportBatchOutput(imported=0, skipped=skipped, failed=0)

    if input.dry_run:
        logger.info("plain_import_dry_run_batch", team_id=team.id, would_import=len(to_import), skipped=skipped)
        return ImportBatchOutput(imported=len(to_import), skipped=skipped, failed=0)

    imported = 0
    failed = 0

    # Phase 1: Fetch all threads + timeline entries OUTSIDE the transaction (network I/O).
    thread_data: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    for thread_id in to_import:
        try:
            plain_thread = client.fetch_thread(thread_id)
            timeline_entries = client.fetch_timeline_entries(thread_id)
            thread_data.append((plain_thread, timeline_entries))
        except Exception as exc:
            failed += 1
            logger.exception(
                "plain_import_thread_fetch_failed",
                team_id=team.id,
                plain_thread_id=thread_id,
                error=str(exc),
            )

    if not thread_data:
        return ImportBatchOutput(imported=0, skipped=skipped, failed=failed)

    # Phase 2: Process each thread (attachments involve network I/O, so outside atomic).
    tickets_to_create: list[Ticket] = []
    ticket_comments_map: list[tuple[int, list[Comment], int, int]] = []
    ticket_create_to_data_idx: list[int] = []
    ticket_tags_map: list[tuple[int, list[str]]] = []

    for idx, (plain_thread, timeline_entries) in enumerate(thread_data):
        plain_id = str(plain_thread["id"])
        try:
            customer = plain_thread.get("customer") or {}
            email_obj = customer.get("email") or {}
            requester_email = _strip_nul(
                (email_obj.get("email") or f"plain-customer-{customer.get('id') or plain_id}").strip()
            )
            requester_name = _strip_nul((customer.get("fullName") or "").strip())
            # Access identity: use the Plain customer email verbatim. Same identity-poisoning
            # reasoning as the Zendesk import — do not resolve via person properties.email.
            distinct_id = requester_email

            anonymous_traits: dict[str, str] = {}
            if requester_name:
                anonymous_traits["name"] = requester_name
            if "@" in requester_email:
                anonymous_traits["email"] = requester_email

            message_source = ((plain_thread.get("firstInboundMessageInfo") or {}).get("messageSource")) or None
            channel_source = map_plain_channel_source(message_source)
            email_config = default_email_channel if channel_source == Channel.EMAIL else None

            ticket = Ticket(
                team=team,
                channel_source=channel_source,
                widget_session_id=str(uuid.uuid4()),
                distinct_id=distinct_id,
                status=map_plain_status(plain_thread.get("status")),
                priority=map_plain_priority(plain_thread.get("priority")),
                email_subject=_strip_nul(plain_thread.get("title") or "")[:500] or None,
                email_from=requester_email if "@" in requester_email else None,
                email_config=email_config,
                anonymous_traits=anonymous_traits,
                plain_thread_id=plain_id,
            )

            plain_tags = {
                tagify(_strip_nul(str((label.get("labelType") or {}).get("name") or "")))[:255]
                for label in (plain_thread.get("labels") or [])
                if isinstance(label, dict)
            }
            tag_names = sorted(t for t in plain_tags if t)

            comments_to_create: list[Comment] = []
            customer_message_count = 0
            agent_reply_count = 0

            for timeline_node in timeline_entries:
                entry = timeline_node.get("entry") or {}
                if not isinstance(entry, dict):
                    continue
                actor = timeline_node.get("actor") or {}
                actor_typename = actor.get("__typename") if isinstance(actor, dict) else None
                entry_typename = entry.get("__typename")
                author_type, is_private = map_plain_author_type(
                    actor_typename=actor_typename, entry_typename=entry_typename
                )
                body = _strip_nul(extract_entry_body(entry))
                rich_content: dict[str, Any] | None = None
                body, rich_content = _process_attachments(client, team, entry, body, rich_content)
                if not body and not rich_content:
                    continue

                if is_private:
                    pass
                elif author_type == "customer":
                    customer_message_count += 1
                else:
                    agent_reply_count += 1

                author_name, author_email = extract_entry_author(entry)
                if author_name:
                    author_name = _strip_nul(author_name)
                if author_email:
                    author_email = _strip_nul(author_email)
                item_context: dict[str, Any] = {
                    "author_type": author_type,
                    "is_private": is_private,
                    "from_plain": True,
                    "plain_timeline_entry_id": timeline_node.get("id"),
                }
                if author_name:
                    item_context["author_name"] = author_name
                if author_email:
                    item_context["author_email"] = author_email

                timestamp = (timeline_node.get("timestamp") or {}).get("iso8601")
                comment_created_at = _parse_plain_datetime(timestamp)
                comment_obj = Comment(
                    team=team,
                    scope="conversations_ticket",
                    item_id="",
                    content=_strip_nul(body),
                    rich_content=rich_content,
                    item_context=item_context,
                )
                comment_obj._plain_created_at = comment_created_at  # type: ignore[attr-defined]
                comments_to_create.append(comment_obj)

            # Enqueue the ticket, its tags and its comments together only after every label,
            # timeline entry and attachment for this thread processed without error. Appending
            # the ticket earlier meant a mid-thread exception (e.g. a media upload failure) left a
            # partial, comment-less ticket that phase 3 still persisted — and a retry then skipped
            # it by plain_thread_id, permanently dropping its comments and tags.
            create_idx = len(tickets_to_create)
            tickets_to_create.append(ticket)
            ticket_create_to_data_idx.append(idx)
            ticket_tags_map.append((create_idx, tag_names))
            ticket_comments_map.append((create_idx, comments_to_create, customer_message_count, agent_reply_count))
        except Exception as exc:
            failed += 1
            logger.exception(
                "plain_import_thread_failed",
                team_id=team.id,
                plain_thread_id=plain_id,
                error=str(exc),
            )

    if not tickets_to_create:
        return ImportBatchOutput(imported=0, skipped=skipped, failed=failed)

    all_tag_names = {name for _, names in ticket_tags_map for name in names}
    tags_by_name = {name: Tag.objects.get_or_create(name=name, team_id=team.id)[0] for name in all_tag_names}

    # Phase 3: Persist tickets + comments in a single transaction (no network I/O).
    # IMPORTANT: bulk_create/bulk_update ONLY — bypasses $conversation_* signals so a
    # historical backfill stays silent (no workflows, no outbound replies).
    with transaction.atomic():
        Team.objects.select_for_update().get(id=team.id)
        max_num = Ticket.objects.filter(team_id=team.id).aggregate(Max("ticket_number"))["ticket_number__max"] or 0
        for offset, ticket_to_number in enumerate(tickets_to_create):
            ticket_to_number.ticket_number = max_num + 1 + offset
        created_tickets = Ticket.objects.bulk_create(tickets_to_create)

        ticket_ts_updates: list[Ticket] = []
        for i, ticket_obj in enumerate(created_tickets):
            data_idx = ticket_create_to_data_idx[i]
            plain_thread = thread_data[data_idx][0]
            created_at = _parse_plain_datetime((plain_thread.get("createdAt") or {}).get("iso8601"))
            if created_at:
                ticket_obj.created_at = created_at
                ticket_obj.updated_at = created_at
                ticket_ts_updates.append(ticket_obj)
        if ticket_ts_updates:
            Ticket.objects.bulk_update(ticket_ts_updates, ["created_at", "updated_at"])

        tagged_items_to_create = [
            TaggedItem(tag=tags_by_name[name], ticket=created_tickets[idx])
            for idx, names in ticket_tags_map
            if idx < len(created_tickets)
            for name in names
        ]
        if tagged_items_to_create:
            TaggedItem.objects.bulk_create(tagged_items_to_create, ignore_conflicts=True)

        all_comments: list[Comment] = []
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
            comment_ts_updates: list[Comment] = []
            for c in created_comments:
                historical = getattr(c, "_plain_created_at", None)
                if historical is not None:
                    c.created_at = historical
                    comment_ts_updates.append(c)
            if comment_ts_updates:
                Comment.objects.bulk_update(comment_ts_updates, ["created_at"])

        for ticket_obj, cust_count, agent_count in ticket_counter_updates:
            update_fields_dict: dict[str, Any] = {
                "message_count": F("message_count") + cust_count + agent_count,
            }
            ticket_comments = [c for c in all_comments if c.item_id == str(ticket_obj.id)]
            last_visible = next((c for c in reversed(ticket_comments) if not _comment_is_private(c)), None)
            if last_visible is not None:
                update_fields_dict["last_message_at"] = last_visible.created_at
                update_fields_dict["last_message_text"] = (last_visible.content or "")[:500]
            is_active = ticket_obj.status in (Status.NEW, Status.OPEN)
            if is_active and cust_count:
                update_fields_dict["unread_team_count"] = F("unread_team_count") + cust_count
            if is_active and agent_count:
                update_fields_dict["unread_customer_count"] = F("unread_customer_count") + agent_count
            Ticket.objects.filter(team_id=team.id, id=ticket_obj.id).update(**update_fields_dict)

        imported = len(created_tickets)

    return ImportBatchOutput(imported=imported, skipped=skipped, failed=failed)


@activity.defn
async def plain_import_enumerate_threads_activity(input: EnumerateThreadsInput) -> EnumerateThreadsOutput:
    async with Heartbeater():
        return await database_sync_to_async(_enumerate_threads_sync, thread_sensitive=False)(input)


def _enumerate_threads_sync(input: EnumerateThreadsInput) -> EnumerateThreadsOutput:
    job = PlainImportJob.objects.unscoped().get(id=input.job_id)
    client = PlainImportClient(_credentials_from_job(job))
    thread_ids, next_cursor, end_of_stream = client.list_thread_ids_page(cursor=input.cursor)
    return EnumerateThreadsOutput(thread_ids=thread_ids, next_cursor=next_cursor, end_of_stream=end_of_stream)


@activity.defn
async def plain_import_batch_activity(input: ImportBatchInput) -> ImportBatchOutput:
    async with Heartbeater():
        return await database_sync_to_async(_import_thread_batch_sync, thread_sensitive=False)(input)


@activity.defn
async def plain_import_await_batch_activity(input: AwaitBatchInput) -> ImportBatchOutput:
    """Attach to an already-existing batch child workflow and return its real counts.

    Reached when the coordinator tries to (re)start a batch child whose id already exists — a
    still-running or already-completed prior attempt. Returning zeros there would let the
    coordinator advance its cursor past a batch whose outcome was never counted; instead we wait
    for the existing execution (workflows can't await a child they didn't start this run) and roll
    up its actual totals. Idempotent: a retry just re-attaches by workflow id. If the existing
    execution failed, count the whole batch as failed so the job reflects it rather than silently
    dropping the threads.
    """
    async with Heartbeater():
        client = await async_connect()
        handle = client.get_workflow_handle(input.child_id)
        try:
            result: Any = await handle.result()
        except Exception:
            activity.logger.warning("plain_import_await_batch_failed", extra={"child_id": input.child_id})
            return ImportBatchOutput(imported=0, skipped=0, failed=input.thread_count)
    return ImportBatchOutput(
        imported=int(result["imported"]),
        skipped=int(result["skipped"]),
        failed=int(result["failed"]),
    )


def _update_job_status_sync(input: UpdateJobStatusInput) -> None:
    job = PlainImportJob.objects.unscoped().get(id=input.job_id)
    update_fields = ["status", "updated_at"]
    job.status = input.status
    if input.latest_error is not None:
        job.latest_error = input.latest_error
        update_fields.append("latest_error")
    if input.status == PlainImportJob.Status.RUNNING and job.started_at is None:
        job.started_at = timezone.now()
        update_fields.append("started_at")
    if input.status in (PlainImportJob.Status.COMPLETED, PlainImportJob.Status.FAILED):
        job.finished_at = timezone.now()
        update_fields.append("finished_at")
    job.save(update_fields=update_fields)


def _update_job_progress_sync(input: UpdateJobProgressInput) -> None:
    updates: dict[str, Any] = {}
    if input.processed is not None:
        updates["processed_tickets"] = input.processed
    if input.imported is not None:
        updates["imported_tickets"] = input.imported
    if input.skipped is not None:
        updates["skipped_tickets"] = input.skipped
    if input.failed is not None:
        updates["failed_tickets"] = input.failed
    if input.total is not None:
        updates["total_tickets"] = input.total
    if input.export_cursor is not None:
        updates["export_cursor"] = input.export_cursor
    if updates:
        PlainImportJob.objects.unscoped().filter(id=input.job_id).update(**updates)


@activity.defn
async def plain_import_update_job_status_activity(input: UpdateJobStatusInput) -> None:
    async with Heartbeater():
        await database_sync_to_async(_update_job_status_sync, thread_sensitive=False)(input)


@activity.defn
async def plain_import_update_job_progress_activity(input: UpdateJobProgressInput) -> None:
    async with Heartbeater():
        await database_sync_to_async(_update_job_progress_sync, thread_sensitive=False)(input)
