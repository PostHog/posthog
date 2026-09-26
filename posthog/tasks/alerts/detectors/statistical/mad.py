import numpy as np
from pyod.models.mad import MAD

from posthog.schema import DetectorType

from posthog.tasks.alerts.detectors.base import PointScore, RollingWindowDetector
from posthog.tasks.alerts.detectors.registry import register_detector


@register_detector(DetectorType.MAD)
class MADDetector(RollingWindowDetector):
    """
    Median Absolute Deviation (MAD) anomaly detector.

    Uses pyod's MAD implementation to detect outliers based on
    the modified z-score: 0.6745 * |x - median| / MAD.

    More robust than z-score because it uses median instead of mean,
    making it resistant to outliers skewing the baseline.

    Scores are normalized to [0, 1] probabilities using pyod's
    predict_proba (erf-based conversion).

    Config:
        threshold: float - Anomaly probability threshold (default: 0.95)
        window: int - Rolling window size (default: 30)
    """

    def score_point(self, window_data: np.ndarray, value: float) -> PointScore:
        clf = MAD()
        clf.fit(window_data.reshape(-1, 1))
        test_point = np.array([[value]])

        return PointScore(
            # pyod's erf-based conversion already normalizes to [0, 1]
            probability=float(clf.predict_proba(test_point)[0, 1]),
            metadata={
                "median": float(clf.median_),
                "median_abs_deviation": float(clf.median_diff_),
                "value": value,
                "raw_score": float(clf.decision_function(test_point)[0]),
            },
        )

    @classmethod
    def get_default_config(cls) -> dict:
        return {
            "type": DetectorType.MAD.value,
            "threshold": cls.DEFAULT_THRESHOLD,
            "window": 30,
            "preprocessing": {"diffs_n": 1},
        }
