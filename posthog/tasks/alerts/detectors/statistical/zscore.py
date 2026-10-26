from typing import Any

import numpy as np

from posthog.schema import DetectorType

from posthog.tasks.alerts.detectors.base import BaseDetector, DetectionResult, DetectorArtifact
from posthog.tasks.alerts.detectors.registry import register_detector


def _normalize_zscore(z_score: float, min_z: float, max_z: float) -> float:
    """Normalize a z-score to a [0, 1] anomaly probability.

    Uses min-max normalization against the training window z-scores,
    consistent with PyOD's default ``linear`` method. The score represents
    where the current z-score falls relative to the range observed in the
    training window: 0 means at or below the minimum, 1 means at or above
    the maximum.
    """
    if max_z == min_z:
        return 1.0 if z_score > max_z else 0.0
    return float(np.clip((z_score - min_z) / (max_z - min_z), 0.0, 1.0))


def _probability(value: float, mean: float, std: float, min_z: float, max_z: float) -> float:
    """The anomaly probability of ``value``. With a flat window, any change scores 1."""
    if std == 0:
        return 1.0 if abs(value - mean) > 0 else 0.0
    return _normalize_zscore(abs((value - mean) / std), min_z, max_z)


def _is_return(
    value: float, recent: np.ndarray, mean: float, std: float, min_z: float, max_z: float, threshold: float
) -> bool:
    """Whether ``value`` moves against a recent value that scores above ``threshold``.

    On differenced data, the fall of a spike back to its baseline is a large change in the
    opposite direction of its rise, so it scores as high as the rise itself.
    """
    direction = np.sign(value - mean)
    return any(
        np.sign(previous - mean) == -direction and _probability(previous, mean, std, min_z, max_z) > threshold
        for previous in recent
    )


