"""Slack direct message to a ticket's assignee, sent by the "Message assignee on Slack" workflow step.

The recipient is always resolved from the ticket on the server. The workflow only names the ticket,
so Hog code cannot choose who in the workspace receives ticket content.
"""

import hashlib
from datetime import datetime

from django.db import models

import structlog
from slack_sdk.errors import SlackApiError

from posthog.dataclasses import frozen
from posthog.egress.slack.client import SlackWebClient
from posthog.models.integration import Integration, SlackIntegration
from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration
from posthog.slack.formatting import escape_slack_mrkdwn
from posthog.user_permissions import user_can_access_team

from products.conversations.backend.models import Ticket, TicketAssignment
from products.conversations.backend.reply_dedupe import ReservationState, publish, release, reserve
from products.conversations.backend.slack import ticket_deep_link

logger = structlog.get_logger(__name__)

# A step can be dispatched again long after its first attempt, for example when a worker dies before
# it records the result. The reply window that suits a support reply is too short for that.
_REPLAY_TTL_SECONDS = 24 * 60 * 60


class AssigneeSlackDmOutcome(models.TextChoices):
    SENT = "sent", "Sent"
    UNASSIGNED = "unassigned", "Unassigned"


@frozen
class AssigneeSlackDmResult:
    outcome: AssigneeSlackDmOutcome
    slack_user_id: str | None = None


class AssigneeSlackDmUndeliverable(Exception):
    """The message cannot reach the assignee. The text goes verbatim to the workflow logs."""


class AssigneeSlackDmInFlight(Exception):
    """Another attempt of the same workflow step is still sending this message."""


class _SendOutcomeUnknown(Exception):
    def __init__(self, slack_user_id: str) -> None:
        super().__init__(slack_user_id)
        self.slack_user_id = slack_user_id


@frozen
class _StepFingerprint:
    """Reservation identity for one workflow step execution.

    A Slack message leaves no row to find again, so a replay comes only from the published
    reservation and there is no persisted match to fall back on.
    """

    team_id: int
    idempotency_key: str

    @property
    def key(self) -> str:
        digest = hashlib.sha256(f"{self.team_id}:{self.idempotency_key}".encode()).hexdigest()
        return f"conversations:assignee_slack_dm:v1:{digest}"

    def find_persisted_match(self, *, created_after: datetime) -> None:
        return None

    def load_replay_target(self, object_id: str | None) -> str | None:
        return object_id


def send_assignee_slack_dm(
    *, team: Team, ticket: Ticket, integration: Integration, text: str, idempotency_key: str
) -> AssigneeSlackDmResult:
    # The worker retries a request whose response it never received. A Slack message cannot be
    # taken back, so the retry must not send a second one.
    reservation = reserve(_StepFingerprint(team_id=team.id, idempotency_key=idempotency_key))
    if reservation.state is ReservationState.REPLAY:
        return AssigneeSlackDmResult(outcome=AssigneeSlackDmOutcome.SENT, slack_user_id=reservation.object_id)
    if reservation.state is ReservationState.IN_FLIGHT:
        raise AssigneeSlackDmInFlight()

    try:
        slack_user_id = _deliver(team=team, ticket=ticket, integration=integration, text=text)
    except _SendOutcomeUnknown as exc:
        # Slack may have delivered the message, so a retry must replay instead of sending it again.
        publish(reservation, exc.slack_user_id, replay_ttl_seconds=_REPLAY_TTL_SECONDS)
        raise AssigneeSlackDmUndeliverable(
            "Slack did not confirm the message, so the assignee may or may not have it. "
            "Check Slack before you run this step again."
        ) from exc
    except Exception:
        release(reservation)
        raise
    if slack_user_id is None:
        release(reservation)
        return AssigneeSlackDmResult(outcome=AssigneeSlackDmOutcome.UNASSIGNED)
    publish(reservation, slack_user_id, replay_ttl_seconds=_REPLAY_TTL_SECONDS)
    return AssigneeSlackDmResult(outcome=AssigneeSlackDmOutcome.SENT, slack_user_id=slack_user_id)


