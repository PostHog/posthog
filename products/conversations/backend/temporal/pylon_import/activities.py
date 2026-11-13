"""Temporal activities for Pylon historical issue import."""

from __future__ import annotations

import uuid
import mimetypes
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit

import structlog
from temporalio import activity, workflow

# The package __init__ imports this module inside the Temporal workflow sandbox; only the activity
# sync helpers touch Django/models at runtime, so pass them through the sandbox unmodified.
with workflow.unsafe.imports_passed_through():
    from django.db import InterfaceError, OperationalError
    from django.utils import timezone

    from posthog.dataclasses import frozen
    from posthog.event_usage import report_team_action
    from posthog.exceptions_capture import capture_exception
    from posthog.models import Team
    from posthog.models.comment import Comment
    from posthog.models.tag import tagify
    from posthog.sync import database_sync_to_async
    from posthog.temporal.common.heartbeat import Heartbeater

    from products.conversations.backend.models import EmailChannel, PurgedTicketThread, PylonImportJob, Ticket
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
    from products.conversations.backend.services.email_links import recover_links_from_html
    from products.conversations.backend.services.html_text import html_to_text
    from products.conversations.backend.temporal.pylon_import.client import (
        PylonCredentials,
        PylonImportClient,
        PylonNotFoundError,
        is_retryable_error,
    )
    from products.conversations.backend.temporal.pylon_import.mappers import (
        is_standard_pylon_state,
        map_pylon_author_type,
        map_pylon_priority,
        map_pylon_state,
    )
    from products.conversations.backend.temporal.ticket_import.attachment_download import AttachmentTooLargeError
    from products.conversations.backend.temporal.ticket_import.persistence import (
        BuiltTicket,
        persist_ticket_batch,
        resolve_email_channels,
        resolve_tags,
        set_historical_created_at,
        strip_nul,
    )

logger = structlog.get_logger(__name__)

# A contact controls how many files they attach, so cap what one issue can make the import
# download and store. Attachments past the budget are skipped, not failed.
MAX_ATTACHMENT_BYTES_PER_ISSUE = 200 * 1024 * 1024

_GENERIC_CONTENT_TYPES = frozenset({"", "application/octet-stream", "binary/octet-stream"})


@frozen
class EnumerateIssuesInput:
    job_id: str
    cursor: str | None = None


@frozen
class EnumerateIssuesOutput:
    issue_ids: list[str]
    next_cursor: str | None


@frozen
class ImportBatchInput:
    job_id: str
    team_id: int
    issue_ids: list[str]
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
class _IssuePartition:
    existing_ids: set[str]
    to_import: list[str]
    skipped: int


@frozen
class _Requester:
    name: str
    email: str
    contact_id: str


@frozen(eq=False)
class _EmailChannels:
    by_address: dict[str, EmailChannel]
    default: EmailChannel | None


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


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _credentials_from_job(job: PylonImportJob) -> PylonCredentials:
    inputs = job.job_inputs or {}
    region = str(inputs.get("region") or "")
    api_token = str(inputs.get("api_token") or "")
    if not region or not api_token:
        raise ValueError("Pylon import job is missing credentials")
    return PylonCredentials(region=region, api_token=api_token)


def _clean(value: Any) -> str:
    return strip_nul(str(value or "").strip())


def _partition_new_issues(team_id: int, issue_ids: list[str]) -> _IssuePartition:
    # all_objects so a soft-deleted import still counts as present. Re-inserting it would hit the
    # unique constraint, or reopen a deleted thread.
    existing_ids = {
        issue_id
        for issue_id in Ticket.all_objects.filter(team_id=team_id)
        .filter(pylon_issue_id__in=issue_ids)
        .values_list("pylon_issue_id", flat=True)
        if issue_id is not None
    }
    # A purged import stays out, so the next import does not bring the deleted ticket back.
    purged_keys = set(
        PurgedTicketThread.objects.for_team(team_id)
        .filter(thread_key__in=[ticket_thread_key(pylon_issue_id=issue_id) for issue_id in issue_ids])
        .values_list("thread_key", flat=True)
    )
    to_import = [
        issue_id
        for issue_id in issue_ids
        if issue_id not in existing_ids and ticket_thread_key(pylon_issue_id=issue_id) not in purged_keys
    ]
    return _IssuePartition(existing_ids=existing_ids, to_import=to_import, skipped=len(issue_ids) - len(to_import))


