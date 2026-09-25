"""TypeSafe incarnation of the egress transport.

``typesafe_request`` is the one way to call TypeSafe from anywhere in the codebase: it gates on the
instance's shared account budget and records telemetry by construction. It stays token-agnostic
like the other incarnations, so the caller owns where the API key comes from:
:mod:`posthog.egress.typesafe.client` reads it from settings.
"""

from typing import Any

import requests

from posthog.egress.limiter.policies import Priority
from posthog.egress.transport.transport import EgressBudgetExhausted, EgressClient
from posthog.egress.typesafe.limiter import ACCOUNT_SCOPE_ID, consume_typesafe_sync
from posthog.egress.typesafe.observability import typesafe_egress


class TypeSafeEgressBudgetExhausted(EgressBudgetExhausted):
    """A sheddable (BATCH/NORMAL) TypeSafe call was shed by our egress limiter before it was sent.
    Callers degrade by skipping the judgment or deferring it to a later run."""


class TypeSafeClient(EgressClient):
    """The TypeSafe incarnation of :class:`EgressClient`. Stateless, so one shared instance serves
    every caller; wire it through :func:`typesafe_request`."""

    observability = typesafe_egress

    def _standard_headers(self) -> dict[str, str]:
        return {"Accept": "application/json", "Content-Type": "application/json"}

    def _consume(self, scope: str, priority: Priority, source: str, url: str) -> bool:
        return consume_typesafe_sync(priority=priority, source=source)

    def _budget_exhausted_error(self, scope: str) -> TypeSafeEgressBudgetExhausted:
        return TypeSafeEgressBudgetExhausted("TypeSafe egress budget exhausted; degrading", scope=scope)


_typesafe_client = TypeSafeClient()

# A connection that will not open is never worth waiting on. A caller where a person waits for the
# answer passes a shorter read timeout.
DEFAULT_TIMEOUT: tuple[float, float] = (3.0, 15.0)


def typesafe_request(
    method: str,
    url: str,
    *,
    api_key: str,
    source: str,
    endpoint: str,
    priority: Priority = Priority.NORMAL,
    timeout: float | tuple[float, float] = DEFAULT_TIMEOUT,
    **kwargs: Any,
) -> requests.Response:
    """Make a gated, recorded TypeSafe request. ``source`` attributes the call to a subsystem.

    Every call is sheddable: the state sent to TypeSafe is derived from user input, and every caller
    can do without the judgment. A CRITICAL call is never shed, so it would skip the hourly ceiling,
    which is the only cap on per-token spend. This function rejects CRITICAL for that reason.
    """
    if priority is Priority.CRITICAL:
        raise ValueError("TypeSafe calls must be sheddable, so use NORMAL or BATCH")
    return _typesafe_client.request(
        method,
        url,
        source=source,
        headers={"Authorization": f"Bearer {api_key}"},
        scope=ACCOUNT_SCOPE_ID,
        priority=priority,
        endpoint=endpoint,
        timeout=timeout,
        **kwargs,
    )
