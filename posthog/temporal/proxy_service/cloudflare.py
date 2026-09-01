"""
Cloudflare for SaaS API client for managing Custom Hostnames and Worker Routes.

This module provides functions to interact with Cloudflare's API for:
- Creating/deleting Custom Hostnames (for TLS certificate provisioning)
- Creating/deleting Worker Routes (for routing traffic to the proxy worker)
- Getting Custom Hostname status (for monitoring certificate status)
"""

import re
import typing as t
from dataclasses import dataclass, field
from enum import Enum

from django.conf import settings

import requests

from posthog.dataclasses import frozen

CLOUDFLARE_API_BASE = "https://api.cloudflare.com/client/v4"
CLOUDFLARE_MIN_TLS_VERSION = "1.2"

# Must stay under the tightest calling activity's 10s start_to_close, or Temporal kills the
# activity before the request times out and a slow Cloudflare looks like an opaque timeout.
CLOUDFLARE_API_TIMEOUT_S = 8.0


class CloudflareAPIError(Exception):
    """Exception raised when Cloudflare API returns an error."""

    def __init__(self, message: str, errors: t.Optional[list[dict]] = None) -> None:
        super().__init__(message)
        self.errors = errors or []

    def is_rate_limited(self) -> bool:
        return any(err.get("code") == 10000 for err in self.errors) or "rate limit" in str(self).lower()


class CloudflareStatus(str, Enum):
    """Base for Cloudflare status enums.

    Cloudflare extends these sets without notice, and a status we do not model is still
    worth reporting, so an unmodeled value becomes a member carrying the raw string
    rather than raising and taking down the caller.
    """

    @classmethod
    def _missing_(cls, value: object) -> t.Optional["CloudflareStatus"]:
        if not isinstance(value, str):
            return None
        unmodeled = str.__new__(cls, value)
        unmodeled._name_ = value.upper()
        unmodeled._value_ = value
        return unmodeled


class CustomHostnameSSLStatus(CloudflareStatus):
    """SSL certificate status for a Custom Hostname.

    Names the states a proxy of ours reaches. Cloudflare's staging and backup certificate
    states are absent on purpose, since our flow never asks for them, and the base class
    keeps them parseable if one ever arrives.
    """

    INITIALIZING = "initializing"
    PENDING_VALIDATION = "pending_validation"
    DELETED = "deleted"
    PENDING_ISSUANCE = "pending_issuance"
    PENDING_DEPLOYMENT = "pending_deployment"
    PENDING_DELETION = "pending_deletion"
    PENDING_EXPIRATION = "pending_expiration"
    EXPIRED = "expired"
    ACTIVE = "active"
    INITIALIZING_TIMED_OUT = "initializing_timed_out"
    VALIDATION_TIMED_OUT = "validation_timed_out"
    ISSUANCE_TIMED_OUT = "issuance_timed_out"
    DEPLOYMENT_TIMED_OUT = "deployment_timed_out"
    DELETION_TIMED_OUT = "deletion_timed_out"
    DEACTIVATING = "deactivating"
    INACTIVE = "inactive"


class CustomHostnameStatus(CloudflareStatus):
    """Status for a Custom Hostname.

    Cloudflare's `test_*` states are absent on purpose, since we never create test hostnames.
    """

    ACTIVE = "active"
    PENDING = "pending"
    ACTIVE_REDEPLOYING = "active_redeploying"
    MOVED = "moved"
    PENDING_DELETION = "pending_deletion"
    DELETED = "deleted"
    PENDING_BLOCKED = "pending_blocked"
    PENDING_MIGRATION = "pending_migration"
    PENDING_PROVISIONED = "pending_provisioned"
    PROVISIONED = "provisioned"
    BLOCKED = "blocked"


# Custom Hostname statuses where Cloudflare stops serving traffic for the hostname, even when
# the SSL certificate is active. `blocked` and `pending_blocked` mean the edge rejects requests
# with a cross-user ban (error 1014). The usual cause is a zone hold on the customer's own
# Cloudflare zone, which forbids other accounts from activating the domain. `moved` means the
# hostname no longer points at our zone. `pending_migration` means the hostname is mid-migration
# and does not serve traffic yet. All four statuses cause the certificate check to fail.
BLOCKED_HOSTNAME_STATUSES: frozenset[CustomHostnameStatus] = frozenset(
    {
        CustomHostnameStatus.BLOCKED,
        CustomHostnameStatus.PENDING_BLOCKED,
        CustomHostnameStatus.MOVED,
        CustomHostnameStatus.PENDING_MIGRATION,
    }
)

