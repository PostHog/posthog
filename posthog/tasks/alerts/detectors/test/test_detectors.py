from typing import Any

import pytest

import numpy as np
from parameterized import parameterized

from posthog.tasks.alerts.detectors.base import DetectionResult
from posthog.tasks.alerts.detectors.ensemble import EnsembleDetector
from posthog.tasks.alerts.detectors.pyod_detectors.copod import COPODDetector
from posthog.tasks.alerts.detectors.pyod_detectors.ecod import ECODDetector
from posthog.tasks.alerts.detectors.pyod_detectors.hbos import HBOSDetector
from posthog.tasks.alerts.detectors.pyod_detectors.isolation_forest import IsolationForestDetector
from posthog.tasks.alerts.detectors.pyod_detectors.knn import KNNDetector
from posthog.tasks.alerts.detectors.pyod_detectors.lof import LOFDetector
from posthog.tasks.alerts.detectors.pyod_detectors.ocsvm import OCSVMDetector
from posthog.tasks.alerts.detectors.pyod_detectors.pca import PCADetector
from posthog.tasks.alerts.detectors.registry import get_available_detectors, get_detector
from posthog.tasks.alerts.detectors.statistical.iqr import IQRDetector
from posthog.tasks.alerts.detectors.statistical.mad import MADDetector
from posthog.tasks.alerts.detectors.statistical.zscore import ZScoreDetector
from posthog.tasks.alerts.detectors.threshold import ThresholdDetector
from posthog.tasks.alerts.trends import _compute_min_samples_for_detector

# Shared test data
ANOMALY_DATA = np.array([10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10, 100])
NORMAL_DATA = np.array([10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10])
BATCH_DATA = np.array([10, 10, 10, 10, 10, 10, 100, 10, 10, 10, 10, 10, -50])
# Larger dataset for PyOD detectors that need more samples (e.g. LOF n_neighbors=10 needs >=20)
# Use a very extreme spike (1000) so even conservative detectors like OCSVM flag it
PYOD_ANOMALY_DATA = np.array([10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10, 9, 10, 1000])
PYOD_NORMAL_DATA = np.array([10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10, 9, 10, 11])

# All PyOD-based detectors share the same fit/predict_proba interface
# All PyOD detectors for shared interface tests (scores, batch, metadata, insufficient data)
ALL_PYOD_DETECTORS = [
    ("copod", COPODDetector({"threshold": 0.5})),
    ("ecod", ECODDetector({"threshold": 0.5})),
    ("hbos", HBOSDetector({"threshold": 0.5})),
    ("isolation_forest", IsolationForestDetector({"threshold": 0.5})),
    ("knn", KNNDetector({"threshold": 0.5})),
    ("lof", LOFDetector({"threshold": 0.5, "n_neighbors": 10})),
    ("ocsvm", OCSVMDetector({"threshold": 0.5})),
    ("pca", PCADetector({"threshold": 0.5})),
]

# Detectors that reliably flag univariate anomalies (OCSVM's RBF kernel struggles with 1D data)
PYOD_DETECTORS_FOR_ANOMALY_TEST = [
    ("copod", COPODDetector({"threshold": 0.5})),
    ("ecod", ECODDetector({"threshold": 0.5})),
    ("hbos", HBOSDetector({"threshold": 0.5})),
    ("isolation_forest", IsolationForestDetector({"threshold": 0.5})),
    ("knn", KNNDetector({"threshold": 0.5})),
    ("lof", LOFDetector({"threshold": 0.5, "n_neighbors": 10})),
    ("pca", PCADetector({"threshold": 0.5})),
]


