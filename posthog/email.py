import sys
from typing import Optional

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
from decimal import Decimal
import requests

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


def is_http_email_service_available() -> bool:
    """
    Returns whether HTTP email services are available on this instance (i.e. settings are in place).
    This currently only supports Customer.io.
    """
    return bool(settings.CUSTOMER_IO_API_KEY)


def is_smtp_email_service_available() -> bool:
    """
    Returns whether SMTP email services are available on this instance (i.e. settings are in place).
    """
    return bool(get_instance_setting("EMAIL_HOST"))


def is_email_available(with_absolute_urls: bool = False) -> bool:
    """
    Returns whether email services are available on this instance (i.e. settings are in place).
    Emails with absolute URLs can't be sent if SITE_URL is unset.
    """
    email_enabled = get_instance_setting("EMAIL_ENABLED")
    smtp_email_service_available = is_smtp_email_service_available()
    http_email_service_available = is_http_email_service_available()
    site_url_set = settings.SITE_URL is not None

    if not email_enabled:
        return False

    if not (smtp_email_service_available or http_email_service_available):
        return False

    if with_absolute_urls and not site_url_set:
        return False

    return True


EMAIL_TASK_KWARGS = {
    "queue": CeleryQueue.EMAIL.value,
    "ignore_result": True,
    "autoretry_for": (Exception,),
    "max_retries": 3,
    "retry_backoff": True,
}


# Note: this http sender is only configure for customer.io right now
def _send_via_http(
    to: list[dict[str, str]],
    campaign_key: str,
    subject: str,
    html_body: str,
    headers: dict,
    reply_to: Optional[str] = None,
) -> None:
    """Sends emails using Customer.io API"""
    customerio_api_key = settings.CUSTOMER_IO_API_KEY

    if not customerio_api_key:
        raise Exception(f"Missing Customer.io API key: {customerio_api_key}")

    api_headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {customerio_api_key}",
    }

    try:
        for dest in to:
            with transaction.atomic():
                record, _ = MessagingRecord.objects.get_or_create(
                    raw_email=dest["raw_email"], campaign_key=campaign_key
                )

                record = MessagingRecord.objects.select_for_update().get(pk=record.pk)
                if record.sent_at:
                    continue

                properties = {
                    "subject": subject,
                    "body": html_body,
                    "reply_to": reply_to or get_instance_setting("EMAIL_REPLY_TO"),
                    **headers,
                }

                # Convert any Decimal values to float for JSON serialization
                properties = {k: float(v) if isinstance(v, Decimal) else v for k, v in properties.items()}

                payload = {
                    "transactional_message_id": campaign_key,
                    "to": dest["raw_email"],
                    "identifiers": {"email": dest["raw_email"]},
                    "message_data": properties,
                }

                response = requests.post("https://api.customer.io/v1/send/email", headers=api_headers, json=payload)

                if response.status_code != 200:
                    raise Exception(f"Customer.io API error: {response.status_code} - {response.text}")

                record.sent_at = timezone.now()
                record.save()

    except Exception as err:
        print("Could not send email via http:", err, file=sys.stderr)
        capture_exception(err)


def _send_via_smtp(
    to: list[dict[str, str]],
    campaign_key: str,
    subject: str,
    txt_body: str,
    html_body: str,
    headers: dict,
    reply_to: Optional[str] = None,
) -> None:
    """Sends emails using SMTP"""
    messages: list = []
    records: list = []

    with transaction.atomic():
        for dest in to:
            record, _ = MessagingRecord.objects.get_or_create(raw_email=dest["raw_email"], campaign_key=campaign_key)

            record = MessagingRecord.objects.select_for_update().get(pk=record.pk)
            if record.sent_at:
                record.save()
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
            print("Could not send email:", err, file=sys.stderr)
            capture_exception(err)
        finally:
            try:
                connection.close()  # type: ignore
            except Exception as err:
                print(
                    "Could not close email connection (this can be ignored):",
                    err,
                    file=sys.stderr,
                )


@shared_task(**EMAIL_TASK_KWARGS)
def _send_email(
    campaign_key: str,
    to: list[dict[str, str]],
    subject: str,
    headers: dict,
    txt_body: str = "",
    html_body: str = "",
    reply_to: Optional[str] = None,
    use_http: Optional[bool] = False,
) -> None:
    """
    Sends built email message asynchronously, either through SMTP or HTTP
    """
    if use_http:
        _send_via_http(
            to=to,
            campaign_key=campaign_key,
            subject=subject,
            html_body=html_body,
            headers=headers,
            reply_to=reply_to,
        )
    else:
        _send_via_smtp(
            to=to,
            campaign_key=campaign_key,
            subject=subject,
            txt_body=txt_body,
            html_body=html_body,
            headers=headers,
            reply_to=reply_to,
        )


class EmailMessage:
    def __init__(
        self,
        campaign_key: str,
        subject: str,
        template_name: str,
        template_context: Optional[dict] = None,
        headers: Optional[dict] = None,
        reply_to: Optional[str] = None,
        use_http: Optional[bool] = False,
    ):
        if template_context is None:
            template_context = {}
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
        self.to: list[dict[str, str]] = []
        self.reply_to = reply_to
        self.use_http = use_http

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
            "use_http": self.use_http,
        }

        if send_async:
            _send_email.apply_async(kwargs=kwargs)
        else:
            _send_email.apply(kwargs=kwargs)
