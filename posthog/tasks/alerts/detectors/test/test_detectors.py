from typing import Any

import pytest
from unittest.mock import patch

import numpy as np
from parameterized import parameterized
from pyod.models.mad import MAD
from scipy.special import erf

from posthog.schema import DetectorConfig

from posthog.tasks.alerts.detector import _compute_min_samples_for_detector
from posthog.tasks.alerts.detectors import normalizers
from posthog.tasks.alerts.detectors.base import BaseDetector, DetectionResult
from posthog.tasks.alerts.detectors.ensemble import EnsembleDetector
from posthog.tasks.alerts.detectors.normalizers import (
    FitError,
    Normalizer,
    QuantileNormalizer,
    min_quantile_training_scores,
    register_normalizer,
)
from posthog.tasks.alerts.detectors.preprocessing import moving_average
from posthog.tasks.alerts.detectors.pyod_detectors.base_pyod import BasePyODDetector
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

    @parameterized.expand(
        [
            ("zscore", ZScoreDetector),
            ("iqr", IQRDetector),
            ("mad", MADDetector),
        ]
    )
    def test_rejects_data_that_only_covers_the_undiffed_window(self, _name: str, detector_cls: Any) -> None:
        # With diffs_n=1, the training window needs one extra raw point beyond
        # window+1, otherwise first_difference()'s synthetic leading value (a
        # zero) would land inside the fit window and silently shrink it by one
        # genuine point. window+1 must be rejected outright, not scored — a
        # scored-but-not-anomalous flat series would also report is_anomaly=False,
        # so assert the rejection path specifically via its empty metadata/score.
        data = np.array([10, 10, 10, 10, 10, 10])  # len == window + 1
        detector = detector_cls({"threshold": 0.9, "window": 5, "preprocessing": {"diffs_n": 1}})
        result = detector.detect(data)
        assert result.is_anomaly is False
        assert result.score is None
        assert result.metadata == {}

    @parameterized.expand(
        [
            # zscore's mean/std and MAD's median tolerate the flat baseline BATCH_DATA
            # uses; IQR's fences collapse to zero width on a flat window (a separate,
            # pre-existing gap in IQR's zero-IQR handling), so it needs a baseline with
            # some spread.
            ("zscore", ZScoreDetector, BATCH_DATA, 6),
            ("iqr", IQRDetector, np.array([10, 8, 12, 9, 11, 10, 8, 12, 9, 11, 100, 8, 12, 9]), 10),
            ("mad", MADDetector, BATCH_DATA, 6),
        ]
    )
    def test_batch_triggered_indices_align_with_raw_series_when_diffing(
        self, _name: str, detector_cls: Any, data: Any, spike_index: int
    ) -> None:
        # detect_batch trims preprocess()'s synthetic leading point internally, so the
        # first scorable position is window + diffs_n + offset - 1, not window alone.
        # triggered_indices/all_scores must be shifted back so callers (which map
        # indices to dates on the original series) don't get an off-by-one against
        # every date after the first.
        detector = detector_cls({"threshold": 0.9, "window": 5, "preprocessing": {"diffs_n": 1}})
        result = detector.detect_batch(data)
        assert len(result.all_scores) == len(data)
        assert result.all_scores[:6] == [None] * 6
        assert result.all_scores[6] is not None
        assert all(0 <= i < len(data) for i in result.triggered_indices)
        # A diffed detector may also flag the reversion right after the spike, but
        # never an index outside the raw series.
        assert spike_index in result.triggered_indices

    @parameterized.expand(
        [
            ("zscore", ZScoreDetector, np.array([9, 11, 10, 9, 11, 10, 30, 11, 14])),
            ("iqr", IQRDetector, np.array([9, 11, 10, 9, 11, 10, 30, 11, 20])),
            ("mad", MADDetector, np.array([9, 11, 10, 9, 11, 10, 30, 11, 14])),
        ]
    )
    def test_detect_honors_training_offset_n(self, _name: str, detector_cls: Any, data: Any) -> None:
        # Changing training_offset_n must change which historical points enter the
        # training window: a spike that falls inside the offset=1 window but outside
        # the offset=4 one must flip whether the same trailing point is flagged.
        offset_1 = detector_cls({"threshold": 0.9, "window": 5, "training_offset_n": 1})
        offset_4 = detector_cls({"threshold": 0.9, "window": 5, "training_offset_n": 4})
        assert offset_1.detect(data).is_anomaly is False
        assert offset_4.detect(data).is_anomaly is True

    @parameterized.expand(
        [
            (f"{name}_{fields}", detector_type, detector_cls, explicit)
            for name, detector_type, detector_cls in (
                ("zscore", "zscore", ZScoreDetector),
                ("iqr", "iqr", IQRDetector),
                ("mad", "mad", MADDetector),
            )
            for fields, explicit in (
                ("preprocessing_none", {"window": 5, "preprocessing": None}),
                ("schema_defaults", {}),
            )
        ]
    )
    def test_handles_explicit_none_config_values(
        self, _name: str, detector_type: str, detector_cls: Any, explicit: dict[str, Any]
    ) -> None:
        # Serializers round-trip a detector_config through the schema's model_dump(), which
        # writes every unset field as an explicit None (not merely omitted). `config.get(key,
        # default)` only falls back when the key is absent, so a present-but-None value used
        # to reach detect()/detect_batch()/fit() and crash on arithmetic or comparison.
        config = DetectorConfig.model_validate({"type": detector_type, **explicit}).model_dump()
        detector = detector_cls(config)
        data = np.array([10.0, 12.0, 11.0, 13.0] * 15 + [500.0])
        assert detector.detect(data).score is not None
        assert detector.detect_batch(data).all_scores[-1] is not None
        detector.fit(data[:-1])

    @parameterized.expand(
        [
            ("zero", {"multiplier": 0.0}, 2.25, True),
            ("none", {"multiplier": None}, 4.5, False),
            ("omitted", {}, 4.5, False),
        ]
    )
    def test_iqr_multiplier_sets_fences(
        self, _name: str, multiplier: dict[str, Any], upper_fence: float, is_anomaly: bool
    ) -> None:
        # The training window [0, 1, 2, 3] has q1=0.75, q3=2.25 and iqr=1.5, so 4.0 is outside only the zero fence.
        data = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
        detector = IQRDetector({"window": 4, **multiplier})

        result = detector.detect(data)
        assert result.metadata["upper_fence"] == upper_fence
        assert result.is_anomaly is is_anomaly
        assert detector.detect_batch(data).is_anomaly is is_anomaly
        assert detector.fit(data[:-1]).params["upper_fence"] == upper_fence

    @parameterized.expand(
        [
            (f"{name}_diffs_{diffs_n}", detector_type, detector_cls, diffs_n)
            for name, detector_type, detector_cls in (
                ("zscore", "zscore", ZScoreDetector),
                ("iqr", "iqr", IQRDetector),
                ("mad", "mad", MADDetector),
            )
            for diffs_n in (0, 1, 2)
        ]
    )
    def test_detect_scores_the_sample_count_the_check_fetches(
        self, _name: str, detector_type: str, detector_cls: Any, diffs_n: int
    ) -> None:
        # A check only fetches _compute_min_samples_for_detector() points, so any detector
        # demanding more silently returns the _validate_data rejection (score None) forever
        # instead of firing. preprocess_data treats diffs_n as a boolean toggle, so a
        # detector counting it as a pass count over-reserves once diffs_n > 1 and drifts
        # out of agreement with the fetch.
        window = 30
        config = {"type": detector_type, "window": window, "preprocessing": {"diffs_n": diffs_n}}
        data = np.array([10.0] * (_compute_min_samples_for_detector(config) - 1) + [500.0])
        result = detector_cls({"threshold": 0.9, "window": window, "preprocessing": {"diffs_n": diffs_n}}).detect(data)
        assert result.score is not None