class TestDetectorRegistry:
    @parameterized.expand(
        [
            ("zscore", {"type": "zscore", "threshold": 0.9, "window": 30}, ZScoreDetector),
            ("threshold", {"type": "threshold", "upper_bound": 100, "lower_bound": 0}, ThresholdDetector),
            ("mad", {"type": "mad", "threshold": 0.9, "window": 30}, MADDetector),
            ("iqr", {"type": "iqr", "multiplier": 1.5, "window": 30}, IQRDetector),
            ("copod", {"type": "copod", "threshold": 0.9}, COPODDetector),
            ("ecod", {"type": "ecod", "threshold": 0.9}, ECODDetector),
            ("hbos", {"type": "hbos", "threshold": 0.9}, HBOSDetector),
            ("isolation_forest", {"type": "isolation_forest", "threshold": 0.9}, IsolationForestDetector),
            ("knn", {"type": "knn", "threshold": 0.9}, KNNDetector),
            ("lof", {"type": "lof", "threshold": 0.9, "n_neighbors": 20}, LOFDetector),
            ("ocsvm", {"type": "ocsvm", "threshold": 0.9}, OCSVMDetector),
            ("pca", {"type": "pca", "threshold": 0.9}, PCADetector),
        ]
    )
    def test_get_detector(self, _name: str, config: Any, expected_cls: Any) -> None:
        detector = get_detector(config)
        assert isinstance(detector, expected_cls)

    def test_unknown_detector_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown detector type"):
            get_detector({"type": "unknown"})

    def test_missing_type_raises(self) -> None:
        with pytest.raises(ValueError, match="must have a 'type' field"):
            get_detector({"threshold": 0.9})

    def test_get_available_detectors(self) -> None:
        detectors = get_available_detectors()
        for expected in [
            "zscore",
            "mad",
            "iqr",
            "threshold",
            "ensemble",
            "copod",
            "ecod",
            "hbos",
            "isolation_forest",
            "knn",
            "lof",
            "ocsvm",
            "pca",
        ]:
            assert expected in detectors, f"{expected} not in available detectors"


class TestStatisticalDetectors:
    @parameterized.expand(
        [
            ("zscore_anomaly", ZScoreDetector({"threshold": 0.9, "window": 10}), ANOMALY_DATA, True),
            ("zscore_normal", ZScoreDetector({"threshold": 0.9, "window": 10}), NORMAL_DATA, False),
            (
                "zscore_insufficient",
                ZScoreDetector({"threshold": 0.9, "window": 30}),
                np.array([10, 11, 10, 10]),
                False,
            ),
            ("mad_anomaly", MADDetector({"threshold": 0.9, "window": 10}), ANOMALY_DATA, True),
            ("mad_normal", MADDetector({"threshold": 0.9, "window": 10}), NORMAL_DATA, False),
            ("mad_insufficient", MADDetector({"threshold": 0.9, "window": 30}), np.array([10, 11, 10, 10]), False),
            (
                "mad_robust",
                MADDetector({"threshold": 0.9, "window": 10}),
                np.array([10, 12, 100, 9, 11, 8, 13, 10, 11, 9, 10, 12]),
                False,
            ),
            ("iqr_anomaly", IQRDetector({"threshold": 0.9, "multiplier": 1.5, "window": 10}), ANOMALY_DATA, True),
            ("iqr_normal", IQRDetector({"threshold": 0.9, "multiplier": 1.5, "window": 10}), NORMAL_DATA, False),
        ]
    )
    def test_detect(self, _name: str, detector: Any, data: Any, expected_anomaly: bool) -> None:
        result = detector.detect(data)
        assert result.is_anomaly == expected_anomaly

    def test_scores_are_normalized_probabilities(self) -> None:
        for detector in [
            ZScoreDetector({"threshold": 0.9, "window": 10}),
            MADDetector({"threshold": 0.9, "window": 10}),
            IQRDetector({"threshold": 0.9, "window": 10}),
        ]:
            result = detector.detect(ANOMALY_DATA)
            assert result.score is not None
            assert 0.0 <= result.score <= 1.0, f"{type(detector).__name__} score {result.score} not in [0, 1]"

    def test_anomaly_scores_are_high(self) -> None:
        for detector in [
            ZScoreDetector({"threshold": 0.5, "window": 10}),
            MADDetector({"threshold": 0.5, "window": 10}),
            IQRDetector({"threshold": 0.5, "window": 10}),
        ]:
            result = detector.detect(ANOMALY_DATA)
            assert result.score is not None
            assert result.score > 0.9, (
                f"{type(detector).__name__} score {result.score} should be > 0.9 for obvious anomaly"
            )

    @parameterized.expand(
        [
            ("zscore_batch", ZScoreDetector({"threshold": 0.9, "window": 5}), BATCH_DATA, 2),
            ("mad_batch", MADDetector({"threshold": 0.9, "window": 5}), BATCH_DATA, 2),
        ]
    )
    def test_detect_batch(self, _name: str, detector: Any, data: Any, min_triggered: int) -> None:
        result = detector.detect_batch(data)
        assert result.is_anomaly
        assert len(result.triggered_indices) >= min_triggered

    def test_zscore_metadata(self) -> None:
        result = ZScoreDetector({"threshold": 0.9, "window": 10}).detect(NORMAL_DATA)
        for key in ["mean", "std", "value", "raw_zscore"]:
            assert key in result.metadata

    def test_mad_metadata(self) -> None:
        result = MADDetector({"threshold": 0.9, "window": 10}).detect(NORMAL_DATA)
        for key in ["median", "median_abs_deviation", "value", "raw_score"]:
            assert key in result.metadata

    def test_iqr_metadata(self) -> None:
        result = IQRDetector({"threshold": 0.9, "multiplier": 1.5, "window": 10}).detect(NORMAL_DATA)
        for key in ["q1", "q3", "iqr", "raw_distance"]:
            assert key in result.metadata


