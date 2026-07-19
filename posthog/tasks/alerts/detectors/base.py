from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from posthog.tasks.alerts.detectors.preprocessing import preprocess_data, remove_outliers


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

    # Default robust-sigma distance for removing training/baseline outliers.
    # Keeps a single unflagged mega-spike from skewing the baseline the next
    # point is judged against. Set to 0 to disable outlier removal.
    DEFAULT_OUTLIER_SIGMAS = 4.0

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.preprocessing_config = config.get("preprocessing", {})
        self.training_offset: int = config.get("training_offset_n", self.DEFAULT_TRAINING_OFFSET)
        self.outlier_sigmas: float = config.get("outlier_sigmas", self.DEFAULT_OUTLIER_SIGMAS)

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

    def remove_training_outliers(self, data: np.ndarray) -> np.ndarray:
        """Remove extreme outliers from a training/baseline slice before fitting.

        Meant for the historical portion only — never pass the point being
        scored, or a genuine spike would be removed and missed.
        """
        return remove_outliers(data, self.outlier_sigmas)

    def preprocess_robust(self, data: np.ndarray, protect_last: int = 1) -> np.ndarray:
        """Remove historical outliers on the raw series, then preprocess.

        Outlier removal runs before smoothing so a past mega-spike can't bleed
        across neighboring points (and into the value being scored) once
        smoothed. The most recent ``protect_last`` points are left untouched so
        a genuine current spike still surfaces.
        """
        if self.outlier_sigmas <= 0 or data.ndim != 1 or protect_last < 1 or len(data) <= protect_last + 1:
            return self.preprocess(data)

        result = data.astype(float).copy()
        result[:-protect_last] = self.remove_training_outliers(result[:-protect_last])
        return self.preprocess(result)

    @classmethod
    def get_default_config(cls) -> dict[str, Any]:
        """Return default configuration for this detector type."""
        return {}

    def _validate_data(self, data: np.ndarray, min_length: int = 2) -> bool:
        """Validate input data meets minimum requirements."""
        if data is None or len(data) < min_length:
            return False
        return True
