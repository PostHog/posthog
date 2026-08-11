"""Core types for the anomaly detection pure functions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum

import numpy as np

from products.apm.backend.logic.anomaly_detection.constants import BUCKET_MINUTES


class VerdictType(StrEnum):
    SPIKE = "spike"
    DROP = "drop"
    SILENCE = "silence"


class Direction(StrEnum):
    UP = "up"
    DOWN = "down"


class BaselineStage(StrEnum):
    INSUFFICIENT = "insufficient"
    COLD_START = "cold_start"
    DEVELOPING = "developing"
    MATURE = "mature"


class TrafficTier(StrEnum):
    """Rate bands over trailing per-bucket rate (thresholds in config)."""

    A = "a"  # >=0.5/s
    B = "b"  # 0.1-0.5/s
    C = "c"  # 1/min-0.1/s
    D = "d"  # <1/min — below the detection floor


VERDICT_DIRECTION: dict[VerdictType, Direction] = {
    VerdictType.SPIKE: Direction.UP,
    VerdictType.DROP: Direction.DOWN,
    VerdictType.SILENCE: Direction.DOWN,
}


@dataclass(frozen=True, slots=True)
class SeriesKey:
    namespace: str
    service: str
    environment: str
    severity: str


@dataclass(frozen=True, slots=True)
class Band:
    lower: float
    upper: float
    expected: float


@dataclass(frozen=True, slots=True)
class BucketVerdict:
    key: SeriesKey
    bucket_index: int
    verdict_type: VerdictType
    observed: float
    band: Band
    stage: BaselineStage
    tier: TrafficTier


@dataclass(frozen=True, slots=True)
class BucketEvaluation:
    """Full evaluation of one bucket, verdict or not.

    ``band`` and ``tier`` are None when the bucket was gated out or the
    baseline was unscorable — consumers that chart observed-vs-band use the
    band wherever it exists, independent of whether a verdict fired.
    """

    observed: float
    band: Band | None
    stage: BaselineStage | None
    tier: TrafficTier | None
    verdict: BucketVerdict | None


@dataclass(slots=True)
class SeriesHistory:
    """Dense per-series counts on the 5-minute grid.

    ``counts[i]`` is the count for the bucket starting at
    ``grid_start + i * 5min``. A missing rollup row is a zero count — for log
    volume the two are the same observation.

    ``baseline_floor_index`` re-anchors the baseline window: buckets before it
    never enter baselines. A re-baselining policy (e.g. a stability test that
    accepts a level shift as the new normal) sets it to the shift point.
    """

    grid_start: datetime
    counts: np.ndarray
    excluded: set[int] = field(default_factory=set)
    baseline_floor_index: int = 0

    def __post_init__(self) -> None:
        if self.grid_start.tzinfo is None:
            raise ValueError("grid_start must be timezone-aware")
        if self.grid_start.astimezone(UTC).minute % BUCKET_MINUTES != 0 or self.grid_start.second != 0:
            raise ValueError("grid_start must be aligned to the 5-minute UTC grid")

    def bucket_time(self, index: int) -> datetime:
        return self.grid_start + timedelta(minutes=BUCKET_MINUTES * index)

    @property
    def first_active_index(self) -> int | None:
        nonzero = np.flatnonzero(self.counts)
        return int(nonzero[0]) if nonzero.size else None

    def last_active_index(self, before: int) -> int | None:
        nonzero = np.flatnonzero(self.counts[:before])
        return int(nonzero[-1]) if nonzero.size else None
