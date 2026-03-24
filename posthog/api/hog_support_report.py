import dataclasses
from typing import Literal, cast

import structlog
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models import Team, User
from posthog.models.proxy_record import ProxyRecord
from posthog.utils import capture_exception

logger = structlog.get_logger(__name__)

CheckStatus = Literal["ok", "warning", "info", "error", "skipped"]


@dataclasses.dataclass
class DiagnosticResult:
    id: str
    label: str
    status: CheckStatus
    value: str | None = None
    detail: str | None = None


def check_custom_api_host(team: Team) -> DiagnosticResult:
    """Check whether $lib_custom_api_host is set in the most recent 10 events."""
    query = parse_select("SELECT properties.$lib_custom_api_host FROM events ORDER BY timestamp DESC LIMIT 10")
    result = execute_hogql_query(query, team=team, query_type="hog_support_report_custom_api_host")
    rows = result.results or []
    if not rows:
        return DiagnosticResult(
            id="custom_api_host",
            label="Custom API host",
            status="skipped",
            value="No recent events",
        )
    values = [str(row[0]) for row in rows if row[0] is not None]
    if values:
        unique = list(dict.fromkeys(values))  # deduplicate, preserve order
        return DiagnosticResult(
            id="custom_api_host",
            label="Custom API host",
            status="info",
            value=", ".join(unique[:3]),
        )
    return DiagnosticResult(
        id="custom_api_host",
        label="Custom API host",
        status="ok",
        value="Not configured",
    )


def check_reverse_proxy(team: Team) -> DiagnosticResult:
    """Check for a configured reverse proxy via ProxyRecord or $lib_custom_api_host in recent events."""
    # Check for managed PostHog proxy records on the organization
    proxy_records = list(ProxyRecord.objects.filter(organization=team.organization).values_list("domain", "status"))
    valid_domains = [domain for domain, status in proxy_records if status == ProxyRecord.Status.VALID]
    other_domains = [domain for domain, status in proxy_records if status != ProxyRecord.Status.VALID]

    # Check events for $lib_custom_api_host (covers self-managed proxies too)
    query = parse_select(
        """
        SELECT DISTINCT properties.$lib_custom_api_host
        FROM events
        WHERE timestamp >= now() - INTERVAL 1 DAY
          AND properties.$lib_custom_api_host IS NOT NULL
          AND event IN ('$pageview', '$screen')
        LIMIT 10
        """
    )
    result = execute_hogql_query(query, team=team, query_type="hog_support_report_reverse_proxy")
    event_hosts = [str(row[0]) for row in (result.results or []) if row[0] is not None]

    if valid_domains or event_hosts:
        parts: list[str] = []
        if valid_domains:
            parts.append(f"managed: {', '.join(valid_domains)}")
        if event_hosts:
            parts.append(f"detected in events: {', '.join(event_hosts[:3])}")
        detail = f"pending/erroring proxy records: {', '.join(other_domains)}" if other_domains else None
        return DiagnosticResult(
            id="reverse_proxy",
            label="Reverse proxy",
            status="info",
            value="; ".join(parts),
            detail=detail,
        )

    if other_domains:
        return DiagnosticResult(
            id="reverse_proxy",
            label="Reverse proxy",
            status="warning",
            value="Proxy record exists but not yet valid",
            detail=f"domains: {', '.join(other_domains)}",
        )

    return DiagnosticResult(
        id="reverse_proxy",
        label="Reverse proxy",
        status="ok",
        value="Not configured",
    )


# Registry — add new checks here
DIAGNOSTIC_CHECKS = [
    check_custom_api_host,
    check_reverse_proxy,
]


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def hog_support_report(request: Request) -> Response:
    user = cast(User, request.user)
    team: Team | None = user.team
    if not team:
        return Response({"checks": []})

    results: list[dict] = []
    for check in DIAGNOSTIC_CHECKS:
        try:
            result = check(team)
            results.append(dataclasses.asdict(result))
        except Exception as e:
            capture_exception(e)
            results.append(
                {
                    "id": check.__name__,
                    "label": check.__name__,
                    "status": "error",
                    "value": "Check failed",
                    "detail": None,
                }
            )

    return Response({"checks": results})
