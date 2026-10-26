"""The health contract: one row per service that every Application Observability surface renders.

Status today comes from the error-rate band alone. The detector verdict, SLOs, and lag join this
row in later slices and take precedence over the band when they are present; the thresholds here
match the prototype so the two implementations stay in step.
"""

from dataclasses import dataclass, replace
from enum import StrEnum

WARNING_ERROR_RATE = 0.01
SERIOUS_ERROR_RATE = 0.05

_STATUS_RANK = {"critical": 0, "serious": 1, "warning": 2, "good": 3}


class HealthStatus(StrEnum):
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
