"""Harmonic incarnation of the egress transport — async, since the Harmonic client is aiohttp-based
(``ee/billing/salesforce_enrichment/harmonic_client.py``). It does not subclass
:class:`posthog.egress.transport.transport.EgressClient`: that base's gate -> request -> record
algorithm is written against ``requests.Response`` (sync, ``.status_code``), which
``aiohttp.ClientResponse`` does not share (``.status``). ``HarmonicTransport`` mirrors its hooks and
priority-based denial semantics call for call, the way :mod:`posthog.egress.logodev.transport` does
for the sync case.
"""

from typing import Any

import aiohttp

from posthog.egress.harmonic.limiter import acquire_harmonic
from posthog.egress.harmonic.observability import record_harmonic_api_exception, record_harmonic_api_response
from posthog.egress.limiter.policies import Priority
from posthog.egress.transport.transport import EgressBudgetExhausted


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


class HarmonicTransport:
    """Gated, recorded async transport for Harmonic API calls. Stateless; the caller supplies its
    own ``aiohttp.ClientSession`` (``AsyncHarmonicClient`` already manages one via ``async with``,
    matching aiohttp's recommended session-reuse pattern rather than one session per call)."""

    def _standard_headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json"}

    async def _gate(self, priority: Priority, source: str) -> None:
        granted = await acquire_harmonic(priority, source)
        if not granted and priority is not Priority.CRITICAL:
            raise HarmonicEgressBudgetExhausted("Harmonic egress budget exhausted; degrading")

    async def request(
        self,
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
        await self._gate(priority, source)

        request_headers = {**self._standard_headers(), **(headers or {})}
        try:
            response = await session.request(method, url, headers=request_headers, **kwargs)
        except aiohttp.ClientError:
            # Best-effort telemetry must never mask the real transport error — record and re-raise.
            record_harmonic_api_exception(source=source, method=method, endpoint=endpoint)
            raise

        record_harmonic_api_response(response.status, response.headers, source=source, method=method, endpoint=endpoint)
        return response


_harmonic_transport = HarmonicTransport()


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
    return await _harmonic_transport.request(
        session,
        method,
        url,
        source=source,
        priority=priority,
        endpoint=endpoint,
        headers=headers,
        **kwargs,
    )
