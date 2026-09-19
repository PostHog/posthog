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


class TypesafeEgressBudgetExhausted(EgressBudgetExhausted):
    """A sheddable (BATCH/NORMAL) TypeSafe call was shed by our egress limiter before it was sent.
    Callers degrade by leaving the field for the person to fill in."""


class TypesafeClient(EgressClient):
    """The TypeSafe incarnation of :class:`EgressClient`. Stateless, so one shared instance serves
    every caller; wire it through :func:`typesafe_request`."""

    observability = typesafe_egress

    def _standard_headers(self) -> dict[str, str]:
        return {"Accept": "application/json", "Content-Type": "application/json"}

    def _consume(self, scope: str, priority: Priority, source: str, url: str) -> bool:
        return consume_typesafe_sync(priority=priority, source=source)

    def _budget_exhausted_error(self, scope: str) -> TypesafeEgressBudgetExhausted:
        return TypesafeEgressBudgetExhausted("TypeSafe egress budget exhausted; degrading")


# Stateless, so one shared instance serves the whole process.
_typesafe_client = TypesafeClient()


def typesafe_request(
    method: str,
    url: str,
    *,
    api_key: str,
    source: str,
    endpoint: str,
    priority: Priority = Priority.NORMAL,
    timeout: float | tuple[float, float] | None = None,
    **kwargs: Any,
) -> requests.Response:
    """Make a gated, recorded TypeSafe request. ``source`` attributes the call to a subsystem.

    The default lane is sheddable: the state Jev classifies is user-supplied text, and every caller
    can do without the answer, so TypeSafe traffic must not be able to consume the whole budget the
    way a CRITICAL lane would.
    """
    # The whole instance shares one TypeSafe API key, so every call carries the same scope.
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
