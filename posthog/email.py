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
from django.db import InterfaceError, OperationalError, transaction
from django.template.loader import get_template
from django.utils import timezone
from django.utils.module_loading import import_string

import urllib3
import requests
import structlog
import css_inline
import posthoganalytics
from celery import current_task, shared_task
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
    # SMTP retries wait 5s, 10s and 20s. Without jitter the last attempt cannot come within a second of the first.
    # HTTP retries use HTTP_SEND_RETRY_COUNTDOWNS_SECONDS instead.
    "retry_backoff": 5,
    "retry_jitter": False,
}

# Failure rate as an alertable time series. Labelled only by outcome+transport to bound
# cardinality (per-team volume lives in MessagingRecord); scraped via prometheus multiprocess.
EMAIL_SEND_COUNTER = Counter(
    "posthog_email_send_total",
    "Email send attempts by outcome (sent|failed|undeliverable) and transport (smtp|http).",
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
    "2fa_enabled": "01a1645b-71b3-0000-6894-2ea67c11761f",
    "2fa_disabled": "01a16464-c956-0000-a67a-e8014f9566bd",
    "2fa_backup_code_used": "01a16465-2cfa-0000-2d68-689f6a6ce4f3",
    "2fa_reset": "01a16465-992f-0000-b686-dfbd321721a6",
    "password_reset": "01a1597a-5d91-0000-99fa-9eeb18d293c5",
    "invite": "01a16466-2c26-0000-00ea-11f6b69aa254",
    "member_join": "01a16466-9901-0000-d083-3e41d7458c2b",
    "email_change_old_address": "01a16466-fde6-0000-7fe2-5549cbf7fbdf",
    "email_change_new_address": "01a16467-9143-0000-29d6-de5e283ede18",
    "password_changed": "01a16467-f65c-0000-31de-f71cdefe710f",
    "login_notification": "01a16468-8007-0000-8fd2-911a6b6e5891",
    "personal_api_key_exposed": "01a16469-2b55-0000-aff5-d3bcfc293ff8",
    "code_based_verification": "01a16472-1d73-0000-2828-3a196b3d5bc5",
    "email_verification_code": "01a16473-0e70-0000-fcab-8290ccf17558",
    "feature_flags_secure_api_key_exposed": "01a16469-95fd-0000-6717-9ec46285eef3",
    "project_secret_api_key_exposed": "01a16472-afbb-0000-e94f-9c65348f46e9",
    "oauth_token_exposed": "01a1646a-003a-0000-8d21-32e544374fe7",
    "passkey_added": "01a1646a-85df-0000-d018-9cdc391f507a",
    "passkey_removed": "01a1646a-ec21-0000-5989-5dd4bb7ecf47",
    "new_conversation_ticket": "01a1646b-6047-0000-06f5-956fcb309c33",
    "project_deleted": "01a1646b-e43c-0000-c54d-9ab304e2084e",
    "organization_deleted": "01a1646c-4a57-0000-19c3-4d5fbb1d8030",
    "approval_requested": "01a16311-33e6-0000-c533-f383fd8e70f0",
    "approval_approved": "01a1646c-ae43-0000-dc0f-70a90476419c",
    "approval_rejected": "01a1646d-2ca8-0000-849e-6d0f6fd6e7af",
    "approval_expired": "01a1646d-8fb5-0000-b8bb-9347407f1e06",
    "approval_applied": "01a1646d-eeb4-0000-b84b-6e0de52e284f",
    "conversation_restore": "01a1646e-8a53-0000-76c1-e7a99a8ee3cb",
    "proxy_provisioned": "01a16311-b3de-0000-8aec-7c865f3e5432",
    "delegation_invite": "01a1646f-0222-0000-db43-2831af7b0f2d",
    "provisioning_welcome": "01a1646f-ba3d-0000-ecbb-d588b45bcb19",
    "baa_signed_ai_disabled": "01a16470-2afa-0000-aec4-390d56587c4c",
    "integration_access_requested": "01a16470-c82d-0000-6436-a68687c19f8c",
    "posthog_ai_access_requested": "01a16471-350d-0000-75a6-3ebb077c03a1",
    "wizard_pr_ready": "01a16471-c17b-0000-8ee5-eb254065b7a1",
    "loop_run_summary": "01a16473-9c4d-0000-99d8-958c03b0f1a0",
}

