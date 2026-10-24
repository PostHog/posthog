import re
import html
import uuid
import hashlib
import smtplib
import datetime
import dataclasses
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal, Optional

if TYPE_CHECKING:
    from posthog.models import Organization, Team, User

from django.conf import settings
from django.core import exceptions, mail
from django.core.cache import cache
from django.core.mail.backends.smtp import EmailBackend
from django.db import transaction
from django.template.loader import get_template
from django.utils import timezone
from django.utils.module_loading import import_string

import urllib3
import requests
import structlog
import css_inline
import posthoganalytics
from celery import shared_task
from lxml import html as lxml_html
from prometheus_client import Counter

from posthog.celery_queues import CeleryQueue
from posthog.exceptions_capture import capture_exception
from posthog.helpers.email_utils import sanitize_display_name, sanitize_email_string
from posthog.models.instance_setting import get_instance_setting
from posthog.models.messaging import MessagingRecord, get_email_hashes
from posthog.ph_client import ScopedCapture, ph_scoped_capture
from posthog.utils import get_instance_region

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
    This currently only supports Customer.io. Workflows only takes over emails that this path sends.
    """
    return bool(settings.CUSTOMER_IO_API_KEY)


def is_smtp_email_service_available() -> bool:
    """
    Returns whether SMTP email services are available on this instance (i.e. settings are in place).
    """
    return bool(get_instance_setting("EMAIL_HOST"))


def single_line(value: str) -> str:
    """Flatten CR/LF to a single space so a user-set value is safe in an email Subject.

    A CR or LF in a Subject makes Django raise BadHeaderError, which the send path swallows, so
    the whole notification would be dropped. A run of CR/LF (e.g. "\r\n") collapses to one space
    rather than one per character, so it reads like a single line break once flattened.
    """
    return re.sub(r"[\r\n]+", " ", value)


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
    "email_change_old_address": "36",
    "email_change_new_address": "37",
    "password_changed": "42",
    "login_notification": "44",
    "personal_api_key_exposed": "45",
    "code_based_verification": "75",
    "email_verification_code": "79",
    "feature_flags_secure_api_key_exposed": "49",
    "project_secret_api_key_exposed": "76",
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
    "wizard_pr_ready": "74",
    "loop_run_summary": "77",
}

# Message template ids in the US project, for templates that can send through Workflows instead of Customer.io.
# A template sends through Workflows only for recipients the flag below matches.
WORKFLOWS_TEMPLATE_ID_MAP: dict[str, str] = {
    "password_reset": "01a1597a-5d91-0000-99fa-9eeb18d293c5",
}

# Release conditions match the `email` and `transactional_email_template` person properties passed at evaluation,
# so one flag picks both the recipients and the templates that move.
WORKFLOWS_TRANSACTIONAL_EMAIL_FLAG = "transactional-emails-via-workflows"

# Matches how long the send API keeps an idempotency key, which outlasts every Celery retry.
WORKFLOWS_PIN_TTL_SECONDS = 24 * 60 * 60

EMAIL_WORKFLOWS_FALLBACK_COUNTER = Counter(
    "posthog_email_workflows_fallback_total",
    "Emails that Workflows refused and Customer.io sent instead, by template.",
    labelnames=["template_name"],
)


def get_email_team_and_org_context(
    team: Optional["Team"] = None,
    organization: Optional["Organization"] = None,
) -> dict[str, str]:
    """
    team_name, organization_name, and customer_id (the billing customer) for a transactional
    email. Spread it into template_context whenever a team or organization is in scope. Absent
    values are omitted so templates render only what's present, and both names are sanitized,
    so one that happens to be a URL degrades to a placeholder instead of rendering as a link.
    """
    if organization is None and team is not None:
        organization = team.organization
    context: dict[str, str] = {}
    if team is not None and team.name:
        context["team_name"] = sanitize_display_name(
            team.name,
            fallback="your project",
            context={"helper": "get_email_team_and_org_context", "field": "team_name"},
        )
    if organization is not None:
        if organization.name:
            context["organization_name"] = sanitize_display_name(
                organization.name,
                fallback="your organization",
                context={"helper": "get_email_team_and_org_context", "field": "organization_name"},
            )
        if organization.customer_id:
            context["customer_id"] = organization.customer_id
    return context


def get_customer_io_template_id(template_name: str) -> str:
    """Get Customer.io template ID from template name"""
    template_id = CUSTOMER_IO_TEMPLATE_ID_MAP.get(template_name)
    if not template_id:
        raise Exception(f"Unknown template name: {template_name}")
    return template_id


class WorkflowsEmailError(Exception):
    """Workflows did not queue the email, or the caller could not tell whether it did.

    `code` and `status_code` match posthog-python's `EmailError`, so the fallback rule keeps working when the
    SDK sends instead. `status_code` is None when no response came back.
    """

    def __init__(self, message: str, *, code: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _workflows_error_allows_fallback(err: WorkflowsEmailError) -> bool:
    """Whether Customer.io can send the email without the risk of a duplicate."""
    if err.status_code is None:
        # A connection that was never made and a client that queued nothing sent nothing. Any other network
        # failure can come after Workflows queued the email.
        return err.code in ("connection_error", "not_queued")
    # Redirects and 4xx answers come before anything is queued, apart from 408 and the two idempotency answers:
    # 409 (an attempt with this key is in flight) and 422 (this key already queued an email). A 5xx can follow a
    # queued email, because the send API also returns 503 when the workflow service queued it but failed to answer.
    return 300 <= err.status_code < 500 and err.status_code not in (408, 409, 422)


def _never_connected(err: requests.ConnectionError) -> bool:
    """Whether the request failed before a connection existed, so Workflows cannot have received it."""
    if isinstance(err, requests.ConnectTimeout):
        return True
    reason = err.args[0] if err.args else None
    if isinstance(reason, urllib3.exceptions.MaxRetryError):
        reason = reason.reason
    # A reset after the request went out arrives as a ProtocolError instead.
    return isinstance(reason, urllib3.exceptions.NewConnectionError)


def get_workflows_template_id(
    template_name: str, dest: dict[str, str], pinned_template_id: str | None = None
) -> str | None:
    """The message template to send this email with through Workflows, or None to send it through Customer.io.

    A pinned template skips only the flag. The settings checks still apply, because they turn Workflows off.
    """
    template_id = pinned_template_id or WORKFLOWS_TEMPLATE_ID_MAP.get(template_name)
    if not template_id or not settings.POSTHOG_TRANSACTIONAL_EMAIL_API_KEY:
        return None
    if not settings.POSTHOG_HOST.startswith("https://") and not settings.DEBUG:
        # The request carries the secret key and the email's contents, such as a password reset link.
        logger.warning("email_workflows_insecure_host", template_name=template_name)
        return None
    if pinned_template_id:
        return pinned_template_id
    try:
        enabled = posthoganalytics.feature_enabled(
            WORKFLOWS_TRANSACTIONAL_EMAIL_FLAG,
            dest.get("distinct_id") or dest["raw_email"],
            person_properties={"email": dest["raw_email"], "transactional_email_template": template_name},
            send_feature_flag_events=False,
        )
    except Exception as err:
        logger.warning("email_workflows_flag_check_failed", template_name=template_name, error=str(err))
        return None
    return template_id if enabled else None


def _unescape_for_liquid(value: Any, key: Any = None) -> Any:
    """Undo the html.escape in sanitize_email_properties, and keep the URL defang.

    Customer.io outputs Liquid values as they are, so the properties arrive pre-escaped. Workflows escapes Liquid
    output itself, so a pre-escaped value renders as `&amp;amp;` and shows the entity to the reader.
    """
    if key is not None and _classify_key(key) == "passthrough":
        return value
    if isinstance(value, str):
        return html.unescape(value)
    if isinstance(value, dict):
        return {k: _unescape_for_liquid(v, key=k) for k, v in value.items()}
    if isinstance(value, list):
        return [_unescape_for_liquid(item) for item in value]
    return value


def _queue_workflows_email(
    *,
    to: str,
    template_id: str,
    template_data: dict[str, Any],
    distinct_id: str | None = None,
    idempotency_key: str,
) -> dict[str, Any]:
    """Queue one email from a Workflows transactional template and return its `message_id` and `replayed`.

    Takes the same arguments as posthog-python's `Emails.send`, so the SDK can replace this body once it ships.
    """
    payload: dict[str, Any] = {"to": to, "message_data": template_data}
    if distinct_id:
        payload["identifiers"] = {"distinct_id": distinct_id}
    try:
        response = requests.post(
            # The project secret API key names the project, so `@current` resolves to it.
            f"{settings.POSTHOG_HOST.rstrip('/')}/api/projects/@current/messaging_templates/{template_id}/send/",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {settings.POSTHOG_TRANSACTIONAL_EMAIL_API_KEY}",
                "Idempotency-Key": idempotency_key,
            },
            json=payload,
            # The caller holds the MessagingRecord row lock for the whole request, so keep it short.
            timeout=10,
            allow_redirects=False,
        )
    except requests.ConnectionError as err:
        code = "connection_error" if _never_connected(err) else "network_error"
        raise WorkflowsEmailError(str(err), code=code) from err
    except requests.Timeout as err:
        raise WorkflowsEmailError(str(err), code="timeout") from err

    if response.status_code != 202:
        try:
            code = response.json().get("code") or "api_error"
        except ValueError:
            code = "api_error"
        raise WorkflowsEmailError(
            f"{response.status_code} - {response.text}", code=code, status_code=response.status_code
        )
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not body.get("message_id"):
        # A 202 means Workflows may have queued the email, so this must not fall back to Customer.io.
        raise WorkflowsEmailError("202 without a message_id", code="invalid_response", status_code=response.status_code)
    return {"message_id": body["message_id"], "replayed": bool(body.get("replayed", False))}


def _workflows_idempotency_key(campaign_key: str, raw_email: str) -> str:
    # Derived from the email itself, so a Celery retry of the whole send cannot queue it twice.
    return hashlib.sha256(f"{campaign_key}\n{raw_email}".encode()).hexdigest()


def _pinned_workflows_template_id(idempotency_key: str) -> str | None:
    """The template of an earlier attempt that Workflows may have queued, so a retry sends it the same way."""
    try:
        return cache.get(f"email_workflows_pin:{idempotency_key}")
    except Exception as err:
        logger.warning("email_workflows_pin_read_failed", error=str(err))
        return None


def _pin_to_workflows(idempotency_key: str, template_id: str) -> None:
    try:
        cache.set(f"email_workflows_pin:{idempotency_key}", template_id, timeout=WORKFLOWS_PIN_TTL_SECONDS)
    except Exception as err:
        logger.warning("email_workflows_pin_write_failed", error=str(err))


def _send_one_via_workflows(
    dest: dict[str, str], campaign_key: str, template_id: str, properties: dict
) -> dict[str, Any]:
    # Workflows templates read only `variables.*`, so the Customer.io `customer.*` attributes travel in the data.
    customer = {"email": dest["raw_email"]}
    if dest.get("distinct_id"):
        customer["id"] = dest["distinct_id"]
    if dest.get("first_name"):
        customer["first_name"] = sanitize_email_string(dest["first_name"])

    result = _queue_workflows_email(
        to=dest["raw_email"],
        template_id=template_id,
        template_data=_unescape_for_liquid({**properties, "customer": customer}),
        distinct_id=dest.get("distinct_id") or None,
        idempotency_key=_workflows_idempotency_key(campaign_key, dest["raw_email"]),
    )
    if not result["message_id"]:
        # A disabled SDK client queues nothing and returns no ID.
        raise WorkflowsEmailError("Workflows queued nothing", code="not_queued")
    return result


def _send_one_via_customer_io(dest: dict[str, str], template_name: str, properties: dict) -> dict[str, Any]:
    if not settings.CUSTOMER_IO_API_KEY:
        raise Exception("Missing Customer.io API key")

    identifiers: dict[str, str] = {"email": dest["raw_email"]}
    if dest.get("distinct_id"):
        identifiers["id"] = dest["distinct_id"]

    payload = {
        "transactional_message_id": get_customer_io_template_id(template_name),
        "to": dest["raw_email"],
        "identifiers": identifiers,
        "message_data": properties,
    }

    response = requests.post(
        f"{settings.CUSTOMER_IO_API_URL}/v1/send/email",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.CUSTOMER_IO_API_KEY}",
        },
        json=payload,
        timeout=30,
    )

    if response.status_code != 200:
        raise Exception(f"Customer.io API error: {response.status_code} - {response.text}")

    return response.json()


def _capture_email_event(capture: ScopedCapture, dest: dict[str, str], event: str, properties: dict[str, Any]) -> None:
    try:
        capture(
            distinct_id=dest.get("distinct_id") or dest["raw_email"],
            event=event,
            properties={"recipient_email": dest["raw_email"], **properties},
        )
    except Exception as analytics_err:
        logger.warning("email_send_analytics_capture_failed", error=str(analytics_err))


def _send_one(
    capture: ScopedCapture, dest: dict[str, str], campaign_key: str, template_name: str, properties: dict
) -> tuple[str, dict]:
    """Send one email and return the provider that sent it with the provider's response."""
    idempotency_key = _workflows_idempotency_key(campaign_key, dest["raw_email"])
    # After an attempt Workflows may have queued, a retry skips the flag and never falls back. Otherwise a flag
    # change or a different error on the retry would send the same email again through Customer.io.
    pinned_template_id = _pinned_workflows_template_id(idempotency_key)
    workflows_template_id = get_workflows_template_id(template_name, dest, pinned_template_id)
    if workflows_template_id:
        try:
            return "workflows", _send_one_via_workflows(dest, campaign_key, workflows_template_id, properties)
        except WorkflowsEmailError as err:
            if pinned_template_id or not _workflows_error_allows_fallback(err):
                _pin_to_workflows(idempotency_key, workflows_template_id)
                raise
            logger.warning("email_workflows_send_rejected", template_name=template_name, error=str(err))
            EMAIL_WORKFLOWS_FALLBACK_COUNTER.labels(template_name=template_name).inc()
            _capture_email_event(
                capture,
                dest,
                "transactional email workflows rejected",
                {"template_name": template_name, "campaign_key": campaign_key, "error": str(err)[:500]},
            )
    return "customer_io", _send_one_via_customer_io(dest, template_name, properties)


