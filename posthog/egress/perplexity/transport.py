"""Perplexity incarnation of the egress transport.

``perplexity_request`` is the one way to call Perplexity from anywhere in the codebase: it gates on
the instance's shared account budget and records telemetry by construction. It stays token-agnostic
like the other incarnations, so the caller owns where the API key comes from.
"""

from typing import Any

import requests

from posthog.egress.limiter.policies import Priority
from posthog.egress.perplexity.limiter import ACCOUNT_SCOPE_ID, consume_perplexity_sync
from posthog.egress.perplexity.observability import perplexity_egress
from posthog.egress.transport.transport import EgressBudgetExhausted, EgressClient

PERPLEXITY_API_BASE = "https://api.perplexity.ai"
AGENT_ENDPOINT = "/v1/agent"


class PerplexityEgressBudgetExhausted(EgressBudgetExhausted):
    """A sheddable Perplexity call was shed by our egress limiter before it was sent. The caller
    records the call as failed or defers it, and never treats it as an empty answer."""


class PerplexityClient(EgressClient):
    """The Perplexity incarnation of :class:`EgressClient`. Stateless, so one shared instance serves
    every caller; wire it through :func:`perplexity_request`."""

    observability = perplexity_egress
    egress_domain = "perplexity"

    def _standard_headers(self) -> dict[str, str]:
        return {"Accept": "application/json", "Content-Type": "application/json"}

    def _consume(self, scope: str, priority: Priority, source: str, url: str) -> bool:
        return consume_perplexity_sync(priority=priority, source=source)

    def _budget_exhausted_error(self, scope: str) -> PerplexityEgressBudgetExhausted:
        return PerplexityEgressBudgetExhausted("Perplexity egress budget exhausted; degrading")


_perplexity_client = PerplexityClient()


def perplexity_request(
    method: str,
    url: str,
    *,
    api_key: str,
    source: str,
    endpoint: str,
    priority: Priority = Priority.BATCH,
    timeout: float | tuple[float, float] | None = None,
    session: requests.Session | None = None,
    **kwargs: Any,
) -> requests.Response:
    """Make a gated, recorded Perplexity request. ``source`` attributes the call to a subsystem.

    The default lane is BATCH because every caller is background work that can be deferred, and
    the prompts sent come from user-managed prompt sets, so this traffic must stay sheddable.
    """
    return _perplexity_client.request(
        method,
        url,
        source=source,
        headers={"Authorization": f"Bearer {api_key}"},
        scope=ACCOUNT_SCOPE_ID,
        priority=priority,
        endpoint=endpoint,
        timeout=timeout,
        session=session,
        **kwargs,
    )