def _backfill_missing_email_channel(team_id: int, existing_ids: set[str], default_email_channel: EmailChannel) -> None:
    # Re-import backfill: tickets a previous run imported without an email channel adopt this
    # run's default. QuerySet.update() bypasses the signal receivers and keeps updated_at.
    backfilled = Ticket.objects.filter(
        team_id=team_id,
        pylon_issue_id__in=existing_ids,
        email_config__isnull=True,
    ).update(email_config=default_email_channel)
    if backfilled:
        logger.info("pylon_import_backfilled_email_channel", team_id=team_id, backfilled=backfilled)


def _author_contact_id(message: dict[str, Any]) -> str:
    return _clean(((message.get("author") or {}).get("contact") or {}).get("id"))


def _resolve_requester(client: PylonImportClient, issue: dict[str, Any], messages: list[dict[str, Any]]) -> _Requester:
    # The issue names its requester by id and email only. The requester's own messages carry the
    # name, so the contact is fetched only when no message does, or when the email is missing.
    requester = issue.get("requester") or {}
    contact_id = _clean(requester.get("id"))
    email = _clean(requester.get("email"))
    if not contact_id:
        return _Requester(name="", email=email, contact_id="")
    name = next(
        (
            author_name
            for message in messages
            if _author_contact_id(message) == contact_id
            and (author_name := _clean((message.get("author") or {}).get("name")))
        ),
        "",
    )
    if name and email:
        return _Requester(name=name, email=email, contact_id=contact_id)
    try:
        contact = client.fetch_contact(contact_id)
    except PylonNotFoundError:
        # A deleted contact shouldn't drop the whole issue, so import it with what the issue has.
        # Any other failure propagates so Temporal retries rather than saving a ticket with no email.
        logger.warning("pylon_import_contact_not_found", contact_id=contact_id)
        return _Requester(name=name, email=email, contact_id=contact_id)
    return _Requester(
        name=name or _clean(contact.get("name")), email=email or _clean(contact.get("email")), contact_id=contact_id
    )


def _attachment_file_name(url: str) -> str:
    # The message lists its files as bare URLs, so the name comes from the URL path. The uploader
    # chose it, and it is rendered inside Markdown link and image syntax.
    return sanitize_attachment_filename(unquote(PurePosixPath(urlsplit(url).path).name))


def _attachment_content_type(declared: str, file_name: str) -> str:
    # Object storage often serves a generic type, so fall back to the file extension.
    if declared not in _GENERIC_CONTENT_TYPES:
        return declared
    return mimetypes.guess_type(file_name)[0] or "application/octet-stream"


def _process_attachments(
    client: PylonImportClient,
    team: Team,
    file_urls: list[Any],
    content: str,
    budget: _AttachmentBudget,
) -> tuple[str, dict[str, Any] | None]:
    images: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    for url in file_urls[:MAX_ATTACHMENTS_PER_MESSAGE]:
        if not isinstance(url, str) or not url:
            continue
        file_name = _attachment_file_name(url)
        max_bytes = min(CONVERSATIONS_MAX_IMAGE_BYTES, budget.remaining)
        if max_bytes <= 0:
            logger.warning("pylon_import_attachment_budget_exhausted", team_id=team.id, file_name=file_name)
            continue
        try:
            attachment = client.download_attachment(url, max_bytes=max_bytes)
        except AttachmentTooLargeError as exc:
            # The bytes streamed before the cap tripped still count, or repeated oversized files
            # without an honest Content-Length would bypass the issue budget.
            budget.remaining -= exc.bytes_read
            logger.warning(
                "pylon_import_attachment_too_large", team_id=team.id, file_name=file_name, max_bytes=max_bytes
            )
            continue
        except Exception as exc:
            # Timeouts and 5xx retry the whole batch through Temporal; a deleted link (4xx) won't
            # come back on a retry, so skip it. Log only the type, because a requests error
            # message embeds the signed URL.
            if is_retryable_error(exc):
                raise
            logger.warning(
                "pylon_import_attachment_download_failed",
                team_id=team.id,
                file_name=file_name,
                error_type=type(exc).__name__,
                status_code=getattr(exc, "status_code", None),
            )
            continue
        budget.remaining -= len(attachment.content)
        content_type = _attachment_content_type(attachment.content_type, file_name)
        is_image = content_type.startswith("image/")
        media_url = save_file_to_uploaded_media(
            team, file_name, content_type, attachment.content, validate_images=is_image, raise_on_storage_error=True
        )
        if not media_url:
            continue
        entry = {"url": media_url, "name": file_name}
        budget.staged.append(entry)
        (images if is_image else files).append(entry)
    return build_content_with_images(content, None, images, files)


