"""Facade for alert email notifications."""

from __future__ import annotations

from collections.abc import Collection

from ..logic import email_notifications


def send_alert_email(
    *,
    recipients: Collection[str],
    campaign_key: str,
    subject: str,
    template_name: str,
    template_context: dict[str, object],
) -> None:
    """Send one alert email to every recipient."""
    email_notifications.send_alert_email(
        recipients=recipients,
        campaign_key=campaign_key,
        subject=subject,
        template_name=template_name,
        template_context=template_context,
    )
