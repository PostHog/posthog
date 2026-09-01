from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from uuid import UUID

from django.core.files.uploadedfile import UploadedFile
from django.db import IntegrityError, transaction
from django.db.models.functions import Lower

from posthog.models.comment import Comment
from posthog.models.organization import OrganizationMembership

from products.conversations.backend.models import (
    EMAIL_THREAD_COMMENT_SCOPE,
    EmailChannel,
    EmailThread,
    EmailThreadMessage,
    EmailThreadMessageDirection,
    EmailThreadParticipant,
    EmailThreadParticipantKind,
)
from products.customer_analytics.backend.facade.email_matching import (
    schedule_email_thread_link_recalculation_for_threads,
)


@dataclass(frozen=True, kw_only=True)
class EmailAddress:
    name: str
    email: str

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "email": self.email}


@dataclass(frozen=True, kw_only=True)
class ParsedEmail:
    message_id: str
    in_reply_to: str | None
    references: tuple[str, ...]
    sent_at: datetime
    sender: EmailAddress
    to_recipients: tuple[EmailAddress, ...]
    cc_recipients: tuple[EmailAddress, ...]
    subject: str
    body_plain: str
    stripped_text: str
    sender_authenticated: bool
    dkim_passed: bool
    dkim_signing_domains: tuple[str, ...]
    capture_address: str
    attachments: tuple[UploadedFile, ...]
    forwarding_challenge_tokens: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class EmailThreadIngestionResult:
    thread_id: UUID
    message_id: UUID
    created: bool


def _mailgun_source_id(message_id: str) -> str:
    if len(message_id) <= 512:
        return message_id
    return f"sha256:{sha256(message_id.encode()).hexdigest()}"


def _find_existing_message(*, team_id: int, email: ParsedEmail) -> EmailThreadMessage | None:
    return (
        EmailThreadMessage.objects.for_team(team_id)
        .select_related("thread")
        .filter(message_id=email.message_id)
        .first()
    )


def _find_thread(*, team_id: int, email: ParsedEmail) -> EmailThread | None:
    message_candidates = tuple(
        dict.fromkeys(candidate for candidate in (email.in_reply_to, *reversed(email.references)) if candidate)
    )
    if message_candidates:
        messages_by_id = {
            message.message_id: message.thread
            for message in EmailThreadMessage.objects.for_team(team_id)
            .select_related("thread")
            .filter(message_id__in=message_candidates)
        }
        for candidate in message_candidates:
            if candidate in messages_by_id:
                return messages_by_id[candidate]

    thread_key_candidates = tuple(
        dict.fromkeys(
            candidate for candidate in (email.message_id, email.in_reply_to, *reversed(email.references)) if candidate
        )
    )
    threads_by_key = {
        thread.canonical_thread_key: thread
        for thread in EmailThread.objects.for_team(team_id).filter(canonical_thread_key__in=thread_key_candidates)
    }
    for candidate in thread_key_candidates:
        if candidate in threads_by_key:
            return threads_by_key[candidate]
    return None


def _get_or_create_thread(*, team_id: int, email: ParsedEmail) -> EmailThread:
    existing_thread = _find_thread(team_id=team_id, email=email)
    if existing_thread is not None:
        return existing_thread

    canonical_thread_key = email.references[0] if email.references else email.in_reply_to or email.message_id
    thread, _ = EmailThread.objects.for_team(team_id).get_or_create(
        team_id=team_id,
        canonical_thread_key=canonical_thread_key,
        defaults={"subject": email.subject},
    )
    return thread


def _upsert_participants(
    *,
    team_id: int,
    thread: EmailThread,
    channel: EmailChannel,
    email: ParsedEmail,
) -> None:
    owner = channel.owner
    if owner is None:
        raise ValueError("Customer communication channels require an owner")

    addresses = [email.sender, *email.to_recipients, *email.cc_recipients]
    addresses.append(EmailAddress(name=channel.from_name, email=channel.from_email.lower()))
    if owner.email.lower() != channel.from_email.lower():
        addresses.append(EmailAddress(name="", email=owner.email.lower()))

    addresses_by_email: dict[str, EmailAddress] = {}
    capture_address = email.capture_address.lower()
    for address in addresses:
        normalized_email = address.email.strip().lower()[:400]
        if not normalized_email or normalized_email == capture_address:
            continue
        current = addresses_by_email.get(normalized_email)
        if current is None or (not current.name and address.name):
            addresses_by_email[normalized_email] = EmailAddress(name=address.name[:400], email=normalized_email)

    organization_member_emails = set(
        OrganizationMembership.objects.filter(
            organization_id=channel.team.organization_id,
            user__is_active=True,
        )
        .annotate(normalized_member_email=Lower("user__email"))
        .filter(normalized_member_email__in=list(addresses_by_email))
        .values_list("normalized_member_email", flat=True)
    )
    organization_member_emails.update({channel.from_email.lower(), owner.email.lower()})

    for address in addresses_by_email.values():
        kind = (
            EmailThreadParticipantKind.INTERNAL
            if address.email in organization_member_emails
            else EmailThreadParticipantKind.CUSTOMER
        )
        participant, created = EmailThreadParticipant.objects.for_team(team_id).get_or_create(
            team_id=team_id,
            thread=thread,
            email=address.email,
            defaults={"display_name": address.name, "kind": kind},
        )
        if created:
            continue

        update_fields: list[str] = []
        if address.name and participant.display_name != address.name:
            participant.display_name = address.name
            update_fields.append("display_name")
        if kind == EmailThreadParticipantKind.INTERNAL and participant.kind != kind:
            participant.kind = kind
            update_fields.append("kind")
        if update_fields:
            participant.save(update_fields=[*update_fields, "updated_at"])


