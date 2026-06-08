from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from posthog.clickhouse.query_tagging import Product
from posthog.dags.common.owners import JobOwners
from posthog.temporal.health_checks.detectors import DEFAULT_EXECUTION_POLICY, HealthExecutionPolicy
from posthog.temporal.health_checks.models import DEFAULT_ACTIVE_SINCE_DAYS, HealthCheckResult
from posthog.temporal.health_checks.registry import _DETECT_FNS, HEALTH_CHECKS

if TYPE_CHECKING:
    from posthog.models.health_issue import HealthIssue


@dataclass(frozen=True)
class AlertContent:
    """User-facing description of a fired health-check alert.

    Health checks override `HealthCheck.render_alert` to produce one of
    these. The fields are embedded into `$health_check_issue_firing` and
    `$health_check_issue_resolved` event properties, where HogFunction
    templates pick them up as `event.properties.title`, etc.
    """

    title: str
    summary: str
    # Relative path inside the PostHog app (e.g. "/health/sdk-health").
    # HogFunction templates concatenate this onto {project.url}.
    link: str


@dataclass(frozen=True)
class HealthCheckRegistration:
    name: str
    kind: str
    owner: JobOwners
    schedule: str | None
    batch_size: int
    max_concurrent: int
    rollout_percentage: float
    not_processed_threshold: float
    dry_run: bool
    active_since_days: int | None
    product: Product | None


def _register_health_check(cls: type[HealthCheck]) -> None:
    existing = HEALTH_CHECKS.get(cls.kind)
    if existing is not None and existing.name != cls.name:
        raise ValueError(f"Health check kind '{cls.kind}' already registered by '{existing.name}'")

    registration = HealthCheckRegistration(
        name=cls.name,
        kind=cls.kind,
        owner=cls.owner,
        schedule=cls.schedule,
        batch_size=cls.policy.batch_size,
        max_concurrent=cls.policy.max_concurrent,
        rollout_percentage=cls.rollout_percentage,
        not_processed_threshold=cls.not_processed_threshold,
        dry_run=cls.dry_run,
        active_since_days=cls.active_since_days,
        product=cls.product,
    )

    HEALTH_CHECKS[cls.kind] = registration
    _DETECT_FNS[cls.kind] = cls().detect


class HealthCheck:
    name: str
    kind: str
    owner: JobOwners
    product: Product | None = None
    policy: HealthExecutionPolicy = DEFAULT_EXECUTION_POLICY
    schedule: str | None = None
    rollout_percentage: float = 1.0
    not_processed_threshold: float = 0.1
    dry_run: bool = False
    active_since_days: int | None = DEFAULT_ACTIVE_SINCE_DAYS

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if not hasattr(cls, "name") or not hasattr(cls, "kind"):
            return
        _register_health_check(cls)

    def detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        raise NotImplementedError

    @classmethod
    def render_alert(cls, issue: HealthIssue) -> AlertContent:
        """Build the alert content surfaced to HogFunction destinations.

        The default produces a generic title/summary keyed off `kind` and
        `severity` with a link to /health. Concrete checks override this to
        produce a human-readable message that names the affected resource.
        """
        return AlertContent(
            title=cls.name,
            summary=f"{cls.kind} ({issue.severity})",
            link="/health",
        )
