"""WorkOS Radar incarnation of the egress transport.

``workos_radar_request`` is the one way to call the WorkOS Radar API: it gates on the instance's
shared Radar budget and records telemetry by construction. It stays token-agnostic like the other
incarnations, so the caller owns where the API key comes from.
"""

import requests

from posthog.egress.limiter.policies import Priority
from posthog.egress.transport.transport import EgressBudgetExhausted, EgressClient
from posthog.egress.workos_radar.limiter import API_KEY_SCOPE_ID, consume_workos_radar_sync
from posthog.egress.workos_radar.observability import workos_radar_egress


class WorkosRadarEgressBudgetExhausted(EgressBudgetExhausted):
    """Our egress limiter shed a Radar call before it was sent."""


class WorkosRadarClient(EgressClient):
    """The WorkOS Radar incarnation of :class:`EgressClient`. Stateless, so one shared instance
    serves every caller; wire it through :func:`workos_radar_request`."""

    observability = workos_radar_egress
    egress_domain = "workos_radar"

    def _standard_headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json"}

    def _consume(self, scope: str, priority: Priority, source: str, url: str) -> bool:
        return consume_workos_radar_sync(priority=priority, source=source)

    def _budget_exhausted_error(self, scope: str) -> WorkosRadarEgressBudgetExhausted:
        return WorkosRadarEgressBudgetExhausted("WorkOS Radar egress budget exhausted", scope=scope)


_workos_radar_client = WorkosRadarClient()


def workos_radar_request(
    method: str,
    url: str,
    *,
    api_key: str,
    source: str,
    endpoint: str,
    priority: Priority,
    timeout: float,
    json: dict[str, str],
) -> requests.Response:
    """Make a gated, recorded Radar request. ``source`` attributes the call to a flow.

    There is no default lane. A check that a person waits on passes ``NORMAL``, and a report that
    can go later passes ``BATCH``. Nothing runs ``CRITICAL``, because every call carries an address
    that someone typed, and a lane that is never shed would let a flood of them spend the budget.
    """
    return _workos_radar_client.request(
        method,
        url,
        source=source,
        headers={"Authorization": f"Bearer {api_key}"},
        scope=API_KEY_SCOPE_ID,
        priority=priority,
        endpoint=endpoint,
        timeout=timeout,
        json=json,
    )
