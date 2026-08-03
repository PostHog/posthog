"""Gated, recorded transport for calls to the Composio API."""

import hashlib
from typing import Any
from urllib.parse import urljoin

from django.conf import settings

import requests

from posthog.egress.composio.limiter import consume_composio_account_sync, consume_composio_team_sync
from posthog.egress.composio.observability import (
    normalize_composio_endpoint,
    record_composio_api_exception,
    record_composio_api_response,
)
from posthog.egress.limiter.policies import Priority
from posthog.egress.transport.transport import EgressBudgetExhausted, EgressClient

COMPOSIO_DEFAULT_BASE_URL = "https://backend.composio.dev"


class ComposioEgressBudgetExhausted(EgressBudgetExhausted):
    pass


class ComposioNotConfigured(Exception):
    """No `COMPOSIO_API_KEY` is set. Expected on self-hosted and in dev — callers should treat
    Composio as an absent feature rather than an error."""


class ComposioClient(EgressClient):
    def _standard_headers(self) -> dict[str, str]:
        return {"Accept": "application/json", "Content-Type": "application/json"}

    def _consume(self, scope: str, priority: Priority, source: str, url: str) -> bool:
        # Both meters are drawn on every call. When the instance budget denies, the team draw has
        # already been consumed — an over-count of at most one on a sliding window, which the next
        # window sheds. Order matters the other way: checking the team first would let a single
        # team's burst consume instance headroom it was never going to be admitted for.
        account_fingerprint, team_id = _split_scope(scope)
        if not consume_composio_account_sync(account_fingerprint, priority=priority, source=source):
            return False
        if team_id is None:
            return True
        return consume_composio_team_sync(team_id, priority=priority, source=source)

    def _record_response(
        self, response: requests.Response, *, source: str, scope: str | None, method: str, endpoint: str | None
    ) -> None:
        account_fingerprint, _ = _split_scope(scope or "")
        record_composio_api_response(
            response,
            source=source,
            account=account_fingerprint,
            method=method,
            endpoint=endpoint or normalize_composio_endpoint(getattr(getattr(response, "request", None), "url", None)),
        )

    def _record_exception(self, *, source: str, scope: str | None, method: str, url: str, endpoint: str | None) -> None:
        account_fingerprint, _ = _split_scope(scope or "")
        record_composio_api_exception(
            source=source,
            account=account_fingerprint,
            method=method,
            endpoint=endpoint or normalize_composio_endpoint(url),
            url=url,
        )

    def _budget_exhausted_error(self, scope: str) -> ComposioEgressBudgetExhausted:
        return ComposioEgressBudgetExhausted("Composio egress budget exhausted")


_composio_client = ComposioClient()


def _split_scope(scope: str) -> tuple[str, int | None]:
    """Unpack the composite `{account_fingerprint}:{team_id}` scope. The account fingerprint is the
    identity the external API meters; the team id rides along for the fairness lane only, and the
    metric labels keep the account so one real budget stays one series."""
    fingerprint, _, raw_team_id = scope.partition(":")
    if not raw_team_id:
        return fingerprint, None
    try:
        return fingerprint, int(raw_team_id)
    except ValueError:
        return fingerprint, None


def composio_api_key() -> str:
    key = getattr(settings, "COMPOSIO_API_KEY", "")
    if not key:
        raise ComposioNotConfigured("COMPOSIO_API_KEY is not set")
    return key


def is_composio_configured() -> bool:
    return bool(getattr(settings, "COMPOSIO_API_KEY", ""))


def composio_request(
    method: str,
    path: str,
    *,
    source: str,
    team_id: int | None = None,
    priority: Priority = Priority.NORMAL,
    endpoint: str | None = None,
    timeout: float | tuple[float, float] | None = 30.0,
    session: requests.Session | None = None,
    **kwargs: Any,
) -> requests.Response:
    """Call the Composio API. `path` is relative to the configured base URL (an absolute URL is
    also accepted, for follow-on links Composio hands back).

    Runs on the NORMAL lane by default: Composio calls sit behind an agent's tool call, so shedding
    is preferable to blowing the shared account budget, but they are not bulk traffic either.
    """
    api_key = composio_api_key()
    base_url = getattr(settings, "COMPOSIO_API_BASE_URL", COMPOSIO_DEFAULT_BASE_URL)
    url = path if path.startswith("http://") or path.startswith("https://") else urljoin(base_url, path)
    account_fingerprint = hashlib.sha256(api_key.encode()).hexdigest()[:16]
    scope = f"{account_fingerprint}:{team_id}" if team_id is not None else account_fingerprint

    return _composio_client.request(
        method,
        url,
        source=source,
        headers={"x-api-key": api_key},
        scope=scope,
        priority=priority,
        endpoint=endpoint or normalize_composio_endpoint(url),
        timeout=timeout,
        session=session,
        **kwargs,
    )