class TestMovingAverageSmoothing:
    def test_smoothed_value_is_stable_once_computed(self) -> None:
        # moving_average recomputes over the whole series on every call, since each
        # detector check re-preprocesses the full historical window it fetches. A
        # centered window pads the newest point with a replica of itself, so its
        # smoothed value is provisional and silently changes once real future points
        # arrive - a look-ahead bug for anything scored incrementally. Causal
        # (trailing) smoothing must give a point the same smoothed value regardless
        # of how much data arrives after it.
        data = np.array([20.0, 19.0, 21.0, 2.0, 21.0, 20.0, 19.0, 21.0])
        first_look = moving_average(data[:4], window=3)[-1]
        later_look = moving_average(data, window=3)[3]
        assert first_look == later_look

    def test_anomaly_attributed_to_the_drop_not_the_rebound(self) -> None:
        # Regression for a live gateway-volume alert: with the old centered,
        # edge-padded moving_average, a single-point cliff scored as non-anomalous
        # at the bucket where it happened (score 0.0) and only crossed the threshold
        # two buckets later, once the cliff was fully interior to the window and the
        # recovery had entered it too - attributing the anomaly to a normal-looking
        # rebound point instead of the actual drop.
        baseline = [20, 19, 21] * 11
        data = np.array(baseline, dtype=float)
        cliff_index = len(data) - 6
        data[cliff_index] = 2.0
        data[cliff_index + 1] = 21.0

        detector = ZScoreDetector({"threshold": 0.9, "window": 10, "preprocessing": {"smooth_n": 3, "diffs_n": 1}})
        result = detector.detect_batch(data)

        assert cliff_index in result.triggered_indices
        assert cliff_index + 2 not in result.triggered_indices


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

    @parameterized.expand(
        [
            # The AI detector holds no training point back, so its lookback is the exact requirement.
            ("hour", "hour", 169),
            ("day", "day", 90),
            ("week", "week", 52),
            ("month", "month", 24),
            ("no_interval", None, 90),
        ]
    )
    def test_llm_lookback_follows_the_interval(self, _name: str, interval: str | None, expected: int) -> None:
        assert _compute_min_samples_for_detector({"type": "llm"}, interval) == expected


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
            ("zscore", ZScoreDetector({"threshold": 0.95, "window": 168, "preprocessing": {"diffs_n": 1}})),
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
            ("zscore", ZScoreDetector({"threshold": 0.95, "window": 168, "preprocessing": {"diffs_n": 1}})),
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
        zr = ZScoreDetector({"threshold": 0.95, "window": 168, "preprocessing": {"diffs_n": 1}}).detect(STABLE_HOURLY)
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


