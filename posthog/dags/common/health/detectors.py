from dataclasses import dataclass

from posthog.dags.common.health.types import BatchDetectFn


@dataclass(frozen=True)
class HealthExecutionPolicy:
    batch_size: int
    max_concurrent: int


DEFAULT_EXECUTION_POLICY = {"batch_size": 1000, "max_concurrent": 5}
CLICKHOUSE_BATCH_EXECUTION_POLICY = {"batch_size": 250, "max_concurrent": 1}


@dataclass(frozen=True)
class HealthDetector:
    detect_fn: BatchDetectFn
    execution_policy: HealthExecutionPolicy


def batch_detector(detect_fn: BatchDetectFn, *, batch_size: int = 1000, max_concurrent: int = 5) -> HealthDetector:
    return HealthDetector(
        detect_fn=detect_fn,
        execution_policy=HealthExecutionPolicy(batch_size=batch_size, max_concurrent=max_concurrent),
    )


def resolve_execution_policy(
    detector: HealthDetector,
    *,
    batch_size: int | None = None,
    max_concurrent: int | None = None,
) -> HealthExecutionPolicy:
    base_policy = detector.execution_policy
    resolved = HealthExecutionPolicy(
        batch_size=batch_size if batch_size is not None else base_policy.batch_size,
        max_concurrent=max_concurrent if max_concurrent is not None else base_policy.max_concurrent,
    )

    if resolved.batch_size <= 0:
        raise ValueError(f"batch_size must be > 0, got {resolved.batch_size}")
    if resolved.max_concurrent <= 0:
        raise ValueError(f"max_concurrent must be > 0, got {resolved.max_concurrent}")

    return resolved
