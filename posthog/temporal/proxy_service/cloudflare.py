"""
Cloudflare for SaaS API client for managing Custom Hostnames and Worker Routes.

This module provides functions to interact with Cloudflare's API for:
- Creating/deleting Custom Hostnames (for TLS certificate provisioning)
- Creating/deleting Worker Routes (for routing traffic to the proxy worker)
- Getting Custom Hostname status (for monitoring certificate status)
"""

import typing as t
from dataclasses import dataclass, field
from enum import Enum

from django.conf import settings

import requests

CLOUDFLARE_API_BASE = "https://api.cloudflare.com/client/v4"


class CloudflareAPIError(Exception):
    """Exception raised when Cloudflare API returns an error."""

    def __init__(self, message: str, errors: t.Optional[list[dict]] = None) -> None:
        super().__init__(message)
        self.errors = errors or []

    def is_rate_limited(self) -> bool:
        return any(err.get("code") == 10000 for err in self.errors) or "rate limit" in str(self).lower()


class CustomHostnameSSLStatus(str, Enum):
    """SSL certificate status for a Custom Hostname."""

    INITIALIZING = "initializing"
    PENDING_VALIDATION = "pending_validation"
    PENDING_ISSUANCE = "pending_issuance"
    PENDING_DEPLOYMENT = "pending_deployment"
    ACTIVE = "active"
    PENDING_DELETION = "pending_deletion"
    DELETED = "deleted"


class CustomHostnameStatus(str, Enum):
    """Status for a Custom Hostname."""

    ACTIVE = "active"
    PENDING = "pending"
    MOVED = "moved"
    DELETED = "deleted"
    BLOCKED = "blocked"


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


@dataclass
class CustomHostnameInfo:
    """Information about a Custom Hostname."""

    id: str
    hostname: str
    status: CustomHostnameStatus
    ssl: CustomHostnameSSL


def _get_headers() -> dict[str, str]:
    """Get headers for Cloudflare API requests."""
    if not settings.CLOUDFLARE_API_TOKEN or not settings.CLOUDFLARE_ZONE_ID:
        raise ValueError("CLOUDFLARE_API_TOKEN and CLOUDFLARE_ZONE_ID must be configured when using Cloudflare proxy")
    return {
        "Authorization": f"Bearer {settings.CLOUDFLARE_API_TOKEN}",
        "Content-Type": "application/json",
    }


def _parse_hostname(result: dict) -> "CustomHostnameInfo":
    """Build a CustomHostnameInfo from a Cloudflare API custom_hostname result object."""
    ssl_payload = result.get("ssl", {})
    return CustomHostnameInfo(
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


def create_custom_hostname(domain: str) -> CustomHostnameInfo:
    """
    Create a Custom Hostname in Cloudflare for SaaS.

    This creates a custom hostname with:
    - SSL certificate provided by Cloudflare
    - HTTP validation method
    - Default origin server

    Args:
        domain: The customer's domain (e.g., "analytics.customer.com")

    Returns:
        CustomHostnameInfo with the created hostname details

    Raises:
        CloudflareAPIError: If the API request fails
    """
    url = f"{CLOUDFLARE_API_BASE}/zones/{settings.CLOUDFLARE_ZONE_ID}/custom_hostnames"

    payload = {
        "hostname": domain,
        "ssl": {
            "method": "http",
            "type": "dv",
        },
    }

    response = requests.post(url, headers=_get_headers(), json=payload, timeout=30)
    data = _handle_response(response)
    return _parse_hostname(data["result"])


def get_custom_hostname(hostname_id: str) -> t.Optional[CustomHostnameInfo]:
    """
    Get details of a Custom Hostname by ID.

    Args:
        hostname_id: The Cloudflare Custom Hostname ID

    Returns:
        CustomHostnameInfo or None if not found

    Raises:
        CloudflareAPIError: If the API request fails (except for 404)
    """
    url = f"{CLOUDFLARE_API_BASE}/zones/{settings.CLOUDFLARE_ZONE_ID}/custom_hostnames/{hostname_id}"

    response = requests.get(url, headers=_get_headers(), timeout=30)

    if response.status_code == 404:
        return None

    data = _handle_response(response)
    return _parse_hostname(data["result"])


def get_custom_hostname_by_domain(domain: str) -> t.Optional[CustomHostnameInfo]:
    """
    Find a Custom Hostname by domain name.

    Args:
        domain: The customer's domain (e.g., "analytics.customer.com")

    Returns:
        CustomHostnameInfo or None if not found

    Raises:
        CloudflareAPIError: If the API request fails
    """
    url = f"{CLOUDFLARE_API_BASE}/zones/{settings.CLOUDFLARE_ZONE_ID}/custom_hostnames"
    params = {"hostname": domain}

    response = requests.get(url, headers=_get_headers(), params=params, timeout=30)
    data = _handle_response(response)

    results = data.get("result", [])
    if not results:
        return None

    return _parse_hostname(results[0])


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

    response = requests.delete(url, headers=_get_headers(), timeout=30)

    if response.status_code == 404:
        # Resource already gone, treat as success (idempotent delete)
        return True

    _handle_response(response)
    return True