_PARITY_PREPROCESSING = [
    ("raw", {}),
    ("diffs", {"diffs_n": 1}),
    ("lags", {"lags_n": 3}),
    ("smooth", {"smooth_n": 3}),
    ("diffs_lags_smooth", {"diffs_n": 1, "lags_n": 5, "smooth_n": 3}),
]


def _parity_config(
    detector_type: str, preprocessing: dict[str, Any], training_offset: int, normalizer: str | None = None
) -> dict[str, Any]:
    shared: dict[str, Any] = {"preprocessing": preprocessing, "training_offset_n": training_offset}
    if normalizer:
        shared["normalizer"] = normalizer
    if detector_type == "ensemble":
        return {
            "type": "ensemble",
            "operator": "or",
            "detectors": [{"type": "zscore", "window": 30, **shared}, {"type": "knn", **shared}],
        }
    if detector_type == "threshold":
        return {"type": "threshold", "upper_bound": 150, **shared}
    return {"type": detector_type, "window": 30, **shared}


class TestFitAndScore:
    @parameterized.expand(
        [
            (
                f"{detector_type}_{name}_offset_{offset}_{normalizer or 'default'}",
                detector_type,
                preprocessing,
                offset,
                normalizer,
            )
            for detector_type in get_available_detectors()
            for name, preprocessing in _PARITY_PREPROCESSING
            for offset in (1, 3)
            for normalizer in (None, "quantile")
        ]
    )
    def test_scoring_a_fitted_artifact_matches_detect(
        self, _name: str, detector_type: str, preprocessing: dict[str, Any], offset: int, normalizer: str | None
    ) -> None:
        data = np.random.default_rng(0).normal(100, 10, size=80)
        data[-1] = 200.0
        detector = get_detector(_parity_config(detector_type, preprocessing, offset, normalizer))

        expected = detector.detect(data)
        scored = detector.score(detector.fit(data[:-1]), data[-1 - detector.context_buckets() :])

        assert len(scored.all_scores) == 1
        assert scored.score == pytest.approx(expected.score)
        assert scored.is_anomaly is expected.is_anomaly

    def test_ensemble_scores_each_bucket_through_its_sub_artifacts(self) -> None:
        detector = get_detector(_parity_config("ensemble", {"diffs_n": 1, "lags_n": 5, "smooth_n": 3}, 1))
        data = np.random.default_rng(1).normal(100, 10, size=80)
        data[-2] = 400.0

        artifact = detector.fit(data[:60])
        scored = detector.score(artifact, data[60 - detector.context_buckets() :])

        assert [child.detector_type for child in artifact.children] == ["zscore", "knn"]
        assert artifact.children[1].model_bytes
        assert detector.context_buckets() == 8
        assert len(scored.all_scores) == len(scored.all_metadata) == 20
        assert 18 in scored.triggered_indices
        assert [sub["type"] for sub in scored.all_metadata[18]["sub_results"]] == ["zscore", "knn"]


