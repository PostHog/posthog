"""Firecrawl incarnation of the egress transport.

``firecrawl_request`` is the one way to call Firecrawl from anywhere in the codebase: it gates on
the instance's shared account budget and records telemetry by construction. It stays token-agnostic
like the other incarnations, so the caller owns where the API key comes from:
:mod:`posthog.egress.firecrawl.client` reads it from settings.
"""

from typing import Any

import requests

from posthog.egress.firecrawl.limiter import consume_firecrawl_sync
from posthog.egress.firecrawl.observability import record_firecrawl_api_exception, record_firecrawl_api_response
from posthog.egress.limiter.policies import Priority
from posthog.egress.transport.transport import EgressBudgetExhausted, EgressClient

# The whole instance shares one Firecrawl account, so every call carries the same scope.
_ACCOUNT_SCOPE = "default"


class FirecrawlEgressBudgetExhausted(EgressBudgetExhausted):
    """A sheddable (BATCH/NORMAL) Firecrawl call was shed by our egress limiter before it was sent.
    Callers that can degrade (e.g. opening a session without scraped company context) catch this."""


class FirecrawlClient(EgressClient):
    """The Firecrawl incarnation of :class:`EgressClient`. Stateless, so one shared instance serves
    every caller; wire it through :func:`firecrawl_request`."""

    def _standard_headers(self) -> dict[str, str]:
        return {"Accept": "application/json", "Content-Type": "application/json"}

    def _consume(self, scope: str, priority: Priority, source: str, url: str) -> bool:
        return consume_firecrawl_sync(priority=priority, source=source)

    def _record_response(
        self, response: requests.Response, *, source: str, scope: str | None, method: str, endpoint: str | None
    ) -> None:
        record_firecrawl_api_response(response, source=source, method=method, endpoint=endpoint)

    def _record_exception(self, *, source: str, scope: str | None, method: str, url: str, endpoint: str | None) -> None:
        record_firecrawl_api_exception(source=source, method=method, url=url, endpoint=endpoint)

    def _budget_exhausted_error(self, scope: str) -> FirecrawlEgressBudgetExhausted:
        return FirecrawlEgressBudgetExhausted("Firecrawl egress budget exhausted; degrading")


# Stateless, so one shared instance serves the whole process.
_firecrawl_client = FirecrawlClient()


def firecrawl_request(
    method: str,
    url: str,
    *,
    api_key: str,
    source: str,
    endpoint: str,
    priority: Priority = Priority.NORMAL,
    timeout: float | tuple[float, float] | None = None,
    **kwargs: Any,
) -> requests.Response:
    """Make a gated, recorded Firecrawl request. ``source`` attributes the call to a subsystem.

    The default lane is sheddable: what we scrape is derived from user-supplied input, and every
    caller so far can do without the scrape, so Firecrawl traffic must not be able to consume the
    whole budget the way a CRITICAL lane would.
    """
    return _firecrawl_client.request(
        method,
        url,
        source=source,
        headers={"Authorization": f"Bearer {api_key}"},
        scope=_ACCOUNT_SCOPE,
        priority=priority,
        endpoint=endpoint,
        timeout=timeout,
        **kwargs,
    )
