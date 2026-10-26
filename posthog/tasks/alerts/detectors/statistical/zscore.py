from typing import Any

import numpy as np

from posthog.schema import DetectorType

from posthog.tasks.alerts.detectors.base import BaseDetector, DetectionResult, DetectorArtifact
from posthog.tasks.alerts.detectors.registry import register_detector


def _zscore_to_probability(z_score: float, window_zscores: np.ndarray) -> float:
    """Normalize a z-score to a [0, 1] anomaly probability.

    Uses min-max normalization against the training window z-scores,
    consistent with PyOD's default ``linear`` method. The score represents
    where the current z-score falls relative to the range observed in the
    training window: 0 means at or below the minimum, 1 means at or above
    the maximum.
    """
    return _normalize_zscore(z_score, float(window_zscores.min()), float(window_zscores.max()))


def _normalize_zscore(z_score: float, min_z: float, max_z: float) -> float:
    if max_z == min_z:
        return 1.0 if z_score > max_z else 0.0
    return float(np.clip((z_score - min_z) / (max_z - min_z), 0.0, 1.0))


def _warm_up_row(mean: float, std: float, value: float, after_flat: bool) -> tuple[float | None, dict[str, Any]]:
    """The first move away from a flat window scores 1.0 once, as the onset. Other warm-up buckets get no score."""
    if std == 0 and value != mean and after_flat:
        return 1.0, {"mean": mean, "std": 0.0, "value": value, "raw_zscore": None, "onset": True}
    return None, {}


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
        warm_up_flat_windows: bool - Give no score while the window moves less than one level change does,
            and flag only the first move away from a flat window (default: False)
    """

    def _warm_up(self, window_data: np.ndarray) -> bool:
        # A window of mostly equal values has a spread near zero, so every later move would score near 1.0.
        if not self.config.get("warm_up_flat_windows"):
            return False
        # Smoothing spreads one level change over `smooth_n` buckets.
        changes = max(self.preprocessing_config.get("smooth_n") or 1, 1)
        return int(np.count_nonzero(window_data != np.median(window_data))) <= changes

    def context_buckets(self) -> int:
        # The onset check reads the bucket before the first scored bucket.
        return super().context_buckets() + (1 if self.config.get("warm_up_flat_windows") else 0)

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

        if self._warm_up(window_data):
            score, metadata = _warm_up_row(float(mean), float(std), float(current_value), bool(values[-2] == mean))
            return DetectionResult(
                is_anomaly=score is not None,
                score=score,
                triggered_indices=[original_length - 1] if score is not None else [],
                all_scores=[score],
                metadata=metadata,
            )

        if std == 0:
            is_anomaly = abs(current_value - mean) > 0
            return DetectionResult(
                is_anomaly=is_anomaly,
                score=1.0 if is_anomaly else 0.0,
                triggered_indices=[original_length - 1] if is_anomaly else [],
                all_scores=[1.0 if is_anomaly else 0.0],
                metadata={"mean": float(mean), "std": 0.0, "value": float(current_value), "raw_zscore": None},
            )

        z_score = abs((current_value - mean) / std)
        window_zscores = np.abs((window_data - mean) / std)
        prob = _zscore_to_probability(z_score, window_zscores)

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

        for i in range(window + offset - 1, len(values)):
            window_data = values[i - window - offset + 1 : i - offset + 1]
            mean = np.mean(window_data)
            std = np.std(window_data)

            current_val = values[i]

            if std == 0:
                if abs(current_val - mean) > 0:
                    scores.append(1.0)
                    triggered.append(i + diffs_n)
                else:
                    scores.append(0.0)
                continue

            z_score = abs((current_val - mean) / std)
            window_zscores = np.abs((window_data - mean) / std)
            prob = _zscore_to_probability(z_score, window_zscores)
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
        if self._warm_up(window_data):
            params["warm_up"] = True
        if std != 0:
            window_zscores = np.abs((window_data - mean) / std)
            params.update(min_z=float(window_zscores.min()), max_z=float(window_zscores.max()))
        return self._artifact(params)

    def score(self, artifact: DetectorArtifact, data: np.ndarray) -> DetectionResult:
        if not artifact.params.get("warm_up"):
            return super().score(artifact, data)
        self._check_artifact(artifact)
        context = self.context_buckets()
        if len(data) <= context:
            return DetectionResult(is_anomaly=False)
        rows = self.preprocess(np.asarray(data, dtype=float))
        values = rows if rows.ndim == 1 else rows[:, 0]
        mean = artifact.params["mean"]
        # Differencing makes the first row synthetic.
        first = 1 if self.preprocessing_config.get("diffs_n") else 0
        scores: list[float | None] = []
        metadata: list[dict[str, Any]] = []
        for i in range(context, len(values)):
            # A score step reads only a few buckets, so one equal neighbor of a steady series must not mark a new onset.
            after_flat = i > first and bool(np.all(values[first:i] == mean))
            score, row_metadata = _warm_up_row(mean, artifact.params["std"], float(values[i]), after_flat)
            scores.append(score)
            metadata.append(row_metadata)
        return self._scored_result(scores, metadata)

    def _score_rows(
        self, artifact: DetectorArtifact, rows: np.ndarray
    ) -> tuple[list[float | None], list[dict[str, Any]]]:
        mean = artifact.params["mean"]
        std = artifact.params["std"]
        scores: list[float | None] = []
        metadata: list[dict[str, Any]] = []
        for value in rows if rows.ndim == 1 else rows[:, 0]:
            if std == 0:
                scores.append(1.0 if abs(value - mean) > 0 else 0.0)
                metadata.append({"mean": mean, "std": 0.0, "value": float(value), "raw_zscore": None})
                continue
            z_score = abs((value - mean) / std)
            scores.append(_normalize_zscore(z_score, artifact.params["min_z"], artifact.params["max_z"]))
            metadata.append({"mean": mean, "std": std, "value": float(value), "raw_zscore": float(z_score)})
        return scores, metadata

    @classmethod
    def get_default_config(cls) -> dict:
        return {
            "type": DetectorType.ZSCORE.value,
            "threshold": cls.DEFAULT_THRESHOLD,
            "window": 30,
            "preprocessing": {"diffs_n": 1},
        }
