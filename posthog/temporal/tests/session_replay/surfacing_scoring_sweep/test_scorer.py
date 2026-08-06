"""Integration tests for `surfacing_scoring_sweep.scorer`.

Boosters come from the shared `surfacing_booster_path` fixture (binary:logistic
on `FEATURE_RANGES.keys()`) or are trained inline via `train_synthetic_booster`
when a test needs a custom shape (regression objective, custom feature set, etc).

Singleton cleanup is autouse from conftest.py — tests just set env vars and call.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from unittest import mock

import numpy as np
import pandas as pd
import xgboost as xgb

from posthog.temporal.session_replay.surfacing_scoring_sweep import scorer as scorer_mod
from posthog.temporal.session_replay.surfacing_scoring_sweep.features import FEATURE_RANGES, MissingFeatureRangeError
from posthog.temporal.session_replay.surfacing_scoring_sweep.scorer import (
    ScoreRangeError,
    _load_booster,
    get_feature_names,
    predict,
    warmup,
    warmup_best_effort,
)
from posthog.temporal.tests.session_replay.surfacing_scoring_sweep.conftest import (
    train_synthetic_booster,
    wire_booster_as_s3,
)

_TRAINING_FEATURE_NAMES: tuple[str, ...] = tuple(FEATURE_RANGES.keys())


@pytest.fixture
def regression_model_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """`reg:squarederror` booster with labels in [0, 100] — predicts > 1, trips ScoreRangeError."""
    rng = np.random.default_rng(7)
    data = rng.random((128, len(_TRAINING_FEATURE_NAMES))).astype(np.float32)
    df = pd.DataFrame(data, columns=list(_TRAINING_FEATURE_NAMES))
    labels = (df[_TRAINING_FEATURE_NAMES[0]] * 100).to_numpy()  # [0, 100] → predicts well above 1
    dmat = xgb.DMatrix(df, label=labels, feature_names=list(_TRAINING_FEATURE_NAMES))
    booster = xgb.train(
        {"objective": "reg:squarederror", "max_depth": 2, "eta": 0.5, "verbosity": 0},
        dmat,
        num_boost_round=2,
    )
    model_path = tmp_path / "regression_model.ubj"
    booster.save_model(str(model_path))
    wire_booster_as_s3(monkeypatch, model_path)
    return model_path


class TestModelLoading:
    def test_load_booster_loads_from_s3(self, surfacing_booster_path: Path) -> None:
        booster = _load_booster()
        # If load failed, _load_booster would raise; getting a Booster back is
        # the main assertion. num_features is a cheap sanity probe.
        assert booster.num_features() == len(_TRAINING_FEATURE_NAMES)

    def test_load_booster_caches_singleton(self, surfacing_booster_path: Path) -> None:
        # The hot path (every chunk's predict) hits this. It must hand back
        # the same Booster object on every call, not re-load from disk.
        first = _load_booster()
        second = _load_booster()
        third = _load_booster()
        assert first is second is third

    def test_load_booster_thread_safe(self, surfacing_booster_path: Path) -> None:
        # If `max_concurrent_activities > 1`, the first chunks contend on
        # _load_booster simultaneously. The double-checked lock must produce
        # exactly one booster. We probe for that by snapshotting the cache
        # mid-flight from many threads and asserting they all converge.
        boosters = []
        barrier = threading.Barrier(8)

        def worker() -> None:
            barrier.wait()
            boosters.append(_load_booster())

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(boosters) == 8
        assert all(b is boosters[0] for b in boosters)

    def test_warmup_loads_eagerly(self, surfacing_booster_path: Path) -> None:
        assert scorer_mod._BOOSTER is None
        warmup()
        assert scorer_mod._BOOSTER is not None

    def test_load_booster_raises_when_s3_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # If S3 returns None (object missing), we must raise loudly so the
        # operator sees the misconfig instead of getting silent NaN scores.
        monkeypatch.setenv("SESSION_SURFACING_MODEL_S3_URI", "s3://bucket/missing.ubj")
        monkeypatch.setattr(
            "posthog.temporal.session_replay.surfacing_scoring_sweep.scorer.object_storage.read_bytes",
            lambda key, *, bucket=None: None,
        )
        with pytest.raises(FileNotFoundError):
            _load_booster()

    def test_load_booster_raises_when_no_env_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SESSION_SURFACING_MODEL_S3_URI", raising=False)
        with pytest.raises(scorer_mod.ModelNotConfiguredError):
            _load_booster()

    def test_warmup_best_effort_returns_true_on_success(self, surfacing_booster_path: Path) -> None:
        assert warmup_best_effort() is True
        assert scorer_mod._BOOSTER is not None

    def test_warmup_best_effort_does_not_crash_when_no_env_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The session-replay worker calls this on boot; an unset model URI must
        # NOT take the whole worker down — it logs and returns False.
        monkeypatch.delenv("SESSION_SURFACING_MODEL_S3_URI", raising=False)
        assert warmup_best_effort() is False
        assert scorer_mod._BOOSTER is None

    def test_warmup_best_effort_does_not_crash_when_model_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SESSION_SURFACING_MODEL_S3_URI", "s3://bucket/missing.ubj")
        monkeypatch.setattr(
            "posthog.temporal.session_replay.surfacing_scoring_sweep.scorer.object_storage.read_bytes",
            lambda key, *, bucket=None: None,
        )
        assert warmup_best_effort() is False
        assert scorer_mod._BOOSTER is None

    def test_load_booster_fetches_once_and_caches(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # The fetch is cached in _S3_CACHED_PATH; a second _load_booster call
        # must not re-fetch from S3 (would defeat the per-pod-once design).
        booster = train_synthetic_booster(_TRAINING_FEATURE_NAMES, seed=11)
        src = tmp_path / "from_s3.ubj"
        booster.save_model(str(src))
        payload = src.read_bytes()

        monkeypatch.setenv("SESSION_SURFACING_MODEL_S3_URI", "s3://my-bucket/path/to/model.ubj")
        with mock.patch(
            "posthog.temporal.session_replay.surfacing_scoring_sweep.scorer.object_storage.read_bytes",
            return_value=payload,
        ) as read_bytes_mock:
            loaded = _load_booster()
            _load_booster()
        assert loaded.num_features() == len(_TRAINING_FEATURE_NAMES)
        read_bytes_mock.assert_called_once_with("path/to/model.ubj", bucket="my-bucket")

    @pytest.mark.parametrize("uri", ["model.ubj", "s3://only-bucket", "s3:///key-only", "http://wrong/scheme"])
    def test_load_booster_rejects_malformed_s3_uri(self, monkeypatch: pytest.MonkeyPatch, uri: str) -> None:
        monkeypatch.setenv("SESSION_SURFACING_MODEL_S3_URI", uri)
        with pytest.raises(ValueError, match="SESSION_SURFACING_MODEL_S3_URI"):
            _load_booster()


class TestGetFeatureNames:
    def test_returns_booster_feature_names(self, surfacing_booster_path: Path) -> None:
        # The booster IS the source of truth — get_feature_names must hand
        # back exactly what training pinned in the model file, in order.
        names = get_feature_names()
        assert names == _TRAINING_FEATURE_NAMES

    def test_triggers_lazy_load_on_first_call(self, surfacing_booster_path: Path) -> None:
        assert scorer_mod._BOOSTER is None
        get_feature_names()
        assert scorer_mod._BOOSTER is not None

    def test_caches_after_first_load(self, surfacing_booster_path: Path) -> None:
        # Per-predict overhead matters; `_FEATURE_NAMES` is a cached tuple so
        # we don't pay a C++ -> Python attr crossing on every chunk.
        first = get_feature_names()
        second = get_feature_names()
        assert first is second  # exact same tuple object

    def test_load_raises_when_booster_has_features_outside_ranges(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A retrained booster that introduces a feature without a
        # FEATURE_RANGES entry must fail at warmup, not on the first chunk —
        # otherwise the validator wouldn't know what to bounds-check against
        # and bad CH output for the new column would slip through silently.
        booster = train_synthetic_booster(("event_rate", "bogus_new_feature"), seed=0, rows=64)
        model_path = tmp_path / "uncovered_model.ubj"
        booster.save_model(str(model_path))
        wire_booster_as_s3(monkeypatch, model_path)

        with pytest.raises(MissingFeatureRangeError, match="bogus_new_feature"):
            _load_booster()


class TestPredict:
    def test_predict_returns_scores_in_unit_interval(
        self, surfacing_booster_path: Path, feature_frame: pd.DataFrame
    ) -> None:
        # Booster was trained binary:logistic — every prediction must land in [0, 1].
        scores = predict(feature_frame)

        assert isinstance(scores, np.ndarray)
        assert scores.dtype == np.float32
        assert scores.shape == (len(feature_frame),)
        assert scores.min() >= 0.0
        assert scores.max() <= 1.0

    def test_predict_handles_nan_features(self, surfacing_booster_path: Path, feature_frame: pd.DataFrame) -> None:
        # Our SQL produces NaN when denominators are zero (nullIf(...)).
        # XGBoost handles NaN natively; predict must not raise or crash.
        feature_frame.loc[0, "event_rate"] = float("nan")
        feature_frame.loc[1, "mouse_velocity_mean"] = float("nan")

        scores = predict(feature_frame)

        assert np.isfinite(scores).all()

    def test_predict_with_id_columns_alongside_features(
        self, surfacing_booster_path: Path, feature_frame: pd.DataFrame
    ) -> None:
        # The CH SELECT returns id columns + features mixed together. predict
        # delegates to feature_matrix, which strips ids; this end-to-end test
        # protects that contract.
        df = feature_frame.copy()
        df["team_id"] = 42
        df["session_id"] = "00000000-0000-7000-0000-000000000000"
        df["distinct_id"] = "user-1"
        df["min_first_timestamp"] = pd.Timestamp("2026-01-01")

        scores = predict(df)

        assert scores.shape == (len(feature_frame),)

    def test_predict_is_invariant_to_input_column_order(
        self, surfacing_booster_path: Path, feature_frame: pd.DataFrame
    ) -> None:
        # We pass feature_names into DMatrix so XGBoost reorders by name, not
        # position. That means we get the same scores regardless of how the
        # caller orders the columns — a regression here would silently mis-score.
        scores_a = predict(feature_frame)
        shuffled = feature_frame.loc[:, list(reversed(_TRAINING_FEATURE_NAMES))]
        scores_b = predict(shuffled)

        np.testing.assert_array_equal(scores_a, scores_b)

    def test_predict_empty_dataframe(self, surfacing_booster_path: Path) -> None:
        df = pd.DataFrame(columns=pd.Index(_TRAINING_FEATURE_NAMES))
        scores = predict(df)
        assert scores.shape == (0,)


class TestPredictGuards:
    def test_score_out_of_range_raises(self, regression_model_path: Path, feature_frame: pd.DataFrame) -> None:
        # Training a regression model with labels in [0, 100] → predictions
        # well above 1. predict must reject this loudly rather than write
        # garbage scores into ClickHouse.
        with pytest.raises(ScoreRangeError, match=r"outside \[0, 1\]"):
            predict(feature_frame)
