from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from posthog.dataclasses import frozen
from posthog.tasks.alerts.detectors.preprocessing import preprocess_data

# A change to what `fit` stores or what `score` reads needs a new version, so an older artifact is never read.
ARTIFACT_SCHEMA_VERSION = 1


@dataclass(frozen=False)
class DetectionResult:
    """Result from anomaly detection."""

    is_anomaly: bool
    score: float | None = None
    triggered_indices: list[int] = field(default_factory=list)
    all_scores: list[float | None] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    # One entry per scored bucket of `score()`, with the values that `metadata` holds for `detect()`.
    all_metadata: list[dict[str, Any]] = field(default_factory=list)


@frozen
class DetectorArtifact:
    """What `fit` learned from a history. `score` reads it instead of fitting again."""

    detector_type: str
    schema_version: int
    # The detector config the artifact was fit with, preprocessing and threshold included.
    config: dict[str, Any]
    # JSON-safe values only.
    params: dict[str, Any]
    model_bytes: bytes | None = None
    # The artifacts of the sub-detectors of an ensemble, in config order.
    children: tuple["DetectorArtifact", ...] = ()


class FitError(ValueError):
    """The history cannot fit this detector, for example because it is too short."""


class BaseDetector(ABC):
    """Abstract base class for all anomaly detectors.

    A detector scores a bare array of values and nothing else. A scorer that needs to know
    what the series means or who is asking (the AI judge) is a different contract, kept in
    ``products.alerts.backend.judge``.
    """

    # Default anomaly probability threshold. Higher = fewer alerts.
    DEFAULT_THRESHOLD = 0.95

    # Default rolling window size for the statistical detectors.
    DEFAULT_WINDOW = 30

    # Default number of recent points to exclude from training data.
    # Prevents the model from fitting on the points it's about to score.
    # Higher values make the model slower to adapt to recent distribution shifts.
    DEFAULT_TRAINING_OFFSET = 1

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.preprocessing_config = config.get("preprocessing") or {}
        self.training_offset: int = config.get("training_offset_n", self.DEFAULT_TRAINING_OFFSET)
        # A schema-normalized config keeps an unset field as an explicit None, which `dict.get` does not replace.
        threshold = config.get("threshold")
        self.threshold: float = self.DEFAULT_THRESHOLD if threshold is None else threshold
        window = config.get("window")
        self.window: int = self.DEFAULT_WINDOW if window is None else window

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

    def fit(self, history: np.ndarray) -> DetectorArtifact:
        """Fit on ``history``, the buckets before the first bucket to score.

        The newest ``training_offset - 1`` buckets of ``history`` stay out of the fit, so
        ``score(fit(data[:-1]), ...)`` reads the same training data as ``detect(data)``.
        """
        raise NotImplementedError(f"{type(self).__name__} cannot fit an artifact")

    def score(self, artifact: DetectorArtifact, data: np.ndarray) -> DetectionResult:
        """Score buckets with a fitted artifact.

        ``data`` holds ``context_buckets()`` buckets, then the buckets to score. The result has one entry in
        ``all_scores`` and ``all_metadata`` per scored bucket, and ``triggered_indices`` count from the first scored bucket.
        """
        self._check_artifact(artifact)
        context = self.context_buckets()
        if len(data) <= context:
            return DetectionResult(is_anomaly=False)
        processed = self.preprocess(np.asarray(data, dtype=float))[context:]
        scores, metadata = self._score_rows(artifact, processed)
        return self._scored_result(scores, metadata)

    def context_buckets(self) -> int:
        """Buckets that preprocessing reads before the first scored bucket: diffs, lags and smoothing."""
        preprocessing = self.preprocessing_config
        return (
            max((preprocessing.get("smooth_n") or 0) - 1, 0)
            + (1 if preprocessing.get("diffs_n") else 0)
            + min(max(preprocessing.get("lags_n") or 0, 0), 10)
        )

    def _score_rows(
        self, artifact: DetectorArtifact, rows: np.ndarray
    ) -> tuple[list[float | None], list[dict[str, Any]]]:
        """The score and metadata of each preprocessed row."""
        raise NotImplementedError(f"{type(self).__name__} cannot score an artifact")

    def _artifact(
        self,
        params: dict[str, Any],
        *,
        model_bytes: bytes | None = None,
        children: tuple[DetectorArtifact, ...] = (),
    ) -> DetectorArtifact:
        return DetectorArtifact(
            detector_type=str(self.config.get("type")),
            schema_version=ARTIFACT_SCHEMA_VERSION,
            config=self.config,
            params=params,
            model_bytes=model_bytes,
            children=children,
        )

    def _check_artifact(self, artifact: DetectorArtifact) -> None:
        if artifact.schema_version != ARTIFACT_SCHEMA_VERSION or artifact.detector_type != self.config.get("type"):
            raise ValueError(f"Artifact {artifact.detector_type} v{artifact.schema_version} does not fit this detector")

    def _fit_rows(self, history: np.ndarray, min_rows: int) -> np.ndarray:
        """The preprocessed rows of ``history`` that a fit reads, without the newest ``training_offset - 1``."""
        rows = self.preprocess(np.asarray(history, dtype=float))
        rows = rows[: len(rows) - (max(self.training_offset, 1) - 1)]
        if len(rows) < min_rows:
            raise FitError(f"{len(rows)} buckets cannot fit, {min_rows} needed")
        return rows

    def _scored_result(self, scores: list[float | None], metadata: list[dict[str, Any]]) -> DetectionResult:
        triggered = [i for i, score in enumerate(scores) if score is not None and score > self.threshold]
        return DetectionResult(
            is_anomaly=bool(triggered) and triggered[-1] == len(scores) - 1,
            score=scores[-1] if scores else None,
            triggered_indices=triggered,
            all_scores=scores,
            all_metadata=metadata,
        )

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
