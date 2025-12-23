import numpy as np

from posthog.schema import DetectorType, EnsembleMode

from posthog.tasks.alerts.detectors.base import BaseDetector, DetectionResult
from posthog.tasks.alerts.detectors.registry import get_detector, register_detector

MIN_DETECTORS = 2
MAX_DETECTORS = 5


@register_detector(DetectorType.ENSEMBLE)
class EnsembleDetector(BaseDetector):
    """
    Ensemble detector that combines multiple detectors using AND/OR logic.

    AND mode: All detectors must trigger for the ensemble to trigger
    OR mode: Any detector triggering causes the ensemble to trigger

    Scores are aggregated as the mean of individual detector scores.

    Config:
        mode: str - "and" or "or" (default: "or")
        detectors: list[dict] - List of detector configs (2-5 detectors)

    Limitations:
        - No nested ensembles allowed
        - Minimum 2, maximum 5 detectors
    """

    def __init__(self, config: dict):
        super().__init__(config)
        self._validate_ensemble_config(config)
        self.mode = EnsembleMode(config.get("mode", "or"))
        self.detector_configs = config.get("detectors", [])
        self._child_detectors: list[BaseDetector] | None = None

    def _validate_ensemble_config(self, config: dict) -> None:
        """Validate ensemble configuration."""
        detectors = config.get("detectors", [])

        if len(detectors) < MIN_DETECTORS:
            raise ValueError(f"Ensemble requires at least {MIN_DETECTORS} detectors, got {len(detectors)}")

        if len(detectors) > MAX_DETECTORS:
            raise ValueError(f"Ensemble allows at most {MAX_DETECTORS} detectors, got {len(detectors)}")

        # Check for nested ensembles
        for detector_config in detectors:
            detector_type = detector_config.get("type")
            if detector_type == DetectorType.ENSEMBLE.value or detector_type == DetectorType.ENSEMBLE:
                raise ValueError("Nested ensembles are not allowed")

    def _get_child_detectors(self) -> list[BaseDetector]:
        """Lazily create child detector instances."""
        if self._child_detectors is None:
            self._child_detectors = [get_detector(config) for config in self.detector_configs]
        return self._child_detectors

    def detect(self, data: np.ndarray) -> DetectionResult:
        """Check if the latest point triggers according to ensemble logic."""
        child_detectors = self._get_child_detectors()

        results: list[DetectionResult] = []
        for detector in child_detectors:
            result = detector.detect(data)
            results.append(result)

        return self._aggregate_results(results, data_length=len(data))

    def detect_batch(self, data: np.ndarray) -> DetectionResult:
        """Check all points according to ensemble logic."""
        child_detectors = self._get_child_detectors()

        results: list[DetectionResult] = []
        for detector in child_detectors:
            result = detector.detect_batch(data)
            results.append(result)

        return self._aggregate_batch_results(results, data_length=len(data))

    def _aggregate_results(self, results: list[DetectionResult], data_length: int) -> DetectionResult:
        """Aggregate single-point results from child detectors."""
        anomaly_flags = [r.is_anomaly for r in results]
        scores = [r.score for r in results if r.score is not None]

        if self.mode == EnsembleMode.AND_:
            is_anomaly = all(anomaly_flags)
        else:  # OR mode
            is_anomaly = any(anomaly_flags)

        # Average of non-None scores
        avg_score = float(np.mean(scores)) if scores else None

        return DetectionResult(
            is_anomaly=is_anomaly,
            score=avg_score,
            triggered_indices=[data_length - 1] if is_anomaly else [],
            all_scores=[avg_score] if avg_score is not None else [],
            metadata={
                "mode": self.mode.value,
                "child_results": [{"is_anomaly": r.is_anomaly, "score": r.score} for r in results],
            },
        )

    def _aggregate_batch_results(self, results: list[DetectionResult], data_length: int) -> DetectionResult:
        """Aggregate batch results from child detectors."""
        # Build per-point anomaly flags and scores
        all_triggered: list[set[int]] = []
        all_scores_per_detector: list[list[float | None]] = []

        for result in results:
            all_triggered.append(set(result.triggered_indices))
            all_scores_per_detector.append(result.all_scores if result.all_scores else [])

        # Determine triggered indices based on mode
        if self.mode == EnsembleMode.AND_:
            # Intersection: point must be flagged by ALL detectors
            if all_triggered:
                triggered_set = all_triggered[0].copy()
                for other in all_triggered[1:]:
                    triggered_set &= other
            else:
                triggered_set = set()
        else:  # OR mode
            # Union: point flagged by ANY detector
            triggered_set = set()
            for s in all_triggered:
                triggered_set |= s

        triggered = sorted(triggered_set)

        # Compute average scores per point
        aggregated_scores: list[float | None] = []
        max_len = max((len(s) for s in all_scores_per_detector), default=0)

        for i in range(max_len):
            point_scores = []
            for detector_scores in all_scores_per_detector:
                if i < len(detector_scores) and detector_scores[i] is not None:
                    point_scores.append(detector_scores[i])
            if point_scores:
                aggregated_scores.append(float(np.mean(point_scores)))
            else:
                aggregated_scores.append(None)

        return DetectionResult(
            is_anomaly=len(triggered) > 0,
            score=aggregated_scores[-1] if aggregated_scores else None,
            triggered_indices=triggered,
            all_scores=aggregated_scores,
            metadata={
                "mode": self.mode.value,
                "detector_count": len(results),
            },
        )

    @classmethod
    def get_default_config(cls) -> dict:
        return {
            "type": DetectorType.ENSEMBLE.value,
            "mode": EnsembleMode.OR.value,
            "detectors": [],
        }
