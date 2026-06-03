from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class DetectionResult:
    """Outcome of evaluating one candidate weekly series for a notable change."""

    triggered: bool
    baseline_median: float
    change_pct: float
    impact: float
    robust_z: float


class PulseDetector(ABC):
    """Strategy for deciding whether a candidate metric changed notably.

    Mirrors the alert detector seam (posthog/tasks/alerts/detectors/base.py)
    but operates on a pre-extracted weekly series, not a numpy training window —
    the alert DETECTOR_MIN_SAMPLES=31 floor rejects short weekly baselines.
    """

    @abstractmethod
    def detect(
        self,
        current: float,
        baseline: list[float],
        min_change_pct: float,
        robust_z_threshold: float,
        min_baseline_value: float,
    ) -> DetectionResult:
        """Evaluate one candidate. robust_z is informational; the gate is in the strategy.

        `min_baseline_value` is the volume floor — metrics with a quieter baseline are skipped to
        avoid noisy percentage swings on near-zero traffic.
        """
        ...
