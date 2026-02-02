import numpy as np

from posthog.schema import DetectorType

from posthog.tasks.alerts.detectors.base import BaseDetector, DetectionResult
from posthog.tasks.alerts.detectors.registry import register_detector

# Consistency constant for MAD to approximate standard deviation
# For normally distributed data, MAD * 1.4826 ≈ standard deviation
MAD_CONSTANT = 1.4826


@register_detector(DetectorType.MAD)
class MADDetector(BaseDetector):
    """
    Median Absolute Deviation (MAD) based anomaly detection.

    More robust than z-score as it uses median instead of mean,
    making it less sensitive to existing outliers in the data.

    Config:
        threshold: float - Number of scaled MADs from median (default: 3.0)
        window: int - Rolling window size (default: 30)
    """

    def detect(self, data: np.ndarray) -> DetectionResult:
        """Check if the latest point is a MAD anomaly."""
        threshold = self.config.get("threshold", 3.0)
        window = self.config.get("window", 30)

        if not self._validate_data(data, min_length=window + 1):
            return DetectionResult(is_anomaly=False)

        data = self.preprocess(data)
        values = data if data.ndim == 1 else data[:, 0]

        # Use rolling window (exclude current point)
        window_data = values[-(window + 1) : -1]
        median = np.median(window_data)
        mad = np.median(np.abs(window_data - median))

        # Scale MAD to be comparable to standard deviation
        scaled_mad = mad * MAD_CONSTANT

        if scaled_mad == 0:
            return DetectionResult(is_anomaly=False, score=0.0)

        current_value = values[-1]
        mad_score = abs((current_value - median) / scaled_mad)

        return DetectionResult(
            is_anomaly=mad_score > threshold,
            score=float(mad_score),
            triggered_indices=[len(values) - 1] if mad_score > threshold else [],
            all_scores=[float(mad_score)],
            metadata={"median": float(median), "mad": float(mad), "value": float(current_value)},
        )

    def detect_batch(self, data: np.ndarray) -> DetectionResult:
        """Check all points for MAD anomalies."""
        threshold = self.config.get("threshold", 3.0)
        window = self.config.get("window", 30)

        if not self._validate_data(data, min_length=window + 1):
            return DetectionResult(is_anomaly=False)

        data = self.preprocess(data)
        values = data if data.ndim == 1 else data[:, 0]

        triggered = []
        scores: list[float | None] = [None] * window  # Pad initial window

        for i in range(window, len(values)):
            window_data = values[i - window : i]
            median = np.median(window_data)
            mad = np.median(np.abs(window_data - median))
            scaled_mad = mad * MAD_CONSTANT

            if scaled_mad == 0:
                mad_score = 0.0
            else:
                mad_score = abs((values[i] - median) / scaled_mad)

            scores.append(float(mad_score))
            if mad_score > threshold:
                triggered.append(i)

        return DetectionResult(
            is_anomaly=len(triggered) > 0,
            score=scores[-1] if scores else None,
            triggered_indices=triggered,
            all_scores=scores,
        )

    @classmethod
    def get_default_config(cls) -> dict:
        return {
            "type": DetectorType.MAD.value,
            "threshold": 3.0,
            "window": 30,
        }
