"""Thin RevenueCat API v2 client used by the data warehouse source.

Spec: https://www.revenuecat.com/docs/api-v2

Everything in this module routes through ``make_tracked_session`` so outbound
calls show up in our HTTP logs, OTel metrics, and sample-capture pipeline.
"""

import dataclasses
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import urlencode

import requests
import structlog

from posthog.temporal.data_imports.sources.common.base import (
    ExternalWebhookInfo,
    WebhookCreationResult,
    WebhookDeletionResult,
)
from posthog.temporal.data_imports.sources.common.http import make_tracked_session
from posthog.temporal.data_imports.sources.revenuecat.constants import (
    REVENUECAT_API_BASE_URL,
    REVENUECAT_AUTO_WEBHOOK_NAME,
    REVENUECAT_WEBHOOK_EVENT_TYPES,
)

LOGGER = structlog.get_logger(__name__)

DEFAULT_PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 30


@dataclasses.dataclass
class RevenueCatResumeConfig:
    """Cursor state for resumable list iteration.

    ``starting_after`` is the RevenueCat-issued cursor value (the id of the last
    item from the previous page). ``endpoint`` scopes the cursor to a single
    endpoint so we never replay a customers cursor against products.
    """

    endpoint: str
    starting_after: str


def _auth_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _session(api_key: str) -> requests.Session:
    return make_tracked_session(headers=_auth_headers(api_key))


def _project_path(project_id: str, suffix: str) -> str:
    return f"/projects/{project_id}{suffix}"


def _format_http_error(error: requests.HTTPError) -> str:
    response = error.response
    status_code = response.status_code if response is not None else None
    if status_code == 401:
        return (
            "RevenueCat rejected the API key (401). Generate a v2 secret API key "
            "from Project settings > API keys and check that it has not been revoked."
        )
    if status_code == 403:
        return (
            "RevenueCat denied the request (403). Make sure the v2 secret API key "
            "has the permissions required for this resource."
        )
    if status_code == 404:
        return "RevenueCat could not find the project (404). Double-check the project id."
    if status_code == 429:
        return "RevenueCat rate-limited the request (429). Try again in a few seconds."
    return f"RevenueCat API error ({status_code})."