_SCORE_BASED_DETECTORS = [
    detector_type for detector_type in get_available_detectors() if detector_type not in ("ensemble", "threshold")
]


def _legacy_score(detector: BaseDetector, train: np.ndarray, point: float) -> float:
    """The score of each detector before the shared normalizer, rebuilt from its original formula."""
    if isinstance(detector, ZScoreDetector):
        mean, std = train.mean(), train.std()
        train_z = np.abs((train - mean) / std)
        return float(np.clip((abs(point - mean) / std - train_z.min()) / (train_z.max() - train_z.min()), 0, 1))
    if isinstance(detector, IQRDetector):
        q1, q3 = np.percentile(train, 25), np.percentile(train, 75)
        iqr = q3 - q1
        lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        distances = np.where(train < lower, (lower - train) / iqr, np.where(train > upper, (train - upper) / iqr, 0.0))
        distance = (lower - point) / iqr if point < lower else (point - upper) / iqr if point > upper else 0.0
        return float(np.clip(erf((distance - distances.mean()) / distances.std() / np.sqrt(2)), 0, 1))
    assert isinstance(detector, MADDetector | BasePyODDetector)
    model = MAD() if isinstance(detector, MADDetector) else detector._build_model(n_samples=len(train))
    model.fit(train.reshape(-1, 1))
    return float(model.predict_proba(np.array([[point]]))[0, 1])


