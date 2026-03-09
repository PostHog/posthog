from dataclasses import dataclass

from posthog.temporal.health_checks.detectors import HealthDetector, resolve_execution_policy
from posthog.temporal.health_checks.owners import HealthCheckOwners
from posthog.temporal.health_checks.registry import _DETECT_FNS, HEALTH_CHECKS


@dataclass(frozen=True)
class HealthCheckRegistration:
    name: str
    kind: str
    owner: HealthCheckOwners
    schedule: str | None
    batch_size: int
    max_concurrent: int
    rollout_percentage: float
    not_processed_threshold: float
    dry_run: bool


def create_health_check(
    name: str,
    kind: str,
    detector: HealthDetector,
    owner: HealthCheckOwners,
    *,
    schedule: str | None = None,
    batch_size: int | None = None,
    max_concurrent: int | None = None,
    rollout_percentage: float = 1.0,
    not_processed_threshold: float = 0.1,
    dry_run: bool = False,
) -> HealthCheckRegistration:
    existing = HEALTH_CHECKS.get(kind)
    if existing is not None and existing.name != name:
        raise ValueError(f"Health check kind '{kind}' already registered by '{existing.name}'")

    policy = resolve_execution_policy(
        detector,
        batch_size=batch_size,
        max_concurrent=max_concurrent,
    )

    registration = HealthCheckRegistration(
        name=name,
        kind=kind,
        owner=owner,
        schedule=schedule,
        batch_size=policy.batch_size,
        max_concurrent=policy.max_concurrent,
        rollout_percentage=rollout_percentage,
        not_processed_threshold=not_processed_threshold,
        dry_run=dry_run,
    )

    HEALTH_CHECKS[kind] = registration
    _DETECT_FNS[kind] = detector.detect_fn

    return registration
