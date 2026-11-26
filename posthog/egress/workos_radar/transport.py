"""WorkOS Radar incarnation of the egress transport.

``workos_radar_check`` sends a login or signup check and records it. ``workos_radar_report`` sends a
success report against the report budget and records it. Both stay token-agnostic like the other
incarnations, so the caller owns where the API key comes from.
"""

import requests

from posthog.egress.limiter.policies import Priority
from posthog.egress.transport.transport import EgressBudgetExhausted, EgressClient, RecordedEgressClient
from posthog.egress.workos_radar.limiter import API_KEY_SCOPE_ID, consume_workos_radar_report_sync
from posthog.egress.workos_radar.observability import workos_radar_egress


class WorkosRadarEgressBudgetExhausted(EgressBudgetExhausted):
    """Our egress limiter shed a success report before it was sent."""


class WorkosRadarCheckClient(RecordedEgressClient):
    """Records the checks without a gate, so the login path never waits on the limiter's Redis."""

    observability = workos_radar_egress
    egress_domain = "workos_radar"

    def _standard_headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json"}


class WorkosRadarReportClient(EgressClient):
    """Gates the success reports on the report budget."""

    observability = workos_radar_egress
    egress_domain = "workos_radar"

    def _standard_headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json"}

    def _consume(self, scope: str, priority: Priority, source: str, url: str) -> bool:
        return consume_workos_radar_report_sync(source=source)

    def _budget_exhausted_error(self, scope: str) -> WorkosRadarEgressBudgetExhausted:
        return WorkosRadarEgressBudgetExhausted("WorkOS Radar report budget exhausted", scope=scope)


_check_client = WorkosRadarCheckClient()
_report_client = WorkosRadarReportClient()


def workos_radar_check(
    url: str, *, api_key: str, source: str, timeout: float, json: dict[str, str]
) -> requests.Response:
    """Send a check and record it. A check is never shed, because a shed check lets the attempt through."""
    return _check_client.request(
        "POST",
        url,
        source=source,
        headers={"Authorization": f"Bearer {api_key}"},
        scope=API_KEY_SCOPE_ID,
        endpoint="attempts",
        timeout=timeout,
        json=json,
    )


def workos_radar_report(url: str, *, api_key: str, timeout: float, json: dict[str, str]) -> requests.Response:
    """Send a success report against the report budget. Raises WorkosRadarEgressBudgetExhausted when it is spent."""
    return _report_client.request(
        "PUT",
        url,
        source="success_report",
        headers={"Authorization": f"Bearer {api_key}"},
        scope=API_KEY_SCOPE_ID,
        priority=Priority.BATCH,
        endpoint="attempts/:id",
        timeout=timeout,
        json=json,
    )
