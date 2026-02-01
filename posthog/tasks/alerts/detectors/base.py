from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class DetectionResult:
    """Result from a detector's detect method."""

    is_anomaly: bool
    score: float | None = None
    triggered_indices: list[int] = field(default_factory=list)
    all_scores: list[float | None] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseDetector(ABC):
    """Base class for all anomaly detectors."""

    def __init__(self, config: dict[str, Any]):
        self.config = config

    @abstractmethod
    def detect(self, data: np.ndarray) -> DetectionResult:
        """
        Detect if the most recent point is an anomaly.

        Args:
            data: Time series data as numpy array

        Returns:
            DetectionResult with anomaly status and metadata
        """
        pass

    def detect_batch(self, data: np.ndarray) -> DetectionResult:
        """
        Detect anomalies across all points in the data.
        Default implementation calls detect() - subclasses can override for efficiency.

        Args:
            data: Time series data as numpy array

        Returns:
            DetectionResult with all triggered indices
        """
        return self.detect(data)

    def _validate_data(self, data: np.ndarray, min_length: int = 2) -> bool:
        """Validate that data has minimum required length."""
        if data is None or len(data) < min_length:
            return False
        return True
