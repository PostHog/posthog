"""logo.dev incarnation of the egress transport.

``logodev_request`` is the one way to call logo.dev from anywhere in the codebase: it gates on the
instance's shared account budget and records telemetry by construction. The caller owns auth —
logo.dev takes the token as a ``token`` query parameter, so pass it via ``params``.
"""

from typing import Any

import requests

from posthog.egress.limiter.policies import Priority
from posthog.egress.logodev.limiter import consume_logodev_sync
from posthog.egress.logodev.observability import record_logodev_api_exception, record_logodev_api_response
from posthog.egress.transport.transport import EgressBudgetExhausted, EgressClient

# The whole instance shares one logo.dev account, so every call carries the same scope.
_ACCOUNT_SCOPE = "default"


class LogoDevEgressBudgetExhausted(EgressBudgetExhausted):
    """A sheddable (BATCH/NORMAL) logo.dev call was shed by our egress limiter before it was sent.
    Callers that can degrade (e.g. an icon search returning no results) catch this and do so."""


class LogoDevClient(EgressClient):
    """The logo.dev incarnation of :class:`EgressClient`. Stateless — one shared instance serves
    every caller; wire it through :func:`logodev_request`."""

    def _standard_headers(self) -> dict[str, str]:
        return {}

    def _consume(self, scope: str, priority: Priority, source: str, url: str) -> bool:
        return consume_logodev_sync(priority=priority, source=source)

    def _record_response(
        self, response: requests.Response, *, source: str, scope: str | None, method: str, endpoint: str | None
    ) -> None:
        record_logodev_api_response(response, source=source, method=method, endpoint=endpoint)

    def _record_exception(self, *, source: str, scope: str | None, method: str, url: str, endpoint: str | None) -> None:
        record_logodev_api_exception(source=source, method=method, url=url, endpoint=endpoint)

    def _budget_exhausted_error(self, scope: str) -> LogoDevEgressBudgetExhausted:
        return LogoDevEgressBudgetExhausted("logo.dev egress budget exhausted; degrading")


# Stateless — one shared instance for the whole process.
_logodev_client = LogoDevClient()


def logodev_request(
    method: str,
    url: str,
    *,
    source: str,
    priority: Priority = Priority.CRITICAL,
    endpoint: str | None = None,
    timeout: float | tuple[float, float] | None = None,
    **kwargs: Any,
) -> requests.Response:
    """Make a gated, recorded logo.dev request. ``source`` attributes the call to a subsystem; pass
    the account token via ``params`` (logo.dev's auth is a query parameter, not a header)."""
    return _logodev_client.request(
        method,
        url,
        source=source,
        scope=_ACCOUNT_SCOPE,
        priority=priority,
        endpoint=endpoint,
        timeout=timeout,
        **kwargs,
    )
