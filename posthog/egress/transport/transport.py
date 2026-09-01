"""Generic outbound egress transport — the third egress lane, composing the limiter and observability.

An :class:`EgressClient` makes an outbound HTTP request that is *gated* (against the shared per-owner
budget) and *recorded* (request volume + the API's rate-limit headers) by construction, so no caller
can make a request that bypasses either. The gate→request→record algorithm and the priority-based
denial semantics are domain-agnostic and live here; each third-party API subclasses and fills the
domain hooks (standard headers, the limiter gate, the recorders, the endpoint normaliser, the
budget-exhausted exception). GitHub is the first incarnation — see :mod:`posthog.egress.github.transport`.

:class:`AsyncEgressClient` is the same algorithm for an aiohttp-based domain (Harmonic is the first —
see :mod:`posthog.egress.harmonic.transport`): ``request``/``_consume`` are coroutines and the transport
returns/catches aiohttp's types instead of ``requests``'. The two bases share the priority-based denial
rule via :func:`_raise_if_denied` rather than each encoding it themselves.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

import aiohttp
import requests

from posthog.egress.limiter.policies import Priority


class EgressBudgetExhausted(Exception):
    """A *sheddable* (non-CRITICAL) outbound call was denied by the egress limiter before it was sent.
    Callers that can defer should catch this and back off/retry — it means our own shared budget is
    spent, not that the third-party API returned an error. CRITICAL calls are never raised on; they
    proceed and let the API's own rate limiting be the backstop."""


def _raise_if_denied(granted: bool, priority: Priority, make_error: Callable[[], EgressBudgetExhausted]) -> None:
    # CRITICAL never blocks: it records the decision (and consumes if there's room) but proceeds
    # regardless, so a user-facing call is never shed by us — the API's own 429 is the backstop.
    # Sheddable lanes back off so their headroom is left for higher-priority traffic. Shared by both
    # the sync and async gate so the rule can't drift between the two.
    if not granted and priority is not Priority.CRITICAL:
        raise make_error()


class EgressClient(ABC):
    """One outbound API's transport: gate → request → record, with priority-based denial semantics.

    The algorithm is fixed here; subclasses supply the domain hooks. ``scope`` is the shared budget
    owner's id in the API's own namespace (e.g. a GitHub App installation id); ``None`` means the
    caller is identity-blind (a raw token with no shared budget), which skips the gate and records
    request volume only.
    """

    def request(
        self,
        method: str,
        url: str,
        *,
        source: str,
        headers: dict[str, str] | None = None,
        scope: str | None = None,
        priority: Priority = Priority.CRITICAL,
        endpoint: str | None = None,
        timeout: float | tuple[float, float] | None = None,
        session: requests.Session | None = None,
        **kwargs: Any,
    ) -> requests.Response:
        self._gate(scope, source, priority, url)

        request_headers = {**self._standard_headers(), **(headers or {})}
        sender = session or requests
        try:
            response = sender.request(method, url, headers=request_headers, timeout=timeout, **kwargs)
        except requests.RequestException:
            # Best-effort telemetry must never mask the real transport error — record and re-raise it.
            self._record_exception(source=source, scope=scope, method=method, url=url, endpoint=endpoint)
            raise

        self._record_response(response, source=source, scope=scope, method=method, endpoint=endpoint)
        return response

    def _gate(self, scope: str | None, source: str, priority: Priority, url: str) -> None:
        # Identity-blind callers have no shared budget to draw on — record volume only, never gate.
        # An empty scope is no identity either: gating on it would key a phantom budget/metric series.
        if not scope:
            return
        granted = self._consume(scope, priority, source, url)
        _raise_if_denied(granted, priority, lambda: self._budget_exhausted_error(scope))

    # --- domain hooks -------------------------------------------------------------------------------

    @abstractmethod
    def _standard_headers(self) -> dict[str, str]:
        """Default headers merged under the caller's (the caller's win) — e.g. Accept, API version."""

    @abstractmethod
    def _consume(self, scope: str, priority: Priority, source: str, url: str) -> bool:
        """Draw ``1`` from the domain's shared budget for ``scope`` at ``priority``; True if granted.
        ``url`` lets a domain route the draw to the resource-specific meter GitHub bills the URL to."""

    @abstractmethod
    def _record_response(
        self, response: requests.Response, *, source: str, scope: str | None, method: str, endpoint: str | None
    ) -> None:
        """Record a returned response (volume + the API's rate-limit headers) via the domain's recorder."""

    @abstractmethod
    def _record_exception(self, *, source: str, scope: str | None, method: str, url: str, endpoint: str | None) -> None:
        """Record a request that raised before returning a response (timeout, connection error)."""

    @abstractmethod
    def _budget_exhausted_error(self, scope: str) -> EgressBudgetExhausted:
        """The domain-specific exception raised when a sheddable call is denied (a subclass of
        :class:`EgressBudgetExhausted`)."""


class AsyncEgressClient(ABC):
    """The aiohttp counterpart to :class:`EgressClient`, for a domain whose client is async (Harmonic
    is the first — see :mod:`posthog.egress.harmonic.transport`). Same gate → request → record
    algorithm, same domain hooks, and the same ``scope``/priority semantics; only the transport is
    async and speaks aiohttp's types instead of ``requests``'.
    """

    async def request(
        self,
        session: aiohttp.ClientSession,
        method: str,
        url: str,
        *,
        source: str,
        headers: dict[str, str] | None = None,
        scope: str | None = None,
        priority: Priority = Priority.CRITICAL,
        endpoint: str | None = None,
        **kwargs: Any,
    ) -> aiohttp.ClientResponse:
        await self._gate(scope, source, priority, url)

        request_headers = {**self._standard_headers(), **(headers or {})}
        try:
            response = await session.request(method, url, headers=request_headers, **kwargs)
        except aiohttp.ClientError:
            # Best-effort telemetry must never mask the real transport error — record and re-raise it.
            self._record_exception(source=source, scope=scope, method=method, url=url, endpoint=endpoint)
            raise

        self._record_response(response, source=source, scope=scope, method=method, endpoint=endpoint)
        return response

    async def _gate(self, scope: str | None, source: str, priority: Priority, url: str) -> None:
        # Identity-blind callers have no shared budget to draw on — record volume only, never gate.
        # An empty scope is no identity either: gating on it would key a phantom budget/metric series.
        if not scope:
            return
        granted = await self._consume(scope, priority, source, url)
        _raise_if_denied(granted, priority, lambda: self._budget_exhausted_error(scope))

    # --- domain hooks -------------------------------------------------------------------------------

    @abstractmethod
    def _standard_headers(self) -> dict[str, str]:
        """Default headers merged under the caller's (the caller's win) — e.g. Content-Type."""

    @abstractmethod
    async def _consume(self, scope: str, priority: Priority, source: str, url: str) -> bool:
        """Draw ``1`` from the domain's shared budget for ``scope`` at ``priority``; True if granted."""

    @abstractmethod
    def _record_response(
        self, response: aiohttp.ClientResponse, *, source: str, scope: str | None, method: str, endpoint: str | None
    ) -> None:
        """Record a returned response (volume + the API's rate-limit headers) via the domain's recorder."""

    @abstractmethod
    def _record_exception(self, *, source: str, scope: str | None, method: str, url: str, endpoint: str | None) -> None:
        """Record a request that raised before returning a response (timeout, connection error)."""

    @abstractmethod
    def _budget_exhausted_error(self, scope: str) -> EgressBudgetExhausted:
        """The domain-specific exception raised when a sheddable call is denied (a subclass of
        :class:`EgressBudgetExhausted`)."""