def _deliver(*, team: Team, ticket: Ticket, integration: Integration, text: str) -> str | None:
    """Send the message and return the Slack member id it went to, or None when the ticket is unassigned."""
    assignment = TicketAssignment.objects.select_related("user", "role").filter(ticket_id=ticket.id).first()
    if assignment is None:
        return None
    if assignment.user is None:
        role_name = assignment.role.name if assignment.role else "a role"
        raise AssigneeSlackDmUndeliverable(
            f"Ticket #{ticket.ticket_number} is assigned to {role_name}. Slack messages to a role are not "
            "supported. Assign the ticket to a person, or send the message to a Slack channel instead."
        )

    assignee = assignment.user
    # Checked at send time because a ticket can stay assigned to someone after they leave the
    # project, and the message carries ticket content.
    if not (assignee.is_active and user_can_access_team(assignee, team)):
        raise AssigneeSlackDmUndeliverable(
            f"The assignee of ticket #{ticket.ticket_number} no longer has access to this project, "
            "so PostHog did not message them."
        )

    slack = SlackIntegration(integration, source="conversations_assignee_slack_dm")
    client = slack.client
    slack_user_id = _resolve_slack_member(slack, client, integration, assignee)
    if slack_user_id is None:
        raise AssigneeSlackDmUndeliverable(
            f"PostHog could not find {_display_name(assignee)} in this Slack workspace. Ask them to connect "
            "their Slack account to PostHog, or to use the same email address in Slack and PostHog."
        )

    # The text is rendered from workflow variables, which can carry customer-controlled ticket fields.
    # Escaping stops those from becoming disguised links or mentions in a message from the PostHog bot.
    safe_text = escape_slack_mrkdwn(text)
    try:
        client.chat_postMessage(
            channel=slack_user_id,
            text=safe_text,
            blocks=_message_blocks(team=team, ticket=ticket, text=safe_text),
            unfurl_links=False,
        )
    except SlackApiError as exc:
        logger.warning("assignee_slack_dm_failed", ticket_id=str(ticket.id), error=_slack_error_code(exc))
        raise AssigneeSlackDmUndeliverable(
            f"Slack refused the message ({_slack_error_code(exc) or 'unknown error'})."
        ) from exc
    except Exception as exc:
        logger.warning("assignee_slack_dm_outcome_unknown", ticket_id=str(ticket.id), exc_info=True)
        raise _SendOutcomeUnknown(slack_user_id) from exc
    return slack_user_id


def _resolve_slack_member(
    slack: SlackIntegration, client: SlackWebClient, integration: Integration, user: User
) -> str | None:
    """The assignee's Slack member id in this workspace, or None when they cannot receive a DM.

    The Slack account the user linked to PostHog answers first. Their PostHog email against the
    workspace directory is the fallback, so the step works before anyone links an account.
    `get_user_by_id` then rejects bots, guests, deactivated members, and Slack Connect members whose
    home workspace is another one. `users.lookupByEmail` also returns Slack Connect members, whose
    profile email is set by another workspace's admin.
    """
    try:
        member_id = _linked_slack_member_id(user, integration) or _slack_member_id_by_email(client, user.email)
        if not member_id:
            return None
        return member_id if slack.get_user_by_id(member_id) else None
    except SlackApiError as exc:
        if _slack_error_code(exc) == "missing_scope":
            raise AssigneeSlackDmUndeliverable(
                "PostHog cannot look up members in this Slack workspace. Reconnect Slack to give it the "
                "users:read and users:read.email permissions."
            ) from exc
        raise AssigneeSlackDmUndeliverable(
            f"Slack did not answer the member lookup ({_slack_error_code(exc) or 'unknown error'})."
        ) from exc


def _linked_slack_member_id(user: User, integration: Integration) -> str | None:
    link = (
        UserIntegration.objects.filter(
            user=user,
            kind=UserIntegration.IntegrationKind.SLACK,
            config__slack_team_id=integration.integration_id,
        )
        .order_by("-created_at")
        .first()
    )
    return link.integration_id if link else None


def _slack_member_id_by_email(client: SlackWebClient, email: str) -> str | None:
    if not email:
        return None
    try:
        response = client.users_lookupByEmail(email=email)
    except SlackApiError as exc:
        if _slack_error_code(exc) == "users_not_found":
            return None
        raise
    user = response.get("user") or {}
    return str(user["id"]) if user.get("id") else None


def _slack_error_code(exc: SlackApiError) -> str | None:
    return exc.response.get("error") if exc.response else None


def _display_name(user: User) -> str:
    return f"{user.first_name} {user.last_name}".strip() or user.email


def _message_blocks(*, team: Team, ticket: Ticket, text: str) -> list[dict]:
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": text}},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": f"View ticket #{ticket.ticket_number}"},
                    "url": ticket_deep_link(ticket, team),
                }
            ],
        },
    ]
