"""Facade for alert email notifications."""

from __future__ import annotations

from collections.abc import Collection
from uuid import UUID

from posthog.email import EmailMessage

from products.alerts.backend.logic import alert_email


def send_alert_email(
    *,
    recipients: Collection[str],
    campaign_key: str,
    subject: str,
    template_name: str,
    template_context: dict[str, object],
) -> None:
    """Send one alert email to every recipient."""
    message = EmailMessage(
        campaign_key=campaign_key,
        subject=subject,
        template_name=template_name,
        template_context=template_context,
    )
    for recipient in recipients:
        message.add_recipient(email=recipient)
    message.send()


def alert_email_recipients(*, team_id: int, alert_id: UUID) -> list[tuple[int, str]]:
    """Subscribed users who can still view the project and the alert's insight, as (id, email)."""
    return alert_email.alert_email_recipients(team_id=team_id, alert_id=alert_id)