def validate_credentials(api_key: str, project_id: str | None) -> tuple[bool, str | None]:
    """Probe the cheapest endpoint that confirms the key + project.

    GET /v2/projects lists every project the key can see — that's enough to
    confirm the key is genuine. If a ``project_id`` is set, we additionally
    fetch that project to catch typos and revoked-project access.
    """
    session = _session(api_key)
    try:
        response = session.get(f"{REVENUECAT_API_BASE_URL}/projects", timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.HTTPError as e:
        return False, _format_http_error(e)
    except requests.RequestException as e:
        return False, f"Could not reach RevenueCat: {e}"

    if project_id:
        try:
            response = session.get(
                f"{REVENUECAT_API_BASE_URL}/projects/{project_id}",
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except requests.HTTPError as e:
            return False, _format_http_error(e)
        except requests.RequestException as e:
            return False, f"Could not reach RevenueCat: {e}"

    return True, None


def iterate_list_endpoint(
    api_key: str,
    project_id: str,
    path_suffix: str,
    *,
    endpoint_name: str,
    starting_after: str | None = None,
    on_cursor_advance: Callable[[str, str], None] | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield rows from a RevenueCat v2 list endpoint, transparently following the cursor.

    RevenueCat returns ``{"items": [...], "next_page": "/v2/path?starting_after=ID"}``.
    When ``next_page`` is null/absent, the list is exhausted.

    ``on_cursor_advance`` is invoked with the last item's id every time we finish
    yielding a page so callers (e.g. the resumable manager) can checkpoint. We
    save state *after* yielding so a crash re-yields the last page rather than
    skipping it — merge dedupes on primary key.
    """
    session = _session(api_key)
    params: dict[str, Any] = {"limit": DEFAULT_PAGE_SIZE}
    if starting_after:
        params["starting_after"] = starting_after

    url = f"{REVENUECAT_API_BASE_URL}{_project_path(project_id, path_suffix)}"

    while True:
        response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json() or {}

        rows = payload.get("items") or []
        if not isinstance(rows, list):
            return

        last_id: str | None = None
        for row in rows:
            if not isinstance(row, dict):
                continue
            yield row
            row_id = row.get("id")
            if isinstance(row_id, str):
                last_id = row_id

        next_page = payload.get("next_page")
        if last_id is not None and on_cursor_advance is not None:
            on_cursor_advance(endpoint_name, last_id)

        if not next_page:
            return

        # next_page is a relative path including its own query string (e.g.
        # `/v2/projects/{id}/customers?starting_after=cus_abc&limit=20`). The
        # path already encodes the next cursor, so re-send it as-is with no
        # extra params — passing both `params=` and a query-bearing url would
        # produce duplicate `limit=` values.
        url = next_page if next_page.startswith("http") else f"https://api.revenuecat.com{next_page}"
        params = {}


def create_webhook(
    api_key: str,
    project_id: str,
    webhook_url: str,
    authorization_header_value: str | None = None,
) -> WebhookCreationResult:
    """Auto-register a webhook integration in RevenueCat pointing at ``webhook_url``.

    Auth-header note: RevenueCat does not HMAC-sign its webhook deliveries —
    instead, the integration ships an ``Authorization`` header whose value the
    user sets at creation time. We let callers pass that value through so we
    can later verify it in the Hog template. If not supplied, the integration
    is created without an auth header and the user finishes setup by adding one
    via the webhook fields (handled by the surrounding warehouse-source flow).
    """
    logger = LOGGER.bind(project_id=project_id)

    body: dict[str, Any] = {
        "url": webhook_url,
        "events": list(REVENUECAT_WEBHOOK_EVENT_TYPES),
        "name": REVENUECAT_AUTO_WEBHOOK_NAME,
    }
    if authorization_header_value:
        # RevenueCat names this field `signing_secret` in their API even though
        # the upstream behavior is just "send this verbatim as Authorization".
        body["signing_secret"] = authorization_header_value

    url = f"{REVENUECAT_API_BASE_URL}{_project_path(project_id, '/integrations/webhook')}"

    try:
        existing = _find_webhook_integration(api_key, project_id, webhook_url)
        if existing is not None:
            # Webhook for this URL already exists — treat as success so the user
            # can finish setup by supplying the authorization header value. We
            # don't list the existing auth header value: RevenueCat omits it
            # from list responses.
            return WebhookCreationResult(success=True, pending_inputs=["authorization_header"])

        response = _session(api_key).post(url, json=body, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.HTTPError as e:
        logger.warning("Failed to create RevenueCat webhook integration", error=str(e))
        return WebhookCreationResult(success=False, error=_format_http_error(e))
    except requests.RequestException as e:
        logger.warning("Could not reach RevenueCat to create webhook", error=str(e))
        return WebhookCreationResult(success=False, error=f"Could not reach RevenueCat: {e}")

    pending: list[str] = []
    if not authorization_header_value:
        pending.append("authorization_header")
    return WebhookCreationResult(success=True, pending_inputs=pending)


def _list_webhook_integrations(api_key: str, project_id: str) -> list[dict[str, Any]]:
    """Iterate the webhook integrations under a project, following cursor pages."""
    items: list[dict[str, Any]] = []
    session = _session(api_key)
    params: dict[str, Any] = {"limit": DEFAULT_PAGE_SIZE}
    url = f"{REVENUECAT_API_BASE_URL}{_project_path(project_id, '/integrations/webhook')}"

    while True:
        # Build the URL with explicit query encoding so the call signature stays
        # stable across pages and we never accidentally pass duplicate `limit`s.
        request_url = f"{url}?{urlencode(params)}" if params else url
        response = session.get(request_url, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json() or {}

        page = payload.get("items") or []
        if isinstance(page, list):
            for hook in page:
                if isinstance(hook, dict):
                    items.append(hook)

        next_page = payload.get("next_page")
        if not next_page:
            return items
        url = next_page if next_page.startswith("http") else f"https://api.revenuecat.com{next_page}"
        params = {}


def _find_webhook_integration(api_key: str, project_id: str, webhook_url: str) -> dict[str, Any] | None:
    try:
        integrations = _list_webhook_integrations(api_key, project_id)
    except requests.RequestException:
        return None
    for hook in integrations:
        if hook.get("url") == webhook_url:
            return hook
    return None


def delete_webhook(api_key: str, project_id: str, webhook_url: str) -> WebhookDeletionResult:
    logger = LOGGER.bind(project_id=project_id)

    try:
        integrations = _list_webhook_integrations(api_key, project_id)
    except requests.HTTPError as e:
        logger.warning("Failed to list RevenueCat webhook integrations", error=str(e))
        return WebhookDeletionResult(success=False, error=_format_http_error(e))
    except requests.RequestException as e:
        logger.warning("Could not reach RevenueCat to list webhooks", error=str(e))
        return WebhookDeletionResult(success=False, error=f"Could not reach RevenueCat: {e}")

    target = next((hook for hook in integrations if hook.get("url") == webhook_url), None)
    if target is None:
        # Nothing to delete is a success — keep delete idempotent.
        return WebhookDeletionResult(success=True)

    webhook_id = target.get("id")
    if not webhook_id:
        return WebhookDeletionResult(
            success=False,
            error="RevenueCat returned a webhook without an id; please delete it manually.",
        )

    url = f"{REVENUECAT_API_BASE_URL}{_project_path(project_id, f'/integrations/webhook/{webhook_id}')}"
    try:
        response = _session(api_key).delete(url, timeout=REQUEST_TIMEOUT_SECONDS)
        if response.status_code == 404:
            return WebhookDeletionResult(success=True)
        response.raise_for_status()
    except requests.HTTPError as e:
        logger.warning("Failed to delete RevenueCat webhook integration", error=str(e))
        return WebhookDeletionResult(success=False, error=_format_http_error(e))
    except requests.RequestException as e:
        logger.warning("Could not reach RevenueCat to delete webhook", error=str(e))
        return WebhookDeletionResult(success=False, error=f"Could not reach RevenueCat: {e}")

    return WebhookDeletionResult(success=True)


def get_external_webhook_info(api_key: str, project_id: str, webhook_url: str) -> ExternalWebhookInfo:
    try:
        integrations = _list_webhook_integrations(api_key, project_id)
    except requests.HTTPError as e:
        return ExternalWebhookInfo(exists=False, error=_format_http_error(e))
    except requests.RequestException as e:
        return ExternalWebhookInfo(exists=False, error=f"Could not reach RevenueCat: {e}")

    target = next((hook for hook in integrations if hook.get("url") == webhook_url), None)
    if target is None:
        return ExternalWebhookInfo(exists=False)

    events_value = target.get("events")
    enabled_events = events_value if isinstance(events_value, list) else None
    created_at_raw = target.get("created_at")
    created_at = str(created_at_raw) if created_at_raw is not None else None

    return ExternalWebhookInfo(
        exists=True,
        url=target.get("url"),
        enabled_events=enabled_events,
        # RevenueCat doesn't expose an enabled/disabled state on the integration
        # object — once created, it's active. Report "enabled" to surface that.
        status="enabled",
        description=target.get("name"),
        created_at=created_at,
    )
