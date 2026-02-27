from dataclasses import dataclass
from typing import Literal

from posthog.dags.common.health.types import BatchDetectFn

DetectorKind = Literal["default", "clickhouse_batch"]


@dataclass(frozen=True)
class HealthDetector:
    detect_fn: BatchDetectFn
    kind: DetectorKind = "default"


@dataclass(frozen=True)
class HealthExecutionPolicy:
    batch_size: int
    max_concurrent: int


_DEFAULT_POLICY_BY_KIND: dict[DetectorKind, HealthExecutionPolicy] = {
    "default": HealthExecutionPolicy(batch_size=1000, max_concurrent=5),
    "clickhouse_batch": HealthExecutionPolicy(batch_size=250, max_concurrent=1),
}


def batch_detector(detect_fn: BatchDetectFn, kind: DetectorKind = "default") -> HealthDetector:
    return HealthDetector(detect_fn=detect_fn, kind=kind)


def resolve_execution_policy(
    detector: HealthDetector,
    *,
    batch_size: int | None = None,
    max_concurrent: int | None = None,
) -> HealthExecutionPolicy:
    base_policy = _DEFAULT_POLICY_BY_KIND[detector.kind]
    resolved = HealthExecutionPolicy(
        batch_size=batch_size if batch_size is not None else base_policy.batch_size,
        max_concurrent=max_concurrent if max_concurrent is not None else base_policy.max_concurrent,
    )

    if resolved.batch_size <= 0:
        raise ValueError(f"batch_size must be > 0, got {resolved.batch_size}")
    if resolved.max_concurrent <= 0:
        raise ValueError(f"max_concurrent must be > 0, got {resolved.max_concurrent}")

    return resolved
