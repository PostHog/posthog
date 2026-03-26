"""Mailgun integration helpers for conversations email channel."""

import hmac
import time
import hashlib
from typing import Any

from django.conf import settings as django_settings
from django.core import mail
from django.utils.module_loading import import_string

import requests
import structlog

from posthog.models.instance_setting import get_instance_setting

logger = structlog.get_logger(__name__)

MAILGUN_API_BASE = "https://api.mailgun.net/v3"

WEBHOOK_TIMESTAMP_MAX_AGE_SECONDS = 300  # 5 minutes


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
        raise ValueError("CONVERSATIONS_EMAIL_MAILGUN_API_KEY is not configured")
    return key


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
            "sending_dns_records": data.get("sending_dns_records", []),
        }

    if resp.status_code == 400:
        try:
            error_msg = resp.json().get("message", "")
            if "already exists" in error_msg.lower():
                return get_domain_dns_records(domain)
            if "already taken" in error_msg.lower():
                raise ValueError(f"Domain {domain} is already registered by another Mailgun account")
        except ValueError:
            raise
        except Exception:
            pass

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
        "sending_dns_records": data.get("sending_dns_records", []),
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
        "sending_dns_records": data.get("sending_dns_records", []),
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


def get_smtp_connection():
    """Create an SMTP connection from instance settings.

    Raises a clear error if the email backend is misconfigured.
    """
    backend_path = django_settings.EMAIL_BACKEND
    try:
        klass = import_string(backend_path) if backend_path else mail.get_connection().__class__
    except ImportError:
        raise ValueError(f"Invalid EMAIL_BACKEND: {backend_path!r}")

    return klass(
        host=get_instance_setting("EMAIL_HOST"),
        port=get_instance_setting("EMAIL_PORT"),
        username=get_instance_setting("EMAIL_HOST_USER"),
        password=get_instance_setting("EMAIL_HOST_PASSWORD"),
        use_tls=get_instance_setting("EMAIL_USE_TLS"),
        use_ssl=get_instance_setting("EMAIL_USE_SSL"),
    )
