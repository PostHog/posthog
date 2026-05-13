"""
Shared utilities for proxying flag evaluation requests to the Rust flags service.

All flag evaluation (decide, toolbar, local eval API, etc.) now goes through the Rust
flags service. This module provides a shared HTTP client and proxy function.
"""

from typing import Any

from django.conf import settings

from posthog.security.outbound_proxy import internal_requests_session

# Reusable session for proxying to the flags service with connection pooling
_FLAGS_SERVICE_SESSION = internal_requests_session()


def get_flags_from_service(
    token: str,
    distinct_id: str,
    groups: dict[str, Any] | None = None,
    detailed_analysis: bool = False,
    person_properties: dict[str, Any] | None = None,
    only_use_override_person_properties: bool = False,
    flag_keys: list[str] | None = None,
    internal_request_token: str | None = None,
    override_flags_definitions: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Proxy a request to the Rust feature flags service /flags endpoint.

    Args:
        token: The project API token (the public token) for the team
        distinct_id: The distinct ID for the user
        groups: Optional groups for group-based flags (default: None)
        detailed_analysis: Whether to include detailed condition analysis (default: False)
        person_properties: Optional person properties for evaluation (default: None)
        only_use_override_person_properties: Whether to ignore database person properties and only use provided ones (default: False)
        flag_keys: Optional list of specific flag keys to evaluate (default: None, evaluates all flags)
        internal_request_token: Optional token to mark request as internal (non-billable) (default: None)
        override_flags_definitions: Optional dict of flag key -> flag definition to override database flags (default: None)

    Returns:
        The full response from the flags service as a dict, typically containing:
        - "flags": dict of flag key -> flag data (enabled, variant, etc.)
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

    if person_properties is not None:
        payload["person_properties"] = person_properties

    if flag_keys:
        payload["flag_keys"] = flag_keys

    if override_flags_definitions:
        payload["override_flags_definitions"] = override_flags_definitions

    params: dict[str, str] = {"v": "2"}

    if detailed_analysis:
        params["detailed_analysis"] = "true"

    if only_use_override_person_properties:
        params["only_use_override_person_properties"] = "true"

    headers = {}
    if internal_request_token and internal_request_token.strip():
        headers["Authorization"] = f"Bearer {internal_request_token}"

    response = _FLAGS_SERVICE_SESSION.post(
        f"{flags_service_url}/flags",
        params=params,
        json=payload,
        headers=headers,
        timeout=proxy_timeout,
    )
    response.raise_for_status()
    return response.json()
