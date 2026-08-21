"""
Facade API for conversations.

The only conversations surface other products may import. Wraps the SupportHog
Slack integration behind contract types so callers never touch slack_sdk or the
team's Slack credentials directly.
"""

import asyncio
from datetime import datetime
from typing import Any, Protocol, cast

from django.conf import settings
from django.db import transaction
from django.db.models import F, OuterRef, Prefetch, Q, QuerySet, Subquery

import structlog
from slack_sdk.errors import SlackApiError
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError

from posthog.models.comment import Comment
from posthog.models.team import Team
from posthog.temporal.common.client import sync_connect

from products.conversations.backend.channel_summary_ids import build_channel_summary_workflow_id
from products.conversations.backend.facade.types import (
    AccountEmailThreadMessage as AccountEmailThreadMessage,
    AccountEmailThreadSummary as AccountEmailThreadSummary,
    ConversationMessageSender as ConversationMessageSender,
    ConversationMessageSummary as ConversationMessageSummary,
    EmailThreadAccountLinkInput as EmailThreadAccountLinkInput,
    EmailThreadAddress as EmailThreadAddress,
    EmailThreadForAccountMatching as EmailThreadForAccountMatching,
    EmailThreadParticipantSummary as EmailThreadParticipantSummary,
    SupportChannel as SupportChannel,
    SupportTicketMessage as SupportTicketMessage,
    TicketSummary as TicketSummary,
)
from products.conversations.backend.models import (
    EmailThread,
    EmailThreadAccountLink,
    EmailThreadAccountMatchSource,
    EmailThreadMessage,
    EmailThreadParticipant,
    EmailThreadParticipantKind,
    Ticket,
)
from products.conversations.backend.slack import get_slack_client
from products.conversations.backend.support_slack import get_support_slack_bot_token
from products.conversations.backend.support_slack_channels import (
    SupportSlackChannelsUnavailable as SupportSlackChannelsUnavailable,
    SupportSlackNotConfigured as SupportSlackNotConfigured,
    list_support_bot_channels as _list_support_bot_channels,
)

logger = structlog.get_logger(__name__)


class _TicketAccessControl(Protocol):
    def filter_queryset_by_access_level(self, queryset: QuerySet[Ticket]) -> QuerySet[Ticket]: ...


class _EmailThreadWithFacadePrefetch(Protocol):
    facade_participants: list[EmailThreadParticipant]
    facade_first_message_direction: str | None
    facade_first_message_sender_email: str | None
    facade_first_message_sender_name: str | None
    facade_first_message_sent_at: datetime | None
    facade_last_message_direction: str | None
    facade_last_message_sender_email: str | None
    facade_last_message_sender_name: str | None
    facade_last_message_sent_at: datetime | None


class GoogleAccountEmailSyncError(Exception):
    pass


