"""Thin HTTP client the build worker uses to call the Deployments internal API.

The internal endpoints (`POST /api/internal/deployments/{id}/transitions/`
and `.../events/`) live in `products/deployments/backend/api/internal.py`.
The worker uses them to advance the deployment's state machine and to
append timeline events as activities run.

Auth is the shared `X-Internal-Api-Secret` header. URL is configurable
via `DEPLOYMENTS_INTERNAL_API_BASE_URL` so the worker can target the
cluster-internal Service rather than the public ingress.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.conf import settings

import httpx
from temporalio.exceptions import ApplicationError

from ..domain.status import Status
from ..domain.trigger import ErrorStep

# Tight enough that activity heartbeats from a hung internal API surface
# fast, but generous enough to ride out a routine pod restart.
INTERNAL_API_TIMEOUT_SECONDS = 15


class InternalApiError(Exception):
    """Raised when the internal API returns a non-2xx response."""


def _raise_for_status(*, method: str, path: str, status_code: int, body: str) -> None:
    """Raise the right exception type for a non-2xx response.

    4xx indicates a client error (invalid transition, missing row, auth
    failure) — retrying won't help, so raise as a non-retryable
    `ApplicationError` so Temporal stops immediately. 5xx is a server
    error or transient infra failure; raise the plain `InternalApiError`
    so Temporal's retry policy kicks in.
    """
    message = f"Internal API {method} {path} failed: {status_code} {body[:200]}"
    if 400 <= status_code < 500:
        raise ApplicationError(message, type="InternalApiClientError", non_retryable=True)
    raise InternalApiError(message)


def _base_url() -> str:
    base = getattr(settings, "DEPLOYMENTS_INTERNAL_API_BASE_URL", "") or getattr(settings, "SITE_URL", "")
    if not base:
        # Missing env vars won't fix themselves between retries — raise
        # a non-retryable error so the activity fails immediately rather
        # than burning the full _API_RETRY budget on a misconfiguration.
        raise ApplicationError(
            "Missing setting: DEPLOYMENTS_INTERNAL_API_BASE_URL (or SITE_URL). "
            "The deployments worker needs a URL to call back to the web pods.",
            type="InternalApiConfigError",
            non_retryable=True,
        )
    return base.rstrip("/")


def _headers() -> dict[str, str]:
    secret = getattr(settings, "INTERNAL_API_SECRET", "")
    if not secret:
        raise ApplicationError(
            "Missing setting: INTERNAL_API_SECRET.",
            type="InternalApiConfigError",
            non_retryable=True,
        )
    return {"X-Internal-Api-Secret": secret, "Content-Type": "application/json"}


async def post_transition(
    *,
    deployment_id: UUID | str,
    status: Status,
    cloudflare_deployment_id: str | None = None,
    deployment_url: str | None = None,
    error_message: str | None = None,
    error_step: ErrorStep | None = None,
) -> None:
    """Post a status transition to the internal API."""
    body: dict[str, Any] = {"status": status.value}
    if cloudflare_deployment_id:
        body["cloudflare_deployment_id"] = cloudflare_deployment_id
    if deployment_url:
        body["deployment_url"] = deployment_url
    if error_message:
        body["error_message"] = error_message
    if error_step is not None:
        body["error_step"] = error_step.value

    url = f"{_base_url()}/api/internal/deployments/{deployment_id}/transitions/"
    async with httpx.AsyncClient(timeout=INTERNAL_API_TIMEOUT_SECONDS) as client:
        response = await client.post(url, json=body, headers=_headers())
    if not response.is_success:
        _raise_for_status(method="POST", path="transitions", status_code=response.status_code, body=response.text)


async def post_event(*, deployment_id: UUID | str, event_type: str, payload: dict[str, Any] | None = None) -> None:
    """Append a timeline event for the deployment."""
    body: dict[str, Any] = {"event_type": event_type}
    if payload is not None:
        body["payload"] = payload

    url = f"{_base_url()}/api/internal/deployments/{deployment_id}/events/"
    async with httpx.AsyncClient(timeout=INTERNAL_API_TIMEOUT_SECONDS) as client:
        response = await client.post(url, json=body, headers=_headers())
    if not response.is_success:
        _raise_for_status(method="POST", path="events", status_code=response.status_code, body=response.text)
