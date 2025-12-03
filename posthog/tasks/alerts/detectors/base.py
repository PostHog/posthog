from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TypeVar

from posthog.schema import (
    DetectorType,
    ThresholdDetectorConfig,
    ZScoreDetectorConfig,
    KMeansDetectorConfig,
)


@dataclass
class DetectorResult:
    """Result of evaluating a detector on a data series."""

    is_breaching: bool
    breach_indices: list[int]  # Indices in the data array that are breaching
    value: float | None  # The calculated value (e.g., z-score, threshold comparison)
    message: str | None  # Human-readable description of the breach


DetectorConfigT = TypeVar(
    "DetectorConfigT",
    ThresholdDetectorConfig,
    ZScoreDetectorConfig,
    KMeansDetectorConfig,
)


class BaseDetector(ABC):
    """
    Abstract base class for alert detectors.

    Detectors analyze time series data and determine if alert conditions are met.
    Each detector type (threshold, z-score, k-means) implements its own detection logic.
    """

    detector_type: DetectorType

    @abstractmethod
    def evaluate(
        self,
        data: list[float],
        timestamps: list[str],
        series_label: str,
        check_index: int | None = None,
    ) -> DetectorResult:
        """
        Evaluate the detector on the given data series.

        Args:
            data: List of numerical values from the time series (ordered chronologically)
            timestamps: List of timestamp strings corresponding to each data point
            series_label: Label for the series being evaluated (for breach messages)
            check_index: Optional specific index to check (default: check the most recent point).
                        Use -1 for the last point, -2 for second-to-last, etc.
                        If None, defaults to -1 (most recent completed interval).

        Returns:
            DetectorResult containing breach status and details
        """
        pass

    @abstractmethod
    def get_breach_points(
        self,
        data: list[float],
        timestamps: list[str],
    ) -> list[int]:
        """
        Get all indices in the data that would trigger this detector.

        This is used for visualization - highlighting all points that breach
        the detector's conditions.

        Args:
            data: List of numerical values from the time series
            timestamps: List of timestamp strings corresponding to each data point

        Returns:
            List of indices where breaches occur
        """
        pass

    @classmethod
    def get_minimum_data_points(cls) -> int:
        """
        Returns the minimum number of data points required for this detector.

        Override in subclasses that need historical data (e.g., z-score needs
        enough points to calculate meaningful statistics).
        """
        return 1
