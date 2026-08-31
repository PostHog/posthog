from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from posthog.tasks.alerts.detectors.preprocessing import preprocess_data


@dataclass
class DetectionResult:
    """Result from anomaly detection."""

    is_anomaly: bool
    score: float | None = None
    triggered_indices: list[int] = field(default_factory=list)
    all_scores: list[float | None] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseDetector(ABC):
    """Abstract base class for all anomaly detectors."""

    # Default anomaly probability threshold. Higher = fewer alerts.
    DEFAULT_THRESHOLD = 0.95

    # Default number of recent points to exclude from training data.
    # Prevents the model from fitting on the points it's about to score.
    # Higher values make the model slower to adapt to recent distribution shifts.
    DEFAULT_TRAINING_OFFSET = 1

    # Side of the baseline a deviation must fall on to count as an anomaly.
    # "both" fires on any deviation; "down" fires only on drops below the
    # baseline, "up" only on spikes above it. A drop-monitoring alert on a
    # series that swings both ways (e.g. a diurnal metric) sets "down" so the
    # normal ramp-up stops firing.
    DEFAULT_DIRECTION = "both"
    VALID_DIRECTIONS = ("both", "up", "down")

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.preprocessing_config = config.get("preprocessing") or {}
        self.training_offset: int = config.get("training_offset_n", self.DEFAULT_TRAINING_OFFSET)
        self.direction: str = config.get("direction") or self.DEFAULT_DIRECTION
        if self.direction not in self.VALID_DIRECTIONS:
            raise ValueError(f"Invalid direction: {self.direction}. Must be one of {self.VALID_DIRECTIONS}.")

    @abstractmethod
    def detect(self, data: np.ndarray) -> DetectionResult:
        """
        Run anomaly detection on the provided data, checking the latest point.

        Args:
            data: Time series data as numpy array (1D for univariate)

        Returns:
            DetectionResult with is_anomaly flag for the latest point
        """
        pass

    @abstractmethod
    def detect_batch(self, data: np.ndarray) -> DetectionResult:
        """
        Run anomaly detection on all points in the data (for backfill).

        Args:
            data: Time series data as numpy array

        Returns:
            DetectionResult with triggered_indices for all anomalous points
        """
        pass

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

    def _direction_allows(self, value: float, baseline: float) -> bool:
        """Return True when a deviation from ``baseline`` matches the configured direction.

        ``both`` keeps every anomaly. ``up`` keeps only points above the
        baseline (a spike); ``down`` keeps only points below it (a drop).
        """
        if self.direction == "up":
            return bool(value > baseline)
        if self.direction == "down":
            return bool(value < baseline)
        return True

    @classmethod
    def get_default_config(cls) -> dict[str, Any]:
        """Return default configuration for this detector type."""
        return {}

    def _validate_data(self, data: np.ndarray, min_length: int = 2) -> bool:
        """Validate input data meets minimum requirements."""
        if data is None or len(data) < min_length:
            return False
        return True
