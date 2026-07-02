"""Temporal activities for Zendesk historical ticket import."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from django.db import transaction
from django.db.models import F, Func, Max, Value
from django.db.models.fields.json import JSONField
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.html import strip_tags

import structlog
from temporalio import activity

from posthog.models import Team
from posthog.models.comment import Comment
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater

from products.conversations.backend.models import Ticket, ZendeskImportJob
from products.conversations.backend.person_lookup import _get_persons_by_email
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
from products.conversations.backend.temporal.zendesk_import.constants import EMAIL_RESOLUTION_BATCH_SIZE
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


def _comment_body(comment: dict[str, Any]) -> str:
    body = (comment.get("body") or "").strip()
    if body:
        return body
    html_body = comment.get("html_body") or ""
    return strip_tags(html_body).strip()


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


# nosemgrep: python.django.security.audit.extends-custom-expression.extends-custom-expression -- constant template + operator; operands are a column F() and a parameterized Value, never user input
class _JSONBConcat(Func):
    """Atomic ``jsonb || jsonb`` merge (right-hand keys win).

    Up to ``MAX_CONCURRENT_BATCH_WORKFLOWS`` batch activities run at once and each
    updates ``email_distinct_id_cache``. A full-object ``save()`` is last-writer-wins
    and silently drops every other batch's newly-resolved keys. Merging at the DB in a
    single row-locked ``UPDATE`` serializes concurrent writers, so no entries are lost.
    """

    function = None
    arg_joiner = " || "
    template = "%(expressions)s"


def _resolve_distinct_ids(
    team: Team,
    emails: set[str],
    cache: dict[str, str],
) -> dict[str, str]:
    unresolved = sorted(email for email in emails if email and email.lower() not in cache)
    for i in range(0, len(unresolved), EMAIL_RESOLUTION_BATCH_SIZE):
        batch = unresolved[i : i + EMAIL_RESOLUTION_BATCH_SIZE]
        matched = _get_persons_by_email(team, batch)
        for email in batch:
            person = matched.get(email.lower())
            if person is not None and person.distinct_ids:
                cache[email.lower()] = person.distinct_ids[0]
            else:
                cache[email.lower()] = email
    return cache


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

    emails: set[str] = set()
    for zendesk_ticket in zendesk_tickets:
        requester_id = zendesk_ticket.get("requester_id")
        if requester_id is None:
            continue
        user = users_by_id.get(int(requester_id), {})
        email = (user.get("email") or "").strip()
        if email:
            emails.add(email)

    cache: dict[str, str] = dict(job.email_distinct_id_cache or {})
    resolved_before = set(cache)
    cache = _resolve_distinct_ids(team, emails, cache)
    new_entries = {key: cache[key] for key in cache.keys() - resolved_before}
    if new_entries:
        ZendeskImportJob.objects.for_team(input.team_id).filter(id=input.job_id).update(
            email_distinct_id_cache=_JSONBConcat(
                F("email_distinct_id_cache"),
                Value(new_entries, output_field=JSONField()),
                output_field=JSONField(),
            ),
            updated_at=timezone.now(),
        )

    imported = 0
    failed = 0

    # Phase 1: Fetch all comments + attachments OUTSIDE the transaction (network I/O).
    ticket_data: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    for zendesk_ticket in zendesk_tickets:
        zendesk_id = int(zendesk_ticket["id"])
        try:
            comments = client.fetch_comments(zendesk_id)
            # Resolve any unknown comment authors
            for zd_comment in comments:
                author_id = zd_comment.get("author_id")
                if author_id is not None and int(author_id) not in users_by_id:
                    author = client.fetch_users([int(author_id)]).get(int(author_id), {})
                    if author:
                        users_by_id[int(author_id)] = author
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

    # Phase 2: Process each ticket (attachments involve network I/O, so outside atomic).
    tickets_to_create: list[Ticket] = []
    ticket_comments_map: list[tuple[int, list[Comment], int, int]] = []
    # Maps index in tickets_to_create → index in ticket_data
    ticket_create_to_data_idx: list[int] = []

    for idx, (zendesk_ticket, comments) in enumerate(ticket_data):
        zendesk_id = int(zendesk_ticket["id"])
        try:
            requester = users_by_id.get(int(zendesk_ticket.get("requester_id") or 0), {})
            requester_email = (requester.get("email") or f"zendesk-user-{zendesk_ticket.get('requester_id')}").strip()
            distinct_id = cache.get(requester_email.lower(), requester_email)

            ticket = Ticket(
                team=team,
                channel_source=default_channel_source(),
                widget_session_id=str(uuid.uuid4()),
                distinct_id=distinct_id,
                status=map_zendesk_status(zendesk_ticket.get("status")),
                priority=map_zendesk_priority(zendesk_ticket.get("priority")),
                email_subject=(zendesk_ticket.get("subject") or "")[:500] or None,
                email_from=requester_email if "@" in requester_email else None,
                zendesk_ticket_id=zendesk_id,
            )
            create_idx = len(tickets_to_create)
            tickets_to_create.append(ticket)
            ticket_create_to_data_idx.append(idx)

            comments_to_create: list[Comment] = []
            customer_message_count = 0
            team_message_count = 0

            for zd_comment in comments:
                author_id = zd_comment.get("author_id")
                author = users_by_id.get(int(author_id), {}) if author_id is not None else {}

                is_public = bool(zd_comment.get("public", True))
                author_type, is_private = map_zendesk_author_type(role=author.get("role"), is_public=is_public)
                body = _comment_body(zd_comment)
                rich_content: dict[str, Any] | None = None
                body, rich_content = _process_attachments(client, team, zd_comment, body, rich_content)
                if not body and not rich_content:
                    continue

                if is_private:
                    team_message_count += 1
                elif author_type == "customer":
                    customer_message_count += 1
                else:
                    team_message_count += 1

                comment_created_at = _parse_zendesk_datetime(zd_comment.get("created_at"))
                comment_obj = Comment(
                    team=team,
                    scope="conversations_ticket",
                    item_id="",  # placeholder — set after ticket gets an ID
                    content=body,
                    rich_content=rich_content,
                    item_context={
                        "author_type": author_type,
                        "is_private": is_private,
                        "from_zendesk": True,
                        "zendesk_comment_id": zd_comment.get("id"),
                    },
                )
                # auto_now_add clobbers created_at during bulk_create, so stash the
                # historical value on a shadow attr and re-apply it via bulk_update.
                comment_obj._zendesk_created_at = comment_created_at  # type: ignore[attr-defined]
                comments_to_create.append(comment_obj)

            ticket_comments_map.append((create_idx, comments_to_create, customer_message_count, team_message_count))
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
        ticket_counter_updates: list[tuple[Ticket, int, int, int]] = []
        for idx, comments_list, cust_count, team_count in ticket_comments_map:
            if idx >= len(created_tickets):
                continue
            ticket_obj = created_tickets[idx]
            for c in comments_list:
                c.item_id = str(ticket_obj.id)
            all_comments.extend(comments_list)
            if comments_list:
                ticket_counter_updates.append((ticket_obj, len(comments_list), cust_count, team_count))

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

        # Update denormalized counters per ticket
        for ticket_obj, msg_count, cust_count, team_count in ticket_counter_updates:
            update_fields_dict: dict[str, Any] = {
                "message_count": F("message_count") + msg_count,
            }
            # Find the last comment for this ticket
            ticket_comments = [c for c in all_comments if c.item_id == str(ticket_obj.id)]
            if ticket_comments:
                last = ticket_comments[-1]
                update_fields_dict["last_message_at"] = last.created_at
                update_fields_dict["last_message_text"] = (last.content or "")[:500]
            if cust_count:
                update_fields_dict["unread_team_count"] = F("unread_team_count") + cust_count
            if team_count:
                update_fields_dict["unread_customer_count"] = F("unread_customer_count") + team_count
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
    # Narrow update_fields so this write can't clobber counters / cursor / cache
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
