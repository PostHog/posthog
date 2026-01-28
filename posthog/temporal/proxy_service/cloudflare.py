"""
Cloudflare for SaaS API client for managing Custom Hostnames and Worker Routes.

This module provides functions to interact with Cloudflare's API for:
- Creating/deleting Custom Hostnames (for TLS certificate provisioning)
- Creating/deleting Worker Routes (for routing traffic to the proxy worker)
- Getting Custom Hostname status (for monitoring certificate status)
"""

import typing as t
from dataclasses import dataclass
from enum import Enum

from django.conf import settings

import requests

CLOUDFLARE_API_BASE = "https://api.cloudflare.com/client/v4"


class CloudflareAPIError(Exception):
    """Exception raised when Cloudflare API returns an error."""

    def __init__(self, message: str, errors: t.Optional[list[dict]] = None):
        super().__init__(message)
        self.errors = errors or []


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


@dataclass
class CustomHostnameSSL:
    """SSL configuration for a Custom Hostname."""

    status: CustomHostnameSSLStatus
    validation_errors: list[dict]


@dataclass
class CustomHostnameInfo:
    """Information about a Custom Hostname."""

    id: str
    hostname: str
    status: CustomHostnameStatus
    ssl: CustomHostnameSSL


@dataclass
class WorkerRouteInfo:
    """Information about a Worker Route."""

    id: str
    pattern: str
    script: str


def _get_headers() -> dict[str, str]:
    """Get headers for Cloudflare API requests."""
    if not settings.CLOUDFLARE_API_TOKEN or not settings.CLOUDFLARE_ZONE_ID:
        raise ValueError("CLOUDFLARE_API_TOKEN and CLOUDFLARE_ZONE_ID must be configured when using Cloudflare proxy")
    return {
        "Authorization": f"Bearer {settings.CLOUDFLARE_API_TOKEN}",
        "Content-Type": "application/json",
    }


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

    result = data["result"]
    return CustomHostnameInfo(
        id=result["id"],
        hostname=result["hostname"],
        status=CustomHostnameStatus(result["status"]),
        ssl=CustomHostnameSSL(
            status=CustomHostnameSSLStatus(result["ssl"]["status"]),
            validation_errors=result["ssl"].get("validation_errors", []),
        ),
    )


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
    result = data["result"]

    return CustomHostnameInfo(
        id=result["id"],
        hostname=result["hostname"],
        status=CustomHostnameStatus(result["status"]),
        ssl=CustomHostnameSSL(
            status=CustomHostnameSSLStatus(result["ssl"]["status"]),
            validation_errors=result["ssl"].get("validation_errors", []),
        ),
    )


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

    result = results[0]
    return CustomHostnameInfo(
        id=result["id"],
        hostname=result["hostname"],
        status=CustomHostnameStatus(result["status"]),
        ssl=CustomHostnameSSL(
            status=CustomHostnameSSLStatus(result["ssl"]["status"]),
            validation_errors=result["ssl"].get("validation_errors", []),
        ),
    )


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


def create_worker_route(domain: str) -> WorkerRouteInfo:
    """
    Create a Worker Route for a domain.

    This routes all traffic for the domain to the configured worker.

    Args:
        domain: The customer's domain (e.g., "analytics.customer.com")

    Returns:
        WorkerRouteInfo with the created route details

    Raises:
        CloudflareAPIError: If the API request fails
    """
    if not settings.CLOUDFLARE_WORKER_NAME:
        raise ValueError("CLOUDFLARE_WORKER_NAME must be configured when creating worker routes")

    url = f"{CLOUDFLARE_API_BASE}/zones/{settings.CLOUDFLARE_ZONE_ID}/workers/routes"

    pattern = f"{domain}/*"
    payload = {
        "pattern": pattern,
        "script": settings.CLOUDFLARE_WORKER_NAME,
    }

    response = requests.post(url, headers=_get_headers(), json=payload, timeout=30)
    data = _handle_response(response)

    result = data["result"]
    return WorkerRouteInfo(
        id=result["id"],
        pattern=result.get("pattern", pattern),
        script=result.get("script", settings.CLOUDFLARE_WORKER_NAME),
    )


def get_worker_route_by_pattern(domain: str) -> t.Optional[WorkerRouteInfo]:
    """
    Find a Worker Route by domain pattern.

    Args:
        domain: The customer's domain (e.g., "analytics.customer.com")

    Returns:
        WorkerRouteInfo or None if not found

    Raises:
        CloudflareAPIError: If the API request fails
    """
    url = f"{CLOUDFLARE_API_BASE}/zones/{settings.CLOUDFLARE_ZONE_ID}/workers/routes"

    response = requests.get(url, headers=_get_headers(), timeout=30)
    data = _handle_response(response)

    pattern = f"{domain}/*"
    for route in data.get("result", []):
        if route.get("pattern") == pattern:
            return WorkerRouteInfo(
                id=route["id"],
                pattern=route["pattern"],
                script=route.get("script", ""),
            )

    return None


def delete_worker_route(route_id: str) -> bool:
    """
    Delete a Worker Route.

    Args:
        route_id: The Cloudflare Worker Route ID

    Returns:
        True if deleted successfully or already gone (404)

    Raises:
        CloudflareAPIError: If the API request fails (except for 404)
    """
    url = f"{CLOUDFLARE_API_BASE}/zones/{settings.CLOUDFLARE_ZONE_ID}/workers/routes/{route_id}"

    response = requests.delete(url, headers=_get_headers(), timeout=30)

    if response.status_code == 404:
        # Resource already gone, treat as success (idempotent delete)
        return True

    _handle_response(response)
    return True
