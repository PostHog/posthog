from collections.abc import Collection

from posthog.email import EmailMessage


def send_alert_email(
    *,
    recipients: Collection[str],
    campaign_key: str,
    subject: str,
    template_name: str,
    template_context: dict[str, object],
) -> None:
    message = EmailMessage(
        campaign_key=campaign_key,
        subject=subject,
        template_name=template_name,
        template_context=template_context,
    )
    for recipient in recipients:
        message.add_recipient(email=recipient)
    message.send()