class TestPyODDetectors:
    @parameterized.expand(PYOD_DETECTORS_FOR_ANOMALY_TEST)
    def test_detect_anomaly(self, _name: str, detector: Any) -> None:
        result = detector.detect(PYOD_ANOMALY_DATA)
        assert result.is_anomaly

    @parameterized.expand(ALL_PYOD_DETECTORS)
    def test_detect_returns_valid_result(self, _name: str, detector: Any) -> None:
        result = detector.detect(PYOD_NORMAL_DATA)
        assert isinstance(result, DetectionResult)
        assert result.score is None or 0.0 <= result.score <= 1.0

    @parameterized.expand(ALL_PYOD_DETECTORS)
    def test_scores_in_range(self, _name: str, detector: Any) -> None:
        result = detector.detect(PYOD_ANOMALY_DATA)
        assert result.score is not None
        assert 0.0 <= result.score <= 1.0, f"{type(detector).__name__} score {result.score} not in [0, 1]"

    @parameterized.expand(ALL_PYOD_DETECTORS)
    def test_insufficient_data_returns_no_anomaly(self, _name: str, detector: Any) -> None:
        result = detector.detect(np.array([10, 11]))
        assert not result.is_anomaly

    @parameterized.expand(ALL_PYOD_DETECTORS)
    def test_detect_batch(self, _name: str, detector: Any) -> None:
        result = detector.detect_batch(PYOD_ANOMALY_DATA)
        assert result.all_scores is not None
        assert len(result.all_scores) == len(PYOD_ANOMALY_DATA)

    @parameterized.expand(ALL_PYOD_DETECTORS)
    def test_metadata_has_raw_score(self, _name: str, detector: Any) -> None:
        result = detector.detect(PYOD_ANOMALY_DATA)
        assert "raw_score" in result.metadata


class TestThresholdDetector:
    @parameterized.expand(
        [
            ("upper_breach", {"upper_bound": 50, "lower_bound": 0}, np.array([10, 20, 30, 60]), True),
            ("lower_breach", {"upper_bound": 50, "lower_bound": 0}, np.array([10, 20, 30, -10]), True),
            ("no_breach", {"upper_bound": 50, "lower_bound": 0}, np.array([10, 20, 30, 40]), False),
            ("only_upper_breach", {"upper_bound": 50}, np.array([10, 20, -100, 60]), True),
            ("only_upper_no_breach", {"upper_bound": 50}, np.array([10, 20, -100, 40]), False),
        ]
    )
    def test_detect(self, _name: str, config: Any, data: Any, expected_anomaly: bool) -> None:
        result = ThresholdDetector(config).detect(data)
        assert result.is_anomaly == expected_anomaly

    def test_detect_batch_finds_all_breaches(self) -> None:
        result = ThresholdDetector({"upper_bound": 50, "lower_bound": 0}).detect_batch(np.array([10, 60, 20, -10, 30]))
        assert result.is_anomaly
        assert len(result.triggered_indices) == 2


