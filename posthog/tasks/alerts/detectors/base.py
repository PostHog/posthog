from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from posthog.tasks.alerts.detectors.preprocessing import (
    preprocess_data,
    preprocessing_alters_scored_value,
    within_normal_band,
)


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

    # How far (in standard deviations of the raw window) a raw value may sit from its
    # historical mean and still count as "within the normal band" for the raw-band guard.
    DEFAULT_RAW_BAND_SIGMA = 3.0

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.preprocessing_config = config.get("preprocessing", {})
        self.training_offset: int = config.get("training_offset_n", self.DEFAULT_TRAINING_OFFSET)
        self.raw_band_sigma: float = config.get("raw_band_sigma", self.DEFAULT_RAW_BAND_SIGMA)

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

    def raw_value_within_normal_band(self, raw_data: np.ndarray, index: int, window: int) -> bool:
        """Reconcile a transformed-signal anomaly with the raw value the user is shown.

        Smoothing/differencing make the detector score a transformed signal, so a point can
        score as anomalous while its raw value is squarely inside the series' normal range —
        e.g. the sharp drop as a metric returns to baseline after a spike produces a large
        first difference that trips the score, even though the raw value is unremarkable. In
        that case the fired value (raw) and the scored signal disagree and we should not page.

        Returns False (no suppression) when preprocessing leaves the scored value equal to the
        raw value, since then there is nothing to reconcile — a genuine outlier still fires.
        """
        if not preprocessing_alters_scored_value(self.preprocessing_config):
            return False
        raw_values = raw_data if raw_data.ndim == 1 else raw_data[:, 0]
        window_slice = raw_values[max(index - window, 0) : index]
        if len(window_slice) == 0:
            return False
        return within_normal_band(window_slice, float(raw_values[index]), self.raw_band_sigma)

    @classmethod
    def get_default_config(cls) -> dict[str, Any]:
        """Return default configuration for this detector type."""
        return {}

    def _validate_data(self, data: np.ndarray, min_length: int = 2) -> bool:
        """Validate input data meets minimum requirements."""
        if data is None or len(data) < min_length:
            return False
        return True
