import html
import uuid
import smtplib
import datetime
import dataclasses
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal, Optional

if TYPE_CHECKING:
    from posthog.models import User

from django.conf import settings
from django.core import exceptions, mail
from django.core.mail.backends.smtp import EmailBackend
from django.db import transaction
from django.template.loader import get_template
from django.utils import timezone
from django.utils.module_loading import import_string

import requests
import structlog
import css_inline
import posthoganalytics
from celery import shared_task
from lxml import html as lxml_html
from prometheus_client import Counter

from posthog.celery_queues import CeleryQueue
from posthog.exceptions_capture import capture_exception
from posthog.helpers.email_utils import sanitize_email_string
from posthog.models.instance_setting import get_instance_setting
from posthog.models.messaging import MessagingRecord

logger = structlog.get_logger(__name__)


def inline_css(value: str) -> str:
    """
    Returns an HTML document with inline CSS.
    Forked from getsentry/sentry

    `keep_at_rules=True` preserves at-rules that can't be inlined onto elements — chiefly the
    `@media` responsive block. Without it, css_inline drops every `<style>` block after
    inlining and media queries never apply.
    """
    inlined = css_inline.inline(value, keep_at_rules=True)
    tree = lxml_html.document_fromstring(inlined)
    # CSS media query support is inconsistent when the DOCTYPE declaration is
    # missing, so we force it to HTML5 here.
    return lxml_html.tostring(tree, doctype="<!DOCTYPE html>").decode("utf-8")


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

# Failure rate as an alertable time series. Labelled only by outcome+transport to bound
# cardinality (per-team volume lives in MessagingRecord); scraped via prometheus multiprocess.
EMAIL_SEND_COUNTER = Counter(
    "posthog_email_send_total",
    "Email send attempts by outcome (sent|failed) and transport (smtp|http).",
    labelnames=["outcome", "transport"],
)

# Retryable connection/network errors only. NOT bare OSError: every smtplib exception subclasses
# it, so OSError would also retry auth/recipient failures and re-hammer the relay's per-IP limit.
_TRANSIENT_SMTP_ERRORS = (
    smtplib.SMTPServerDisconnected,
    smtplib.SMTPConnectError,
    smtplib.SMTPHeloError,
    TimeoutError,  # socket timeouts
    ConnectionError,  # reset / refused / aborted
)

CUSTOMER_IO_TEMPLATE_ID_MAP = {
    # Set up in customer.io
    "2fa_enabled": "31",
    "2fa_disabled": "30",
    "2fa_backup_code_used": "29",
    "2fa_reset": "62",
    "password_reset": "32",
    "invite": "33",
    "member_join": "34",
    "email_verification": "35",
    "email_change_old_address": "36",
    "email_change_new_address": "37",
    "password_changed": "42",
    "login_notification": "44",
    "personal_api_key_exposed": "45",
    "code_based_verification": "48",
    "project_secret_api_key_exposed": "49",
    "oauth_token_exposed": "50",
    "passkey_added": "51",
    "passkey_removed": "52",
    "new_conversation_ticket": "53",
    "project_deleted": "54",
    "organization_deleted": "55",
    "approval_requested": "60",
    "approval_approved": "57",
    "approval_rejected": "58",
    "approval_expired": "59",
    "approval_applied": "61",
    "conversation_restore": "63",
    "proxy_provisioned": "64",
    "delegation_invite": "66",
    "provisioning_welcome": "67",
    "baa_signed_ai_disabled": "68",
    "integration_access_requested": "70",
    "posthog_ai_access_requested": "72",
}


def get_customer_io_template_id(template_name: str) -> str:
    """Get Customer.io template ID from template name"""
    template_id = CUSTOMER_IO_TEMPLATE_ID_MAP.get(template_name)
    if not template_id:
        raise Exception(f"Unknown template name: {template_name}")
    return template_id