def _message_text(message: dict[str, Any]) -> str:
    # Pylon returns message bodies as HTML only.
    html = str(message.get("message_html") or "")
    if not html.strip():
        return ""
    return strip_nul(recover_links_from_html(html_to_text(html), html))


def _build_comment(
    client: PylonImportClient, team: Team, message: dict[str, Any], budget: _AttachmentBudget
) -> _BuiltComment | None:
    """Build one Comment from an issue message. Empty messages return None."""
    author = message.get("author") or {}
    contact = author.get("contact") or {}
    user = author.get("user") or {}
    author_type, is_private = map_pylon_author_type(
        is_private=message.get("is_private") is True, is_contact=bool(contact.get("id"))
    )
    body, rich_content = _process_attachments(
        client, team, message.get("file_urls") or [], _message_text(message), budget
    )
    if not body and not rich_content:
        return None

    item_context: dict[str, Any] = {
        "author_type": author_type,
        "is_private": is_private,
        "from_pylon": True,
        "pylon_message_id": message.get("id"),
    }
    author_name = _clean(author.get("name"))
    author_email = _clean(contact.get("email") or user.get("email"))
    if author_name:
        item_context["author_name"] = author_name
    if author_email:
        item_context["author_email"] = author_email

    comment = Comment(
        team=team,
        scope="conversations_ticket",
        item_id="",  # Set once the ticket has an id.
        content=strip_nul(body),
        rich_content=rich_content,
        item_context=item_context,
    )
    set_historical_created_at(comment, _parse_timestamp(message.get("timestamp")))
    return _BuiltComment(comment=comment, author_type=author_type, is_private=is_private)