@register_detector(DetectorType.ZSCORE)
class ZScoreDetector(BaseDetector):
    """
    Z-Score based anomaly detector.

    Detects anomalies by calculating how many standard deviations
    a value is from the rolling mean.

    Scores are normalized to [0, 1] using min-max normalization against
    the training window z-scores (consistent with PyOD's default ``linear``
    method).

    Config:
        threshold: float - Anomaly probability threshold (default: 0.95)
        window: int - Rolling window size (default: 30)
        suppress_return_n: int - Buckets after a value above the threshold in which a value in the
            opposite direction is not flagged, so the end of a spike does not flag again (default: 0, off)
    """

    def _return_lookback(self) -> int:
        return max(self.config.get("suppress_return_n") or 0, 0)

    def _without_return(
        self,
        prob: float,
        value: float,
        recent: np.ndarray,
        mean: float,
        std: float,
        min_z: float,
        max_z: float,
        threshold: float,
    ) -> float:
        """``prob``, capped at ``threshold`` when the value is the return of a recent spike."""
        if prob > threshold and len(recent) and _is_return(value, recent, mean, std, min_z, max_z, threshold):
            return threshold
        return prob

    def context_buckets(self) -> int:
        return super().context_buckets() + self._return_lookback()

    def detect(self, data: np.ndarray) -> DetectionResult:
        """Check if the most recent point is an anomaly based on z-score."""
        threshold = self.config.get("threshold", self.DEFAULT_THRESHOLD)
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

        # Use rolling window for mean/std, honoring training_offset to exclude
        # points closest to the one being scored, so a live check agrees with
        # detect_batch().
        window_data = values[-(window + offset) : -offset]
        mean = np.mean(window_data)
        std = np.std(window_data)

        current_value = values[-1]
        lookback = self._return_lookback()
        recent = values[max(len(values) - 1 - lookback, 0) : -1]

        if std == 0:
            score = self._without_return(
                _probability(current_value, mean, 0.0, 0.0, 0.0), current_value, recent, mean, 0.0, 0.0, 0.0, threshold
            )
            is_anomaly = score > threshold
            return DetectionResult(
                is_anomaly=is_anomaly,
                score=score,
                triggered_indices=[original_length - 1] if is_anomaly else [],
                all_scores=[score],
                metadata={"mean": float(mean), "std": 0.0, "value": float(current_value), "raw_zscore": None},
            )

        z_score = abs((current_value - mean) / std)
        window_zscores = np.abs((window_data - mean) / std)
        min_z, max_z = float(window_zscores.min()), float(window_zscores.max())
        prob = self._without_return(
            _normalize_zscore(z_score, min_z, max_z), current_value, recent, mean, std, min_z, max_z, threshold
        )

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
            },
        )

    def detect_batch(self, data: np.ndarray) -> DetectionResult:
        """Check all points for z-score anomalies."""
        threshold = self.config.get("threshold", self.DEFAULT_THRESHOLD)
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
        lookback = self._return_lookback()

        for i in range(window + offset - 1, len(values)):
            window_data = values[i - window - offset + 1 : i - offset + 1]
            mean = np.mean(window_data)
            std = np.std(window_data)

            current_val = values[i]
            recent = values[max(i - lookback, 0) : i]

            if std == 0:
                min_z = max_z = 0.0
            else:
                window_zscores = np.abs((window_data - mean) / std)
                min_z, max_z = float(window_zscores.min()), float(window_zscores.max())
            prob = self._without_return(
                _probability(current_val, mean, std, min_z, max_z),
                current_val,
                recent,
                mean,
                std,
                min_z,
                max_z,
                threshold,
            )
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
        window = self.config.get("window", 30)
        diffs_n = 1 if self.preprocessing_config.get("diffs_n") else 0
        rows = self._fit_rows(history, min_rows=window + diffs_n)
        values = rows if rows.ndim == 1 else rows[:, 0]
        window_data = values[diffs_n:][-window:]
        mean = np.mean(window_data)
        std = np.std(window_data)
        params: dict[str, Any] = {"mean": float(mean), "std": float(std)}
        if std != 0:
            window_zscores = np.abs((window_data - mean) / std)
            params.update(min_z=float(window_zscores.min()), max_z=float(window_zscores.max()))
        return self._artifact(params)

    def score(self, artifact: DetectorArtifact, data: np.ndarray) -> DetectionResult:
        self._check_artifact(artifact)
        context = self.context_buckets()
        if len(data) <= context:
            return DetectionResult(is_anomaly=False)
        processed = self.preprocess(np.asarray(data, dtype=float))
        # The rows before the first scored row stay, so the first scored rows can see a spike that started before them.
        start = context - self._return_lookback()
        scores, metadata = self._score_rows(artifact, processed[start:], first=context - start)
        return self._scored_result(scores, metadata)

    def _score_rows(
        self, artifact: DetectorArtifact, rows: np.ndarray, first: int = 0
    ) -> tuple[list[float | None], list[dict[str, Any]]]:
        """The score and metadata of each row from ``first`` on. The rows before ``first`` are only read as recent values."""
        mean = artifact.params["mean"]
        std = artifact.params["std"]
        min_z = artifact.params.get("min_z", 0.0)
        max_z = artifact.params.get("max_z", 0.0)
        threshold = self.config.get("threshold", self.DEFAULT_THRESHOLD)
        lookback = self._return_lookback()
        values = rows if rows.ndim == 1 else rows[:, 0]
        scores: list[float | None] = []
        metadata: list[dict[str, Any]] = []
        for i in range(first, len(values)):
            value = values[i]
            recent = values[max(i - lookback, 0) : i]
            scores.append(
                self._without_return(
                    _probability(value, mean, std, min_z, max_z), value, recent, mean, std, min_z, max_z, threshold
                )
            )
            raw_zscore = None if std == 0 else float(abs((value - mean) / std))
            metadata.append({"mean": mean, "std": std, "value": float(value), "raw_zscore": raw_zscore})
        return scores, metadata

    @classmethod
    def get_default_config(cls) -> dict:
        return {
            "type": DetectorType.ZSCORE.value,
            "threshold": cls.DEFAULT_THRESHOLD,
            "window": 30,
            "preprocessing": {"diffs_n": 1},
        }
