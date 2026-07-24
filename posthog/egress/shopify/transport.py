"""Shopify incarnation of the egress transport.

``shopify_request`` is the one way to call Shopify from anywhere in the codebase: it gates on the
instance's shared store budget and records telemetry by construction. The caller owns auth — pass the
Admin API token via the ``X-Shopify-Access-Token`` header in ``headers``.
"""

from typing import Any

import requests

from posthog.egress.limiter.policies import Priority
from posthog.egress.shopify.limiter import consume_shopify_sync
from posthog.egress.shopify.observability import record_shopify_api_exception, record_shopify_api_response
from posthog.egress.transport.transport import EgressBudgetExhausted, EgressClient

# The whole instance shares one Shopify store, so every call carries the same scope.
_STORE_SCOPE = "default"


class ShopifyEgressBudgetExhausted(EgressBudgetExhausted):
    """A Shopify call was shed by our egress limiter before it was sent (budget spent)."""


class ShopifyClient(EgressClient):
    """The Shopify incarnation of :class:`EgressClient`. Stateless — one shared instance serves every
    caller; wire it through :func:`shopify_request`."""

    def _standard_headers(self) -> dict[str, str]:
        return {}

    def _consume(self, scope: str, priority: Priority, source: str, url: str) -> bool:
        return consume_shopify_sync(priority=priority, source=source)

    def _record_response(
        self, response: requests.Response, *, source: str, scope: str | None, method: str, endpoint: str | None
    ) -> None:
        record_shopify_api_response(response, source=source, method=method, endpoint=endpoint)

    def _record_exception(self, *, source: str, scope: str | None, method: str, url: str, endpoint: str | None) -> None:
        record_shopify_api_exception(source=source, method=method, url=url, endpoint=endpoint)

    def _budget_exhausted_error(self, scope: str) -> ShopifyEgressBudgetExhausted:
        return ShopifyEgressBudgetExhausted("Shopify egress budget exhausted")


# Stateless — one shared instance for the whole process.
_shopify_client = ShopifyClient()


def shopify_request(
    method: str,
    url: str,
    *,
    source: str,
    priority: Priority = Priority.CRITICAL,
    endpoint: str | None = None,
    timeout: float | tuple[float, float] | None = None,
    **kwargs: Any,
) -> requests.Response:
    """Make a gated, recorded Shopify request. ``source`` attributes the call to a subsystem; pass the
    Admin API token via ``headers={"X-Shopify-Access-Token": ...}``."""
    return _shopify_client.request(
        method,
        url,
        source=source,
        scope=_STORE_SCOPE,
        priority=priority,
        endpoint=endpoint,
        timeout=timeout,
        **kwargs,
    )
