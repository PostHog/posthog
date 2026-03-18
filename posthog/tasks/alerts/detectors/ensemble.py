from typing import Any

import numpy as np

from posthog.tasks.alerts.detectors.base import BaseDetector, DetectionResult
from posthog.tasks.alerts.detectors.registry import get_detector, register_detector


@register_detector("ensemble")
class EnsembleDetector(BaseDetector):
    """
    Combines multiple detectors with AND/OR logic.

    Config:
        operator: 'and' | 'or' - How to combine results
        detectors: list[dict] - Sub-detector configurations (minimum 2)
    """

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        operator = config.get("operator", "and")
        if operator not in ("and", "or"):
            raise ValueError(f"Invalid ensemble operator: {operator}. Must be 'and' or 'or'.")

        detector_configs = config.get("detectors", [])
        if len(detector_configs) < 2:
            raise ValueError("Ensemble detector requires at least 2 sub-detectors.")

        self.operator = operator
        self.sub_detectors = [get_detector(cfg) for cfg in detector_configs]

    def detect(self, data: np.ndarray) -> DetectionResult:
        results = [d.detect(data) for d in self.sub_detectors]

        if self.operator == "and":
            is_anomaly = all(r.is_anomaly for r in results)
            score = min((r.score for r in results if r.score is not None), default=None)
        else:
            is_anomaly = any(r.is_anomaly for r in results)
            score = max((r.score for r in results if r.score is not None), default=None)

        return DetectionResult(
            is_anomaly=is_anomaly,
            score=score,
            triggered_indices=results[-1].triggered_indices if is_anomaly else [],
            all_scores=results[-1].all_scores,
            metadata={
                "operator": self.operator,
                "sub_results": [
                    {"type": cfg.get("type"), "is_anomaly": r.is_anomaly, "score": r.score}
                    for cfg, r in zip(self.config.get("detectors", []), results)
                ],
            },
        )

    def detect_batch(self, data: np.ndarray) -> DetectionResult:
        results = [d.detect_batch(data) for d in self.sub_detectors]

        if self.operator == "and":
            # AND: only flag indices where ALL detectors agree
            triggered_sets = [set(r.triggered_indices) for r in results]
            triggered = sorted(set.intersection(*triggered_sets)) if triggered_sets else []
        else:
            # OR: flag indices where ANY detector triggers
            triggered_sets = [set(r.triggered_indices) for r in results]
            triggered = sorted(set.union(*triggered_sets)) if triggered_sets else []

        # Use scores from first detector for the combined view
        scores = results[0].all_scores if results else []

        return DetectionResult(
            is_anomaly=len(triggered) > 0,
            score=scores[-1] if scores else None,
            triggered_indices=triggered,
            all_scores=scores,
            metadata={
                "operator": self.operator,
                "sub_results": [
                    {"type": cfg.get("type"), "triggered_count": len(r.triggered_indices)}
                    for cfg, r in zip(self.config.get("detectors", []), results)
                ],
            },
        )
