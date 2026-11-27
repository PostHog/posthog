from typing import Any

import numpy as np
from pyod.models.mad import MAD

from posthog.schema import DetectorType

from posthog.tasks.alerts.detectors.base import BaseDetector, DetectionResult, DetectorArtifact
from posthog.tasks.alerts.detectors.normalizers import FitError
from posthog.tasks.alerts.detectors.registry import register_detector


@register_detector(DetectorType.MAD)
class MADDetector(BaseDetector):
    """
    Median Absolute Deviation (MAD) anomaly detector.

    Uses pyod's MAD implementation to detect outliers based on
    the modified z-score: 0.6745 * |x - median| / MAD.

    More robust than z-score because it uses median instead of mean,
    making it resistant to outliers skewing the baseline.

    The raw score is the modified z-score. The normalizer maps it to [0, 1]
    against the scores of the training window, with min-max by default, as
    pyod's predict_proba does with its ``linear`` method.

    Config:
        threshold: float - Anomaly probability threshold (default: 0.95)
        window: int - Rolling window size (default: 30)
    """

    def detect(self, data: np.ndarray) -> DetectionResult:
        threshold = self.threshold
        window = self.window
        # preprocess() only ever runs a single first-difference pass when diffs_n is truthy
        # (it's a boolean toggle, not a pass count), so exactly one synthetic leading point
        # is introduced regardless of the configured magnitude.
        diffs_n = 1 if self.preprocessing_config.get("diffs_n") else 0
        offset = max(self.training_offset, 1)

        if not self._validate_data(data, min_length=window + offset + diffs_n):
            return DetectionResult(is_anomaly=False)

        original_length = len(data)
        data = self.preprocess(data)
        values = data if data.ndim == 1 else data[:, 0]
        # Differencing prepends synthetic (zero-valued) points to keep the array
        # length unchanged - drop them so the training window only ever sees
        # genuine differenced values.
        values = values[diffs_n:]

        # Use rolling window, honoring training_offset to exclude points closest
        # to the one being scored, so a live check agrees with detect_batch()
        window_data = values[-(window + offset) : -offset]
        current_value = values[-1]

        clf = MAD()
        clf.fit(window_data.reshape(-1, 1))
        try:
            fitted = self._fit_normalizer(clf.decision_scores_)
        except FitError:
            return DetectionResult(is_anomaly=False)

        raw_score = float(clf.decision_function(np.array([[current_value]]))[0])
        prob = self._normalize(fitted, raw_score)
        is_anomaly = prob > threshold

        return DetectionResult(
            is_anomaly=is_anomaly,
            score=prob,
            triggered_indices=[original_length - 1] if is_anomaly else [],
            all_scores=[prob],
            metadata={
                "median": float(clf.median_),
                "median_abs_deviation": float(clf.median_diff_),
                "value": float(current_value),
                "raw_score": raw_score,
                "normalizer": fitted["method"],
            },
        )

    def detect_batch(self, data: np.ndarray) -> DetectionResult:
        threshold = self.threshold
        window = self.window
        # preprocess() only ever runs a single first-difference pass when diffs_n is truthy
        # (it's a boolean toggle, not a pass count), so exactly one synthetic leading point
        # is introduced regardless of the configured magnitude.
        diffs_n = 1 if self.preprocessing_config.get("diffs_n") else 0
        offset = max(self.training_offset, 1)

        if not self._validate_data(data, min_length=window + offset + diffs_n):
            return DetectionResult(is_anomaly=False)

        data = self.preprocess(data)
        values = data if data.ndim == 1 else data[:, 0]
        # Keep indices aligned with the original series: scores/triggers below
        # are shifted back by diffs_n before being returned.
        values = values[diffs_n:]

        triggered = []
        scores: list[float | None] = [None] * (diffs_n + window + offset - 1)

        for i in range(window + offset - 1, len(values)):
            window_data = values[i - window - offset + 1 : i - offset + 1]
            current_val = values[i]

            clf = MAD()
            clf.fit(window_data.reshape(-1, 1))
            try:
                fitted = self._fit_normalizer(clf.decision_scores_)
            except FitError:
                scores.append(None)
                continue

            prob = self._normalize(fitted, float(clf.decision_function(np.array([[current_val]]))[0]))
            scores.append(prob)

            if prob > threshold:
                triggered.append(i + diffs_n)

        return DetectionResult(
            is_anomaly=len(triggered) > 0,
            score=scores[-1] if scores else None,
            triggered_indices=triggered,
            all_scores=scores,
            metadata={"threshold": threshold, "window": window},
        )

    def fit(self, history: np.ndarray) -> DetectorArtifact:
        window = self.window
        diffs_n = 1 if self.preprocessing_config.get("diffs_n") else 0
        rows = self._fit_rows(history, min_rows=window + diffs_n)
        values = rows if rows.ndim == 1 else rows[:, 0]
        clf = MAD()
        clf.fit(values[diffs_n:][-window:].reshape(-1, 1))
        return self._artifact(
            {
                "median": float(clf.median_),
                "median_abs_deviation": float(clf.median_diff_),
                "normalizer": self._fit_normalizer(clf.decision_scores_),
            }
        )

    def _score_rows(
        self, artifact: DetectorArtifact, rows: np.ndarray
    ) -> tuple[list[float | None], list[dict[str, Any]]]:
        params = artifact.params
        values = rows if rows.ndim == 1 else rows[:, 0]
        clf = MAD()
        clf.median_ = params["median"]
        clf.median_diff_ = params["median_abs_deviation"]
        raw_scores = clf.decision_function(values.reshape(-1, 1))
        fitted = params["normalizer"]
        scores: list[float | None] = []
        metadata: list[dict[str, Any]] = []
        for value, raw_score in zip(values, raw_scores):
            scores.append(self._normalize(fitted, float(raw_score)))
            metadata.append(
                {
                    "median": params["median"],
                    "median_abs_deviation": params["median_abs_deviation"],
                    "value": float(value),
                    "raw_score": float(raw_score),
                    "normalizer": fitted["method"],
                }
            )
        return scores, metadata

    @classmethod
    def get_default_config(cls) -> dict:
        return {
            "type": DetectorType.MAD.value,
            "threshold": cls.DEFAULT_THRESHOLD,
            "window": 30,
            "preprocessing": {"diffs_n": 1},
        }
