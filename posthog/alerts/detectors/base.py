"""Base classes and types for alert detectors."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Optional


class DetectorType(StrEnum):
    """Available detector types."""

    THRESHOLD = "threshold"
    ZSCORE = "zscore"
    MAD = "mad"  # Median Absolute Deviation


class DetectionDirection(StrEnum):
    """Direction for anomaly detection."""

    UP = "up"  # Alert on values above normal
    DOWN = "down"  # Alert on values below normal
    BOTH = "both"  # Alert on values above or below normal


class ValueType(StrEnum):
    """Whether to run detection on raw values or deltas."""

    RAW = "raw"  # Run detection on raw metric values
    DELTA = "delta"  # Run detection on period-over-period changes


@dataclass
class DetectionResult:
    """Result of running a detector on data."""

    value: Optional[float]  # The raw metric value
    detector_score: Optional[float]  # The detector-specific score (e.g., z-score, mad score)
    is_breach: bool  # Whether this constitutes a breach
    breach_messages: list[str]  # Human-readable breach descriptions
    metadata: dict[str, Any]  # Additional detector-specific info


class BaseDetector(ABC):
    """Base class for all alert detectors."""

    def __init__(self, config: dict[str, Any]):
        """Initialize detector with configuration."""
        self.config = config
        self.validate_config()

    @abstractmethod
    def detect(
        self, values: list[float], series_name: str = "Series", value_type: ValueType = ValueType.RAW
    ) -> DetectionResult:
        """
        Run detection on a list of values.

        Args:
            values: Time series values (most recent last)
            series_name: Name of the series for breach messages
            value_type: Whether to use raw values or deltas

        Returns:
            DetectionResult with breach status and details
        """
        pass

    @abstractmethod
    def validate_config(self) -> None:
        """Validate the detector configuration. Raise ValueError if invalid."""
        pass

    @property
    @abstractmethod
    def detector_type(self) -> DetectorType:
        """Return the type of this detector."""
        pass

    def _compute_deltas(self, values: list[float]) -> list[float]:
        """Compute period-over-period deltas from values."""
        if len(values) < 2:
            return []
        return [values[i] - values[i - 1] for i in range(1, len(values))]
