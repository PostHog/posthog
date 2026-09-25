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
from urllib.parse import urlparse

import requests
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

# aiohttp is only needed by AsyncEgressClient, and the sync domains import this module during
# django.setup(). A module-level import would put aiohttp on the startup path of every process.
if TYPE_CHECKING:
    import aiohttp

from posthog.egress.limiter.policies import Priority
from posthog.egress.observability.observability import EgressObservability

tracer = trace.get_tracer(__name__)


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


class _EgressHooks:
    """The hooks every transport shares, sync or async. Subclasses set ``observability``."""

    observability: EgressObservability
    egress_domain = "unknown"
    span_name = "egress.http.request"

    def _standard_headers(self) -> dict[str, str]:
        """Default headers merged under the caller's (the caller's win) — e.g. Accept, API version."""
        return {}

    def _record_exception(self, *, source: str, scope: str | None, method: str, url: str, endpoint: str | None) -> None:
        """Record a request that raised before returning a response (timeout, connection error)."""
        self.observability.record_exception(source=source, scope=scope, method=method, endpoint=endpoint, url=url)

    def _span_attributes(
        self,
        method: str,
        url: str,
        *,
        source: str,
        scope: str | None,
        priority: Priority,
        endpoint: str | None,
    ) -> dict[str, str | bool]:
        return {
            "http.request.method": method.upper(),
            "server.address": urlparse(url).hostname or "unknown",
            "egress.domain": self.egress_domain,
            "egress.source": source,
            "egress.priority": priority.value,
            "egress.endpoint": endpoint or self.observability.normalize_endpoint(url),
            "egress.scoped": bool(scope),
        }

    @staticmethod
    def _mark_span_exception(span: trace.Span, error: Exception) -> None:
        span.set_attribute("error.type", type(error).__name__)
        span.set_status(Status(StatusCode.ERROR))

    @staticmethod
    def _set_span_response_metadata(span: trace.Span, response_url: str | None, status_code: int | None) -> None:
        """Record response URL (after redirects) and status code to the span."""
        if isinstance(response_url, str):
            response_hostname = urlparse(response_url).hostname
            if response_hostname:
                span.set_attribute("server.address", response_hostname)
        if isinstance(status_code, int):
            span.set_attribute("http.response.status_code", status_code)
            if status_code >= 400:
                span.set_status(Status(StatusCode.ERROR))


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
        priority: Priority = Priority.CRITICAL,
        timeout: float | tuple[float, float] | None = None,
        session: requests.Session | None = None,
        **kwargs: Any,
    ) -> requests.Response:
        request_headers = {**self._standard_headers(), **(headers or {})}
        sender = session or requests
        with tracer.start_as_current_span(
            self.span_name,
            kind=trace.SpanKind.CLIENT,
            attributes=self._span_attributes(
                method, url, source=source, scope=scope, priority=priority, endpoint=endpoint
            ),
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                self._before_request(scope, source, priority, url)
                span.set_attribute("egress.admission.granted", True)
                response = sender.request(method, url, headers=request_headers, timeout=timeout, **kwargs)
            except EgressBudgetExhausted:
                span.set_attribute("egress.admission.granted", False)
                raise
            except requests.RequestException as error:
                self._mark_span_exception(span, error)
                # Best-effort telemetry must never mask the real transport error.
                self._record_exception(source=source, scope=scope, method=method, url=url, endpoint=endpoint)
                raise

            self._record_response(response, source=source, scope=scope, method=method, endpoint=endpoint)
            self._set_span_response_metadata(
                span, getattr(response, "url", None), getattr(response, "status_code", None)
            )
            return response

    def _before_request(self, scope: str | None, source: str, priority: Priority, url: str) -> None:
        pass

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
        return super().request(
            method,
            url,
            source=source,
            headers=headers,
            scope=scope,
            endpoint=endpoint,
            priority=priority,
            timeout=timeout,
            session=session,
            **kwargs,
        )

    def _before_request(self, scope: str | None, source: str, priority: Priority, url: str) -> None:
        self._gate(scope, source, priority, url)

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

        request_headers = {**self._standard_headers(), **(headers or {})}
        with tracer.start_as_current_span(
            self.span_name,
            kind=trace.SpanKind.CLIENT,
            attributes=self._span_attributes(
                method, url, source=source, scope=scope, priority=priority, endpoint=endpoint
            ),
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                await self._gate(scope, source, priority, url)
                span.set_attribute("egress.admission.granted", True)
                response = await session.request(method, url, headers=request_headers, **kwargs)
            except EgressBudgetExhausted:
                span.set_attribute("egress.admission.granted", False)
                raise
            except (aiohttp.ClientError, TimeoutError) as error:
                self._mark_span_exception(span, error)
                # aiohttp raises a bare TimeoutError when ClientTimeout.total expires; only the connect
                # phase gets wrapped into a ClientError. Catching just ClientError would drop the most
                # likely outage from the metric.
                # Best-effort telemetry must never mask the real transport error.
                self._record_exception(source=source, scope=scope, method=method, url=url, endpoint=endpoint)
                raise

            self._set_span_response_metadata(span, getattr(response, "url", None), getattr(response, "status", None))
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
