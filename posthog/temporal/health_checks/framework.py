from __future__ import annotations

from dataclasses import dataclass

from posthog.clickhouse.query_tagging import Product
from posthog.dags.common.owners import JobOwners
from posthog.temporal.health_checks.detectors import DEFAULT_EXECUTION_POLICY, HealthExecutionPolicy
from posthog.temporal.health_checks.models import DEFAULT_ACTIVE_SINCE_DAYS, HealthCheckResult
from posthog.temporal.health_checks.registry import _DETECT_FNS, HEALTH_CHECKS


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
