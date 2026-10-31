"""Facade for alert email notifications."""

from __future__ import annotations

from collections.abc import Collection
from uuid import UUID

import structlog

from posthog.email import EmailMessage, is_email_available

from products.alerts.backend.logic import alert_email

logger = structlog.get_logger(__name__)


def send_alert_email(
    *,
    recipients: Collection[str],
    campaign_key: str,
    subject: str,
    template_name: str,
    template_context: dict[str, object],
) -> bool:
    """Send one alert email to every recipient. Returns False and sends nothing when the instance has no email."""
    if not is_email_available():
        logger.info("Skipping alert email because email is not available", campaign_key=campaign_key)
        return False
    message = EmailMessage(
        campaign_key=campaign_key,
        subject=subject,
        template_name=template_name,
        template_context=template_context,
    )
    for recipient in recipients:
        message.add_recipient(email=recipient)
    message.send()
    return True


def alert_email_recipients(*, team_id: int, alert_id: UUID) -> list[tuple[int, str]]:
    """Subscribed users who can still view the project and the alert's insight, as (id, email)."""
    return alert_email.alert_email_recipients(team_id=team_id, alert_id=alert_id)
