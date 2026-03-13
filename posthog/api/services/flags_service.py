"""
Shared utilities for proxying flag evaluation requests to the Rust flags service.

All flag evaluation (decide, toolbar, local eval API, etc.) now goes through the Rust
flags service. This module provides a shared HTTP client and proxy function.
"""

from typing import Any

from django.conf import settings

import requests

# Reusable session for proxying to the flags service with connection pooling
_FLAGS_SERVICE_SESSION = requests.Session()


def get_flags_from_service(
    token: str,
    distinct_id: str,
    groups: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Proxy a request to the Rust feature flags service /flags endpoint.

    Args:
        token: The project API token (the public token) for the team
        distinct_id: The distinct ID for the user
        groups: Optional groups for group-based flags (default: None)

    Returns:
        The full response from the flags service as a dict, typically containing:
        - "flags": dict of flag key -> value/boolean
        - "featureFlagPayloads": dict of flag key -> payload (if requested)
        - Other metadata depending on API version

    Raises:
        requests.RequestException: If the HTTP request fails (timeout, connection error, etc.)
        requests.HTTPError: If the service returns a non-2xx status code

    Example:
        >>> response = get_flags_from_service(
        ...     token="phc_abc123",
        ...     distinct_id="user_123",
        ...     groups={"company": "acme"}
        ... )
        >>> flags_data = response.get("flags", {})
        >>> if flags_data.get("new-feature", {}).get("enabled"):
        ...     # Feature is enabled
    """
    flags_service_url = getattr(settings, "FEATURE_FLAGS_SERVICE_URL", "http://localhost:3001")
    proxy_timeout = getattr(settings, "FEATURE_FLAGS_SERVICE_PROXY_TIMEOUT", 3)

    payload: dict[str, Any] = {
        "token": token,
        "distinct_id": distinct_id,
    }

    if groups:
        payload["groups"] = groups

    params: dict[str, str] = {"v": "2"}

    response = _FLAGS_SERVICE_SESSION.post(
        f"{flags_service_url}/flags",
        params=params,
        json=payload,
        timeout=proxy_timeout,
    )
    response.raise_for_status()
    return response.json()
