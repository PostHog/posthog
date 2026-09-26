from typing import Any

import numpy as np

from posthog.schema import DetectorType

from posthog.tasks.alerts.detectors.base import BaseDetector, DetectionResult
from posthog.tasks.alerts.detectors.registry import register_detector
from posthog.tasks.alerts.detectors.statistical.scoring import (
    NORMAL_IQR_IN_SIGMA,
    NORMAL_Q3_IN_SIGMA,
    deviation_to_probability,
)


def _iqr_distance_to_probability(distance: float, multiplier: float, window_size: int) -> float:
    """Score a fence distance by how extreme it is, not by how it ranks in the window.

    A point inside the fences is not an outlier at all and scores 0. Beyond a fence,
    the distance is converted from IQR units into sigma units, where the fence itself
    already sits ``NORMAL_Q3_IN_SIGMA + NORMAL_IQR_IN_SIGMA * multiplier`` out.
    """
    if distance <= 0:
        return 0.0
    deviation_in_sigma = NORMAL_Q3_IN_SIGMA + NORMAL_IQR_IN_SIGMA * (multiplier + distance)
    return deviation_to_probability(deviation_in_sigma, window_size)


@register_detector(DetectorType.IQR)
class IQRDetector(BaseDetector):
    """
    Interquartile Range (IQR) based anomaly detection.

    Classic outlier detection using Tukey's fences:
    - Values below Q1 - multiplier*IQR are anomalies
    - Values above Q3 + multiplier*IQR are anomalies

    Scores grade how far beyond the fence a value lies, on a scale the window's
    own distances cannot move. See ``scoring.deviation_to_probability``.

    Config:
        threshold: float - Anomaly probability threshold (default: 0.95)
        multiplier: float - IQR multiplier for fences (default: 1.5)
        window: int - Rolling window size (default: 30)
    """

    def detect(self, data: np.ndarray) -> DetectionResult:
        threshold = self.config.get("threshold", self.DEFAULT_THRESHOLD)
        multiplier = self.config.get("multiplier", 1.5)
        window = self.config.get("window", 30)
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

        # Honor training_offset to exclude points closest to the one being
        # scored, so a live check agrees with detect_batch().
        window_data = values[-(window + offset) : -offset]
        q1 = np.percentile(window_data, 25)
        q3 = np.percentile(window_data, 75)
        iqr = q3 - q1

        lower_fence = q1 - multiplier * iqr
        upper_fence = q3 + multiplier * iqr

        current_value = values[-1]

        # Raw distance from nearest fence, normalized by IQR
        if iqr == 0:
            raw_distance = 0.0
        elif current_value < lower_fence:
            raw_distance = (lower_fence - current_value) / iqr
        elif current_value > upper_fence:
            raw_distance = (current_value - upper_fence) / iqr
        else:
            raw_distance = 0.0

        prob = _iqr_distance_to_probability(raw_distance, multiplier, len(window_data))
        is_anomaly = prob > threshold

        return DetectionResult(
            is_anomaly=is_anomaly,
            score=prob,
            triggered_indices=[original_length - 1] if is_anomaly else [],
            all_scores=[prob],
            metadata={
                "q1": float(q1),
                "q3": float(q3),
                "iqr": float(iqr),
                "lower_fence": float(lower_fence),
                "upper_fence": float(upper_fence),
                "value": float(current_value),
                "raw_distance": raw_distance,
            },
        )

    def detect_batch(self, data: np.ndarray) -> DetectionResult:
        threshold = self.config.get("threshold", self.DEFAULT_THRESHOLD)
        multiplier = self.config.get("multiplier", 1.5)
        window = self.config.get("window", 30)
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
            q1 = np.percentile(window_data, 25)
            q3 = np.percentile(window_data, 75)
            iqr = q3 - q1

            lower_fence = q1 - multiplier * iqr
            upper_fence = q3 + multiplier * iqr

            val = values[i]

            if iqr == 0:
                raw_distance = 0.0
            elif val < lower_fence:
                raw_distance = (lower_fence - val) / iqr
            elif val > upper_fence:
                raw_distance = (val - upper_fence) / iqr
            else:
                raw_distance = 0.0

            prob = _iqr_distance_to_probability(raw_distance, multiplier, len(window_data))
            scores.append(prob)
            if prob > threshold:
                triggered.append(i + diffs_n)

        return DetectionResult(
            is_anomaly=len(triggered) > 0,
            score=scores[-1] if scores else None,
            triggered_indices=triggered,
            all_scores=scores,
        )

    @classmethod
    def get_default_config(cls) -> dict[str, Any]:
        return {
            "type": DetectorType.IQR.value,
            "threshold": cls.DEFAULT_THRESHOLD,
            "multiplier": 1.5,
            "window": 30,
        }
