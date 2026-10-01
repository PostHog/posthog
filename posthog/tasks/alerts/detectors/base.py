from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from posthog.dataclasses import frozen
from posthog.tasks.alerts.detectors.preprocessing import preprocess_data


@dataclass
class DetectionResult:
    """Result from anomaly detection."""

    is_anomaly: bool
    score: float | None = None
    triggered_indices: list[int] = field(default_factory=list)
    all_scores: list[float | None] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@frozen(eq=False)
class WindowedSeries:
    """A series prepared for rolling-window scoring, with the window geometry it is scored on.

    ``values`` is preprocessed; ``raw`` holds the untransformed values at the same indices, so a
    caller can read the series' real scale after differencing has centred ``values`` on zero.
    """

    values: np.ndarray
    raw: np.ndarray
    window: int
    offset: int
    diffs_n: int
    original_length: int

    @property
    def last_index(self) -> int:
        return len(self.values) - 1

    def scorable_indices(self) -> range:
        """Indices with a full training window behind them."""
        return range(self.window + self.offset - 1, len(self.values))

    def training_window(self, index: int) -> np.ndarray:
        """The points a detector fits on to score ``index``, excluding the training offset."""
        return self.values[index - self.window - self.offset + 1 : index - self.offset + 1]

    def raw_training_window(self, index: int) -> np.ndarray:
        """``training_window`` before preprocessing, for checks that need the series' real scale."""
        return self.raw[index - self.window - self.offset + 1 : index - self.offset + 1]


class BaseDetector(ABC):
    """Abstract base class for all anomaly detectors.

    A detector scores a bare array of values and nothing else. A scorer that needs to know
    what the series means or who is asking (the AI judge) is a different contract, kept in
    ``products.alerts.backend.judge``.
    """

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

    def below_volume_floor(self, baseline: np.ndarray) -> bool:
        """Report whether a baseline is too small for relative deviation to mean anything.

        ``baseline`` is the raw training window behind the point being scored, so the answer
        tracks the same history the score does. Reading the whole series instead would let a
        metric's own early days veto an anomaly it has since grown past.

        Whether a metric's scale makes this floor meaningful is the caller's call, not this
        method's: only the alerts layer knows a series counts events rather than measuring
        seconds, so only it turns the floor on by default.
        """
        if self.min_baseline <= 0 or len(baseline) == 0:
            return False
        values = baseline if baseline.ndim == 1 else baseline[:, 0]
        return float(np.median(np.abs(values))) < self.min_baseline

    def windowed_series(self, data: np.ndarray) -> WindowedSeries | None:
        """Validate and preprocess ``data`` for rolling-window scoring.

        Returns None when the series is too short to fill one training window.
        """
        window = self.config.get("window", 30)
        # preprocess() only ever runs a single first-difference pass when diffs_n is truthy
        # (it's a boolean toggle, not a pass count), so exactly one synthetic leading point
        # is introduced regardless of the configured magnitude.
        diffs_n = 1 if self.preprocessing_config.get("diffs_n") else 0
        offset = max(self.training_offset, 1)

        if not self._validate_data(data, min_length=window + offset + diffs_n):
            return None

        original_length = len(data)
        raw = data if data.ndim == 1 else data[:, 0]
        processed = self.preprocess(data)
        values = processed if processed.ndim == 1 else processed[:, 0]
        # Differencing prepends synthetic (zero-valued) points to keep the array length
        # unchanged - drop them so the training window only ever sees genuine differenced
        # values. The raw series drops as many so the two stay index-aligned.
        return WindowedSeries(
            values=values[diffs_n:],
            raw=raw[diffs_n:],
            window=window,
            offset=offset,
            diffs_n=diffs_n,
            original_length=original_length,
        )

    def _validate_data(self, data: np.ndarray, min_length: int = 2) -> bool:
        """Validate input data meets minimum requirements."""
        if data is None or len(data) < min_length:
            return False
        return True


@frozen(eq=False)
class PointScore:
    """A detector's verdict on one point, with the fit values behind it."""

    probability: float
    metadata: dict[str, Any] = field(default_factory=dict)


class RollingWindowDetector(BaseDetector):
    """A detector that scores each point against the window of points before it.

    Subclasses supply ``score_point``; the scan over the series, the volume floor and the index
    bookkeeping are implemented once here, so a live check and a backfill cannot drift apart.
    """

    @abstractmethod
    def score_point(self, window_data: np.ndarray, value: float) -> PointScore:
        """Score ``value`` against the training window immediately before it."""
        ...

    def detect(self, data: np.ndarray) -> DetectionResult:
        threshold = self.config.get("threshold", self.DEFAULT_THRESHOLD)
        series = self.windowed_series(data)
        if series is None:
            return DetectionResult(is_anomaly=False)

        index = series.last_index
        if self.below_volume_floor(series.raw_training_window(index)):
            return DetectionResult(is_anomaly=False)

        scored = self.score_point(series.training_window(index), float(series.values[index]))
        is_anomaly = scored.probability > threshold

        return DetectionResult(
            is_anomaly=is_anomaly,
            score=scored.probability,
            triggered_indices=[series.original_length - 1] if is_anomaly else [],
            all_scores=[scored.probability],
            metadata=scored.metadata,
        )

    def detect_batch(self, data: np.ndarray) -> DetectionResult:
        threshold = self.config.get("threshold", self.DEFAULT_THRESHOLD)
        series = self.windowed_series(data)
        if series is None:
            return DetectionResult(is_anomaly=False)

        triggered: list[int] = []
        # Scores stay aligned with the original series: the leading Nones cover the synthetic
        # differencing point and every index without a full training window behind it.
        scores: list[float | None] = [None] * (series.diffs_n + series.window + series.offset - 1)

        for i in series.scorable_indices():
            if self.below_volume_floor(series.raw_training_window(i)):
                scores.append(None)
                continue

            probability = self.score_point(series.training_window(i), float(series.values[i])).probability
            scores.append(probability)
            if probability > threshold:
                triggered.append(i + series.diffs_n)

        return DetectionResult(
            is_anomaly=len(triggered) > 0,
            score=scores[-1] if scores else None,
            triggered_indices=triggered,
            all_scores=scores,
            metadata={"threshold": threshold, "window": series.window},
        )
