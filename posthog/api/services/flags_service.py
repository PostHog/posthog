"""
Shared utilities for proxying flag evaluation requests to the Rust flags service.

All flag evaluation (decide, toolbar, local eval API, etc.) now goes through the Rust
flags service. This module provides a shared HTTP client and proxy function.
"""

from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from posthog.security.outbound_proxy import internal_requests_session

# Reusable session for proxying to the flags service with connection pooling
_FLAGS_SERVICE_SESSION = internal_requests_session()

# One page of batch evaluation covers up to ~10k persons evaluated sequentially in the
# service, so this sits above the service's own per-request timeout (120s) rather than
# the 3s live-proxy timeout.
BATCH_FLAG_EVALUATION_TIMEOUT_SECONDS = 150


class FlagVersionConflictError(Exception):
    """The feature flag changed while a static cohort was being generated from it."""


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
    evaluation_runtime: str | None = None,
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
        evaluation_runtime: Optional override for runtime filtering: "all" | "client" | "server".
            When None, the Rust service auto-detects from request headers (User-Agent, origin, sec-fetch-*).

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

    if evaluation_runtime:
        payload["evaluation_runtime"] = evaluation_runtime

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


def batch_evaluate_flag_for_team(
    *,
    team_id: int,
    project_id: int,
    flag_key: str,
    expected_version: int,
    cursor: int,
    limit: int,
) -> dict[str, Any]:
    """
    Request one page of batch flag evaluation from the Rust flags service.

    The internal endpoint evaluates the flag for a cursor-paged slice of the team's
    persons, exactly like live /flags evaluation (read-only — no continuity override
    writes, no billing or analytics). Used by static cohort generation from a flag.

    Args:
        team_id: The team whose persons are evaluated
        project_id: The project the flag belongs to (informational; flag lookup is team-scoped)
        flag_key: The key of the flag to evaluate
        expected_version: Optimistic-lock pin — the flag `version` read before the run started
        cursor: Exclusive lower bound on person id; 0 for the first page
        limit: Page size; the service rejects (400) any value above its configured
            maximum (BATCH_FLAG_EVAL_MAX_LIMIT, default 10000) rather than clamping it,
            so keep this at or below that maximum

    Returns:
        The page as a dict: {"matched_person_uuids": [...], "next_cursor": int | None, "errors_count": int}

    Raises:
        ImproperlyConfigured: `INTERNAL_REQUEST_TOKEN` is not set
        FlagVersionConflictError: The flag's version no longer matches `expected_version`
        requests.RequestException: If the HTTP request fails (timeout, connection error, etc.)
        requests.HTTPError: If the service returns a non-2xx status code
    """
    flags_service_url = getattr(settings, "FEATURE_FLAGS_SERVICE_URL", "http://localhost:3001")

    # The service refuses all internal requests when its token is unset, so an empty
    # token here can only ever produce an opaque 401 — fail fast with the real cause.
    internal_request_token = settings.INTERNAL_REQUEST_TOKEN
    if not internal_request_token or not internal_request_token.strip():
        raise ImproperlyConfigured("INTERNAL_REQUEST_TOKEN must be set for batch flag evaluation")
    headers = {"Authorization": f"Bearer {internal_request_token}"}

    response = _FLAGS_SERVICE_SESSION.post(
        f"{flags_service_url}/internal/batch_flag_evaluation",
        json={
            "team_id": team_id,
            "project_id": project_id,
            "flag_key": flag_key,
            "expected_version": expected_version,
            "cursor": cursor,
            "limit": limit,
        },
        headers=headers,
        timeout=BATCH_FLAG_EVALUATION_TIMEOUT_SECONDS,
    )
    if response.status_code == 409:
        raise FlagVersionConflictError(
            f"Feature flag '{flag_key}' changed while generating the cohort (expected version "
            f"{expected_version}). Re-run cohort generation to use the latest flag definition."
        )
    response.raise_for_status()
    return response.json()
