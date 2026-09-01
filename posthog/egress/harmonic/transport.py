"""Harmonic incarnation of the egress transport — async, since the Harmonic client is aiohttp-based
(``ee/billing/salesforce_enrichment/harmonic_client.py``). It subclasses
:class:`posthog.egress.transport.transport.AsyncEgressClient`, the aiohttp counterpart to the
``EgressClient`` base the sync domains (github, logo.dev, Firecrawl, Vapi) use.
"""

from typing import Any

import aiohttp

from posthog.egress.harmonic.limiter import acquire_harmonic
from posthog.egress.harmonic.observability import record_harmonic_api_exception, record_harmonic_api_response
from posthog.egress.limiter.policies import Priority
from posthog.egress.transport.transport import AsyncEgressClient, EgressBudgetExhausted

# Harmonic bills one account-wide budget, so every call carries the same scope. AsyncEgressClient
# skips its gate entirely on a falsy scope, and Harmonic has no per-caller identity to gate on
# instead, so this constant is what keeps every Harmonic call gated.
_GLOBAL_SCOPE = "global"


class HarmonicEgressBudgetExhausted(EgressBudgetExhausted):
    """A sheddable (BATCH/NORMAL) Harmonic call was shed by our egress limiter before it was ever
    sent — it is raised before the request reaches Harmonic, so it is never an
    aiohttp.ClientResponseError from Harmonic's own response. Callers that can degrade should catch
    this and back off; CRITICAL calls are never raised on, they proceed and let Harmonic's own rate
    limiting be the backstop.

    This is a transient operational condition, not evidence a company is missing. A caller that
    folds every exception into an enrichment miss (e.g. returning None on ``except Exception``)
    must catch this one first and re-raise or retry, or a throttled request gets permanently
    recorded as a Harmonic not-found."""


class HarmonicClient(AsyncEgressClient):
    """The Harmonic incarnation of :class:`AsyncEgressClient`. Stateless; the caller supplies its
    own ``aiohttp.ClientSession`` (``AsyncHarmonicClient`` already manages one via ``async with``,
    matching aiohttp's recommended session-reuse pattern rather than one session per call)."""

    def _standard_headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json"}

    async def _consume(self, scope: str, priority: Priority, source: str, url: str) -> bool:
        return await acquire_harmonic(priority, source)

    def _record_response(
        self, response: aiohttp.ClientResponse, *, source: str, scope: str | None, method: str, endpoint: str | None
    ) -> None:
        record_harmonic_api_response(response.status, response.headers, source=source, method=method, endpoint=endpoint)

    def _record_exception(self, *, source: str, scope: str | None, method: str, url: str, endpoint: str | None) -> None:
        record_harmonic_api_exception(source=source, method=method, endpoint=endpoint)

    def _budget_exhausted_error(self, scope: str) -> HarmonicEgressBudgetExhausted:
        return HarmonicEgressBudgetExhausted("Harmonic egress budget exhausted; degrading")


_harmonic_client = HarmonicClient()


async def harmonic_request(
    session: aiohttp.ClientSession,
    method: str,
    url: str,
    *,
    source: str,
    priority: Priority = Priority.CRITICAL,
    endpoint: str | None = None,
    headers: dict[str, str] | None = None,
    **kwargs: Any,
) -> aiohttp.ClientResponse:
    """Make a gated, recorded Harmonic request on an existing session. ``source`` attributes the
    call to a subsystem; callers own auth (the ``apikey`` header, never a URL query param — a
    URL-borne key leaks into aiohttp exception telemetry)."""
    return await _harmonic_client.request(
        session,
        method,
        url,
        source=source,
        scope=_GLOBAL_SCOPE,
        priority=priority,
        endpoint=endpoint,
        headers=headers,
        **kwargs,
    )
