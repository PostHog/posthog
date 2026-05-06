"""Mailgun integration helpers for conversations email channel."""

import hmac
import time
import hashlib
from typing import Any

import requests
import structlog

from posthog.models.instance_setting import get_instance_setting

logger = structlog.get_logger(__name__)

MAILGUN_API_BASE = "https://api.mailgun.net/v3"

WEBHOOK_TIMESTAMP_MAX_AGE_SECONDS = 300  # 5 minutes

MAILGUN_SEND_TIMEOUT = 30  # seconds


class MailgunError(Exception):
    """Base class for Mailgun integration errors that callers need to distinguish."""


class MailgunNotConfigured(MailgunError):
    """Mailgun API key is missing from instance settings."""


class MailgunDomainConflict(MailgunError):
    """Mailgun refuses to register the domain because it already exists (in our account or another)."""


class MailgunDomainNotRegistered(MailgunError):
    """Mailgun returned 404 when sending — the domain no longer exists in the account.

    Caller should treat this as a signal to flip domain_verified=False and prompt the
    user to reconnect. Non-retriable.
    """


class MailgunPermanentError(MailgunError):
    """Non-retriable 4xx from Mailgun (bad recipient, oversized payload, compliance reject,
    or a Mailgun-side unverified state). Lumpy bucket — response body is included so
    operators can triage from logs.
    """


class MailgunTransientError(MailgunError):
    """Retriable failure — 429, 5xx, or any pre-response RequestException (connection,
    timeout, chunked-encoding). Callers should bounce these back through Celery retry.
    """


