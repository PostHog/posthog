"""The health contract: one row per service that every Application Observability surface renders.

Status today comes from the error-rate band alone. The detector verdict, SLOs, and lag join this
row in later slices and take precedence over the band when they are present; the thresholds here
match the prototype so the two implementations stay in step.
"""

from dataclasses import dataclass, replace

from posthog.enums import LabeledStrEnum

WARNING_ERROR_RATE = 0.01
SERIOUS_ERROR_RATE = 0.05

_STATUS_RANK = {"critical": 0, "serious": 1, "warning": 2, "good": 3}


class HealthStatus(LabeledStrEnum):
    GOOD = "good"
    WARNING = "warning"
    SERIOUS = "serious"
    CRITICAL = "critical"


@dataclass(frozen=True)
class HealthRow:
    request_rate: float | None
    error_rate: float | None
    p95_ms: float | None
    span_count: int
    error_count: int


@dataclass(frozen=True)
class ServiceHealth:
    service_name: str
    environment: str
    health: HealthRow
    status: HealthStatus = HealthStatus.GOOD
    sparkline: tuple[int, ...] = ()


@dataclass(frozen=True)
class EndpointHealth:
    """One entry span name in one service: a route, an RPC, a consumed message, or a job."""

    service_name: str
    endpoint: str
    environment: str
    health: HealthRow
    status: HealthStatus = HealthStatus.GOOD


@dataclass(frozen=True)
class ServiceEdge:
    """Calls from one service into another, counted on the callee spans whose parent is in the caller."""

    caller: str
    callee: str
    calls: int
    error_count: int
    p95_ms: float | None


def status_of(health: HealthRow) -> HealthStatus:
    rate = health.error_rate or 0.0
    if rate >= SERIOUS_ERROR_RATE:
        return HealthStatus.SERIOUS
    if rate >= WARNING_ERROR_RATE:
        return HealthStatus.WARNING
    return HealthStatus.GOOD


def rank_services(rows: list[ServiceHealth]) -> list[ServiceHealth]:
    """Worst status first, then the higher error rate, then the name, with the status filled in."""
    scored = [replace(row, status=status_of(row.health)) for row in rows]
    return sorted(
        scored,
        key=lambda row: (_STATUS_RANK[row.status], -(row.health.error_rate or 0.0), row.service_name),
    )


def rank_endpoints(rows: list[EndpointHealth]) -> list[EndpointHealth]:
    """The same order as rank_services, with the endpoint name after the service name."""
    scored = [replace(row, status=status_of(row.health)) for row in rows]
    return sorted(
        scored,
        key=lambda row: (
            _STATUS_RANK[row.status],
            -(row.health.error_rate or 0.0),
            row.service_name,
            row.endpoint,
        ),
    )
