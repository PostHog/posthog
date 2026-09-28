"""Generic outbound egress transport — the third egress lane, composing the limiter and observability.

An :class:`EgressClient` makes an outbound HTTP request that is *gated* (against the shared per-owner
budget) and *recorded* (request volume + the API's rate-limit headers) by construction, so no caller
can make a request that bypasses either. The gate→request→record algorithm and the priority-based
denial semantics are domain-agnostic and live here; each third-party API subclasses, points
``observability`` at its metric set, and fills the gate hooks (the limiter draw and the
budget-exhausted exception). See :mod:`posthog.egress.github.transport` for the reference domain.

:class:`RecordedEgressClient` is the same transport without the gate, for an API PostHog observes but
does not budget, because the API publishes no request limit that a rate budget can model.

:class:`AsyncEgressClient` is the gated algorithm for an aiohttp-based domain (see
:mod:`posthog.egress.harmonic.transport`): ``request``/``_consume`` are coroutines and the transport
returns/catches aiohttp's types instead of ``requests``'. The sync and async bases share the
priority-based denial rule via :func:`_raise_if_denied` rather than each encoding it themselves.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import requests

# aiohttp is only needed by AsyncEgressClient, and the sync domains import this module during
# django.setup(). A module-level import would put aiohttp on the startup path of every process.
if TYPE_CHECKING:
    import aiohttp

from posthog.egress.limiter.policies import Priority
from posthog.egress.observability.observability import EgressObservability


class EgressBudgetExhausted(Exception):
    """A *sheddable* (non-CRITICAL) outbound call was denied by the egress limiter before it was sent.
    Callers that can defer should catch this and back off/retry — it means our own shared budget is
    spent, not that the third-party API returned an error. CRITICAL calls are never raised on; they
    proceed and let the API's own rate limiting be the backstop.

    ``scope`` is the budget key that was denied (a GitHub installation id, say). It rides on the
    exception because this is *our* budget: unlike a third-party 429, the limiter can say how long
    until it frees, and a caller that wants to wait for it needs the key to ask. Subclasses that
    name the scope in their message should pass it here too rather than leaving callers to parse
    it back out."""

    def __init__(self, message: str = "", *, scope: str | None = None) -> None:
        # Defaulted so this stays a pure addition: before ``scope`` existed this was a bare
        # Exception, and callers that raise it as a marker construct it with no arguments.
        super().__init__(message)
        self.scope = scope


def _raise_if_denied(granted: bool, priority: Priority, make_error: Callable[[], EgressBudgetExhausted]) -> None:
    # CRITICAL never blocks: it records the decision (and consumes if there's room) but proceeds
    # regardless, so a user-facing call is never shed by us — the API's own 429 is the backstop.
    # Sheddable lanes back off so their headroom is left for higher-priority traffic. Shared by both
    # the sync and async gate so the rule can't drift between the two.
    if not granted and priority is not Priority.CRITICAL:
        raise make_error()


class _EgressHooks:
    """The hooks every transport shares, sync or async. Subclasses set ``observability``."""

    observability: EgressObservability

    def _standard_headers(self) -> dict[str, str]:
        """Default headers merged under the caller's (the caller's win) — e.g. Accept, API version."""
        return {}

    def _record_exception(self, *, source: str, scope: str | None, method: str, url: str, endpoint: str | None) -> None:
        """Record a request that raised before returning a response (timeout, connection error)."""
        self.observability.record_exception(source=source, scope=scope, method=method, endpoint=endpoint, url=url)


class RecordedEgressClient(_EgressHooks):
    """One outbound API's transport without a budget: request → record.

    Subclasses set ``observability`` and may override the headers or the recorders. ``scope`` is the
    metric identity in the API's own namespace; ``None`` records request volume without the gauges.
    """

    def request(
        self,
        method: str,
        url: str,
        *,
        source: str,
        headers: dict[str, str] | None = None,
        scope: str | None = None,
        endpoint: str | None = None,
        timeout: float | tuple[float, float] | None = None,
        session: requests.Session | None = None,
        **kwargs: Any,
    ) -> requests.Response:
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

    def _record_response(
        self, response: requests.Response, *, source: str, scope: str | None, method: str, endpoint: str | None
    ) -> None:
        """Record a returned response (volume + the API's rate-limit headers)."""
        self.observability.record_requests_response(
            response, source=source, scope=scope, method=method, endpoint=endpoint
        )


class EgressClient(RecordedEgressClient, ABC):
    """One outbound API's transport: gate → request → record, with priority-based denial semantics.

    The algorithm is fixed here; subclasses supply the gate hooks. ``scope`` is the shared budget
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
        return super().request(
            method,
            url,
            source=source,
            headers=headers,
            scope=scope,
            endpoint=endpoint,
            timeout=timeout,
            session=session,
            **kwargs,
        )

    def _gate(self, scope: str | None, source: str, priority: Priority, url: str) -> None:
        # Identity-blind callers have no shared budget to draw on — record volume only, never gate.
        # An empty scope is no identity either: gating on it would key a phantom budget/metric series.
        if not scope:
            return
        granted = self._consume(scope, priority, source, url)
        _raise_if_denied(granted, priority, lambda: self._budget_exhausted_error(scope))

    # --- gate hooks ---------------------------------------------------------------------------------

    @abstractmethod
    def _consume(self, scope: str, priority: Priority, source: str, url: str) -> bool:
        """Draw ``1`` from the domain's shared budget for ``scope`` at ``priority``; True if granted.
        ``url`` lets a domain route the draw to the resource-specific meter GitHub bills the URL to."""

    @abstractmethod
    def _budget_exhausted_error(self, scope: str) -> EgressBudgetExhausted:
        """The domain-specific exception raised when a sheddable call is denied (a subclass of
        :class:`EgressBudgetExhausted`)."""


class AsyncEgressClient(_EgressHooks, ABC):
    """The aiohttp counterpart to :class:`EgressClient`, for a domain whose client is async (see
    :mod:`posthog.egress.harmonic.transport`). Same gate → request → record algorithm, same hooks,
    and the same ``scope``/priority semantics; only the transport is async and speaks aiohttp's types
    instead of ``requests``'.
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
        import aiohttp  # noqa: PLC0415

        await self._gate(scope, source, priority, url)

        request_headers = {**self._standard_headers(), **(headers or {})}
        try:
            response = await session.request(method, url, headers=request_headers, **kwargs)
        except (aiohttp.ClientError, TimeoutError):
            # aiohttp raises a bare TimeoutError when ClientTimeout.total expires; only the connect
            # phase gets wrapped into a ClientError. Catching just ClientError would drop the most
            # likely outage from the metric.
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

    def _record_response(
        self, response: aiohttp.ClientResponse, *, source: str, scope: str | None, method: str, endpoint: str | None
    ) -> None:
        """Record a returned response (volume + the API's rate-limit headers)."""
        self.observability.record_response(
            response.status, response.headers, source=source, scope=scope, method=method, endpoint=endpoint
        )

    # --- gate hooks ---------------------------------------------------------------------------------

    @abstractmethod
    async def _consume(self, scope: str, priority: Priority, source: str, url: str) -> bool:
        """Draw ``1`` from the domain's shared budget for ``scope`` at ``priority``; True if granted."""

    @abstractmethod
    def _budget_exhausted_error(self, scope: str) -> EgressBudgetExhausted:
        """The domain-specific exception raised when a sheddable call is denied (a subclass of
        :class:`EgressBudgetExhausted`)."""