# Release conditions match the `email`, `transactional_email_template` and `region` person properties passed at
# evaluation, so one flag picks the recipients, the templates that move and the instances that move them. Both regions
# send to the US project, so a condition on `region` lets each one roll out on its own.
WORKFLOWS_TRANSACTIONAL_EMAIL_FLAG = "transactional-emails-via-workflows"

# Matches how long the send API keeps an idempotency key, which outlasts every Celery retry.
WORKFLOWS_PIN_TTL_SECONDS = 24 * 60 * 60

# 422 codes for an email the send API refused before queueing it because the address can't receive email: the syntax
# is invalid, the domain has no mail servers, or the address hard bounced and is on the suppression list. Every
# provider would bounce it, so the email is dropped. It is not retried and Customer.io does not send it.
WORKFLOWS_UNDELIVERABLE_422_CODES = frozenset({"recipient_unreachable", "recipient_suppressed"})

# 422 codes for an email the send API refused before queueing it: sending is suspended for the project or paused for
# the workflow.
WORKFLOWS_NOT_QUEUED_422_CODES = frozenset({"sending_suspended", "sending_paused"})


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


# Waits between worker attempts of an HTTP send that failed with one of the errors below. Customer.io no longer sends
# an email that Workflows could not take, so the retries span about 19 minutes to outlast a short Workflows outage.
# They stop there, because a login code or a password reset link that arrives later is of no use to the recipient.
# SMTP sends keep the shorter retries in EMAIL_TASK_KWARGS.
HTTP_SEND_RETRY_COUNTDOWNS_SECONDS = (10, 30, 60, 120, 300, 600)

# Errors that a later attempt can fix. A database error can come before the send, when the record is read, or after
# it, when the record is marked sent. A Workflows send is pinned before that write, so its retry replays under the
# same idempotency key. A Customer.io send can go out a second time.
RETRYABLE_HTTP_SEND_ERRORS = (WorkflowsEmailError, OperationalError, InterfaceError)


def _workflows_queued_nothing(err: WorkflowsEmailError) -> bool:
    """Whether the email is certain not to be queued, so a retry can pick its provider again."""
    if err.status_code is None:
        # A connection that was never made and a client that queued nothing sent nothing. Any other network
        # failure can come after Workflows queued the email.
        return err.code in ("connection_error", "not_queued")
    if err.status_code == 422:
        # The send API refuses these before it queues anything. Any other 422 means this key already queued an email.
        return err.code in WORKFLOWS_NOT_QUEUED_422_CODES
    # Redirects and 4xx answers come before anything is queued, apart from 408 and 409 (an attempt with this key is
    # in flight). A 5xx can follow a queued email, because the send API also returns 503 when the workflow service
    # queued it but failed to answer.
    return 300 <= err.status_code < 500 and err.status_code not in (408, 409)


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
    person_properties = {"email": dest["raw_email"], "transactional_email_template": template_name}
    if region := get_instance_region():
        person_properties["region"] = region
    try:
        enabled = posthoganalytics.feature_enabled(
            WORKFLOWS_TRANSACTIONAL_EMAIL_FLAG,
            dest.get("distinct_id") or dest["raw_email"],
            person_properties=person_properties,
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
) -> tuple[str, dict] | None:
    """Send one email and return the provider that sent it with the provider's response.

    Returns None when Workflows refused the recipient as undeliverable, so no provider sent the email.
    """
    idempotency_key = _workflows_idempotency_key(campaign_key, dest["raw_email"])
    # After an attempt Workflows may have queued, a retry skips the flag. Otherwise a flag change on the retry would
    # send the same email again through Customer.io.
    pinned_template_id = _pinned_workflows_template_id(idempotency_key)
    workflows_template_id = get_workflows_template_id(template_name, dest, pinned_template_id)
    if workflows_template_id:
        try:
            response = _send_one_via_workflows(dest, campaign_key, workflows_template_id, properties)
            # Marking the record sent can still fail, and the retry must then replay this send, not move providers.
            _pin_to_workflows(idempotency_key, workflows_template_id)
            return "workflows", response
        except WorkflowsEmailError as err:
            if err.status_code == 422 and err.code in WORKFLOWS_UNDELIVERABLE_422_CODES:
                # The send API replays an idempotency key before it checks the recipient, so this refusal also
                # means that no earlier attempt queued the email. The pin keeps a retry of the batch on Workflows, so a
                # flag change cannot send this recipient through Customer.io, where the email would hard bounce.
                _pin_to_workflows(idempotency_key, workflows_template_id)
                logger.info("email_workflows_recipient_undeliverable", template_name=template_name)
                _capture_email_event(
                    capture,
                    dest,
                    "transactional email workflows rejected",
                    {"template_name": template_name, "campaign_key": campaign_key, "error": str(err)[:500]},
                )
                return None
            # Workflows sends the retry. An email it certainly did not queue stays unpinned, so turning the flag off
            # moves the retry to Customer.io.
            if pinned_template_id or not _workflows_queued_nothing(err):
                _pin_to_workflows(idempotency_key, workflows_template_id)
            raise
    return "customer_io", _send_one_via_customer_io(dest, template_name, properties)


