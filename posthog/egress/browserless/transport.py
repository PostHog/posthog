"""Gated, recorded transport for calls to a Browserless fleet."""

import hashlib
from typing import Any
from urllib.parse import urlsplit

import requests

from posthog.egress.browserless.limiter import consume_browserless_sync
from posthog.egress.browserless.observability import record_browserless_exception, record_browserless_response
from posthog.egress.limiter.policies import Priority
from posthog.egress.transport.transport import EgressBudgetExhausted, EgressClient


class BrowserlessEgressBudgetExhausted(EgressBudgetExhausted):
    pass


def fleet_scope(url: str, token: str) -> str:
    """Identify the pool of browsers a call actually competes for.

    Host and token together, because either alone is wrong. The same credential against a
    different host is a different set of workers, and a self-hosted fleet often has no token at
    all, which would collapse every such deployment onto one shared budget if the token were the
    whole identity.

    Hashed rather than stored plainly because the token is a secret and the scope is a metric
    label: it reaches Prometheus, and from there dashboards and alerts.
    """
    host = urlsplit(url).hostname or ""
    if not host and not token:
        return ""
    return hashlib.sha256(f"{host}|{token}".encode()).hexdigest()[:16]


class BrowserlessClient(EgressClient):
    def _standard_headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json"}

    def _consume(self, scope: str, priority: Priority, source: str, url: str) -> bool:
        return consume_browserless_sync(scope, priority=priority, source=source)

    def _record_response(
        self, response: requests.Response, *, source: str, scope: str | None, method: str, endpoint: str | None
    ) -> None:
        record_browserless_response(
            response,
            source=source,
            scope=scope or "",
            method=method,
            endpoint=endpoint or "unknown",
        )

    def _record_exception(self, *, source: str, scope: str | None, method: str, url: str, endpoint: str | None) -> None:
        record_browserless_exception(
            source=source,
            scope=scope or "",
            method=method,
            endpoint=endpoint or "unknown",
            url=url,
        )

    def _budget_exhausted_error(self, scope: str) -> BrowserlessEgressBudgetExhausted:
        return BrowserlessEgressBudgetExhausted("Browserless egress budget exhausted")


_browserless_client = BrowserlessClient()


def browserless_request(
    method: str,
    url: str,
    *,
    token: str,
    source: str,
    endpoint: str,
    priority: Priority = Priority.NORMAL,
    timeout: float | tuple[float, float] | None = None,
    session: requests.Session | None = None,
    **kwargs: Any,
) -> requests.Response:
    """One Browserless call, gated against the fleet's budget and recorded.

    The token stays in `url`'s query string, which is where Browserless wants it: its REST routes
    do not accept an `Authorization` header. It is passed separately as well so the fleet can be
    fingerprinted without parsing it back out of the url.

    `priority` is the lever that matters here. Every caller draws on one budget per fleet, so a
    background consumer should ask as `BATCH` and be shed first, leaving the headroom for work
    somebody is waiting on. Raises `BrowserlessEgressBudgetExhausted` when the fleet's budget is
    spent; the limiter does not block, so backing off is the caller's job.
    """
    return _browserless_client.request(
        method,
        url,
        source=source,
        scope=fleet_scope(url, token),
        priority=priority,
        endpoint=endpoint,
        timeout=timeout,
        session=session,
        **kwargs,
    )