# Note: this http sender is only configure for customer.io right now and it's set up to send
# via templates so all the configuration is done in the customer.io - i.e. no subject, body, etc.
def _send_via_http(
    to: list[dict[str, str]],
    campaign_key: str,
    template_name: str,
    properties: dict,
) -> None:
    """Sends emails using Customer.io API"""
    customerio_api_key = settings.CUSTOMER_IO_API_KEY

    if not customerio_api_key:
        raise Exception("Missing Customer.io API key")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {customerio_api_key}",
    }

    sent_count = 0
    already_sent_count = 0  # delivered in a prior run — not a failure if the batch later aborts
    try:
        for dest in to:
            with transaction.atomic():
                record, _ = MessagingRecord.objects.get_or_create(
                    raw_email=dest["raw_email"], campaign_key=campaign_key
                )

                record = MessagingRecord.objects.select_for_update().get(pk=record.pk)
                if record.sent_at:
                    already_sent_count += 1
                    continue

                identifiers: dict[str, str] = {"email": dest["raw_email"]}
                if dest.get("distinct_id"):
                    identifiers["id"] = dest["distinct_id"]

                payload = {
                    "transactional_message_id": get_customer_io_template_id(template_name),
                    "to": dest["raw_email"],
                    "identifiers": identifiers,
                    "message_data": properties,
                }

                response = requests.post(f"{settings.CUSTOMER_IO_API_URL}/v1/send/email", headers=headers, json=payload)

                if response.status_code != 200:
                    raise Exception(f"Customer.io API error: {response.status_code} - {response.text}")

                provider_response = response.json()

                posthoganalytics.capture(
                    distinct_id=dest.get("distinct_id") or dest["raw_email"],
                    event="transactional email triggered",
                    properties={
                        "template_name": template_name,
                        "campaign_key": campaign_key,
                        "recipient_email": dest["raw_email"],
                        **provider_response,
                    },
                )

                record.sent_at = timezone.now()
                record.save()

                EMAIL_SEND_COUNTER.labels(outcome="sent", transport="http").inc()
                sent_count += 1

    except Exception as err:
        capture_exception(err)  # already logs the traceback via logger.exception
        # Count every recipient that did not get through (the failing one + any not yet attempted),
        # so `failed` shares the per-recipient unit with `sent` instead of registering once per batch.
        EMAIL_SEND_COUNTER.labels(outcome="failed", transport="http").inc(len(to) - already_sent_count - sent_count)


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
            # Bound the socket so a relay that goes silent mid-conversation raises TimeoutError
            # (retried below) instead of pinning the worker forever — the silent-hang case.
            timeout=get_instance_setting("EMAIL_TIMEOUT"),
        )
        connection.open()

        for dest in to:
            # Per-recipient transaction so each delivery's `sent_at` commits before the next send.
            # A transient mid-batch failure re-raises into autoretry; the `if record.sent_at` guard
            # then skips the recipients already accepted on retry, instead of re-sending (and
            # duplicating) the whole batch.
            with transaction.atomic():
                record, _ = MessagingRecord.objects.get_or_create(
                    raw_email=dest["raw_email"], campaign_key=campaign_key
                )
                record = MessagingRecord.objects.select_for_update().get(pk=record.pk)
                if record.sent_at:
                    continue

                effective_reply_to = reply_to or get_instance_setting("EMAIL_REPLY_TO")
                email_message = mail.EmailMultiAlternatives(
                    subject=subject,
                    body=txt_body,
                    from_email=get_instance_setting("EMAIL_DEFAULT_FROM"),
                    to=[dest["recipient"]],
                    headers=headers,
                    reply_to=[effective_reply_to] if effective_reply_to else None,
                )
                email_message.attach_alternative(html_body, "text/html")

                connection.send_messages([email_message])

                record.sent_at = timezone.now()
                record.save()
                EMAIL_SEND_COUNTER.labels(outcome="sent", transport="smtp").inc()
    except _TRANSIENT_SMTP_ERRORS as err:
        # Re-raise so the task's autoretry (3x + backoff) retries instead of dropping the email.
        # warning, not capture_exception: expected + auto-retried, capturing each attempt is noise.
        logger.warning("email_send_smtp_transient_error", error=str(err))
        EMAIL_SEND_COUNTER.labels(outcome="failed", transport="smtp").inc()
        raise
    except smtplib.SMTPRecipientsRefused as err:
        # Per-recipient codes live in .recipients ({addr: (code, msg)}), not a top-level smtp_code.
        # A 4xx (greylisting) is "try again later" → retry; 5xx (bad mailbox) is permanent.
        EMAIL_SEND_COUNTER.labels(outcome="failed", transport="smtp").inc()
        if any(400 <= code < 500 for code, _ in err.recipients.values()):
            logger.warning("email_send_smtp_transient_error", error=str(err))
            raise
        capture_exception(err)
    except smtplib.SMTPResponseException as err:
        # Send-path response codes (raised by sendmail): 4xx greylisting (450/451) and overloaded-relay
        # 421 are retryable; 5xx and auth (535) are permanent → swallow so we don't retry-storm the relay.
        EMAIL_SEND_COUNTER.labels(outcome="failed", transport="smtp").inc()
        if err.smtp_code is not None and 400 <= err.smtp_code < 500:
            logger.warning("email_send_smtp_transient_error", error=str(err))
            raise
        capture_exception(err)
    except Exception as err:
        capture_exception(err)  # already logs the traceback via logger.exception
        EMAIL_SEND_COUNTER.labels(outcome="failed", transport="smtp").inc()
    finally:
        # Guard against a backend-construction failure (bad EMAIL_BACKEND, or TLS+SSL both set):
        # connection is still None there, and an unguarded None.close() would log a misleading
        # email_connection_close_failed over the real error already captured above.
        if connection is not None:
            try:
                connection.close()
            except Exception as err:
                logger.warning("email_connection_close_failed", error=str(err))


