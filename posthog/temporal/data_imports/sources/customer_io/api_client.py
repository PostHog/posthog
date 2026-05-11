"""Thin client for the Customer.io App API endpoints used by the data warehouse source.

Spec: https://docs.customer.io/api/app/
Broader App API helpers (track events, search, etc.) belong in
`products/messaging/backend/services/customerio_client.py`.
"""

from collections.abc import Iterator
from typing import Any

import requests
import structlog

from posthog.temporal.data_imports.sources.common.base import (
    ExternalWebhookInfo,
    WebhookCreationResult,
    WebhookDeletionResult,
)
from posthog.temporal.data_imports.sources.common.http import make_tracked_session
from posthog.temporal.data_imports.sources.customer_io.constants import (
    CIO_AUTO_WEBHOOK_NAME,
    CIO_EU_BASE_URL,
    CIO_OBJECT_TYPE_TO_EVENTS,
    CIO_US_BASE_URL,
    RESOURCE_TO_CIO_OBJECT_TYPE,
    CIOListEndpoint,
)

LOGGER = structlog.get_logger(__name__)

REPORTING_WEBHOOKS_PATH = "/v1/reporting_webhooks"
WORKSPACES_PATH = "/v1/workspaces"
REQUEST_TIMEOUT_SECONDS = 30


def _base_url(region: str | None) -> str:
    return CIO_EU_BASE_URL if (region or "").lower() == "eu" else CIO_US_BASE_URL


def _auth_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _session(api_key: str) -> requests.Session:
    """Tracked `requests.Session` with auth headers pre-bound.

    The session inherits HTTP logging, OTel metrics, and opt-in sample
    capture from `make_tracked_session` — everything the warehouse-source
    transport gives us.
    """
    return make_tracked_session(headers=_auth_headers(api_key))


def _events_for_resources(resource_names: list[str]) -> list[str]:
    """Expand PostHog resource names into the full Customer.io event list.

    Resource names that aren't in `RESOURCE_TO_CIO_OBJECT_TYPE` (or whose object_type
    has no entries in `CIO_OBJECT_TYPE_TO_EVENTS`) are silently skipped.
    """
    events: list[str] = []
    seen: set[str] = set()
    for resource in resource_names:
        object_type = RESOURCE_TO_CIO_OBJECT_TYPE.get(resource)
        if object_type is None:
            continue
        for event in CIO_OBJECT_TYPE_TO_EVENTS.get(object_type, ()):
            if event not in seen:
                events.append(event)
                seen.add(event)
    return events


def _format_http_error(error: requests.HTTPError) -> str:
    response = error.response
    status_code = response.status_code
    if status_code == 401:
        return (
            "Customer.io rejected the App API Key (401). Generate an App API Key from "
            "Settings > API Credentials > App API Keys and check the region."
        )
    if status_code == 403:
        return "Customer.io denied the request (403). Make sure the App API Key has access to reporting webhooks."
    if status_code == 429:
        return "Customer.io rate-limited the request (429). Try again in a few seconds."
    return f"Customer.io API error ({status_code})."


def validate_credentials(api_key: str, region: str | None) -> tuple[bool, str | None]:
    """Validate the App API Key by listing the workspaces it can see.

    `/v1/workspaces` is the cheapest permission-light call we can make; every App API
    Key can hit it, regardless of whether the key has reporting-webhooks scope.
    """
    url = f"{_base_url(region)}{WORKSPACES_PATH}"
    try:
        response = _session(api_key).get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.HTTPError as e:
        return False, _format_http_error(e)
    except requests.RequestException as e:
        return False, f"Could not reach Customer.io: {e}"
    return True, None