# Note: this http sender is set up to send via templates, so all the configuration is done in Customer.io or in
# the Workflows message template - i.e. no subject, body, etc.
def _send_via_http(
    to: list[dict[str, str]],
    campaign_key: str,
    template_name: str,
    properties: dict,
    will_retry: bool = True,
) -> None:
    """Sends emails using the Customer.io API, or the Workflows transactional email API where the flag matches"""
    if not is_http_email_service_available():
        raise Exception("Missing Customer.io API key")

    if not current_task or current_task.request.is_eager:
        # The dedicated client blocks on its flush, which would hold the request. The web process keeps running,
        # so the global client delivers in the background. ScopedCapture keeps the cloud-only guard.
        _send_via_http_batch(ScopedCapture(posthoganalytics), to, campaign_key, template_name, properties, will_retry)
        return

    # A dedicated client, because the global one may never flush before a Celery worker exits.
    with ph_scoped_capture(event_region=get_instance_region()) as capture:
        _send_via_http_batch(capture, to, campaign_key, template_name, properties, will_retry)


def _send_via_http_batch(
    capture: ScopedCapture,
    to: list[dict[str, str]],
    campaign_key: str,
    template_name: str,
    properties: dict,
    will_retry: bool = True,
) -> None:
    sent_count = 0
    already_sent_count = 0  # delivered in a prior run — not a failure if the batch later aborts
    undeliverable_count = 0
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

                sent = _send_one(capture, dest, campaign_key, template_name, properties)
                if sent is None:
                    # sent_at stays unset, so raise_if_delivery_rejected tells a synchronous caller nothing went out.
                    EMAIL_SEND_COUNTER.labels(outcome="undeliverable", transport="http").inc()
                    undeliverable_count += 1
                    continue
                provider, provider_response = sent

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
        retryable = isinstance(err, RETRYABLE_HTTP_SEND_ERRORS)
        retrying = retryable and will_retry
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
        EMAIL_SEND_COUNTER.labels(outcome="failed", transport="http").inc(
            len(to) - already_sent_count - sent_count - undeliverable_count
        )
        if retryable:
            # The retry sends the same idempotency key, so Workflows returns an email it already queued instead of
            # sending a second one, and recipients already marked sent are skipped.
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


def _worker_send_task() -> Any:
    """The `_send_email` task that a worker runs this send in, or None for an inline or eager send."""
    task = current_task
    if not task or task.name != "posthog.email._send_email" or task.request.is_eager:
        return None
    return task


def _send_will_retry(retry_in_worker: bool) -> bool:
    """Whether a retryable failure of this send gets another attempt."""
    if retry_in_worker:
        return True
    task = _worker_send_task()
    return task is not None and task.request.retries < len(HTTP_SEND_RETRY_COUNTDOWNS_SECONDS)


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
                will_retry=_send_will_retry(retry_in_worker),
            )
        except RETRYABLE_HTTP_SEND_ERRORS as err:
            if not retry_in_worker:
                task = _worker_send_task()
                if task is not None:
                    # After the last wait, Celery raises `err` instead of scheduling another attempt.
                    countdowns = HTTP_SEND_RETRY_COUNTDOWNS_SECONDS
                    raise task.retry(
                        exc=err,
                        countdown=countdowns[min(task.request.retries, len(countdowns) - 1)],
                        max_retries=len(countdowns),
                    )
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
