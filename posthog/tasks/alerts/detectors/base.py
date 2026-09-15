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

    # A count series must reach this median before a relative-deviation flag counts. Off by
    # default, because the registry also serves callers that read a detector's fit metadata and
    # would get an empty result from a skipped check. Alerts turn it on.
    DEFAULT_MIN_BASELINE = 0.0

    # Default number of recent points to exclude from training data.
    # Prevents the model from fitting on the points it's about to score.
    # Higher values make the model slower to adapt to recent distribution shifts.
    DEFAULT_TRAINING_OFFSET = 1

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.preprocessing_config = config.get("preprocessing") or {}
        self.training_offset: int = config.get("training_offset_n", self.DEFAULT_TRAINING_OFFSET)
        min_baseline = config.get("min_baseline")
        self.min_baseline: float = self.DEFAULT_MIN_BASELINE if min_baseline is None else float(min_baseline)

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

    @classmethod
    def get_default_config(cls) -> dict[str, Any]:
        """Return default configuration for this detector type."""
        return {}

    def below_volume_floor(self, data: np.ndarray) -> bool:
        """Report whether a count series is too small for relative deviation to mean anything.

        The floor applies to whole-number series only. A ratio or a duration in seconds sits
        below any count floor by construction, so flooring it would stop the alert from ever
        firing. Reads the raw series, because first-difference preprocessing centres the values
        on zero and would put every series below the floor.
        """
        if self.min_baseline <= 0:
            return False
        values = data if data.ndim == 1 else data[:, 0]
        if len(values) == 0 or not np.all(np.mod(values, 1) == 0):
            return False
        return float(np.median(np.abs(values))) < self.min_baseline

    def _validate_data(self, data: np.ndarray, min_length: int = 2) -> bool:
        """Validate input data meets minimum requirements."""
        if data is None or len(data) < min_length:
            return False
        return True