def iterate_list_endpoint(
    api_key: str,
    region: str | None,
    endpoint: CIOListEndpoint,
) -> Iterator[dict[str, Any]]:
    """Yield rows from a Customer.io list endpoint, transparently following any cursor.

    Endpoints without `cursor_param` set just issue a single GET; cursor-paginated
    endpoints (newsletters, activities) follow the cursor field until it's empty.
    """

    base = f"{_base_url(region)}{endpoint.path}"
    # One tracked session for the whole pagination loop so urllib3 keeps the
    # TLS connection warm across cursor pages.
    session = _session(api_key)
    params: dict[str, Any] = {}
    if endpoint.cursor_param and endpoint.page_size is not None:
        params["limit"] = endpoint.page_size

    while True:
        response = session.get(base, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json() or {}

        rows = payload.get(endpoint.response_key) or []
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    yield row

        if not endpoint.cursor_param or not endpoint.cursor_field:
            return
        next_cursor = payload.get(endpoint.cursor_field)
        if not next_cursor:
            return
        params = {endpoint.cursor_param: next_cursor}
        if endpoint.page_size is not None:
            params["limit"] = endpoint.page_size


def _list_webhooks(api_key: str, region: str | None) -> list[dict[str, Any]]:
    url = f"{_base_url(region)}{REPORTING_WEBHOOKS_PATH}"
    response = _session(api_key).get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    payload = response.json() or {}
    raw = payload.get("reporting_webhooks") or []
    return [hook for hook in raw if isinstance(hook, dict)]


def _find_webhook_by_url(webhooks: list[dict[str, Any]], webhook_url: str) -> dict[str, Any] | None:
    for hook in webhooks:
        if hook.get("endpoint") == webhook_url:
            return hook
    return None


def create_webhook(
    api_key: str,
    region: str | None,
    webhook_url: str,
    resource_names: list[str],
) -> WebhookCreationResult:
    logger = LOGGER.bind(region=region or "us")

    events = _events_for_resources(resource_names)
    if not events:
        supported = ", ".join(sorted(CIO_OBJECT_TYPE_TO_EVENTS.keys()))
        return WebhookCreationResult(
            success=False,
            error=(
                f"None of the selected tables map to Customer.io reporting-webhook events. "
                f"Choose at least one of: {supported}."
            ),
        )

    body: dict[str, Any] = {
        "name": CIO_AUTO_WEBHOOK_NAME,
        "endpoint": webhook_url,
        "events": events,
        "disabled": True,
    }

    url = f"{_base_url(region)}{REPORTING_WEBHOOKS_PATH}"

    try:
        existing = _find_webhook_by_url(_list_webhooks(api_key, region), webhook_url)
        if existing is not None:
            # Webhook already exists for this URL — treat as success so the user can
            # finish setup by entering the signing key. The webhook will be enabled
            # once the signing key is provided.
            return WebhookCreationResult(success=True, pending_inputs=["signing_secret"])

        response = _session(api_key).post(
            url,
            json=body,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.HTTPError as e:
        logger.warning("Failed to create Customer.io reporting webhook", error=str(e))
        return WebhookCreationResult(success=False, error=_format_http_error(e))
    except requests.RequestException as e:
        logger.warning("Could not reach Customer.io to create webhook", error=str(e))
        return WebhookCreationResult(success=False, error=f"Could not reach Customer.io: {e}")

    # Customer.io does NOT return the signing key in the create response — the user
    # has to copy it from the Reporting Webhooks page in the Customer.io UI.
    return WebhookCreationResult(success=True, pending_inputs=["signing_secret"])


def enable_webhook(api_key: str, region: str | None, webhook_url: str) -> tuple[bool, str | None]:
    """Flip the matching reporting webhook to ``disabled: false`` on Customer.io.

    Webhooks are created in a disabled state so Customer.io doesn't start firing
    against the endpoint before PostHog has the signing secret to verify
    deliveries. This is called from ``webhook_inputs_updated`` once the user
    provides that secret.
    """
    logger = LOGGER.bind(region=region or "us")

    try:
        existing = _find_webhook_by_url(_list_webhooks(api_key, region), webhook_url)
        if existing is None:
            return False, "No reporting webhook found for this URL in Customer.io."

        webhook_id = existing.get("id")
        if webhook_id is None:
            return False, "Customer.io returned a webhook without an id; please enable it manually."

        if not existing.get("disabled"):
            return True, None

        url = f"{_base_url(region)}{REPORTING_WEBHOOKS_PATH}/{webhook_id}"
        response = _session(api_key).put(url, json={"disabled": False}, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.HTTPError as e:
        logger.warning("Failed to enable Customer.io reporting webhook", error=str(e))
        return False, _format_http_error(e)
    except requests.RequestException as e:
        logger.warning("Could not reach Customer.io to enable webhook", error=str(e))
        return False, f"Could not reach Customer.io: {e}"

    return True, None


def delete_webhook(api_key: str, region: str | None, webhook_url: str) -> WebhookDeletionResult:
    logger = LOGGER.bind(region=region or "us")

    try:
        webhooks = _list_webhooks(api_key, region)
        existing = _find_webhook_by_url(webhooks, webhook_url)
        if existing is None:
            return WebhookDeletionResult(success=True)

        webhook_id = existing.get("id")
        if webhook_id is None:
            return WebhookDeletionResult(
                success=False,
                error="Customer.io returned a webhook without an id; please delete it manually.",
            )

        url = f"{_base_url(region)}{REPORTING_WEBHOOKS_PATH}/{webhook_id}"
        response = _session(api_key).delete(url, timeout=REQUEST_TIMEOUT_SECONDS)
        if response.status_code == 404:
            return WebhookDeletionResult(success=True)
        response.raise_for_status()
    except requests.HTTPError as e:
        logger.warning("Failed to delete Customer.io reporting webhook", error=str(e))
        return WebhookDeletionResult(success=False, error=_format_http_error(e))
    except requests.RequestException as e:
        logger.warning("Could not reach Customer.io to delete webhook", error=str(e))
        return WebhookDeletionResult(success=False, error=f"Could not reach Customer.io: {e}")

    return WebhookDeletionResult(success=True)


def get_external_webhook_info(api_key: str, region: str | None, webhook_url: str) -> ExternalWebhookInfo:
    try:
        webhooks = _list_webhooks(api_key, region)
    except requests.HTTPError as e:
        return ExternalWebhookInfo(exists=False, error=_format_http_error(e))
    except requests.RequestException as e:
        return ExternalWebhookInfo(exists=False, error=f"Could not reach Customer.io: {e}")

    existing = _find_webhook_by_url(webhooks, webhook_url)
    if existing is None:
        return ExternalWebhookInfo(exists=False)

    enabled_events = existing.get("events")
    if not isinstance(enabled_events, list):
        enabled_events = None

    disabled = bool(existing.get("disabled"))

    return ExternalWebhookInfo(
        exists=True,
        url=existing.get("endpoint"),
        enabled_events=enabled_events,
        status="disabled" if disabled else "enabled",
        description=existing.get("name"),
    )