class TestNormalizers:
    @parameterized.expand(
        [
            ("ties_the_largest_training_score", [1.0, 2.0, 3.0, 3.0], 3.0, 0.5),
            ("above_every_training_score", [1.0, 2.0, 3.0, 3.0], 3.5, 1.0),
            ("below_every_training_score", [1.0, 2.0, 3.0, 3.0], 0.5, 0.0),
            ("constant_training_same_value", [2.0, 2.0, 2.0], 2.0, 0.0),
            ("constant_training_other_value", [2.0, 2.0, 2.0], 2.1, 1.0),
        ]
    )
    def test_quantile_counts_training_scores_strictly_below(
        self, _name: str, training: list[float], raw_score: float, expected: float
    ) -> None:
        normalizer = QuantileNormalizer()
        assert normalizer.score(normalizer.fit(np.array(training), threshold=0.0), raw_score) == expected

    @parameterized.expand(
        [
            ("minmax_shifts_like_pyod", "minmax", [1.0, 1.0, 1.0], 1.5, 0.5),
            ("minmax_treats_float_error_as_a_zero_range", "minmax", [1.0, 1.0 + 2e-16], 1.5, 0.5),
            ("minmax_step_steps_like_zscore", "minmax_step", [1.0, 1.0, 1.0], 1.5, 1.0),
            ("minmax_step_at_the_constant", "minmax_step", [1.0, 1.0, 1.0], 1.0, 0.0),
        ]
    )
    def test_minmax_with_a_zero_range(
        self, _name: str, method: str, training: list[float], raw_score: float, expected: float
    ) -> None:
        normalizer = normalizers.get_normalizer(method)
        assert normalizer.score(normalizer.fit(np.array(training), threshold=0.9), raw_score) == pytest.approx(expected)

    @parameterized.expand([(0.99, 1, 100), (0.98, 1, 50), (0.95, 1, 20), (0.95, 3, 60), (0.99, 3, 300)])
    def test_quantile_minimum_training_size(self, threshold: float, k: int, expected: int) -> None:
        assert min_quantile_training_scores(threshold, k) == expected

    @parameterized.expand([(detector_type,) for detector_type in _SCORE_BASED_DETECTORS])
    def test_default_normalizer_keeps_the_legacy_score(self, detector_type: str) -> None:
        data = np.random.default_rng(3).normal(100, 10, size=31)
        data[-1] = 125.0
        detector = get_detector({"type": detector_type, "window": 30, "threshold": 0.9})

        assert detector.detect(data).score == pytest.approx(_legacy_score(detector, data[:-1], data[-1]))

    @parameterized.expand([(detector_type,) for detector_type in _SCORE_BASED_DETECTORS])
    def test_too_few_training_scores_for_the_quantile_threshold_is_a_warm_up(self, detector_type: str) -> None:
        data = np.random.default_rng(4).normal(100, 10, size=80)
        data[-1] = 1000.0
        # 0.99 needs 100 training scores, and 80 buckets give fewer.
        detector = get_detector({"type": detector_type, "window": 60, "threshold": 0.99, "normalizer": "quantile"})

        with pytest.raises(FitError):
            detector.fit(data[:-1])
        result = detector.detect(data)
        assert (result.is_anomaly, result.score) == (False, None)
        assert detector.detect_batch(data).triggered_indices == []

    @parameterized.expand([(detector_type,) for detector_type in _SCORE_BASED_DETECTORS])
    def test_quantile_flag_rate_on_held_out_data_follows_the_threshold(self, detector_type: str) -> None:
        rng = np.random.default_rng(0)
        train, held_out = rng.normal(100, 10, size=400), rng.normal(100, 10, size=1000)
        threshold = 0.95
        detector = get_detector(
            {"type": detector_type, "window": 400, "threshold": threshold, "normalizer": "quantile"}
        )

        flag_rate = len(detector.score(detector.fit(train), held_out).triggered_indices) / len(held_out)

        if detector_type == "iqr":
            # Points inside the fences all have a distance of 0, so the tie caps the rate below 1 - threshold.
            assert flag_rate <= 1 - threshold
        elif detector_type == "ocsvm":
            # The SVM scores its own training points lower than new points, so new points flag more often.
            assert flag_rate <= 3 * (1 - threshold)
        else:
            assert flag_rate == pytest.approx(1 - threshold, abs=0.02)

    @parameterized.expand([(detector_type,) for detector_type in _SCORE_BASED_DETECTORS])
    def test_a_registered_normalizer_scores_every_detector(self, detector_type: str) -> None:
        class QuarterNormalizer(Normalizer):
            name = "quarter"

            def _fit(self, raw_scores: np.ndarray) -> dict[str, Any]:
                return {"value": 0.25}

            def score(self, params: dict[str, Any], raw_score: float) -> float:
                return params["value"]

        data = np.random.default_rng(5).normal(100, 10, size=80)
        with patch.dict(normalizers._NORMALIZERS):
            register_normalizer(QuarterNormalizer)
            detector = get_detector({"type": detector_type, "window": 30, "normalizer": "quarter"})
            result = detector.detect(data)
            scored = detector.score(detector.fit(data[:-1]), data[-1 - detector.context_buckets() :])

        assert (result.score, result.metadata["normalizer"]) == (0.25, "quarter")
        assert (scored.all_scores, scored.all_metadata[0]["normalizer"]) == ([0.25], "quarter")

    def test_an_ensemble_gives_its_normalizer_to_every_sub_detector(self) -> None:
        detector = get_detector(
            {
                "type": "ensemble",
                "operator": "or",
                "normalizer": "quantile",
                "detectors": [{"type": "zscore", "window": 30}, {"type": "iqr", "window": 30}, {"type": "knn"}],
            }
        )

        artifact = detector.fit(np.random.default_rng(6).normal(100, 10, size=80))

        assert [child.params["normalizer"]["method"] for child in artifact.children] == ["quantile"] * 3
