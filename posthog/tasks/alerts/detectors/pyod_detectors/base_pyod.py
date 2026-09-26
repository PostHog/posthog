from abc import abstractmethod

import numpy as np
from pyod.models.base import BaseDetector as PyODBaseDetector

from posthog.dataclasses import frozen
from posthog.tasks.alerts.detectors.base import BaseDetector, DetectionResult


@frozen(eq=False)
class _FittableSeries:
    """A series in the 2-D shape PyOD fits on, with the raw values at the same indices."""

    values: np.ndarray
    raw: np.ndarray


class BasePyODDetector(BaseDetector):
    """Base class for all PyOD-backed detectors.

    Subclasses only need to implement ``_build_model()`` to return a
    configured PyOD model instance.  The train/test split, reshaping,
    preprocessing and result construction are handled here once.
    """

    MIN_SAMPLES = 10

    @abstractmethod
    def _build_model(self, n_samples: int) -> PyODBaseDetector:
        """Return a configured (but unfitted) PyOD model instance.

        Args:
            n_samples: Number of samples in the training set.
                       Useful for clamping neighbor counts etc.
        """
        ...

    # -- public API -----------------------------------------------------------

    def _fittable_series(self, data: np.ndarray) -> _FittableSeries | None:
        """Validate and preprocess ``data`` into the shape PyOD fits on.

        Returns None when the series is too short to fit. The raw values ride along so the
        volume floor can read the series' real scale after preprocessing has transformed it.
        """
        if not self._validate_data(data, min_length=self.MIN_SAMPLES):
            return None
        raw = data if data.ndim == 1 else data[:, 0]
        values = self.preprocess(data)
        return _FittableSeries(values=values.reshape(-1, 1) if values.ndim == 1 else values, raw=raw)

    def detect(self, data: np.ndarray) -> DetectionResult:
        series = self._fittable_series(data)
        if series is None:
            return DetectionResult(is_anomaly=False)

        threshold = self.config.get("threshold", self.DEFAULT_THRESHOLD)
        offset = max(self.training_offset, 1)

        # These detectors fit on everything before the training offset rather than a rolling
        # window, so that prefix is the baseline the floor has to judge.
        if self.below_volume_floor(series.raw[:-offset]):
            return DetectionResult(is_anomaly=False)

        train_data, test_data = self.train_test_split(series.values)

        # Guard against inf/nan in data (e.g. from preprocessing)
        if not np.all(np.isfinite(train_data)) or not np.all(np.isfinite(test_data)):
            return DetectionResult(is_anomaly=False)

        try:
            model = self._build_model(n_samples=len(train_data))
            model.fit(train_data)

            last_point = test_data[-1:]
            prob = float(model.predict_proba(last_point)[0, 1])
        except (ValueError, np.linalg.LinAlgError):
            return DetectionResult(is_anomaly=False)

        is_anomaly = prob > threshold

        return DetectionResult(
            is_anomaly=is_anomaly,
            score=prob,
            triggered_indices=[len(series.values) - 1] if is_anomaly else [],
            all_scores=[prob],
            metadata={"raw_score": float(model.decision_function(last_point)[0])},
        )

    def detect_batch(self, data: np.ndarray) -> DetectionResult:
        series = self._fittable_series(data)
        if series is None:
            return DetectionResult(is_anomaly=False)

        threshold = self.config.get("threshold", self.DEFAULT_THRESHOLD)
        offset = max(self.training_offset, 1)
        triggered: list[int] = []
        scores: list[float | None] = [None] * self.MIN_SAMPLES

        for i in range(self.MIN_SAMPLES, len(series.values)):
            train_end = i - offset + 1
            train_data = series.values[:train_end]
            if len(train_data) < self.MIN_SAMPLES:
                scores.append(None)
                continue

            if self.below_volume_floor(series.raw[:train_end]):
                scores.append(None)
                continue

            test_point = series.values[i : i + 1]

            # Guard against inf/nan in train or test data (e.g. from preprocessing)
            if not np.all(np.isfinite(train_data)) or not np.all(np.isfinite(test_point)):
                scores.append(None)
                continue

            try:
                model = self._build_model(n_samples=len(train_data))
                model.fit(train_data)
                prob = float(model.predict_proba(test_point)[0, 1])
            except (ValueError, np.linalg.LinAlgError):
                scores.append(None)
                continue

            scores.append(prob)

            if prob > threshold:
                triggered.append(i)

        return DetectionResult(
            is_anomaly=len(triggered) > 0,
            score=scores[-1] if scores else None,
            triggered_indices=triggered,
            all_scores=scores,
        )