# Cloudflare returns this error code in a 403 body when a hostname's CNAME target is banned
# across accounts. See Cloudflare's 1xxx error reference.
CLOUDFLARE_ERROR_CROSS_USER_BANNED = 1014

# Cloudflare's HTML error page shows the code as "Error 1014". The plain-text
# body sent to API clients shows "error code: 1014".
_CF_ERROR_CODE_RE = re.compile(r"error(?:\s+code)?[ :]+(\d{4})(?!\d)", re.IGNORECASE)


def parse_cloudflare_error_code(body: t.Any) -> t.Optional[int]:
    """Extract the Cloudflare error code from a 403 or 5xx error page body.

    Returns the first four-digit code found, or None when the body is not a string or
    contains no Cloudflare error code.
    """
    if not isinstance(body, str):
        return None
    match = _CF_ERROR_CODE_RE.search(body)
    if match:
        return int(match.group(1))
    return None


def describe_blocked_hostname_status(status: CustomHostnameStatus, domain: str) -> str:
    """Customer-facing sentence for a Custom Hostname stuck in a blocked or moved state."""
    if status in (CustomHostnameStatus.MOVED, CustomHostnameStatus.PENDING_MIGRATION):
        return (
            f"`{domain}` is no longer served by the proxy. Its hostname was moved or is "
            "mid-migration. Contact support to restore it."
        )
    return (
        f"`{domain}` is blocked from activating on the proxy. This usually means its Cloudflare "
        "zone has a hold that also covers subdomains. Release the hold on the zone's overview page "
        'in Cloudflare, or turn off "Also prevent subdomains", then run diagnostics again. '
        "If the domain is not on Cloudflare, contact support."
    )


def describe_cross_user_banned(domain: str) -> str:
    """Customer-facing sentence for a 403 carrying Cloudflare error 1014."""
    return (
        f"`{domain}` is not authorized to serve traffic through the proxy (error 1014). "
        "If the domain is on Cloudflare, check its zone for a hold that also covers subdomains "
        "and release it, then run diagnostics again. Otherwise contact support."
    )


@dataclass
class CustomHostnameSSL:
    """SSL configuration for a Custom Hostname."""

    status: CustomHostnameSSLStatus
    validation_errors: list[dict]
    # Optional fields populated by Cloudflare's response and used by diagnostics.
    # Not all SSL configurations expose these (e.g. ACTIVE certs lack a challenge URL).
    http_url: t.Optional[str] = None
    http_body: t.Optional[str] = None
    certificate_authority: t.Optional[str] = None
    validation_records: list[dict] = field(default_factory=list)


@frozen
class CustomHostname:
    """Information about a Custom Hostname."""

    id: str
    hostname: str
    status: CustomHostnameStatus
    ssl: CustomHostnameSSL
    custom_metadata: dict[str, str] = field(default_factory=dict)


def _get_headers() -> dict[str, str]:
    """Get headers for Cloudflare API requests."""
    if not settings.CLOUDFLARE_API_TOKEN or not settings.CLOUDFLARE_ZONE_ID:
        raise ValueError("CLOUDFLARE_API_TOKEN and CLOUDFLARE_ZONE_ID must be configured when using Cloudflare proxy")
    return {
        "Authorization": f"Bearer {settings.CLOUDFLARE_API_TOKEN}",
        "Content-Type": "application/json",
    }


def _parse_hostname(result: dict) -> "CustomHostname":
    """Build a CustomHostname from a Cloudflare API custom_hostname result object."""
    ssl_payload = result.get("ssl", {})
    return CustomHostname(
        id=result["id"],
        hostname=result["hostname"],
        status=CustomHostnameStatus(result["status"]),
        ssl=CustomHostnameSSL(
            status=CustomHostnameSSLStatus(ssl_payload["status"]),
            validation_errors=ssl_payload.get("validation_errors", []),
            http_url=ssl_payload.get("http_url"),
            http_body=ssl_payload.get("http_body"),
            certificate_authority=ssl_payload.get("certificate_authority"),
            validation_records=ssl_payload.get("validation_records", []),
        ),
        custom_metadata=result.get("custom_metadata", {}),
    )


