import io
from abc import abstractmethod
from typing import Any

import numpy as np
import joblib
from pyod.models.base import BaseDetector as PyODBaseDetector

from posthog.tasks.alerts.detectors.base import BaseDetector, DetectionResult, DetectorArtifact, FitError


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

    def detect(self, data: np.ndarray) -> DetectionResult:
        if not self._validate_data(data, min_length=self.MIN_SAMPLES):
            return DetectionResult(is_anomaly=False)

        data = self.preprocess(data)
        threshold = self.threshold

        if data.ndim == 1:
            data = data.reshape(-1, 1)

        train_data, test_data = self.train_test_split(data)

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
            triggered_indices=[len(data) - 1] if is_anomaly else [],
            all_scores=[prob],
            metadata={"raw_score": float(model.decision_function(last_point)[0])},
        )

    def fit(self, history: np.ndarray) -> DetectorArtifact:
        # detect() needs MIN_SAMPLES buckets, the scored one included.
        if len(history) + 1 < self.MIN_SAMPLES:
            raise FitError(f"{len(history)} buckets cannot fit, {self.MIN_SAMPLES - 1} needed")
        rows = self._fit_rows(history, min_rows=1)
        if rows.ndim == 1:
            rows = rows.reshape(-1, 1)
        if not np.all(np.isfinite(rows)):
            raise FitError("The history has values that are not finite")
        try:
            model = self._build_model(n_samples=len(rows))
            model.fit(rows)
        except (ValueError, np.linalg.LinAlgError) as error:
            raise FitError(str(error)) from error
        buffer = io.BytesIO()
        joblib.dump(model, buffer)
        return self._artifact({"n_samples": len(rows)}, model_bytes=buffer.getvalue())

    def _score_rows(
        self, artifact: DetectorArtifact, rows: np.ndarray
    ) -> tuple[list[float | None], list[dict[str, Any]]]:
        if artifact.model_bytes is None:
            raise ValueError("The artifact has no model")
        # nosemgrep: trailofbits.python.scikit-joblib-load.scikit-joblib-load (bytes come only from fit() via a blob whose SHA-256 the caller checked against Postgres)
        model: PyODBaseDetector = joblib.load(io.BytesIO(artifact.model_bytes))
        if rows.ndim == 1:
            rows = rows.reshape(-1, 1)
        scores: list[float | None] = []
        metadata: list[dict[str, Any]] = []
        for i in range(len(rows)):
            point = rows[i : i + 1]
            if not np.all(np.isfinite(point)):
                scores.append(None)
                metadata.append({})
                continue
            try:
                scores.append(float(model.predict_proba(point)[0, 1]))
                metadata.append({"raw_score": float(model.decision_function(point)[0])})
            except (ValueError, np.linalg.LinAlgError):
                scores.append(None)
                metadata.append({})
        return scores, metadata

    def detect_batch(self, data: np.ndarray) -> DetectionResult:
        if not self._validate_data(data, min_length=self.MIN_SAMPLES):
            return DetectionResult(is_anomaly=False)

        data = self.preprocess(data)
        threshold = self.threshold

        if data.ndim == 1:
            data = data.reshape(-1, 1)

        offset = max(self.training_offset, 1)
        triggered: list[int] = []
        scores: list[float | None] = [None] * self.MIN_SAMPLES

        for i in range(self.MIN_SAMPLES, len(data)):
            train_data = data[: i - offset + 1]
            if len(train_data) < self.MIN_SAMPLES:
                scores.append(None)
                continue

            test_point = data[i : i + 1]

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