def _message_content(*, thread: EmailThread, email: ParsedEmail) -> str:
    if thread.message_count > 0:
        return email.stripped_text or email.body_plain
    return email.body_plain or email.stripped_text


def _update_thread_summary(*, thread: EmailThread, email: ParsedEmail, content: str) -> None:
    update_fields = ["message_count", "updated_at"]
    thread.message_count += 1

    if thread.first_message_at is None or email.sent_at < thread.first_message_at:
        thread.first_message_at = email.sent_at
        update_fields.append("first_message_at")

    if thread.last_message_at is None or email.sent_at >= thread.last_message_at:
        thread.last_message_at = email.sent_at
        thread.preview = content[:500]
        update_fields.extend(["last_message_at", "preview"])

    if not thread.subject and email.subject:
        thread.subject = email.subject
        update_fields.append("subject")

    thread.save(update_fields=update_fields)


def _ingest_customer_email_once(
    *,
    team_id: int,
    channel: EmailChannel,
    email: ParsedEmail,
    direction: EmailThreadMessageDirection,
    source_type: str,
    source_id: str | None,
) -> EmailThreadIngestionResult:
    existing_message = _find_existing_message(team_id=team_id, email=email)
    if existing_message is not None:
        return EmailThreadIngestionResult(
            thread_id=existing_message.thread_id,
            message_id=existing_message.id,
            created=False,
        )

    thread = _get_or_create_thread(team_id=team_id, email=email)
    thread = EmailThread.objects.for_team(team_id).select_for_update().get(id=thread.id)

    existing_message = _find_existing_message(team_id=team_id, email=email)
    if existing_message is not None:
        return EmailThreadIngestionResult(
            thread_id=existing_message.thread_id,
            message_id=existing_message.id,
            created=False,
        )

    content = _message_content(thread=thread, email=email)
    comment = Comment.objects.create(
        team_id=team_id,
        scope=EMAIL_THREAD_COMMENT_SCOPE,
        item_id=str(thread.id),
        content=content,
    )
    message = EmailThreadMessage.objects.for_team(team_id).create(
        team_id=team_id,
        thread=thread,
        comment=comment,
        message_id=email.message_id,
        in_reply_to=email.in_reply_to,
        references=list(email.references),
        sent_at=email.sent_at,
        sender_email=email.sender.email,
        sender_name=email.sender.name,
        to_recipients=[recipient.as_dict() for recipient in email.to_recipients],
        cc_recipients=[recipient.as_dict() for recipient in email.cc_recipients],
        sender_authenticated=email.sender_authenticated,
        direction=direction,
        source_type=source_type,
        source_id=source_id or _mailgun_source_id(email.message_id),
    )
    _upsert_participants(team_id=team_id, thread=thread, channel=channel, email=email)
    _update_thread_summary(thread=thread, email=email, content=content)
    return EmailThreadIngestionResult(thread_id=thread.id, message_id=message.id, created=True)


def ingest_customer_email(
    *,
    team_id: int,
    channel: EmailChannel,
    email: ParsedEmail,
    direction: EmailThreadMessageDirection,
    source_type: str = "mailgun",
    source_id: str | None = None,
) -> EmailThreadIngestionResult:
    try:
        with transaction.atomic():
            result = _ingest_customer_email_once(
                team_id=team_id,
                channel=channel,
                email=email,
                direction=direction,
                source_type=source_type,
                source_id=source_id,
            )
    except IntegrityError:
        existing_message = _find_existing_message(team_id=team_id, email=email)
        if existing_message is None:
            raise
        result = EmailThreadIngestionResult(
            thread_id=existing_message.thread_id,
            message_id=existing_message.id,
            created=False,
        )

    schedule_email_thread_link_recalculation_for_threads(team_id, [str(result.thread_id)])
    return result