def _handle_response(response: requests.Response) -> dict:
    """Handle Cloudflare API response and raise errors if needed."""
    try:
        data = response.json()
    except requests.exceptions.JSONDecodeError:
        raise CloudflareAPIError(f"Invalid JSON response (status {response.status_code}): {response.text[:200]}")

    if not data.get("success", False):
        errors = data.get("errors", [])
        error_messages = [e.get("message", "Unknown error") for e in errors]
        raise CloudflareAPIError(
            f"Cloudflare API error: {', '.join(error_messages)}",
            errors=errors,
        )

    return data


def create_custom_hostname(domain: str, root_redirect_url: str | None = None) -> CustomHostname:
    """
    Create a Custom Hostname in Cloudflare for SaaS.

    This creates a custom hostname with:
    - SSL certificate provided by Cloudflare
    - HTTP validation method
    - Default origin server

    Args:
        domain: The customer's domain (e.g., "analytics.customer.com")

    Returns:
        CustomHostname with the created hostname details

    Raises:
        CloudflareAPIError: If the API request fails
    """
    url = f"{CLOUDFLARE_API_BASE}/zones/{settings.CLOUDFLARE_ZONE_ID}/custom_hostnames"

    payload = {
        "hostname": domain,
        "ssl": {
            "method": "http",
            "type": "dv",
            "settings": {
                "min_tls_version": CLOUDFLARE_MIN_TLS_VERSION,
            },
        },
    }
    if root_redirect_url:
        payload["custom_metadata"] = {"root_redirect_url": root_redirect_url}

    response = requests.post(url, headers=_get_headers(), json=payload, timeout=CLOUDFLARE_API_TIMEOUT_S)
    data = _handle_response(response)
    return _parse_hostname(data["result"])


def get_custom_hostname(hostname_id: str) -> t.Optional[CustomHostname]:
    """
    Get details of a Custom Hostname by ID.

    Args:
        hostname_id: The Cloudflare Custom Hostname ID

    Returns:
        CustomHostname or None if not found

    Raises:
        CloudflareAPIError: If the API request fails (except for 404)
    """
    url = f"{CLOUDFLARE_API_BASE}/zones/{settings.CLOUDFLARE_ZONE_ID}/custom_hostnames/{hostname_id}"

    response = requests.get(url, headers=_get_headers(), timeout=CLOUDFLARE_API_TIMEOUT_S)

    if response.status_code == 404:
        return None

    data = _handle_response(response)
    return _parse_hostname(data["result"])


def get_custom_hostname_by_domain(domain: str) -> t.Optional[CustomHostname]:
    """
    Find a Custom Hostname by domain name.

    Args:
        domain: The customer's domain (e.g., "analytics.customer.com")

    Returns:
        CustomHostname or None if not found

    Raises:
        CloudflareAPIError: If the API request fails
    """
    url = f"{CLOUDFLARE_API_BASE}/zones/{settings.CLOUDFLARE_ZONE_ID}/custom_hostnames"
    params = {"hostname": domain}

    response = requests.get(url, headers=_get_headers(), params=params, timeout=CLOUDFLARE_API_TIMEOUT_S)
    data = _handle_response(response)

    results = data.get("result", [])
    if not results:
        return None

    return _parse_hostname(results[0])


def update_custom_hostname_metadata(hostname: CustomHostname, custom_metadata: dict[str, str]) -> CustomHostname:
    """Replace a Custom Hostname's metadata while preserving keys owned by other features."""
    url = f"{CLOUDFLARE_API_BASE}/zones/{settings.CLOUDFLARE_ZONE_ID}/custom_hostnames/{hostname.id}"
    response = requests.patch(
        url,
        headers=_get_headers(),
        json={"custom_metadata": {**hostname.custom_metadata, **custom_metadata}},
        timeout=CLOUDFLARE_API_TIMEOUT_S,
    )
    data = _handle_response(response)
    return _parse_hostname(data["result"])


def delete_custom_hostname(hostname_id: str) -> bool:
    """
    Delete a Custom Hostname.

    Args:
        hostname_id: The Cloudflare Custom Hostname ID

    Returns:
        True if deleted successfully or already gone (404)

    Raises:
        CloudflareAPIError: If the API request fails (except for 404)
    """
    url = f"{CLOUDFLARE_API_BASE}/zones/{settings.CLOUDFLARE_ZONE_ID}/custom_hostnames/{hostname_id}"

    response = requests.delete(url, headers=_get_headers(), timeout=CLOUDFLARE_API_TIMEOUT_S)

    if response.status_code == 404:
        # Resource already gone, treat as success (idempotent delete)
        return True

    _handle_response(response)
    return True