# `utm_tags` carries hardcoded query-string fragments (`a=1&b=2`) and is never
# user-controlled. It must pass through verbatim so the `&` separators don't
# get HTML-escaped before reaching Customer.io — Liquid renders the value raw,
# and mail clients expect the literal `&` between query parameters.
_PASSTHROUGH_KEYS = {"utm_tags"}

# Keys whose values are PostHog-generated URLs (built from `settings.SITE_URL`
# + a path) and should remain clickable in the rendered email. Defanging would
# break every "click here" button, so URL-shape characters (`:`, `/`, `.`) are
# preserved — but attribute-injection characters (`<`, `>`, `"`, `'`, `&`) are
# still html-escaped, so a user-controlled path segment (e.g. the `slug`
# appended in `build_comment_item_url`) cannot break out of `<a href="...">`.
_TRUSTED_URL_KEYS = {"url", "href", "link", "site_url"}
_TRUSTED_URL_KEY_SUFFIXES = ("_url", "_link", "_href")

_KeyPolicy = Literal["passthrough", "trusted_url", "default"]


def _classify_key(key: Any) -> _KeyPolicy:
    if not isinstance(key, str):
        return "default"
    lower = key.lower()
    if lower in _PASSTHROUGH_KEYS:
        return "passthrough"
    if lower in _TRUSTED_URL_KEYS or lower.endswith(_TRUSTED_URL_KEY_SUFFIXES):
        return "trusted_url"
    return "default"


def sanitize_email_properties(properties: dict[str, Any] | None) -> dict[str, Any]:
    """
    Sanitizes properties that will be used in email templates to prevent HTML
    injection and to defang URL-shaped strings so mail clients don't auto-link
    user-controlled content like display names or organization names.
    Recursively processes dictionaries, lists, and scalar values. Keys are
    handled in three tiers:

    - `_PASSTHROUGH_KEYS` (e.g. `utm_tags`) — value returned unchanged.
    - `_TRUSTED_URL_KEYS` and `*_url` / `*_link` / `*_href` — html-escaped only,
      no defang, so the link stays clickable but a user-controlled portion of
      the URL can't escape the href attribute.
    - everything else — full `sanitize_email_string` (NFKC + invisible-strip +
      html-escape + URL defang).

    Args:
        properties: Dictionary of properties to sanitize

    Returns:
        Sanitized copy of the properties dictionary

    Raises:
        TypeError: If an unsupported type is encountered
    """
    if properties is None:
        return {}

    supported_types = (str, int, float, bool, type(None), Decimal, uuid.UUID, datetime.datetime, datetime.date)

    def sanitize_value(value: Any, *, key: Any = None) -> Any:
        policy = _classify_key(key) if key is not None else "default"
        if policy == "passthrough":
            return value
        if isinstance(value, str):
            if policy == "trusted_url":
                return html.escape(value)
            return sanitize_email_string(value)
        elif isinstance(value, dict):
            return {k: sanitize_value(v, key=k) for k, v in value.items()}
        elif isinstance(value, list):
            return [sanitize_value(item) for item in value]
        elif isinstance(value, uuid.UUID):
            return sanitize_email_string(str(value))
        elif isinstance(value, datetime.datetime | datetime.date):
            # Reached via dataclasses.asdict() for facade contracts with created_at-style fields.
            return sanitize_email_string(value.isoformat())
        elif hasattr(value, "_meta") and hasattr(value, "pk"):
            # str(model) often contains user-controlled fields (Team.name, Organization.name)
            # that mail clients would otherwise auto-link.
            return sanitize_email_string(str(value))
        elif isinstance(value, Decimal):
            return float(value)
        elif isinstance(value, int | float | bool | type(None)):
            return value
        elif dataclasses.is_dataclass(value) and not isinstance(value, type):
            return {k: sanitize_value(v, key=k) for k, v in dataclasses.asdict(value).items()}
        else:
            raise TypeError(
                f"Unsupported type in email properties: {type(value).__name__}. "
                f"Only {', '.join(t.__name__ for t in supported_types)}, dict, list, dataclasses, and Django models are supported."
            )

    return {k: sanitize_value(v, key=k) for k, v in properties.items()}