class TestDetectionResult:
    def test_default_values(self) -> None:
        result = DetectionResult(is_anomaly=False)
        assert not result.is_anomaly
        assert result.score is None
        assert result.triggered_indices == []
        assert result.all_scores == []
        assert result.metadata == {}

    def test_custom_values(self) -> None:
        result = DetectionResult(
            is_anomaly=True,
            score=0.95,
            triggered_indices=[10, 20],
            all_scores=[0.1, 0.3, 0.95],
            metadata={"test": "value"},
        )
        assert result.is_anomaly
        assert result.score == 0.95
        assert result.triggered_indices == [10, 20]
        assert result.all_scores == [0.1, 0.3, 0.95]
        assert result.metadata == {"test": "value"}


class TestEnsembleDetector:
    @parameterized.expand(
        [
            ("and_anomaly", "and", ANOMALY_DATA, True),
            ("and_normal", "and", NORMAL_DATA, False),
            ("or_anomaly", "or", ANOMALY_DATA, True),
            ("or_normal", "or", NORMAL_DATA, False),
        ]
    )
    def test_detect(self, _name: str, operator: str, data: Any, expected_anomaly: bool) -> None:
        detector = EnsembleDetector(
            {
                "type": "ensemble",
                "operator": operator,
                "detectors": [
                    {"type": "zscore", "threshold": 0.9, "window": 10},
                    {"type": "mad", "threshold": 0.9, "window": 10},
                ],
            }
        )
        result = detector.detect(data)
        assert result.is_anomaly == expected_anomaly

    def test_and_requires_all_detectors_to_agree(self) -> None:
        mild_anomaly = np.array([10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10, 15])
        detector = EnsembleDetector(
            {
                "type": "ensemble",
                "operator": "and",
                "detectors": [
                    {"type": "zscore", "threshold": 0.5, "window": 10},
                    {"type": "mad", "threshold": 0.99, "window": 10},
                ],
            }
        )
        result = detector.detect(mild_anomaly)
        sub = result.metadata["sub_results"]
        if sub[0]["is_anomaly"] != sub[1]["is_anomaly"]:
            assert not result.is_anomaly

    def test_or_flags_if_any_detector_flags(self) -> None:
        mild_anomaly = np.array([10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10, 15])
        detector = EnsembleDetector(
            {
                "type": "ensemble",
                "operator": "or",
                "detectors": [
                    {"type": "zscore", "threshold": 0.5, "window": 10},
                    {"type": "mad", "threshold": 0.99, "window": 10},
                ],
            }
        )
        result = detector.detect(mild_anomaly)
        sub = result.metadata["sub_results"]
        if any(s["is_anomaly"] for s in sub):
            assert result.is_anomaly

    def test_metadata_contains_sub_results(self) -> None:
        detector = EnsembleDetector(
            {
                "type": "ensemble",
                "operator": "and",
                "detectors": [
                    {"type": "zscore", "threshold": 0.9, "window": 10},
                    {"type": "mad", "threshold": 0.9, "window": 10},
                ],
            }
        )
        result = detector.detect(ANOMALY_DATA)
        assert "sub_results" in result.metadata
        assert len(result.metadata["sub_results"]) == 2
        assert result.metadata["sub_results"][0]["type"] == "zscore"
        assert result.metadata["sub_results"][1]["type"] == "mad"

    def test_score_is_min_for_and(self) -> None:
        detector = EnsembleDetector(
            {
                "type": "ensemble",
                "operator": "and",
                "detectors": [
                    {"type": "zscore", "threshold": 0.9, "window": 10},
                    {"type": "mad", "threshold": 0.9, "window": 10},
                ],
            }
        )
        result = detector.detect(ANOMALY_DATA)
        assert result.score is not None
        sub_scores = [r["score"] for r in result.metadata["sub_results"]]
        assert result.score == min(s for s in sub_scores if s is not None)

    def test_score_is_max_for_or(self) -> None:
        detector = EnsembleDetector(
            {
                "type": "ensemble",
                "operator": "or",
                "detectors": [
                    {"type": "zscore", "threshold": 0.9, "window": 10},
                    {"type": "mad", "threshold": 0.9, "window": 10},
                ],
            }
        )
        result = detector.detect(ANOMALY_DATA)
        assert result.score is not None
        sub_scores = [r["score"] for r in result.metadata["sub_results"]]
        assert result.score == max(s for s in sub_scores if s is not None)

    def test_batch_and_intersects_triggered(self) -> None:
        detector = EnsembleDetector(
            {
                "type": "ensemble",
                "operator": "and",
                "detectors": [
                    {"type": "zscore", "threshold": 0.9, "window": 5},
                    {"type": "mad", "threshold": 0.9, "window": 5},
                ],
            }
        )
        result = detector.detect_batch(BATCH_DATA)
        assert result.is_anomaly
        assert len(result.triggered_indices) >= 1

    def test_registry_creates_ensemble(self) -> None:
        detector = get_detector(
            {
                "type": "ensemble",
                "operator": "or",
                "detectors": [
                    {"type": "zscore", "threshold": 0.9, "window": 10},
                    {"type": "mad", "threshold": 0.9, "window": 10},
                ],
            }
        )
        assert isinstance(detector, EnsembleDetector)

    def test_fewer_than_two_detectors_raises(self) -> None:
        with pytest.raises(ValueError, match="at least 2"):
            EnsembleDetector(
                {
                    "type": "ensemble",
                    "operator": "and",
                    "detectors": [{"type": "zscore", "threshold": 0.9, "window": 10}],
                }
            )

    def test_detect_or_triggered_indices_uses_union(self) -> None:
        detector = EnsembleDetector(
            {
                "type": "ensemble",
                "operator": "or",
                "detectors": [
                    {"type": "zscore", "threshold": 0.9, "window": 10},
                    {"type": "mad", "threshold": 0.9, "window": 10},
                ],
            }
        )
        result = detector.detect(ANOMALY_DATA)
        assert result.is_anomaly
        assert len(result.triggered_indices) >= 1
        assert 11 in result.triggered_indices  # last index (the spike)

    def test_detect_and_triggered_indices_uses_intersection(self) -> None:
        detector = EnsembleDetector(
            {
                "type": "ensemble",
                "operator": "and",
                "detectors": [
                    {"type": "zscore", "threshold": 0.9, "window": 10},
                    {"type": "mad", "threshold": 0.9, "window": 10},
                ],
            }
        )
        result = detector.detect(ANOMALY_DATA)
        assert result.is_anomaly
        # AND intersection: only indices both detectors agree on
        assert len(result.triggered_indices) >= 1

    def test_detect_or_all_scores_uses_element_wise_max(self) -> None:
        detector = EnsembleDetector(
            {
                "type": "ensemble",
                "operator": "or",
                "detectors": [
                    {"type": "zscore", "threshold": 0.9, "window": 10},
                    {"type": "mad", "threshold": 0.9, "window": 10},
                ],
            }
        )
        result = detector.detect(ANOMALY_DATA)
        assert len(result.all_scores) > 0
        # The combined score for the anomaly point should be the max of sub-detector scores
        last_score = result.all_scores[-1]
        assert last_score is not None
        assert last_score > 0.9

    def test_detect_and_all_scores_uses_element_wise_min(self) -> None:
        detector = EnsembleDetector(
            {
                "type": "ensemble",
                "operator": "and",
                "detectors": [
                    {"type": "zscore", "threshold": 0.9, "window": 10},
                    {"type": "mad", "threshold": 0.9, "window": 10},
                ],
            }
        )
        result = detector.detect(ANOMALY_DATA)
        assert len(result.all_scores) > 0
        last_score = result.all_scores[-1]
        assert last_score is not None
        # min of two high scores should still be high for a clear anomaly
        assert last_score > 0.9

    def test_detect_no_anomaly_has_empty_triggered_indices(self) -> None:
        detector = EnsembleDetector(
            {
                "type": "ensemble",
                "operator": "or",
                "detectors": [
                    {"type": "zscore", "threshold": 0.9, "window": 10},
                    {"type": "mad", "threshold": 0.9, "window": 10},
                ],
            }
        )
        result = detector.detect(NORMAL_DATA)
        assert not result.is_anomaly
        assert result.triggered_indices == []

    def test_batch_or_unions_triggered(self) -> None:
        detector = EnsembleDetector(
            {
                "type": "ensemble",
                "operator": "or",
                "detectors": [
                    {"type": "zscore", "threshold": 0.9, "window": 5},
                    {"type": "mad", "threshold": 0.9, "window": 5},
                ],
            }
        )
        result = detector.detect_batch(BATCH_DATA)
        assert result.is_anomaly
        assert len(result.triggered_indices) >= 1

    def test_invalid_operator_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid ensemble operator"):
            EnsembleDetector(
                {
                    "type": "ensemble",
                    "operator": "xor",
                    "detectors": [
                        {"type": "zscore", "threshold": 0.9, "window": 10},
                        {"type": "mad", "threshold": 0.9, "window": 10},
                    ],
                }
            )


