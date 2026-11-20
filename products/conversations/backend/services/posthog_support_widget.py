"""Send a ticket to PostHog's own support team through its support widget, as the person.

The support form in the web app sends through the same widget API from the person's browser. This
client signs the same identity that the web app gives the browser, so a ticket sent from either place
lands in the person's own ticket list.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings

import requests
import structlog
from urllib3.exceptions import NewConnectionError

from posthog.dataclasses import frozen
from posthog.models.instance_setting import get_instance_setting
from posthog.models.user import User
from posthog.utils import resolve_self_flags_team

from products.conversations.backend.services.identity import (
    compute_identity_hash,
    sign_email_claim,
    widget_session_id_for_identity_hash,
)

WIDGET_MESSAGE_PATH = "/api/conversations/v1/widget/message"
WIDGET_REQUEST_TIMEOUT_SECONDS = 10

logger = structlog.get_logger(__name__)


class SupportTicketNotSent(Exception):
    """The widget did not create the ticket, so the same draft can be sent again."""


class SupportTicketOutcomeUnknown(Exception):
    """The request may have reached the widget, so the ticket may exist."""


@frozen
class SupportWidgetTarget:
    host: str
    token: str


@frozen
class SentSupportTicket:
    ticket_id: str
    ticket_number: int | None


def resolve_support_widget_target() -> SupportWidgetTarget:
    if settings.POSTHOG_SUPPORT_WIDGET_HOST and settings.POSTHOG_SUPPORT_WIDGET_TOKEN:
        return SupportWidgetTarget(
            host=settings.POSTHOG_SUPPORT_WIDGET_HOST.rstrip("/"), token=settings.POSTHOG_SUPPORT_WIDGET_TOKEN
        )
    if settings.SELF_CAPTURE:
        # The web app's own posthog-js reports to this team on a dev instance, so its support widget files
        # tickets there too. A ticket sent from here then lands beside the ones sent from the browser.
        team = resolve_self_flags_team()
        token = (team.conversations_settings or {}).get("widget_public_token") if team else None
        if team and team.conversations_enabled and token:
            return SupportWidgetTarget(host=settings.SITE_URL, token=token)
    raise SupportTicketNotSent("PostHog support is not set up on this instance.")


def _never_connected(error: requests.RequestException) -> bool:
    if isinstance(error, requests.ConnectTimeout):
        return True
    # requests wraps a refused connection or a failed DNS lookup in a ConnectionError. The request never
    # left this server in those cases, unlike a connection that drops while the widget answers.
    reason = getattr(error.args[0], "reason", None) if error.args else None
    return isinstance(error, requests.ConnectionError) and isinstance(reason, NewConnectionError)


class PostHogSupportWidgetClient:
    def __init__(self, target: SupportWidgetTarget) -> None:
        self._target = target

    def send_ticket(self, user: User, message: str) -> SentSupportTicket:
        payload = self._payload(user, message)
        try:
            response = requests.post(
                f"{self._target.host}{WIDGET_MESSAGE_PATH}",
                json=payload,
                headers={
                    "X-Conversations-Token": self._target.token,
                    # The widget takes tickets only from the sites its project allows. The person's browser
                    # sends this same origin when they send a ticket from the web app.
                    "Origin": settings.SITE_URL,
                },
                timeout=WIDGET_REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as e:
            # The exception text holds the URL, so log only its type.
            logger.warning("posthog_support_widget_request_failed", error_type=type(e).__name__)
            if _never_connected(e):
                raise SupportTicketNotSent("PostHog support could not be reached.") from e
            raise SupportTicketOutcomeUnknown("The connection to PostHog support failed during the send.") from e

        # The widget checks the token, the origin, the identity, the message and its rate limits before it
        # creates a ticket, so a 4xx answer means that nothing was created.
        if 400 <= response.status_code < 500:
            logger.warning("posthog_support_widget_refused", status=response.status_code)
            raise SupportTicketNotSent("PostHog support refused the ticket.")
        if not response.ok:
            logger.warning("posthog_support_widget_failed", status=response.status_code)
            raise SupportTicketOutcomeUnknown("PostHog support failed while it handled the ticket.")
        try:
            data = response.json()
            return SentSupportTicket(ticket_id=str(data["ticket_id"]), ticket_number=data.get("ticket_number"))
        except (ValueError, KeyError, TypeError) as e:
            raise SupportTicketOutcomeUnknown("PostHog support sent an answer without a ticket.") from e

    def _payload(self, user: User, message: str) -> dict[str, Any]:
        secret = get_instance_setting("CONVERSATIONS_HMAC_SIGNING_SECRET")
        if not secret or not user.distinct_id:
            raise SupportTicketNotSent("Support identity signing is not set up on this instance.")
        identity_hash = compute_identity_hash(user.distinct_id, secret)
        payload: dict[str, Any] = {
            "message": message,
            "identity_distinct_id": user.distinct_id,
            "identity_hash": identity_hash,
            # The widget rate-limits each widget session, or each IP when a request has no session id.
            # Every send comes from a few server IPs, so without the id all people would share one limit.
            "widget_session_id": widget_session_id_for_identity_hash(identity_hash),
            "traits": {key: value for key, value in (("name", user.first_name), ("email", user.email)) if value},
        }
        if user.is_email_verified is True:
            claim = sign_email_claim(user.distinct_id, user.email, secret)
            payload |= {
                "identity_email": claim.value,
                "identity_hash_email": claim.hash,
                "identity_exp_email": claim.expires_at,
            }
        return payload