def _issue_messages(issue: dict[str, Any], messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # The issue body is its first message. If the messages list comes back empty, keep the body
    # as a message from the requester so the ticket still has its opening text.
    if messages or not str(issue.get("body_html") or "").strip():
        return messages
    requester = issue.get("requester") or {}
    return [
        {
            "id": None,
            "message_html": issue.get("body_html"),
            "timestamp": issue.get("created_at"),
            "author": {"contact": requester} if requester.get("id") else {},
            "is_private": False,
            "file_urls": issue.get("attachment_urls") or [],
        }
    ]


def _build_comments(
    client: PylonImportClient, team: Team, messages: list[dict[str, Any]], staged: list[dict[str, Any]]
) -> _BuiltComments:
    budget = _AttachmentBudget(MAX_ATTACHMENT_BYTES_PER_ISSUE, staged)
    built: list[Comment] = []
    customer_message_count = 0
    agent_reply_count = 0
    for message in messages:
        built_comment = _build_comment(client, team, message, budget)
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


def _issue_priority(issue: dict[str, Any]) -> str | None:
    # Pylon stores priority as the built-in `priority` custom field, not as a top-level field.
    custom_fields = issue.get("custom_fields")
    priority = custom_fields.get("priority") if isinstance(custom_fields, dict) else None
    value = priority.get("value") if isinstance(priority, dict) else None
    return map_pylon_priority(value if isinstance(value, str) else None)


def _issue_status(client: PylonImportClient, issue: dict[str, Any]) -> str:
    state = issue.get("state")
    state = state if isinstance(state, str) else None
    if is_standard_pylon_state(state):
        return map_pylon_state(state)
    return map_pylon_state(state, client.issue_status_categories())


def _build_ticket(
    client: PylonImportClient,
    team: Team,
    issue: dict[str, Any],
    messages: list[dict[str, Any]],
    email_channels: _EmailChannels,
    staged: list[dict[str, Any]],
) -> BuiltTicket:
    issue_id = str(issue["id"])
    messages = _issue_messages(issue, messages)
    requester = _resolve_requester(client, issue, messages)
    requester_email = requester.email if "@" in requester.email else ""
    # Pylon accepts messages from unverified senders (public forms, unverified chat visitors), so
    # the email must never become the widget access identity: the widget grants a ticket to any
    # viewer whose distinct_ids contain the ticket's distinct_id, and many apps identify users by
    # email. A namespaced id can't match a real distinct_id. The email still drives display and
    # replies, and restore-by-email proves inbox ownership before granting access.
    distinct_id = f"pylon:{requester.contact_id or issue_id}"

    anonymous_traits: dict[str, str] = {}
    if requester.name:
        anonymous_traits["name"] = requester.name
    if requester_email:
        anonymous_traits["email"] = requester_email

    # `workspace_email` is the support address the customer wrote to, so a ticket goes back to
    # the matching email channel when the team has one.
    workspace_email = _clean(issue.get("workspace_email")).lower()
    email_channel = email_channels.by_address.get(workspace_email) if workspace_email else None

    ticket = Ticket(
        team=team,
        channel_source=Channel.EMAIL,
        widget_session_id=str(uuid.uuid4()),
        distinct_id=distinct_id,
        status=_issue_status(client, issue),
        priority=_issue_priority(issue),
        email_subject=_clean(issue.get("title"))[:500] or None,
        email_from=requester_email or None,
        identity_verified=False,
        email_config=email_channel or email_channels.default,
        anonymous_traits=anonymous_traits,
        pylon_issue_id=issue_id,
    )

    tags = issue.get("tags") or []
    pylon_tags = {tagify(strip_nul(tag))[:255] for tag in tags if isinstance(tag, str)}
    tag_names = sorted(tag for tag in pylon_tags if tag)

    built_comments = _build_comments(client, team, messages, staged)
    return BuiltTicket(
        ticket=ticket,
        comments=built_comments.comments,
        tag_names=tag_names,
        customer_message_count=built_comments.customer_message_count,
        agent_reply_count=built_comments.agent_reply_count,
        created_at=_parse_timestamp(issue.get("created_at")),
        updated_at=_parse_timestamp(issue.get("updated_at")),
    )


def _should_retry_batch(exc: BaseException) -> bool:
    return is_retryable_error(exc) or isinstance(exc, AttachmentStorageError | OperationalError | InterfaceError)


def _fetch_and_build_tickets(
    client: PylonImportClient,
    team: Team,
    issue_ids: list[str],
    email_channels: _EmailChannels,
    staged: list[dict[str, Any]],
) -> tuple[list[BuiltTicket], int]:
    """Fetch each issue with its messages and build its ticket, outside the transaction."""
    built: list[BuiltTicket] = []
    failed = 0
    for issue_id in issue_ids:
        staged_before = len(staged)
        try:
            issue = client.fetch_issue(issue_id)
            messages = client.fetch_messages(issue_id)
            built.append(_build_ticket(client, team, issue, messages, email_channels, staged))
        except Exception as exc:
            # Rate limits, timeouts, 5xx and storage failures retry the whole batch through
            # Temporal. Nothing from this attempt is persisted yet, so the retry rebuilds it.
            if _should_retry_batch(exc):
                raise
            discard_rehosted_attachments(team, staged[staged_before:])
            del staged[staged_before:]
            failed += 1
            logger.exception(
                "pylon_import_issue_failed",
                team_id=team.id,
                pylon_issue_id=issue_id,
                error=str(exc),
            )
    return built, failed


def _import_issue_batch_sync(input: ImportBatchInput) -> ImportBatchOutput:
    job = PylonImportJob.objects.for_team(input.team_id).get(id=input.job_id)
    team = Team.objects.get(id=input.team_id)
    client = PylonImportClient(_credentials_from_job(job))
    by_address, default_email_channel = resolve_email_channels(team.id, input.default_email_channel_id)
    email_channels = _EmailChannels(by_address=by_address, default=default_email_channel)

    partition = _partition_new_issues(input.team_id, input.issue_ids)
    skipped = partition.skipped

    if partition.existing_ids and default_email_channel is not None:
        _backfill_missing_email_channel(input.team_id, partition.existing_ids, default_email_channel)

    if not partition.to_import:
        return ImportBatchOutput(imported=0, skipped=skipped, failed=0)

    staged: list[dict[str, Any]] = []
    try:
        built, failed = _fetch_and_build_tickets(client, team, partition.to_import, email_channels, staged)
        if not built:
            return ImportBatchOutput(imported=0, skipped=skipped, failed=failed)
        imported = persist_ticket_batch(team, built, resolve_tags(team.id, built))
    except Exception:
        # No comment references these uploads, so delete them rather than leave copies behind.
        discard_rehosted_attachments(team, staged)
        raise
    return ImportBatchOutput(imported=imported, skipped=skipped, failed=failed)


def _enumerate_issues_sync(input: EnumerateIssuesInput) -> EnumerateIssuesOutput:
    job = PylonImportJob.objects.unscoped().get(id=input.job_id)
    client = PylonImportClient(_credentials_from_job(job))
    issue_ids, next_cursor = client.list_issue_ids_page(cursor=input.cursor)
    return EnumerateIssuesOutput(issue_ids=issue_ids, next_cursor=next_cursor)


def _report_import_finished(job: PylonImportJob) -> None:
    try:
        report_team_action(
            job.team,
            "support import finished",
            {
                "source": "pylon",
                "import_job_id": str(job.id),
                "status": job.status,
                "imported": job.imported_issues,
                "skipped": job.skipped_issues,
                "failed": job.failed_issues,
            },
        )
    except Exception as e:
        capture_exception(e, {"import_job_id": str(job.id)})


def _update_job_status_sync(input: UpdateJobStatusInput) -> None:
    job = PylonImportJob.objects.unscoped().get(id=input.job_id)
    update_fields = ["status", "updated_at"]
    job.status = input.status
    if input.latest_error is not None:
        job.latest_error = input.latest_error
        update_fields.append("latest_error")
    if input.status == PylonImportJob.Status.RUNNING and job.started_at is None:
        job.started_at = timezone.now()
        update_fields.append("started_at")
    if input.status in (PylonImportJob.Status.COMPLETED, PylonImportJob.Status.FAILED):
        job.finished_at = timezone.now()
        update_fields.append("finished_at")
    # Narrow update_fields so this write can't clobber counters / cursor that in-flight batch
    # children may update concurrently.
    job.save(update_fields=update_fields)
    if input.status in (PylonImportJob.Status.COMPLETED, PylonImportJob.Status.FAILED):
        _report_import_finished(job)


def _update_job_progress_sync(input: UpdateJobProgressInput) -> None:
    updates: dict[str, Any] = {
        # QuerySet.update() skips auto_now. The settings API reads a stale updated_at on a running
        # job as a sign that its workflow stopped.
        "updated_at": timezone.now(),
        "total_issues": input.total,
        "processed_issues": input.processed,
        "imported_issues": input.imported,
        "skipped_issues": input.skipped,
        "failed_issues": input.failed,
    }
    if input.export_cursor is not None:
        updates["export_cursor"] = input.export_cursor
    PylonImportJob.objects.unscoped().filter(id=input.job_id).update(**updates)


@activity.defn
async def pylon_import_enumerate_issues_activity(input: EnumerateIssuesInput) -> EnumerateIssuesOutput:
    async with Heartbeater():
        return await database_sync_to_async(_enumerate_issues_sync, thread_sensitive=False)(input)


@activity.defn
async def pylon_import_batch_activity(input: ImportBatchInput) -> ImportBatchOutput:
    async with Heartbeater():
        return await database_sync_to_async(_import_issue_batch_sync, thread_sensitive=False)(input)


@activity.defn
async def pylon_import_update_job_status_activity(input: UpdateJobStatusInput) -> None:
    async with Heartbeater():
        await database_sync_to_async(_update_job_status_sync, thread_sensitive=False)(input)


@activity.defn
async def pylon_import_update_job_progress_activity(input: UpdateJobProgressInput) -> None:
    async with Heartbeater():
        await database_sync_to_async(_update_job_progress_sync, thread_sensitive=False)(input)
