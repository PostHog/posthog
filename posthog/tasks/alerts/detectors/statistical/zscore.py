from typing import Any

import numpy as np

from posthog.schema import DetectorType

from posthog.tasks.alerts.detectors.base import BaseDetector, DetectionResult, DetectorArtifact
from posthog.tasks.alerts.detectors.normalizers import MINMAX_STEP, FitError
from posthog.tasks.alerts.detectors.registry import register_detector


def _window_zscores(window_data: np.ndarray, mean: float, std: float) -> np.ndarray:
    """The absolute z-scores of the training window, the raw scores that the normalizer fits on.

    A constant window has no z-scores. Its points all tie, so they count as zeros toward the training size.
    """
    if std == 0:
        return np.zeros(len(window_data))
    return np.abs((window_data - mean) / std)


@register_detector(DetectorType.ZSCORE)
class ZScoreDetector(BaseDetector):
    """
    Z-Score based anomaly detector.

    Detects anomalies by calculating how many standard deviations
    a value is from the rolling mean.

    The raw score is the absolute z-score. The normalizer maps it to [0, 1]
    against the z-scores of the training window, with min-max by default.

    Config:
        threshold: float - Anomaly probability threshold (default: 0.95)
        window: int - Rolling window size (default: 30)
    """

    DEFAULT_NORMALIZER = MINMAX_STEP

    def detect(self, data: np.ndarray) -> DetectionResult:
        """Check if the most recent point is an anomaly based on z-score."""
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

        # Use rolling window for mean/std, honoring training_offset to exclude
        # points closest to the one being scored, so a live check agrees with
        # detect_batch().
        window_data = values[-(window + offset) : -offset]
        mean = np.mean(window_data)
        std = np.std(window_data)

        current_value = values[-1]

        try:
            fitted = self._fit_normalizer(_window_zscores(window_data, mean, std))
        except FitError:
            return DetectionResult(is_anomaly=False)

        if std == 0:
            is_anomaly = abs(current_value - mean) > 0
            return DetectionResult(
                is_anomaly=is_anomaly,
                score=1.0 if is_anomaly else 0.0,
                triggered_indices=[original_length - 1] if is_anomaly else [],
                all_scores=[1.0 if is_anomaly else 0.0],
                metadata={
                    "mean": float(mean),
                    "std": 0.0,
                    "value": float(current_value),
                    "raw_zscore": None,
                    "normalizer": fitted["method"],
                },
            )

        z_score = abs((current_value - mean) / std)
        prob = self._normalize(fitted, z_score)

        return DetectionResult(
            is_anomaly=prob > threshold,
            score=prob,
            triggered_indices=[original_length - 1] if prob > threshold else [],
            all_scores=[prob],
            metadata={
                "mean": float(mean),
                "std": float(std),
                "value": float(current_value),
                "raw_zscore": float(z_score),
                "normalizer": fitted["method"],
            },
        )

    def detect_batch(self, data: np.ndarray) -> DetectionResult:
        """Check all points for z-score anomalies."""
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
            mean = np.mean(window_data)
            std = np.std(window_data)

            current_val = values[i]

            try:
                fitted = self._fit_normalizer(_window_zscores(window_data, mean, std))
            except FitError:
                scores.append(None)
                continue

            if std == 0:
                if abs(current_val - mean) > 0:
                    scores.append(1.0)
                    triggered.append(i + diffs_n)
                else:
                    scores.append(0.0)
                continue

            z_score = abs((current_val - mean) / std)
            prob = self._normalize(fitted, z_score)
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
        window_data = values[diffs_n:][-window:]
        mean = np.mean(window_data)
        std = np.std(window_data)
        return self._artifact(
            {
                "mean": float(mean),
                "std": float(std),
                "normalizer": self._fit_normalizer(_window_zscores(window_data, mean, std)),
            }
        )

    def _score_rows(
        self, artifact: DetectorArtifact, rows: np.ndarray
    ) -> tuple[list[float | None], list[dict[str, Any]]]:
        mean = artifact.params["mean"]
        std = artifact.params["std"]
        fitted = artifact.params["normalizer"]
        scores: list[float | None] = []
        metadata: list[dict[str, Any]] = []
        for value in rows if rows.ndim == 1 else rows[:, 0]:
            if std == 0:
                scores.append(1.0 if abs(value - mean) > 0 else 0.0)
                metadata.append(
                    {
                        "mean": mean,
                        "std": 0.0,
                        "value": float(value),
                        "raw_zscore": None,
                        "normalizer": fitted["method"],
                    }
                )
                continue
            z_score = abs((value - mean) / std)
            scores.append(self._normalize(fitted, z_score))
            metadata.append(
                {
                    "mean": mean,
                    "std": std,
                    "value": float(value),
                    "raw_zscore": float(z_score),
                    "normalizer": fitted["method"],
                }
            )
        return scores, metadata

    @classmethod
    def get_default_config(cls) -> dict:
        return {
            "type": DetectorType.ZSCORE.value,
            "threshold": cls.DEFAULT_THRESHOLD,
            "window": 30,
            "preprocessing": {"diffs_n": 1},
        }