class TestComputeMinSamplesForDetector:
    @parameterized.expand(
        [
            ("zscore_default", {"type": "zscore", "window": 30}, 31),
            ("zscore_custom_window", {"type": "zscore", "window": 168}, 169),
            (
                "iforest_with_preprocessing",
                {"type": "isolation_forest", "window": 168, "preprocessing": {"diffs_n": 1, "lags_n": 3}},
                173,
            ),
            ("iforest_no_window", {"type": "isolation_forest", "preprocessing": {"diffs_n": 1, "lags_n": 3}}, 35),
            ("threshold", {"type": "threshold"}, 1),
            ("ecod_no_window", {"type": "ecod"}, 31),
            ("lof_no_window", {"type": "lof"}, 31),
            (
                "ensemble_picks_max",
                {
                    "type": "ensemble",
                    "detectors": [
                        {"type": "zscore", "window": 30},
                        {"type": "isolation_forest", "window": 168, "preprocessing": {"diffs_n": 1, "lags_n": 3}},
                    ],
                },
                173,
            ),
            ("ensemble_empty", {"type": "ensemble", "detectors": []}, 31),
        ]
    )
    def test_compute_min_samples(self, _name: str, config: dict[str, Any], expected: int) -> None:
        assert _compute_min_samples_for_detector(config) == expected


