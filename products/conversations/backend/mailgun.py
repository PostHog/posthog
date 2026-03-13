"""Mailgun API helpers for domain management and webhook validation."""

import hmac
import time
import hashlib

import structlog

from posthog.models.instance_setting import get_instance_setting
from posthog.security.outbound_proxy import external_requests

logger = structlog.get_logger(__name__)


def _get_api_key() -> str:
    key = get_instance_setting("CONVERSATIONS_EMAIL_MAILGUN_API_KEY")
    if not key:
        raise ValueError("CONVERSATIONS_EMAIL_MAILGUN_API_KEY is not configured")
    return key


def _get_api_base_url() -> str:
    region = get_instance_setting("CONVERSATIONS_EMAIL_MAILGUN_REGION") or "us"
    if region == "eu":
        return "https://api.eu.mailgun.net"
    return "https://api.mailgun.net"


def add_domain(domain: str) -> dict:
    """Register a sending domain with Mailgun. Returns DNS records to configure."""
    api_key = _get_api_key()
    base_url = _get_api_base_url()

    response = external_requests.post(
        f"{base_url}/v3/domains",
        auth=("api", api_key),
        data={"name": domain},
    )

    if response.status_code in (200, 201):
        data = response.json()
        dns_records = {
            "sending_dns_records": data.get("sending_dns_records", []),
            "receiving_dns_records": data.get("receiving_dns_records", []),
        }
        return dns_records

    logger.error("mailgun_add_domain_failed", domain=domain, status=response.status_code, body=response.text)
    raise ValueError(f"Failed to add domain to Mailgun: {response.status_code} {response.text}")


def verify_domain(domain: str) -> bool:
    """Check domain verification status. Returns True if verified."""
    api_key = _get_api_key()
    base_url = _get_api_base_url()

    response = external_requests.put(
        f"{base_url}/v3/domains/{domain}/verify",
        auth=("api", api_key),
    )

    if response.status_code == 200:
        data = response.json()
        domain_data = data.get("domain", {})
        return domain_data.get("state") == "active"

    logger.error("mailgun_verify_domain_failed", domain=domain, status=response.status_code)
    return False


def get_domain_info(domain: str) -> dict:
    """Get domain info including DNS records and verification state."""
    api_key = _get_api_key()
    base_url = _get_api_base_url()

    response = external_requests.get(
        f"{base_url}/v3/domains/{domain}",
        auth=("api", api_key),
    )

    if response.status_code == 200:
        return response.json()

    logger.error("mailgun_get_domain_failed", domain=domain, status=response.status_code)
    raise ValueError(f"Failed to get domain from Mailgun: {response.status_code}")


def delete_domain(domain: str) -> None:
    """Remove a sending domain from Mailgun."""
    api_key = _get_api_key()
    base_url = _get_api_base_url()

    response = external_requests.delete(
        f"{base_url}/v3/domains/{domain}",
        auth=("api", api_key),
    )

    if response.status_code not in (200, 404):
        logger.error("mailgun_delete_domain_failed", domain=domain, status=response.status_code)


def validate_webhook_signature(token: str, timestamp: str, signature: str) -> bool:
    """Verify Mailgun inbound webhook authenticity via HMAC-SHA256."""
    signing_key = get_instance_setting("CONVERSATIONS_EMAIL_WEBHOOK_SIGNING_KEY")
    if not signing_key:
        logger.error("mailgun_webhook_signing_key_not_configured")
        return False

    # Reject stale timestamps (> 5 minutes old)
    try:
        ts = int(timestamp)
    except (ValueError, TypeError):
        return False

    if abs(time.time() - ts) > 300:
        return False

    expected = hmac.new(
        key=signing_key.encode(),
        msg=f"{timestamp}{token}".encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)