@shared_task(**EMAIL_TASK_KWARGS)
def _send_email(
    campaign_key: str,
    to: list[dict[str, str]],
    subject: str,
    headers: dict,
    txt_body: str = "",
    html_body: str = "",
    template_name: str = "",
    reply_to: Optional[str] = None,
    use_http: Optional[bool] = False,
    properties: Optional[dict] = None,
) -> None:
    """
    Sends built email message asynchronously, either through SMTP or HTTP
    """
    if use_http and is_http_email_service_available():
        _send_via_http(
            to=to,
            campaign_key=campaign_key,
            template_name=template_name,
            properties=properties or {},
        )
    elif is_smtp_email_service_available():
        _send_via_smtp(
            to=to,
            campaign_key=campaign_key,
            subject=subject,
            txt_body=txt_body,
            html_body=html_body,
            headers=headers,
            reply_to=reply_to,
        )
    else:
        raise Exception("Email is not enabled in this instance.")


class EmailMessage:
    def __init__(
        self,
        campaign_key: str,
        template_name: str,
        subject: Optional[str] = None,
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
        self.use_http = use_http
        self.to: list[dict[str, str]] = []
        self.subject = subject or ""
        self.reply_to = reply_to
        self.template_name = template_name

        self.properties = sanitize_email_properties(template_context)

        template = get_template(f"email/{template_name}.html")
        self.html_body = inline_css(template.render(template_context))
        self.txt_body = ""
        self.headers = headers if headers else {}

    def add_recipient(self, email: str, name: Optional[str] = None, distinct_id: Optional[str] = None) -> None:
        sanitized_name = html.escape(name) if name else None
        recipient_data = {
            "recipient": f'"{sanitized_name}" <{email}>' if sanitized_name else email,
            "raw_email": email,
        }
        if distinct_id:
            recipient_data["distinct_id"] = distinct_id
        self.to.append(recipient_data)

    def add_user_recipient(self, user: "User", email_override: Optional[str] = None) -> None:
        """
        Add a user as a recipient, include their distinct_id for Customer.io reporting wenhooks.
        Use this instead of add_recipient when you have a User object.
        """
        email = email_override or user.email
        self.add_recipient(email=email, name=user.first_name, distinct_id=str(user.distinct_id))

    def send(self, send_async: bool = True) -> None:
        if not self.to:
            raise ValueError("No recipients provided! Use EmailMessage.add_recipient() first!")

        kwargs = {
            "campaign_key": self.campaign_key,
            "to": self.to,
            "subject": self.subject,
            "headers": self.headers,
            "txt_body": self.txt_body,
            "template_name": self.template_name,
            "html_body": self.html_body,
            "reply_to": self.reply_to,
            "use_http": self.use_http,
            "properties": self.properties,
        }

        if send_async:
            _send_email.apply_async(kwargs=kwargs)
        else:
            _send_email.apply(kwargs=kwargs)