# Note: this http sender is set up to send via templates, so all the configuration is done in Customer.io or in
# the Workflows message template - i.e. no subject, body, etc.
def _send_via_http(
    to: list[dict[str, str]],
    campaign_key: str,
    template_name: str,
    properties: dict,
) -> None:
    """Sends emails using the Customer.io API, or the Workflows transactional email API where the flag matches"""
    if not is_http_email_service_available():
        raise Exception("Missing Customer.io API key")

    # A dedicated client, because the global one may never flush before a Celery worker exits.
    with ph_scoped_capture(event_region=get_instance_region()) as capture:
        _send_via_http_batch(capture, to, campaign_key, template_name, properties)


def _send_via_http_batch(
    capture: ScopedCapture, to: list[dict[str, str]], campaign_key: str, template_name: str, properties: dict
) -> None:
    sent_count = 0
    already_sent_count = 0  # delivered in a prior run — not a failure if the batch later aborts
    dest: dict[str, str] | None = None
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

                provider, provider_response = _send_one(capture, dest, campaign_key, template_name, properties)

                # Mark delivery before any non-essential step so a delivered email is never
                # recorded as rejected (raise_if_delivery_rejected keys off sent_at). Analytics
                # is best-effort and isolated so its failure can't roll back a successful send.
                record.sent_at = timezone.now()
                record.save()

                _capture_email_event(
                    capture,
                    dest,
                    "transactional email triggered",
                    {
                        "template_name": template_name,
                        "campaign_key": campaign_key,
                        "provider": provider,
                        **provider_response,
                    },
                )

                EMAIL_SEND_COUNTER.labels(outcome="sent", transport="http").inc()
                sent_count += 1

    except Exception as err:
        capture_exception(err)  # already logs the traceback via logger.exception
        # The exception carries no template name, so this event is what lets a dashboard count failures per template.
        retrying = isinstance(err, WorkflowsEmailError)
        if dest:
            _capture_email_event(
                capture,
                dest,
                "transactional email failed",
                {
                    "template_name": template_name,
                    "campaign_key": campaign_key,
                    "error_type": type(err).__name__,
                    "error": str(err)[:500],
                    "retrying": retrying,
                },
            )
        # Count every recipient that did not get through (the failing one + any not yet attempted),
        # so `failed` shares the per-recipient unit with `sent` instead of registering once per batch.
        EMAIL_SEND_COUNTER.labels(outcome="failed", transport="http").inc(len(to) - already_sent_count - sent_count)
        if retrying:
            # Workflows may have queued this email. The Celery retry sends the same idempotency key, so Workflows
            # returns the queued email instead of sending a second one, and recipients already sent are skipped.
            raise


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

                # Django's contract returns the accepted count, but some backends return None.
                # Treat only an explicit 0 as rejection — a non-zero count or a None (backend that
                # returns nothing after a non-raising handoff) means the provider took the email.
                accepted_count = connection.send_messages([email_message])
                if accepted_count == 0:
                    logger.warning("email_send_smtp_not_accepted", recipient=dest["raw_email"])
                    EMAIL_SEND_COUNTER.labels(outcome="failed", transport="smtp").inc()
                else:
                    if accepted_count != 1:
                        logger.warning(
                            "email_send_smtp_unexpected_count",
                            recipient=dest["raw_email"],
                            accepted_count=accepted_count,
                        )
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