class SupportMessageSendError(Exception):
    """Slack rejected a SupportHog bot message.

    ``code`` is the Slack error code (e.g. ``not_in_channel``); ``retry_after`` carries
    the requested wait in seconds when Slack rate-limited the post, else None.
    """

    def __init__(self, code: str, retry_after: float | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.retry_after = retry_after


def sync_google_account_email(integration_id: int, team_id: int) -> None:
    from products.conversations.backend.services.gmail_sync import (  # noqa: PLC0415 -- avoids the Conversations and Customer Analytics facade cycle
        GmailSyncError,
        sync_gmail_integration,
    )

    try:
        sync_gmail_integration(integration_id, team_id)
    except GmailSyncError as error:
        raise GoogleAccountEmailSyncError(str(error)) from error


def list_support_bot_channels(team_id: int, *, members_only: bool = False) -> list[SupportChannel]:
    """Slack channels the SupportHog bot can see for this team, sorted by name.

    With ``members_only=True``, only channels the bot belongs to (the ones it can
    post to). Raises :class:`SupportSlackNotConfigured` when the bot isn't connected
    and :class:`SupportSlackChannelsUnavailable` when the list can't be resolved.
    """
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        raise SupportSlackNotConfigured()
    try:
        channels = _list_support_bot_channels(team, members_only=members_only)
    except (SupportSlackNotConfigured, SupportSlackChannelsUnavailable):
        raise
    except Exception:
        # slack_sdk errors must not cross the boundary as slack_sdk types.
        raise SupportSlackChannelsUnavailable()
    return [SupportChannel(id=c["id"], name=c["name"], is_member=c["is_member"]) for c in channels]


def post_support_message(team_id: int, channel_id: str, text: str) -> str:
    """Post ``text`` to a Slack channel as the SupportHog bot, applying the team's
    configured bot display name and icon. Returns the posted message's Slack ts.

    Raises :class:`SupportSlackNotConfigured` when the bot isn't connected and
    :class:`SupportMessageSendError` when the post fails.
    """
    try:
        team = Team.objects.get(id=team_id)
        client = get_slack_client(team)
    except (Team.DoesNotExist, ValueError):
        raise SupportSlackNotConfigured()

    message_kwargs: dict[str, Any] = {}
    support_settings = team.conversations_settings or {}
    if bot_display_name := support_settings.get("slack_bot_display_name"):
        message_kwargs["username"] = bot_display_name
    if bot_icon_url := support_settings.get("slack_bot_icon_url"):
        message_kwargs["icon_url"] = bot_icon_url

    try:
        response = client.chat_postMessage(channel=channel_id, text=text, **message_kwargs)
    except SlackApiError as e:
        slack_response = getattr(e, "response", None)
        error_code = str((slack_response or {}).get("error", "unknown"))
        retry_after = None
        # Slack's error code is "ratelimited"; Retry-After is an HTTP header on
        # SlackResponse.headers, not in the JSON body that .get() reads.
        if error_code == "ratelimited":
            raw_retry_after = (getattr(slack_response, "headers", None) or {}).get("Retry-After")
            try:
                retry_after = float(raw_retry_after) if raw_retry_after is not None else None
            except (TypeError, ValueError):
                retry_after = None
        raise SupportMessageSendError(error_code, retry_after=retry_after)
    except Exception:
        # Transport failures (connection/timeout) must not cross the boundary as slack_sdk types.
        raise SupportMessageSendError("transport_error")
    ts = str(response.get("ts") or "")
    if not ts:
        raise SupportMessageSendError("missing_ts")
    return ts


def post_ticket_internal_note(team_id: int, ticket_id: str, content: str, *, dedupe_key: str) -> str | None:
    """Add a team-only note to a ticket, as the AI author. Returns the new comment's id, or None when
    nothing was written because the ticket doesn't exist for this team or this ``dedupe_key`` already
    posted a note.

    Always private: callers use this to hand agent findings to a support teammate, who decides what
    (if anything) reaches the customer. ``dedupe_key`` identifies the thing that produced the note so
    a retrying caller doesn't post twice.
    """
    if not Ticket.objects.filter(team_id=team_id, id=ticket_id).exists():
        return None
    already_posted = Comment.objects.filter(
        team_id=team_id,
        scope="conversations_ticket",
        item_id=ticket_id,
        item_context__internal_note_key=dedupe_key,
        deleted=False,
    ).exists()
    if already_posted:
        return None
    comment = Comment.objects.create(
        team_id=team_id,
        scope="conversations_ticket",
        item_id=ticket_id,
        content=content,
        item_context={"author_type": "AI", "is_private": True, "internal_note_key": dedupe_key},
    )
    return str(comment.id)


def trigger_immediate_channel_summary(
    *,
    team_id: int,
    account_id: str,
    account_name: str,
    slack_channel_id: str,
    cadence: str,
    period_start: datetime,
    period_end: datetime,
) -> bool:
    """Summarize one closed period of an account's Slack channel now, outside the hourly
    coordinator's schedule.

    Applies the same team-level gates the coordinator applies before it fans out: the team
    must have the SupportHog bot (it reads the channel) and the org must have approved AI
    data processing (messages go to an LLM). Returns False when a gate blocks it.

    Fire-and-forget: the caller's own write already succeeded, so a Temporal failure is
    logged and swallowed rather than raised.
    """
    # Deferred: temporal/__init__ loads the summarize workflow, which imports the
    # customer_analytics facade, which imports this module.
    from products.conversations.backend.temporal.channel_summary.schemas import ChannelSummaryInput  # noqa: PLC0415
    from products.conversations.backend.temporal.channel_summary.summarize import (  # noqa: PLC0415
        AccountChannelSummaryWorkflow,
    )

    team = Team.objects.select_related("organization").filter(id=team_id).first()
    if team is None or not team.organization.is_ai_data_processing_approved:
        return False
    if not get_support_slack_bot_token(team):
        return False

    workflow_input = ChannelSummaryInput(
        team_id=team_id,
        account_id=account_id,
        account_name=account_name,
        slack_channel_id=slack_channel_id,
        cadence=cadence,
        period_start=period_start.isoformat(),
        period_end=period_end.isoformat(),
    )
    workflow_id = build_channel_summary_workflow_id(
        account_id=account_id, cadence=cadence, period_start=period_start.date()
    )
    try:
        client = sync_connect()
        asyncio.run(
            client.start_workflow(
                AccountChannelSummaryWorkflow.run,
                workflow_input,
                id=workflow_id,
                task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
            )
        )
    except WorkflowAlreadyStartedError:
        logger.info("immediate_channel_summary_already_started", workflow_id=workflow_id)
        return False
    except RPCError as e:
        logger.warning("immediate_channel_summary_dispatch_failed", workflow_id=workflow_id, error=str(e))
        return False
    return True


def _get_first_string(context: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = context.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _support_ticket_last_message(ticket: Ticket, comment: Comment | None) -> ConversationMessageSummary | None:
    if comment is None:
        return None

    context = comment.item_context if isinstance(comment.item_context, dict) else {}
    author_type = context.get("author_type")
    is_outbound = bool(comment.created_by_id and author_type != "customer") or author_type in {
        "AI",
        "human",
        "support",
    }
    context_name = _get_first_string(
        context,
        (
            "author_name",
            "author_email",
            "slack_author_name",
            "teams_author_name",
            "teams_author_email",
            "email_from_name",
            "slack_author_email",
            "email_from",
        ),
    )
    context_email = _get_first_string(
        context,
        ("author_email", "slack_author_email", "teams_author_email", "email_from"),
    )
    sender_name: str | None
    sender_email: str | None

    if is_outbound:
        if comment.created_by is not None:
            sender_name = comment.created_by.get_full_name() or comment.created_by.email
            sender_email = comment.created_by.email
        else:
            sender_name = context_name or context_email or ("AI" if author_type == "AI" else "Support")
            sender_email = context_email
        sender = ConversationMessageSender(
            name=sender_name or sender_email or "Support",
            email=sender_email,
            person_id=None,
            distinct_id=None,
        )
    else:
        traits = ticket.anonymous_traits or {}
        trait_email = traits.get("email") if isinstance(traits.get("email"), str) else None
        trait_name = traits.get("name") if isinstance(traits.get("name"), str) else None
        sender_email = context_email or trait_email
        sender_name = context_name or trait_name
        sender = ConversationMessageSender(
            name=sender_name or sender_email or "Customer",
            email=sender_email,
            person_id=None,
            distinct_id=ticket.distinct_id,
        )

    return ConversationMessageSummary(
        sender=sender,
        sent_at=comment.created_at,
        direction="outbound" if is_outbound else "inbound",
    )


def list_account_tickets(
    team_id: int,
    organization_id: str,
    user_access_control: _TicketAccessControl,
    *,
    limit: int = 50,
) -> list[TicketSummary]:
    """Support tickets whose resolved customer org matches ``organization_id``, newest activity first.

    ``organization_id`` is the customer's group key (a customer-analytics account's
    ``external_id``). An empty key matches nothing — never every ticket for the team.
    """
    if not organization_id:
        return []
    tickets = list(
        user_access_control.filter_queryset_by_access_level(
            Ticket.objects.filter(team_id=team_id, organization_id=organization_id)
        ).order_by(F("last_message_at").desc(nulls_last=True))[:limit]
    )
    latest_comments = {
        comment.item_id: comment
        for comment in Comment.objects.filter(
            team_id=team_id,
            scope="conversations_ticket",
            item_id__in=[str(ticket.id) for ticket in tickets],
            deleted=False,
        )
        .filter(~Q(item_context__is_private=True) | Q(item_context__is_private__isnull=True))
        .select_related("created_by")
        .order_by("item_id", "-created_at", "-id")
        .distinct("item_id")
    }
    return [
        TicketSummary(
            id=str(ticket.id),
            ticket_number=ticket.ticket_number,
            status=ticket.status,
            last_message_at=ticket.last_message_at,
            last_message_text=ticket.last_message_text,
            last_message=_support_ticket_last_message(ticket, latest_comments.get(str(ticket.id))),
            deep_link=f"{settings.SITE_URL}/project/{team_id}/support/tickets/{ticket.ticket_number}",
            created_at=ticket.created_at,
            started_by=(ticket.anonymous_traits or {}).get("name")
            or (ticket.anonymous_traits or {}).get("email")
            or "Customer",
            distinct_id=ticket.distinct_id,
        )
        for ticket in tickets
    ]


def list_account_ticket_messages(
    team_id: int,
    organization_id: str,
    ticket_id: str,
    user_access_control: _TicketAccessControl,
    *,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[SupportTicketMessage], int] | None:
    ticket = user_access_control.filter_queryset_by_access_level(
        Ticket.objects.filter(team_id=team_id, organization_id=organization_id, id=ticket_id)
    ).first()
    if ticket is None:
        return None

    comments = (
        Comment.objects.filter(
            team_id=team_id,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            deleted=False,
        )
        .select_related("created_by")
        .order_by("created_at", "id")
    )
    count = comments.count()
    messages = []
    for comment in comments[offset : offset + limit]:
        summary = _support_ticket_last_message(ticket, comment)
        if summary is None:
            continue
        context = comment.item_context if isinstance(comment.item_context, dict) else {}
        messages.append(
            SupportTicketMessage(
                id=str(comment.id),
                content=comment.content or "",
                author_name=summary.sender.name,
                direction=summary.direction,
                is_private=context.get("is_private") is True,
                created_at=comment.created_at,
            )
        )
    return messages, count


def resolve_group_keys_by_email(
    team_id: int,
    emails: list[str],
    group_type_index: int,
) -> dict[str, str | None]:
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        return {}

    from products.conversations.backend.person_lookup import (  # noqa: PLC0415 — keeps HogQL and personhog off the facade import path
        get_group_keys_by_email,
    )

    return get_group_keys_by_email(team=team, emails=emails, group_type_index=group_type_index)


def list_email_threads_for_account_matching(
    team_id: int,
    *,
    thread_ids: list[str] | None = None,
    after_id: str | None = None,
    limit: int = 100,
) -> list[EmailThreadForAccountMatching]:
    participants = EmailThreadParticipant.objects.for_team(team_id).filter(kind=EmailThreadParticipantKind.CUSTOMER)
    threads = EmailThread.objects.for_team(team_id).prefetch_related(
        Prefetch("participants", queryset=participants, to_attr="customer_participants")
    )
    if thread_ids is not None:
        threads = threads.filter(id__in=thread_ids)
    if after_id is not None:
        threads = threads.filter(id__gt=after_id)

    return [
        EmailThreadForAccountMatching(
            id=str(thread.id),
            participant_emails=[
                participant.email for participant in cast(list[EmailThreadParticipant], thread.customer_participants)
            ],
        )
        for thread in threads.order_by("id")[:limit]
    ]


@transaction.atomic
def replace_email_thread_account_links(
    team_id: int,
    thread_id: str,
    links: list[EmailThreadAccountLinkInput],
) -> None:
    thread = EmailThread.objects.for_team(team_id).select_for_update().get(id=thread_id)
    links_by_account_id = {link.account_id: link for link in links}
    EmailThreadAccountLink.objects.for_team(team_id).filter(thread=thread).exclude(
        account_id__in=links_by_account_id
    ).delete()

    valid_sources = set(EmailThreadAccountMatchSource.values)
    for account_id, link in links_by_account_id.items():
        if link.match_source not in valid_sources:
            raise ValueError(f"Unknown email account match source: {link.match_source}")
        EmailThreadAccountLink.objects.for_team(team_id).update_or_create(
            team_id=team_id,
            thread=thread,
            account_id=account_id,
            defaults={
                "account_external_id": link.account_external_id,
                "match_source": link.match_source,
            },
        )


def _email_thread_participant_summary(
    participant: EmailThreadParticipant,
) -> EmailThreadParticipantSummary:
    return EmailThreadParticipantSummary(
        email=participant.email,
        display_name=participant.display_name,
        kind=participant.kind,
        person_id=str(participant.person_id) if participant.person_id else None,
    )


def _email_message_summary(
    sender_email: str | None,
    sender_name: str | None,
    sent_at: datetime | None,
    direction: str | None,
    participant_by_email: dict[str, EmailThreadParticipantSummary],
) -> ConversationMessageSummary | None:
    if not sender_email or not sent_at or not direction:
        return None
    participant = participant_by_email.get(sender_email.lower())
    return ConversationMessageSummary(
        sender=ConversationMessageSender(
            name=sender_name or sender_email,
            email=sender_email,
            person_id=participant.person_id if participant else None,
            distinct_id=None,
        ),
        sent_at=sent_at,
        direction=direction,
    )


def _account_email_thread_summary(thread: EmailThread) -> AccountEmailThreadSummary:
    prefetched_thread = cast(_EmailThreadWithFacadePrefetch, thread)
    participants = [
        _email_thread_participant_summary(participant) for participant in prefetched_thread.facade_participants
    ]
    participant_by_email = {participant.email.lower(): participant for participant in participants}
    first_message = _email_message_summary(
        prefetched_thread.facade_first_message_sender_email,
        prefetched_thread.facade_first_message_sender_name,
        prefetched_thread.facade_first_message_sent_at,
        prefetched_thread.facade_first_message_direction,
        participant_by_email,
    )
    last_message = _email_message_summary(
        prefetched_thread.facade_last_message_sender_email,
        prefetched_thread.facade_last_message_sender_name,
        prefetched_thread.facade_last_message_sent_at,
        prefetched_thread.facade_last_message_direction,
        participant_by_email,
    )
    return AccountEmailThreadSummary(
        id=str(thread.id),
        subject=thread.subject,
        preview=thread.preview,
        first_message_at=thread.first_message_at,
        first_message=first_message,
        last_message_at=thread.last_message_at,
        last_message=last_message,
        message_count=thread.message_count,
        participants=participants,
    )


def list_account_email_threads(
    team_id: int,
    account_id: str,
    *,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[AccountEmailThreadSummary], int]:
    participants: QuerySet[EmailThreadParticipant] = EmailThreadParticipant.objects.for_team(team_id).order_by("email")
    first_message = (
        EmailThreadMessage.objects.for_team(team_id).filter(thread_id=OuterRef("pk")).order_by("sent_at", "id")
    )
    latest_message = (
        EmailThreadMessage.objects.for_team(team_id).filter(thread_id=OuterRef("pk")).order_by("-sent_at", "-id")
    )
    threads = (
        EmailThread.objects.for_team(team_id)
        .filter(account_links__team_id=team_id, account_links__account_id=account_id)
        .annotate(
            facade_first_message_direction=Subquery(first_message.values("direction")[:1]),
            facade_first_message_sender_email=Subquery(first_message.values("sender_email")[:1]),
            facade_first_message_sender_name=Subquery(first_message.values("sender_name")[:1]),
            facade_first_message_sent_at=Subquery(first_message.values("sent_at")[:1]),
            facade_last_message_direction=Subquery(latest_message.values("direction")[:1]),
            facade_last_message_sender_email=Subquery(latest_message.values("sender_email")[:1]),
            facade_last_message_sender_name=Subquery(latest_message.values("sender_name")[:1]),
            facade_last_message_sent_at=Subquery(latest_message.values("sent_at")[:1]),
        )
        .prefetch_related(Prefetch("participants", queryset=participants, to_attr="facade_participants"))
        .order_by(F("last_message_at").desc(nulls_last=True), "-id")
    )
    count = threads.count()
    return [_account_email_thread_summary(thread) for thread in threads[offset : offset + limit]], count


def _email_thread_addresses(value: object) -> list[EmailThreadAddress]:
    if not isinstance(value, list):
        return []
    addresses: list[EmailThreadAddress] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        email = item.get("email")
        name = item.get("name", "")
        if isinstance(email, str) and isinstance(name, str):
            addresses.append(EmailThreadAddress(name=name, email=email))
    return addresses


def list_account_email_thread_messages(
    team_id: int,
    account_id: str,
    thread_id: str,
    *,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[AccountEmailThreadMessage], int] | None:
    thread = (
        EmailThread.objects.for_team(team_id)
        .filter(
            id=thread_id,
            account_links__team_id=team_id,
            account_links__account_id=account_id,
        )
        .first()
    )
    if thread is None:
        return None

    messages = (
        EmailThreadMessage.objects.for_team(team_id)
        .filter(thread=thread)
        .select_related("comment")
        .order_by("sent_at", "id")
    )
    count = messages.count()
    return (
        [
            AccountEmailThreadMessage(
                id=str(message.id),
                sent_at=message.sent_at,
                sender=EmailThreadAddress(name=message.sender_name, email=message.sender_email),
                to_recipients=_email_thread_addresses(message.to_recipients),
                cc_recipients=_email_thread_addresses(message.cc_recipients),
                sender_authenticated=message.sender_authenticated,
                direction=message.direction,
                content=message.comment.content or "",
            )
            for message in messages[offset : offset + limit]
        ],
        count,
    )
