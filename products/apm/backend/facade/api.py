"""
Facade for apm.

The ONLY module other products are allowed to import.
Accept frozen dataclasses, call logic/, return frozen
dataclasses. Never return ORM instances or import DRF.

Exposes the flag check plus the pure anomaly-detection core (detector,
issue state machine, config, and types) for consumers that bring their own
counts — currently the logs product's JIT anomaly scan. The detector is
infra-free by contract: everything re-exported here is a pure function or a
frozen dataclass over counts.
"""

from typing import TYPE_CHECKING

from products.apm.backend.feature_flags import is_apm_enabled
from products.apm.backend.logic.anomaly_detection.bands import NegativeBinomialBandModel
from products.apm.backend.logic.anomaly_detection.baseline import TimeGrid, candidate_slice_pad_buckets
from products.apm.backend.logic.anomaly_detection.config import DetectionConfig
from products.apm.backend.logic.anomaly_detection.constants import BUCKET_MINUTES, BUCKETS_PER_DAY, BUCKETS_PER_WEEK
from products.apm.backend.logic.anomaly_detection.detector import (
    evaluate_series_bucket,
    evaluate_series_bucket_detail,
    traffic_tier,
)
from products.apm.backend.logic.anomaly_detection.issues import (
    IssueAction,
    IssueFingerprint,
    IssueSnapshot,
    IssueState,
    evaluate_issue_transition,
    fingerprint_for,
    required_consecutive,
)
from products.apm.backend.logic.anomaly_detection.types import (
    Band,
    BaselineStage,
    BucketEvaluation,
    BucketVerdict,
    Direction,
    SeriesHistory,
    SeriesKey,
    TrafficTier,
    VerdictType,
)
from products.apm.backend.logic.health.contract import (
    EndpointHealth,
    HealthRow,
    HealthStatus,
    ServiceEdge,
    ServiceHealth,
    rank_services,
    status_of,
)
from products.apm.backend.logic.health.sources import (
    ServiceMapResult,
    ServicesHealthResult,
    get_service_map as _get_service_map,
    list_endpoints_health as _list_endpoints_health,
    list_services_health as _list_services_health,
)

if TYPE_CHECKING:
    from datetime import datetime

    from posthog.models import Team

__all__ = [
    "EndpointHealth",
    "HealthRow",
    "HealthStatus",
    "ServiceEdge",
    "ServiceHealth",
    "ServiceMapResult",
    "ServicesHealthResult",
    "get_service_map",
    "list_endpoints_health",
    "list_services_health",
    "rank_services",
    "status_of",
    "BUCKET_MINUTES",
    "BUCKETS_PER_DAY",
    "BUCKETS_PER_WEEK",
    "Band",
    "BaselineStage",
    "BucketEvaluation",
    "BucketVerdict",
    "DetectionConfig",
    "Direction",
    "IssueAction",
    "IssueFingerprint",
    "IssueSnapshot",
    "IssueState",
    "NegativeBinomialBandModel",
    "SeriesHistory",
    "SeriesKey",
    "TimeGrid",
    "TrafficTier",
    "VerdictType",
    "candidate_slice_pad_buckets",
    "evaluate_issue_transition",
    "evaluate_series_bucket",
    "evaluate_series_bucket_detail",
    "fingerprint_for",
    "is_apm_enabled",
    "required_consecutive",
    "traffic_tier",
]


def list_services_health(
    *, team: "Team", date_from: "datetime", date_to: "datetime", environment: str
) -> ServicesHealthResult:
    """One health row per service in the environment and window, worst first.

    Pure contracts out: the presentation layer serializes `ServicesHealthResult` without touching logic.
    """
    return _list_services_health(team=team, date_from=date_from, date_to=date_to, environment=environment)


def list_endpoints_health(
    *, team: "Team", date_from: "datetime", date_to: "datetime", environment: str, service: str | None = None
) -> list[EndpointHealth]:
    """One health row per (service, entry span name) in the environment and window, worst first."""
    return _list_endpoints_health(
        team=team, date_from=date_from, date_to=date_to, environment=environment, service=service
    )


def get_service_map(*, team: "Team", date_from: "datetime", date_to: "datetime", environment: str) -> ServiceMapResult:
    """Service-to-service call edges in the environment and window, from a bounded sample of traces."""
    return _get_service_map(team=team, date_from=date_from, date_to=date_to, environment=environment)
