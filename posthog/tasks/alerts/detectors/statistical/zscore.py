import numpy as np

from posthog.tasks.alerts.detectors.base import BaseDetector, DetectionResult


class ZScoreDetector(BaseDetector):
    """
    Z-Score based anomaly detector.

    Detects anomalies by calculating how many standard deviations
    a value is from the rolling mean.
    """

    def detect(self, data: np.ndarray) -> DetectionResult:
        """Check if the most recent point is an anomaly based on z-score."""
        threshold = self.config.get("threshold", 3.0)
        window = self.config.get("window", 30)

        if not self._validate_data(data, min_length=window + 1):
            return DetectionResult(is_anomaly=False)

        values = data if data.ndim == 1 else data[:, 0]

        # Use rolling window for mean/std (exclude current point)
        window_data = values[-(window + 1) : -1]
        mean = np.mean(window_data)
        std = np.std(window_data)

        current_value = values[-1]

        if std == 0:
            # When std is 0, any deviation from mean is infinite z-score
            # Flag as anomaly if value differs from mean
            is_anomaly = abs(current_value - mean) > 0
            return DetectionResult(
                is_anomaly=is_anomaly,
                score=float("inf") if is_anomaly else 0.0,
                triggered_indices=[len(values) - 1] if is_anomaly else [],
                all_scores=[float("inf") if is_anomaly else 0.0],
                metadata={"mean": float(mean), "std": 0.0, "value": float(current_value)},
            )

        z_score = abs((current_value - mean) / std)

        return DetectionResult(
            is_anomaly=z_score > threshold,
            score=float(z_score),
            triggered_indices=[len(values) - 1] if z_score > threshold else [],
            all_scores=[float(z_score)],
            metadata={"mean": float(mean), "std": float(std), "value": float(current_value)},
        )

    def detect_batch(self, data: np.ndarray) -> DetectionResult:
        """Check all points for z-score anomalies."""
        threshold = self.config.get("threshold", 3.0)
        window = self.config.get("window", 30)

        if not self._validate_data(data, min_length=window + 1):
            return DetectionResult(is_anomaly=False)

        values = data if data.ndim == 1 else data[:, 0]

        triggered = []
        scores: list[float | None] = [None] * window  # Pad initial window

        for i in range(window, len(values)):
            window_data = values[i - window : i]
            mean = np.mean(window_data)
            std = np.std(window_data)

            current_val = values[i]

            if std == 0:
                # When std is 0, any deviation from mean is infinite z-score
                if abs(current_val - mean) > 0:
                    scores.append(float("inf"))
                    triggered.append(i)
                else:
                    scores.append(0.0)
                continue

            z_score = abs((current_val - mean) / std)
            scores.append(float(z_score))

            if z_score > threshold:
                triggered.append(i)

        return DetectionResult(
            is_anomaly=len(triggered) > 0,
            score=scores[-1] if scores else None,
            triggered_indices=triggered,
            all_scores=scores,
            metadata={"threshold": threshold, "window": window},
        )
