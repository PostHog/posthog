import sys
from typing import Dict, List, Optional

import lxml
import toronado
from celery import shared_task
from django.conf import settings
from django.core import exceptions, mail
from django.core.mail.backends.smtp import EmailBackend
from django.db import transaction
from django.template.loader import get_template
from django.utils import timezone
from django.utils.module_loading import import_string
from sentry_sdk import capture_exception

from posthog.models.instance_setting import get_instance_setting
from posthog.models.messaging import MessagingRecord
from posthog.tasks.utils import CeleryQueue


def inline_css(value: str) -> str:
    """
    Returns an HTML document with inline CSS.
    Forked from getsentry/sentry
    """
    tree = lxml.html.document_fromstring(value)
    toronado.inline(tree)
    # CSS media query support is inconsistent when the DOCTYPE declaration is
    # missing, so we force it to HTML5 here.
    return lxml.html.tostring(tree, doctype="<!DOCTYPE html>").decode("utf-8")


def is_email_available(with_absolute_urls: bool = False) -> bool:
    """
    Returns whether email services are available on this instance (i.e. settings are in place).
    Emails with absolute URLs can't be sent if SITE_URL is unset.
    """
    return (
        get_instance_setting("EMAIL_ENABLED")
        and bool(get_instance_setting("EMAIL_HOST"))
        and (not with_absolute_urls or settings.SITE_URL is not None)
    )


EMAIL_TASK_KWARGS = dict(
    queue=CeleryQueue.EMAIL.value,
    ignore_result=True,
    autoretry_for=(Exception,),
    max_retries=3,
    retry_backoff=True,
)


@shared_task(**EMAIL_TASK_KWARGS)
def _send_email(
    campaign_key: str,
    to: List[Dict[str, str]],
    subject: str,
    headers: Dict,
    txt_body: str = "",
    html_body: str = "",
    reply_to: Optional[str] = None,
) -> None:
    """
    Sends built email message asynchronously.
    """

    messages: List = []
    records: List = []

    with transaction.atomic():
        for dest in to:
            record, _ = MessagingRecord.objects.get_or_create(raw_email=dest["raw_email"], campaign_key=campaign_key)

            # Lock object (database-level) while the message is sent
            record = MessagingRecord.objects.select_for_update().get(pk=record.pk)
            # If an email for this campaign was already sent to this user, skip recipient
            if record.sent_at:
                record.save()  # release DB lock
                continue

            records.append(record)
            reply_to = reply_to or get_instance_setting("EMAIL_REPLY_TO")

            email_message = mail.EmailMultiAlternatives(
                subject=subject,
                body=txt_body,
                from_email=get_instance_setting("EMAIL_DEFAULT_FROM"),
                to=[dest["recipient"]],
                headers=headers,
                reply_to=[reply_to] if reply_to else None,
            )

            email_message.attach_alternative(html_body, "text/html")
            messages.append(email_message)

        connection = None
        try:
            klass = import_string(settings.EMAIL_BACKEND) if settings.EMAIL_BACKEND else EmailBackend
            connection = klass(
                host=get_instance_setting("EMAIL_HOST"),
                port=get_instance_setting("EMAIL_PORT"),
                username=get_instance_setting("EMAIL_HOST_USER"),
                password=get_instance_setting("EMAIL_HOST_PASSWORD"),
                use_tls=get_instance_setting("EMAIL_USE_TLS"),
                use_ssl=get_instance_setting("EMAIL_USE_SSL"),
            )
            connection.open()
            connection.send_messages(messages)

            for record in records:
                record.sent_at = timezone.now()
                record.save()

        except Exception as err:
            # Handle exceptions gracefully to avoid breaking the entire task for all teams
            # but make sure they're tracked on Sentry.
            print("Could not send email:", err, file=sys.stderr)
            capture_exception(err)
        finally:
            # Ensure that connection has been closed
            try:
                connection.close()  # type: ignore
            except Exception as err:
                print(
                    "Could not close email connection (this can be ignored):",
                    err,
                    file=sys.stderr,
                )


class EmailMessage:
    def __init__(
        self,
        campaign_key: str,
        subject: str,
        template_name: str,
        template_context: Dict = {},
        headers: Optional[Dict] = None,
        reply_to: Optional[str] = None,
    ):
        if not is_email_available():
            raise exceptions.ImproperlyConfigured("Email is not enabled in this instance.")

        if "utm_tags" not in template_context:
            template_context.update({"utm_tags": f"utm_source=posthog&utm_medium=email&utm_campaign={template_name}"})

        self.campaign_key = campaign_key
        self.subject = subject
        template = get_template(f"email/{template_name}.html")
        self.html_body = inline_css(template.render(template_context))
        self.txt_body = ""
        self.headers = headers if headers else {}
        self.to: List[Dict[str, str]] = []
        self.reply_to = reply_to

    def add_recipient(self, email: str, name: Optional[str] = None) -> None:
        self.to.append({"recipient": f'"{name}" <{email}>' if name else email, "raw_email": email})

    def send(self, send_async: bool = True) -> None:
        if not self.to:
            raise ValueError("No recipients provided! Use EmailMessage.add_recipient() first!")

        kwargs = {
            "campaign_key": self.campaign_key,
            "to": self.to,
            "subject": self.subject,
            "headers": self.headers,
            "txt_body": self.txt_body,
            "html_body": self.html_body,
            "reply_to": self.reply_to,
        }

        if send_async:
            _send_email.apply_async(kwargs=kwargs)
        else:
            _send_email.apply(kwargs=kwargs)
