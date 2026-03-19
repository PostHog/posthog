from abc import abstractmethod

import numpy as np
from pyod.models.base import BaseDetector as PyODBaseDetector

from posthog.tasks.alerts.detectors.base import BaseDetector, DetectionResult


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
        threshold = self.config.get("threshold", 0.9)

        if data.ndim == 1:
            data = data.reshape(-1, 1)

        train_data, test_data = self.train_test_split(data)

        model = self._build_model(n_samples=len(train_data))
        model.fit(train_data)

        last_point = test_data[-1:]
        prob = float(model.predict_proba(last_point)[0, 1])
        is_anomaly = prob > threshold

        return DetectionResult(
            is_anomaly=is_anomaly,
            score=prob,
            triggered_indices=[len(data) - 1] if is_anomaly else [],
            all_scores=[prob],
            metadata={"raw_score": float(model.decision_function(last_point)[0])},
        )

    def detect_batch(self, data: np.ndarray) -> DetectionResult:
        if not self._validate_data(data, min_length=self.MIN_SAMPLES):
            return DetectionResult(is_anomaly=False)

        data = self.preprocess(data)
        threshold = self.config.get("threshold", 0.9)

        if data.ndim == 1:
            data = data.reshape(-1, 1)

        model = self._build_model(n_samples=len(data))
        model.fit(data)

        probs = model.predict_proba(data)[:, 1]
        triggered = [i for i, p in enumerate(probs) if p > threshold]

        return DetectionResult(
            is_anomaly=len(triggered) > 0,
            score=float(probs[-1]) if len(probs) > 0 else None,
            triggered_indices=triggered,
            all_scores=[float(p) for p in probs],
        )
