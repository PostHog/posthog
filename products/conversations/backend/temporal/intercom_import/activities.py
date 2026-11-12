"""Temporal activities for Intercom historical conversation import."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from temporalio import activity, workflow

# The package __init__ imports this module inside the Temporal workflow sandbox; only the activity
# sync helpers touch Django/models at runtime, so pass them through the sandbox unmodified.
with workflow.unsafe.imports_passed_through():
    from django.utils import timezone

    from posthog.dataclasses import frozen
    from posthog.event_usage import report_team_action
    from posthog.exceptions_capture import capture_exception
    from posthog.models import Team
    from posthog.models.comment import Comment
    from posthog.models.tag import tagify
    from posthog.sync import database_sync_to_async
    from posthog.temporal.common.heartbeat import Heartbeater

    from products.conversations.backend.models import EmailChannel, IntercomImportJob, PurgedTicketThread, Ticket
    from products.conversations.backend.models.constants import Channel
    from products.conversations.backend.models.purged_ticket_thread import ticket_thread_key
    from products.conversations.backend.services.attachments import (
        CONVERSATIONS_MAX_IMAGE_BYTES,
        MAX_ATTACHMENTS_PER_MESSAGE,
        AttachmentStorageError,
        build_content_with_images,
        discard_rehosted_attachments,
        sanitize_attachment_filename,
        save_file_to_uploaded_media,
    )
    from products.conversations.backend.temporal.intercom_import.client import (
        IntercomAttachmentTooLargeError,
        IntercomCredentials,
        IntercomImportClient,
        IntercomNotFoundError,
        is_retryable_error,
    )
    from products.conversations.backend.temporal.intercom_import.mappers import (
        CUSTOMER_AUTHOR_TYPES,
        map_intercom_author_type,
        map_intercom_priority,
        map_intercom_state,
    )
    from products.conversations.backend.temporal.ticket_import.persistence import (
        BuiltTicket,
        persist_ticket_batch,
        resolve_email_channels,
        resolve_tags,
        set_historical_created_at,
        strip_nul,
    )

logger = structlog.get_logger(__name__)

# A contact controls how many files they attach, so cap what one conversation can make the import
# download and store. Attachments past the budget are skipped, not failed.
MAX_ATTACHMENT_BYTES_PER_CONVERSATION = 200 * 1024 * 1024


@frozen
class EnumerateConversationsInput:
    job_id: str
    cursor: str | None = None


@frozen
class EnumerateConversationsOutput:
    conversation_ids: list[str]
    next_cursor: str | None


@frozen
class ImportBatchInput:
    job_id: str
    team_id: int
    conversation_ids: list[str]
    default_email_channel_id: str | None = None


@frozen
class ImportBatchOutput:
    imported: int
    skipped: int
    failed: int


@frozen
class UpdateJobStatusInput:
    job_id: str
    status: str
    latest_error: str | None = None


@frozen
class UpdateJobProgressInput:
    """Absolute cumulative counts, so replaying an update after a retry is harmless."""

    job_id: str
    total: int
    processed: int
    imported: int
    skipped: int
    failed: int
    export_cursor: str | None = None


@frozen
class _ConversationPartition:
    existing_ids: set[str]
    to_import: list[str]
    skipped: int


@frozen
class _Requester:
    name: str
    email: str
    contact_id: str


class _AttachmentBudget:
    def __init__(self, max_bytes: int, staged: list[dict[str, Any]]) -> None:
        self.remaining = max_bytes
        # Uploads not yet referenced by a persisted comment, deleted if this attempt gives up.
        self.staged = staged


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


def _parse_unix_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _credentials_from_job(job: IntercomImportJob) -> IntercomCredentials:
    inputs = job.job_inputs or {}
    region = str(inputs.get("region") or "")
    access_token = str(inputs.get("access_token") or "")
    if not region or not access_token:
        raise ValueError("Intercom import job is missing credentials")
    return IntercomCredentials(region=region, access_token=access_token)


def _clean(value: Any) -> str:
    return strip_nul(str(value or "").strip())


def _partition_new_conversations(team_id: int, conversation_ids: list[str]) -> _ConversationPartition:
    # all_objects so a soft-deleted import still counts as present. Re-inserting it would hit the
    # unique constraint, or reopen a deleted thread.
    existing_ids = {
        cid
        for cid in Ticket.all_objects.filter(team_id=team_id)
        .filter(intercom_conversation_id__in=conversation_ids)
        .values_list("intercom_conversation_id", flat=True)
        if cid is not None
    }
    # A purged import stays out, so the next import does not bring the deleted ticket back.
    purged_keys = set(
        PurgedTicketThread.objects.for_team(team_id)
        .filter(thread_key__in=[ticket_thread_key(intercom_conversation_id=cid) for cid in conversation_ids])
        .values_list("thread_key", flat=True)
    )
    to_import = [
        cid
        for cid in conversation_ids
        if cid not in existing_ids and ticket_thread_key(intercom_conversation_id=cid) not in purged_keys
    ]
    return _ConversationPartition(
        existing_ids=existing_ids, to_import=to_import, skipped=len(conversation_ids) - len(to_import)
    )


def _backfill_missing_email_channel(team_id: int, existing_ids: set[str], default_email_channel: EmailChannel) -> None:
    # Re-import backfill: tickets a previous run imported without an email channel adopt this
    # run's default. QuerySet.update() bypasses the signal receivers and keeps updated_at.
    backfilled = Ticket.objects.filter(
        team_id=team_id,
        intercom_conversation_id__in=existing_ids,
        email_config__isnull=True,
    ).update(email_config=default_email_channel)
    if backfilled:
        logger.info("intercom_import_backfilled_email_channel", team_id=team_id, backfilled=backfilled)


def _resolve_requester(client: IntercomImportClient, conversation: dict[str, Any]) -> _Requester:
    # Contact-initiated conversations carry the contact's name/email on the source author.
    # Outbound (admin-initiated) ones don't, so look up the first attached contact instead.
    author = (conversation.get("source") or {}).get("author") or {}
    if author.get("type") in CUSTOMER_AUTHOR_TYPES:
        return _Requester(
            name=_clean(author.get("name")), email=_clean(author.get("email")), contact_id=_clean(author.get("id"))
        )
    contacts = (conversation.get("contacts") or {}).get("contacts") or []
    contact_id = _clean(contacts[0].get("id")) if contacts else ""
    if not contact_id:
        return _Requester(name="", email="", contact_id="")
    try:
        contact = client.fetch_contact(contact_id)
    except IntercomNotFoundError:
        # A deleted contact shouldn't drop the whole conversation, so import it without an email.
        # Any other failure propagates so Temporal retries rather than saving a ticket with no email.
        logger.warning("intercom_import_contact_not_found", contact_id=contact_id)
        return _Requester(name="", email="", contact_id=contact_id)
    return _Requester(name=_clean(contact.get("name")), email=_clean(contact.get("email")), contact_id=contact_id)


def _process_attachments(
    client: IntercomImportClient,
    team: Team,
    attachments: list[dict[str, Any]],
    content: str,
    budget: _AttachmentBudget,
) -> tuple[str, dict[str, Any] | None]:
    images: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    for attachment in attachments[:MAX_ATTACHMENTS_PER_MESSAGE]:
        url = attachment.get("url")
        # Contacts choose the filename, and it is rendered inside Markdown link and image syntax.
        file_name = sanitize_attachment_filename(attachment.get("name"))
        content_type = attachment.get("content_type") or "application/octet-stream"
        if not url:
            continue
        max_bytes = min(CONVERSATIONS_MAX_IMAGE_BYTES, budget.remaining)
        if max_bytes <= 0:
            logger.warning("intercom_import_attachment_budget_exhausted", team_id=team.id, file_name=file_name)
            continue
        try:
            raw = client.download_attachment(url, max_bytes=max_bytes)
        except IntercomAttachmentTooLargeError as exc:
            # The bytes streamed before the cap tripped still count, or repeated oversized files
            # without an honest Content-Length would bypass the conversation budget.
            budget.remaining -= exc.bytes_read
            logger.warning(
                "intercom_import_attachment_too_large", team_id=team.id, file_name=file_name, max_bytes=max_bytes
            )
            continue
        except Exception as exc:
            # Timeouts and 5xx retry the whole batch through Temporal; an expired or deleted link
            # (4xx) won't come back on a retry, so skip it. Log only the type, because a requests
            # error message embeds the signed URL.
            if is_retryable_error(exc):
                raise
            logger.warning(
                "intercom_import_attachment_download_failed",
                team_id=team.id,
                file_name=file_name,
                error_type=type(exc).__name__,
                status_code=getattr(exc, "status_code", None),
            )
            continue
        budget.remaining -= len(raw)
        is_image = content_type.startswith("image/")
        media_url = save_file_to_uploaded_media(
            team, file_name, content_type, raw, validate_images=is_image, raise_on_storage_error=True
        )
        if not media_url:
            continue
        entry = {"url": media_url, "name": file_name}
        budget.staged.append(entry)
        (images if is_image else files).append(entry)
    return build_content_with_images(content, None, images, files)


def _build_comment(
    client: IntercomImportClient,
    team: Team,
    message: dict[str, Any],
    *,
    part_type: str | None,
    created_at: Any,
    budget: _AttachmentBudget,
) -> _BuiltComment | None:
    """Build one Comment from the conversation source or a part. Empty messages return None."""
    author = message.get("author") or {}
    author_type, is_private = map_intercom_author_type(author_type=author.get("type"), part_type=part_type)
    body, rich_content = _process_attachments(
        client, team, message.get("attachments") or [], strip_nul((message.get("body") or "").strip()), budget
    )
    if not body and not rich_content:
        return None

    item_context: dict[str, Any] = {
        "author_type": author_type,
        "is_private": is_private,
        "from_intercom": True,
        "intercom_part_id": message.get("id"),
    }
    author_name = _clean(author.get("name"))
    author_email = _clean(author.get("email"))
    if author_name:
        item_context["author_name"] = author_name
    if author_email:
        item_context["author_email"] = author_email

    comment = Comment(
        team=team,
        scope="conversations_ticket",
        item_id="",  # placeholder — set after ticket gets an ID
        content=strip_nul(body),
        rich_content=rich_content,
        item_context=item_context,
    )
    set_historical_created_at(comment, _parse_unix_timestamp(created_at))
    return _BuiltComment(comment=comment, author_type=author_type, is_private=is_private)


def _build_comments(
    client: IntercomImportClient, team: Team, conversation: dict[str, Any], staged: list[dict[str, Any]]
) -> _BuiltComments:
    source = conversation.get("source") or {}
    parts = (conversation.get("conversation_parts") or {}).get("conversation_parts") or []

    budget = _AttachmentBudget(MAX_ATTACHMENT_BYTES_PER_CONVERSATION, staged)
    candidates = [
        _build_comment(client, team, source, part_type=None, created_at=conversation.get("created_at"), budget=budget)
    ]
    candidates.extend(
        _build_comment(
            client, team, part, part_type=part.get("part_type"), created_at=part.get("created_at"), budget=budget
        )
        for part in parts
    )

    built: list[Comment] = []
    customer_message_count = 0
    agent_reply_count = 0
    for built_comment in candidates:
        if built_comment is None:
            continue
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
    client: IntercomImportClient,
    team: Team,
    conversation: dict[str, Any],
    default_email_channel: EmailChannel | None,
    staged: list[dict[str, Any]],
) -> BuiltTicket:
    conversation_id = str(conversation["id"])
    requester = _resolve_requester(client, conversation)
    requester_email = requester.email if "@" in requester.email else ""
    # Intercom leads type their own email unverified, so the email must never become the widget
    # access identity: the widget grants a ticket to any viewer whose distinct_ids contain the
    # ticket's distinct_id, and many apps identify users by email. A namespaced id can't match a
    # real distinct_id. The email still drives display and replies, and restore-by-email proves
    # inbox ownership before granting access.
    distinct_id = f"intercom:{requester.contact_id or conversation_id}"

    anonymous_traits: dict[str, str] = {}
    if requester.name:
        anonymous_traits["name"] = requester.name
    if requester_email:
        anonymous_traits["email"] = requester_email

    source = conversation.get("source") or {}
    subject = _clean(source.get("subject")) or _clean(conversation.get("title"))

    ticket = Ticket(
        team=team,
        channel_source=Channel.EMAIL,
        widget_session_id=str(uuid.uuid4()),
        distinct_id=distinct_id,
        status=map_intercom_state(conversation.get("state")),
        priority=map_intercom_priority(conversation.get("priority")),
        email_subject=subject[:500] or None,
        email_from=requester_email or None,
        identity_verified=False,
        email_config=default_email_channel,
        anonymous_traits=anonymous_traits,
        intercom_conversation_id=conversation_id,
    )

    tags = (conversation.get("tags") or {}).get("tags") or []
    intercom_tags = {tagify(strip_nul(str(t.get("name") or "")))[:255] for t in tags if isinstance(t, dict)}
    tag_names = sorted(t for t in intercom_tags if t)

    built_comments = _build_comments(client, team, conversation, staged)
    return BuiltTicket(
        ticket=ticket,
        comments=built_comments.comments,
        tag_names=tag_names,
        customer_message_count=built_comments.customer_message_count,
        agent_reply_count=built_comments.agent_reply_count,
        created_at=_parse_unix_timestamp(conversation.get("created_at")),
        updated_at=_parse_unix_timestamp(conversation.get("updated_at")),
    )


def _should_retry_batch(exc: BaseException) -> bool:
    return is_retryable_error(exc) or isinstance(exc, AttachmentStorageError)


def _fetch_and_build_tickets(
    client: IntercomImportClient,
    team: Team,
    conversation_ids: list[str],
    default_email_channel: EmailChannel | None,
    staged: list[dict[str, Any]],
) -> tuple[list[BuiltTicket], int]:
    """Fetch each conversation and build its ticket straight away, outside the transaction.

    Attachment URLs expire 30 minutes after the fetch, so each conversation's attachments are
    downloaded right after it is fetched rather than after the whole batch.
    """
    built: list[BuiltTicket] = []
    failed = 0
    for conversation_id in conversation_ids:
        staged_before = len(staged)
        try:
            conversation = client.fetch_conversation(conversation_id)
            built.append(_build_ticket(client, team, conversation, default_email_channel, staged))
        except Exception as exc:
            # Rate limits, timeouts, 5xx and storage failures retry the whole batch through
            # Temporal. Nothing from this attempt is persisted yet, so the retry rebuilds it.
            if _should_retry_batch(exc):
                raise
            discard_rehosted_attachments(team, staged[staged_before:])
            del staged[staged_before:]
            failed += 1
            logger.exception(
                "intercom_import_conversation_failed",
                team_id=team.id,
                intercom_conversation_id=conversation_id,
                error=str(exc),
            )
    return built, failed


def _import_conversation_batch_sync(input: ImportBatchInput) -> ImportBatchOutput:
    job = IntercomImportJob.objects.for_team(input.team_id).get(id=input.job_id)
    team = Team.objects.get(id=input.team_id)
    client = IntercomImportClient(_credentials_from_job(job))
    _, default_email_channel = resolve_email_channels(team.id, input.default_email_channel_id)

    partition = _partition_new_conversations(input.team_id, input.conversation_ids)
    skipped = partition.skipped

    if partition.existing_ids and default_email_channel is not None:
        _backfill_missing_email_channel(input.team_id, partition.existing_ids, default_email_channel)

    if not partition.to_import:
        return ImportBatchOutput(imported=0, skipped=skipped, failed=0)

    staged: list[dict[str, Any]] = []
    try:
        built, failed = _fetch_and_build_tickets(client, team, partition.to_import, default_email_channel, staged)
        if not built:
            return ImportBatchOutput(imported=0, skipped=skipped, failed=failed)
        imported = persist_ticket_batch(team, built, resolve_tags(team.id, built))
    except Exception:
        # No comment references these uploads, so delete them rather than leave copies behind.
        discard_rehosted_attachments(team, staged)
        raise
    return ImportBatchOutput(imported=imported, skipped=skipped, failed=failed)


def _enumerate_conversations_sync(input: EnumerateConversationsInput) -> EnumerateConversationsOutput:
    job = IntercomImportJob.objects.unscoped().get(id=input.job_id)
    client = IntercomImportClient(_credentials_from_job(job))
    conversation_ids, next_cursor = client.list_conversation_ids_page(cursor=input.cursor)
    return EnumerateConversationsOutput(conversation_ids=conversation_ids, next_cursor=next_cursor)


def _report_import_finished(job: IntercomImportJob) -> None:
    try:
        report_team_action(
            job.team,
            "support import finished",
            {
                "source": "intercom",
                "import_job_id": str(job.id),
                "status": job.status,
                "imported": job.imported_conversations,
                "skipped": job.skipped_conversations,
                "failed": job.failed_conversations,
            },
        )
    except Exception as e:
        capture_exception(e, {"import_job_id": str(job.id)})


def _update_job_status_sync(input: UpdateJobStatusInput) -> None:
    job = IntercomImportJob.objects.unscoped().get(id=input.job_id)
    update_fields = ["status", "updated_at"]
    job.status = input.status
    if input.latest_error is not None:
        job.latest_error = input.latest_error
        update_fields.append("latest_error")
    if input.status == IntercomImportJob.Status.RUNNING and job.started_at is None:
        job.started_at = timezone.now()
        update_fields.append("started_at")
    if input.status in (IntercomImportJob.Status.COMPLETED, IntercomImportJob.Status.FAILED):
        job.finished_at = timezone.now()
        update_fields.append("finished_at")
    # Narrow update_fields so this write can't clobber counters / cursor that in-flight batch
    # children may update concurrently.
    job.save(update_fields=update_fields)
    if input.status in (IntercomImportJob.Status.COMPLETED, IntercomImportJob.Status.FAILED):
        _report_import_finished(job)


def _update_job_progress_sync(input: UpdateJobProgressInput) -> None:
    updates: dict[str, Any] = {
        "total_conversations": input.total,
        "processed_conversations": input.processed,
        "imported_conversations": input.imported,
        "skipped_conversations": input.skipped,
        "failed_conversations": input.failed,
    }
    if input.export_cursor is not None:
        updates["export_cursor"] = input.export_cursor
    IntercomImportJob.objects.unscoped().filter(id=input.job_id).update(**updates)


@activity.defn
async def intercom_import_enumerate_conversations_activity(
    input: EnumerateConversationsInput,
) -> EnumerateConversationsOutput:
    async with Heartbeater():
        return await database_sync_to_async(_enumerate_conversations_sync, thread_sensitive=False)(input)


@activity.defn
async def intercom_import_batch_activity(input: ImportBatchInput) -> ImportBatchOutput:
    async with Heartbeater():
        return await database_sync_to_async(_import_conversation_batch_sync, thread_sensitive=False)(input)


@activity.defn
async def intercom_import_update_job_status_activity(input: UpdateJobStatusInput) -> None:
    async with Heartbeater():
        await database_sync_to_async(_update_job_status_sync, thread_sensitive=False)(input)


@activity.defn
async def intercom_import_update_job_progress_activity(input: UpdateJobProgressInput) -> None:
    async with Heartbeater():
        await database_sync_to_async(_update_job_progress_sync, thread_sensitive=False)(input)
