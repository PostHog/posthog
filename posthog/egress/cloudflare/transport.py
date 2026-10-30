"""Cloudflare incarnation of the egress transport.

``cloudflare_request`` is the one way to call the Cloudflare API: it gates on the instance's shared
budget and records telemetry by construction. It stays token-agnostic, so the caller owns where the
API token comes from.
"""

from typing import Any

import requests

from posthog.egress.cloudflare.limiter import ACCOUNT_SCOPE_ID, consume_cloudflare_sync
from posthog.egress.cloudflare.observability import cloudflare_egress
from posthog.egress.limiter.policies import Priority
from posthog.egress.transport.transport import EgressBudgetExhausted, EgressClient


class CloudflareEgressBudgetExhausted(EgressBudgetExhausted):
    """A sheddable (BATCH/NORMAL) Cloudflare call was shed by our egress limiter before it was sent."""


class CloudflareClient(EgressClient):
    """The Cloudflare incarnation of :class:`EgressClient`. Stateless, so one shared instance serves
    every caller; wire it through :func:`cloudflare_request`."""

    observability = cloudflare_egress
    egress_domain = "cloudflare"

    def _standard_headers(self) -> dict[str, str]:
        return {"Accept": "application/json", "Content-Type": "application/json"}

    def _consume(self, scope: str, priority: Priority, source: str, url: str) -> bool:
        return consume_cloudflare_sync(priority=priority, source=source)

    def _budget_exhausted_error(self, scope: str) -> CloudflareEgressBudgetExhausted:
        return CloudflareEgressBudgetExhausted("Cloudflare egress budget exhausted; degrading")


_cloudflare_client = CloudflareClient()


def cloudflare_request(
    method: str,
    url: str,
    *,
    api_token: str,
    source: str,
    endpoint: str,
    priority: Priority = Priority.NORMAL,
    timeout: float | tuple[float, float] | None = None,
    **kwargs: Any,
) -> requests.Response:
    """Make a gated, recorded Cloudflare request. ``source`` attributes the call to a subsystem.

    ``endpoint`` is the path template, such as ``/zones/{zone_id}/purge_cache``, so the zone id stays
    out of metric labels.
    """
    return _cloudflare_client.request(
        method,
        url,
        source=source,
        headers={"Authorization": f"Bearer {api_token}"},
        scope=ACCOUNT_SCOPE_ID,
        priority=priority,
        endpoint=endpoint,
        timeout=timeout,
        **kwargs,
    )
