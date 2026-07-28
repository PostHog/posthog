from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from posthog.schema import AnomalyDirection

from posthog.tasks.alerts.detectors.preprocessing import preprocess_data


@dataclass
class DetectionResult:
    """Result from anomaly detection."""

    is_anomaly: bool
    score: float | None = None
    triggered_indices: list[int] = field(default_factory=list)
    all_scores: list[float | None] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    # Which side of its baseline the most recently scored point sits on. None when there's no
    # history to compare against, or when the point sits exactly on its baseline.
    direction: AnomalyDirection | None = None


def _as_1d(data: np.ndarray) -> np.ndarray:
    """View multivariate data as its primary series (lag features keep the value in column 0)."""
    return data if data.ndim == 1 else data[:, 0]


def _deviation_direction(values: np.ndarray, index: int, window: int) -> AnomalyDirection | None:
    """Which side of its trailing baseline ``values[index]`` sits on.

    Returns None when the point has no history behind it, or when it sits exactly on its
    baseline, since neither case has a direction to gate on.
    """
    if index <= 0 or index >= len(values):
        return None

    baseline_values = values[max(0, index - window) : index]
    if len(baseline_values) == 0:
        return None

    baseline = float(np.median(baseline_values))
    value = float(values[index])
    if value > baseline:
        return AnomalyDirection.UP
    if value < baseline:
        return AnomalyDirection.DOWN
    return None


class BaseDetector(ABC):
    """Abstract base class for all anomaly detectors."""

    # Default anomaly probability threshold. Higher = fewer alerts.
    DEFAULT_THRESHOLD = 0.95

    # Default number of recent points to exclude from training data.
    # Prevents the model from fitting on the points it's about to score.
    # Higher values make the model slower to adapt to recent distribution shifts.
    DEFAULT_TRAINING_OFFSET = 1

    # Trailing window the direction gate reads a point's baseline from, for detectors
    # that carry no window of their own.
    DEFAULT_BASELINE_WINDOW = 30

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.preprocessing_config = config.get("preprocessing", {})
        self.training_offset: int = config.get("training_offset_n", self.DEFAULT_TRAINING_OFFSET)
        self.direction = AnomalyDirection(config.get("direction") or AnomalyDirection.BOTH)

    def detect(self, data: np.ndarray) -> DetectionResult:
        """
        Run anomaly detection on the provided data, checking the latest point.

        Args:
            data: Time series data as numpy array (1D for univariate)

        Returns:
            DetectionResult with is_anomaly flag for the latest point
        """
        return self._apply_direction(data, self._detect(data))

    def detect_batch(self, data: np.ndarray) -> DetectionResult:
        """
        Run anomaly detection on all points in the data (for backfill).

        Args:
            data: Time series data as numpy array

        Returns:
            DetectionResult with triggered_indices for all anomalous points
        """
        return self._apply_direction(data, self._detect_batch(data))

    @abstractmethod
    def _detect(self, data: np.ndarray) -> DetectionResult:
        """Score the latest point. Called by ``detect()``, which then applies the direction gate."""
        pass

    @abstractmethod
    def _detect_batch(self, data: np.ndarray) -> DetectionResult:
        """Score every point. Called by ``detect_batch()``, which then applies the direction gate."""
        pass

    @property
    def baseline_window(self) -> int:
        """Trailing window of raw values the direction gate compares a point against."""
        return max(int(self.config.get("window") or self.DEFAULT_BASELINE_WINDOW), 1)

    def _apply_direction(self, data: np.ndarray, result: DetectionResult) -> DetectionResult:
        """Record which way the latest point deviated, and drop fires running the other way.

        Scoring is untouched, so this only gates the fire/no-fire decision, per triggered point.
        The side is read against the *raw* series rather than the preprocessed one, because with
        first-order differencing on (the z-score/MAD default) the scored value is a delta: a metric
        that is still below its baseline but recovering has a positive delta, and would otherwise
        read as an upward anomaly.
        """
        values = _as_1d(data)
        if len(values) < 2:
            return result

        window = self.baseline_window
        result.direction = _deviation_direction(values, len(values) - 1, window)

        if self.direction == AnomalyDirection.BOTH or not result.triggered_indices:
            return result

        kept = [i for i in result.triggered_indices if _deviation_direction(values, i, window) == self.direction]
        if len(kept) == len(result.triggered_indices):
            return result

        result.triggered_indices = kept
        # Gating can only ever suppress, so an already-negative verdict stays negative.
        result.is_anomaly = result.is_anomaly and bool(kept)
        return result

    def train_test_split(self, data: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Split data into training (historical) and test (recent) portions.

        Uses ``training_offset`` to exclude the most recent N points from
        the training set so the model is not fitted on data it will score.
        """
        offset = max(self.training_offset, 1)
        return data[:-offset], data[-offset:]

    def preprocess(self, data: np.ndarray) -> np.ndarray:
        """Apply preprocessing pipeline to data."""
        return preprocess_data(data, self.preprocessing_config)

    @classmethod
    def get_default_config(cls) -> dict[str, Any]:
        """Return default configuration for this detector type."""
        return {}

    def _validate_data(self, data: np.ndarray, min_length: int = 2) -> bool:
        """Validate input data meets minimum requirements."""
        if data is None or len(data) < min_length:
            return False
        return True