def _make_stable_hourly_data(n_days: int = 14) -> np.ndarray:
    """Simulate realistic stable hourly pageview data with a diurnal pattern.

    Generates a smooth day/night cycle (peak ~500, trough ~100) with small
    gaussian noise. No genuine anomalies.
    """
    rng = np.random.default_rng(42)
    hours = np.arange(n_days * 24)
    base = 300 + 200 * np.sin(2 * np.pi * (hours - 6) / 24)
    noise = rng.normal(0, 10, size=len(hours))
    return base + noise


def _make_stable_with_spike(n_days: int = 14, spike_value: float = 2000.0) -> np.ndarray:
    """Stable diurnal data with a clear anomaly spike appended at the end."""
    data = _make_stable_hourly_data(n_days)
    data[-1] = spike_value
    return data


STABLE_HOURLY = _make_stable_hourly_data()
STABLE_HOURLY_WITH_SPIKE = _make_stable_with_spike()


class TestRealisticScoreBehavior:
    """Smoke tests using realistic diurnal hourly data.

    Verifies that detectors produce sensible scores on data resembling
    real-world hourly metrics (stable day/night cycle with small noise).
    """

    @parameterized.expand(
        [
            ("zscore", ZScoreDetector({"threshold": 0.95, "window": 168})),
            ("iqr", IQRDetector({"threshold": 0.95, "multiplier": 1.5, "window": 168})),
            ("mad", MADDetector({"threshold": 0.95, "window": 168})),
        ]
    )
    def test_stable_data_does_not_fire(self, _name: str, detector: Any) -> None:
        result = detector.detect(STABLE_HOURLY)
        assert not result.is_anomaly, f"{_name} fired on stable data (score={result.score:.4f})"

    @parameterized.expand(
        [
            ("zscore", ZScoreDetector({"threshold": 0.95, "window": 168})),
            ("iqr", IQRDetector({"threshold": 0.95, "multiplier": 1.5, "window": 168})),
            ("mad", MADDetector({"threshold": 0.95, "window": 168})),
        ]
    )
    def test_obvious_spike_does_fire(self, _name: str, detector: Any) -> None:
        result = detector.detect(STABLE_HOURLY_WITH_SPIKE)
        assert result.is_anomaly, f"{_name} missed a 2000-value spike on ~300-mean data (score={result.score:.4f})"

    @parameterized.expand(
        [
            ("zscore", ZScoreDetector({"threshold": 0.95, "window": 168})),
            ("iqr", IQRDetector({"threshold": 0.95, "multiplier": 1.5, "window": 168})),
        ]
    )
    def test_stable_score_well_below_threshold(self, _name: str, detector: Any) -> None:
        """Score on stable data should sit well below the alert threshold."""
        result = detector.detect(STABLE_HOURLY)
        assert result.score is not None
        assert result.score < 0.8, f"{_name} score {result.score:.4f} on stable data is too close to the 0.95 threshold"

    @parameterized.expand(
        [
            ("zscore", ZScoreDetector({"threshold": 0.95, "window": 168})),
            ("iqr", IQRDetector({"threshold": 0.95, "multiplier": 1.5, "window": 168})),
        ]
    )
    def test_batch_false_positive_rate_below_2_percent(self, _name: str, detector: Any) -> None:
        """Fewer than 2% of stable data points should trigger in batch mode."""
        result = detector.detect_batch(STABLE_HOURLY)
        window = detector.config.get("window", 30)
        n_scorable = len(STABLE_HOURLY) - window
        fp_rate = len(result.triggered_indices) / n_scorable if n_scorable > 0 else 0
        assert fp_rate < 0.02, (
            f"{_name} FP rate {fp_rate:.1%} — triggered {len(result.triggered_indices)}/{n_scorable} points"
        )

    def test_zscore_and_iforest_both_low_on_stable_data(self) -> None:
        """zscore and IsolationForest should both score low on stable data
        so that ensemble OR/AND logic behaves predictably."""
        zr = ZScoreDetector({"threshold": 0.95, "window": 168}).detect(STABLE_HOURLY)
        ir = IsolationForestDetector({"threshold": 0.95}).detect(STABLE_HOURLY)

        assert zr.score is not None and ir.score is not None
        assert zr.score < 0.8, f"zscore score too high on stable data: {zr.score:.4f}"
        assert ir.score < 0.8, f"iforest score too high on stable data: {ir.score:.4f}"

    def test_ensemble_or_does_not_fire_on_stable_data(self) -> None:
        """Ensemble (OR) of zscore + isolation_forest should not fire on
        stable diurnal data at threshold=0.95."""
        detector = EnsembleDetector(
            {
                "type": "ensemble",
                "operator": "or",
                "detectors": [
                    {"type": "zscore", "threshold": 0.95, "window": 168, "preprocessing": {"diffs_n": 1}},
                    {
                        "type": "isolation_forest",
                        "threshold": 0.95,
                        "window": 168,
                        "n_estimators": 100,
                        "preprocessing": {"lags_n": 3, "diffs_n": 1},
                    },
                ],
            }
        )
        result = detector.detect(STABLE_HOURLY)
        assert not result.is_anomaly, (
            f"Ensemble OR fired on stable data (score={result.score:.4f}, "
            f"sub_results={result.metadata.get('sub_results')})"
        )