class EmailDeliveryError(Exception):
    """A synchronous send returned without the provider accepting the email."""


def was_email_delivered(campaign_key: str, email: str) -> bool:
    """Return whether the provider accepted this campaign for this recipient (MessagingRecord.sent_at set)."""
    return MessagingRecord.objects.filter(
        campaign_key=campaign_key, email_hash__in=get_email_hashes(email), sent_at__isnull=False
    ).exists()


def raise_if_delivery_rejected(campaign_key: str, email: str) -> None:
    """Raise EmailDeliveryError only when the provider accepted nothing for this recipient.

    Only fires when zero messages were accepted: SMTP `send_messages` returned 0, or a 5xx
    `SMTPRecipientsRefused` was swallowed without recording any delivery. Any accepted email
    sets `MessagingRecord.sent_at` *before* a post-accept step (posthog capture, record save)
    can raise, so a delivered email never reaches this branch.
    """
    if not was_email_delivered(campaign_key, email):
        raise EmailDeliveryError(f"provider accepted no email for {email} under {campaign_key}")


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


def _send_email_now(
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
    retry_in_worker: bool = False,
) -> None:
    if use_http and is_http_email_service_available():
        try:
            _send_via_http(
                to=to,
                campaign_key=campaign_key,
                template_name=template_name,
                properties=properties or {},
            )
        except WorkflowsEmailError:
            if not retry_in_worker:
                raise
            # The retry sends the same idempotency key, so Workflows does not send the email twice.
            _send_email.apply_async(
                kwargs={
                    "campaign_key": campaign_key,
                    "to": to,
                    "subject": subject,
                    "headers": headers,
                    "txt_body": txt_body,
                    "html_body": html_body,
                    "template_name": template_name,
                    "reply_to": reply_to,
                    "use_http": use_http,
                    "properties": properties,
                }
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


_send_email = shared_task(**EMAIL_TASK_KWARGS, name="posthog.email._send_email")(_send_email_now)


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
        if name:
            recipient_data["first_name"] = name
        self.to.append(recipient_data)

    def add_user_recipient(self, user: "User", email_override: Optional[str] = None) -> None:
        """
        Add a user as a recipient, include their distinct_id for Customer.io reporting wenhooks.
        Use this instead of add_recipient when you have a User object.
        """
        email = email_override or user.email
        self.add_recipient(email=email, name=user.first_name, distinct_id=str(user.distinct_id))

    def send(self, send_async: bool = True, *, retry: bool = True) -> None:
        """Synchronous callers can disable eager retries to own transport failure handling."""
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
        elif retry:
            # Celery runs eager retries at once, so each Workflows timeout would hold the request for another 10s.
            _send_email.apply(kwargs={**kwargs, "retry_in_worker": True})
        else:
            _send_email_now(
                campaign_key=self.campaign_key,
                to=self.to,
                subject=self.subject,
                headers=self.headers,
                txt_body=self.txt_body,
                html_body=self.html_body,
                template_name=self.template_name,
                reply_to=self.reply_to,
                use_http=self.use_http,
                properties=self.properties,
            )