def validate_webhook_signature(token: str, timestamp: str, signature: str) -> bool:
    """Verify inbound Mailgun webhook authenticity via HMAC-SHA256.

    Also rejects timestamps older than 5 minutes to prevent replay attacks.
    """
    # Uncomment this to allow debugging in development
    # if settings.DEBUG:
    #    return True

    signing_key = get_instance_setting("CONVERSATIONS_EMAIL_WEBHOOK_SIGNING_KEY")
    if not signing_key:
        return False

    # Reject stale timestamps
    try:
        ts = int(timestamp)
    except (ValueError, TypeError):
        return False
    if abs(time.time() - ts) > WEBHOOK_TIMESTAMP_MAX_AGE_SECONDS:
        return False

    expected = hmac.new(
        key=signing_key.encode("utf-8"),
        msg=f"{timestamp}{token}".encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


def _get_api_key() -> str:
    key = get_instance_setting("CONVERSATIONS_EMAIL_MAILGUN_API_KEY")
    if not key:
        raise MailgunNotConfigured("CONVERSATIONS_EMAIL_MAILGUN_API_KEY is not configured")
    return key


def _filter_sending_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Strip tracking CNAME records — we don't use open/click tracking."""
    return [r for r in records if r.get("record_type", "").upper() != "CNAME"]


def add_domain(domain: str) -> dict[str, Any]:
    """Register a sending domain with Mailgun. Returns DNS records to configure."""
    resp = requests.post(
        f"{MAILGUN_API_BASE}/domains",
        auth=("api", _get_api_key()),
        data={"name": domain},
        timeout=15,
    )

    if resp.status_code in (200, 201):
        data = resp.json()
        return {
            "sending_dns_records": _filter_sending_records(data.get("sending_dns_records", [])),
        }

    if resp.status_code == 400:
        try:
            error_msg = resp.json().get("message", "").lower()
        except Exception:
            error_msg = ""
        # Never silently adopt a pre-existing Mailgun domain — the shared
        # account may hold domains we don't own. Fail loud so operators
        # can reconcile manually.
        if "already exists" in error_msg:
            raise MailgunDomainConflict(f"Domain {domain} already exists")
        if "already taken" in error_msg:
            raise MailgunDomainConflict(f"Domain {domain} is already registered by another Mailgun account")

    resp.raise_for_status()
    return {}


def get_domain_dns_records(domain: str) -> dict[str, Any]:
    """Fetch DNS records for an existing Mailgun domain."""
    resp = requests.get(
        f"{MAILGUN_API_BASE}/domains/{domain}",
        auth=("api", _get_api_key()),
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    return {
        "sending_dns_records": _filter_sending_records(data.get("sending_dns_records", [])),
    }


def verify_domain(domain: str) -> dict[str, Any]:
    """Trigger DNS verification for a domain and return current status.

    If the domain doesn't exist in Mailgun yet, registers it first.
    """
    api_key = _get_api_key()
    resp = requests.put(
        f"{MAILGUN_API_BASE}/domains/{domain}/verify",
        auth=("api", api_key),
        timeout=15,
    )

    if resp.status_code == 404:
        logger.info("mailgun_verify_domain_not_found_registering", domain=domain)
        add_domain(domain)
        resp = requests.put(
            f"{MAILGUN_API_BASE}/domains/{domain}/verify",
            auth=("api", api_key),
            timeout=15,
        )

    resp.raise_for_status()
    data = resp.json()
    domain_info = data.get("domain", {})
    return {
        "state": domain_info.get("state", "unverified"),
        "sending_dns_records": _filter_sending_records(data.get("sending_dns_records", [])),
    }


def delete_domain(domain: str) -> None:
    """Remove a sending domain from Mailgun."""
    resp = requests.delete(
        f"{MAILGUN_API_BASE}/domains/{domain}",
        auth=("api", _get_api_key()),
        timeout=15,
    )
    if resp.status_code == 404:
        logger.info("mailgun_domain_not_found_on_delete", domain=domain)
        return
    resp.raise_for_status()


def send_mime(domain: str, mime_bytes: bytes, recipients: list[str]) -> str:
    """Send a pre-built MIME message through Mailgun's per-domain endpoint.

    Posts to /v3/<domain>/messages.mime so Mailgun DKIM-signs with the customer's
    domain key (d=<domain>) and uses an envelope return-path under that domain,
    which is required for DMARC alignment.

    `recipients` must contain every envelope target (To + Cc). Mailgun uses the
    `to=` form field as SMTP RCPT regardless of what's in the MIME headers; any
    address not listed here won't be delivered, even if it appears in the Cc: header.

    Tracking rewrites are force-disabled per-message because we intentionally strip
    tracking CNAMEs during domain setup — account-level tracking would rewrite links
    to unconfigured CNAMEs.

    Returns Mailgun's message id from the response body.
    """
    api_key = _get_api_key()

    data = [
        *(("to", addr) for addr in recipients),
        ("o:tracking", "no"),
        ("o:tracking-clicks", "no"),
        ("o:tracking-opens", "no"),
    ]

    try:
        resp = requests.post(
            f"{MAILGUN_API_BASE}/{domain}/messages.mime",
            auth=("api", api_key),
            data=data,
            files={"message": ("message.mime", mime_bytes)},
            timeout=MAILGUN_SEND_TIMEOUT,
        )
    except requests.exceptions.RequestException as e:
        # Any failure before we've seen a response is transient — the request may
        # or may not have reached Mailgun, and a retry is the safe call.
        raise MailgunTransientError(f"Mailgun send request failed: {e}") from e

    status = resp.status_code

    if 200 <= status < 300:
        try:
            message_id = resp.json().get("id", "")
        except ValueError:
            message_id = ""
        logger.info(
            "mailgun_send_succeeded",
            domain=domain,
            mailgun_message_id=message_id,
            recipient_count=len(recipients),
        )
        return message_id

    if status == 404:
        raise MailgunDomainNotRegistered(f"Domain {domain} is not registered with Mailgun")

    # Lumpy bucket: dump the response body so humans can triage from logs.
    body_snippet = resp.text[:500] if resp.text else ""

    if status == 429 or 500 <= status < 600:
        logger.warning(
            "mailgun_send_transient_error",
            domain=domain,
            status=status,
            body=body_snippet,
        )
        raise MailgunTransientError(f"Mailgun {status}: {body_snippet}")

    logger.error(
        "mailgun_send_permanent_error",
        domain=domain,
        status=status,
        body=body_snippet,
    )
    raise MailgunPermanentError(f"Mailgun {status}: {body_snippet}")
