"""Integration tests for `surfacing_scoring_sweep.scorer`.

These tests use a real XGBoost booster trained in-memory by the
`trained_model_path` fixture, saved to disk, and loaded through the same
code path the production worker hits. No mocking of xgboost itself —
the goal is to catch regressions in the actual load + predict path.
"""

from __future__ import annotations

import threading
from collections.abc import Generator
from pathlib import Path

import pytest

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
)

# Test schema: the runtime range contract is the source of truth for what
# `validate_features` knows how to bounds-check, so a booster trained against
# this set is exercising the production load path verbatim.
_TRAINING_FEATURE_NAMES: tuple[str, ...] = tuple(FEATURE_RANGES.keys())


def _synthetic_training_frame(
    rows: int, *, seed: int, feature_names: tuple[str, ...] = _TRAINING_FEATURE_NAMES
) -> pd.DataFrame:
    """Return a DataFrame with the given feature columns and uniform-random values.

    Values are deliberately kept in [0, 1] so the same frame works for any
    feature, including the strict-ratio columns. Labels are a simple linear
    rule on the first feature so the trained booster has a real signal and
    won't degenerate to a constant prediction.
    """
    rng = np.random.default_rng(seed)
    data = rng.random((rows, len(feature_names))).astype(np.float32)
    df = pd.DataFrame(data, columns=pd.Index(feature_names))
    df["__label__"] = (df[feature_names[0]] > 0.5).astype(np.int32)
    return df


def _train_booster(
    df: pd.DataFrame,
    *,
    feature_names: tuple[str, ...] = _TRAINING_FEATURE_NAMES,
    objective: str = "binary:logistic",
) -> xgb.Booster:
    """Train a tiny 2-tree booster on `df` with the given features and column `__label__`."""
    features = df[list(feature_names)]
    labels = df["__label__"].to_numpy()
    dmat = xgb.DMatrix(features, label=labels, feature_names=list(feature_names))
    return xgb.train(
        {"objective": objective, "max_depth": 2, "eta": 0.5, "verbosity": 0},
        dmat,
        num_boost_round=2,
    )


def _reset_booster_singleton() -> None:
    """Clear the scorer module's cached booster + feature_names so the next
    `_load_booster()` call re-reads from disk + repopulates the cache."""
    scorer_mod._BOOSTER = None
    scorer_mod._FEATURE_NAMES = None


@pytest.fixture
def trained_model_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[Path, None, None]:
    """Train + persist a real binary:logistic booster, point env var at it, reset singleton.

    Cleanup: the booster cache in `scorer` is reset both before and after
    so test ordering doesn't leak a model trained for a different test.
    """
    df = _synthetic_training_frame(rows=128, seed=42)
    booster = _train_booster(df)
    model_path = tmp_path / "model.ubj"
    booster.save_model(str(model_path))

    monkeypatch.setenv("SESSION_INTERESTINGNESS_MODEL_PATH", str(model_path))
    _reset_booster_singleton()
    yield model_path
    _reset_booster_singleton()


@pytest.fixture
def regression_model_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[Path, None, None]:
    """Train a `reg:squarederror` booster — used to exercise the out-of-range guard.

    Regression objective emits raw scores whose magnitude depends on the
    label range; we deliberately train with labels well outside [0, 1] so
    the model produces predictions that should trigger `ScoreRangeError`.
    """
    df = _synthetic_training_frame(rows=128, seed=7)
    df["__label__"] = (df[_TRAINING_FEATURE_NAMES[0]] * 100).astype(np.float32)  # labels in [0, 100]
    booster = _train_booster(df, objective="reg:squarederror")
    model_path = tmp_path / "regression_model.ubj"
    booster.save_model(str(model_path))

    monkeypatch.setenv("SESSION_INTERESTINGNESS_MODEL_PATH", str(model_path))
    _reset_booster_singleton()
    yield model_path
    _reset_booster_singleton()


class TestModelLoading:
    def test_load_booster_loads_from_env_var_path(self, trained_model_path: Path) -> None:
        booster = _load_booster()
        # If load failed, _load_booster would raise; getting a Booster back is
        # the main assertion. num_features is a cheap sanity probe.
        assert booster.num_features() == len(_TRAINING_FEATURE_NAMES)

    def test_load_booster_caches_singleton(self, trained_model_path: Path) -> None:
        # The hot path (every chunk's predict) hits this. It must hand back
        # the same Booster object on every call, not re-load from disk.
        first = _load_booster()
        second = _load_booster()
        third = _load_booster()
        assert first is second is third

    def test_load_booster_thread_safe(self, trained_model_path: Path) -> None:
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

    def test_warmup_loads_eagerly(self, trained_model_path: Path) -> None:
        assert scorer_mod._BOOSTER is None
        warmup()
        assert scorer_mod._BOOSTER is not None

    def test_load_booster_raises_when_path_missing(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        # Operator misconfiguration (model file not mounted) should fail loud
        # at the first chunk, not silently return a default booster.
        nonexistent = tmp_path / "does_not_exist.ubj"
        monkeypatch.setenv("SESSION_INTERESTINGNESS_MODEL_PATH", str(nonexistent))
        _reset_booster_singleton()
        with pytest.raises(Exception):
            _load_booster()


class TestGetFeatureNames:
    def test_returns_booster_feature_names(self, trained_model_path: Path) -> None:
        # The booster IS the source of truth — get_feature_names must hand
        # back exactly what training pinned in the model file, in order.
        names = get_feature_names()
        assert names == _TRAINING_FEATURE_NAMES

    def test_triggers_lazy_load_on_first_call(self, trained_model_path: Path) -> None:
        # Activities call get_feature_names() before any predict() — it must
        # trigger the underlying _load_booster() instead of failing because
        # warmup() hasn't been called yet.
        assert scorer_mod._BOOSTER is None
        names = get_feature_names()
        assert scorer_mod._BOOSTER is not None
        assert len(names) == len(_TRAINING_FEATURE_NAMES)

    def test_caches_after_first_load(self, trained_model_path: Path) -> None:
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
        df = _synthetic_training_frame(rows=64, seed=0, feature_names=("event_rate", "bogus_new_feature"))
        booster = _train_booster(df, feature_names=("event_rate", "bogus_new_feature"))
        model_path = tmp_path / "uncovered_model.ubj"
        booster.save_model(str(model_path))

        monkeypatch.setenv("SESSION_INTERESTINGNESS_MODEL_PATH", str(model_path))
        _reset_booster_singleton()

        try:
            with pytest.raises(MissingFeatureRangeError, match="bogus_new_feature"):
                _load_booster()
        finally:
            _reset_booster_singleton()


class TestPredict:
    def test_predict_returns_scores_in_unit_interval(
        self, trained_model_path: Path, feature_frame: pd.DataFrame
    ) -> None:
        # Booster was trained binary:logistic — every prediction must land in [0, 1].
        scores = predict(feature_frame)

        assert isinstance(scores, np.ndarray)
        assert scores.dtype == np.float32
        assert scores.shape == (len(feature_frame),)
        assert scores.min() >= 0.0
        assert scores.max() <= 1.0

    def test_predict_handles_nan_features(self, trained_model_path: Path, feature_frame: pd.DataFrame) -> None:
        # Our SQL produces NaN when denominators are zero (nullIf(...)).
        # XGBoost handles NaN natively; predict must not raise or crash.
        feature_frame.loc[0, "event_rate"] = float("nan")
        feature_frame.loc[1, "mouse_velocity_mean"] = float("nan")

        scores = predict(feature_frame)

        assert np.isfinite(scores).all()

    def test_predict_with_id_columns_alongside_features(
        self, trained_model_path: Path, feature_frame: pd.DataFrame
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
        self, trained_model_path: Path, feature_frame: pd.DataFrame
    ) -> None:
        # We pass feature_names into DMatrix so XGBoost reorders by name, not
        # position. That means we get the same scores regardless of how the
        # caller orders the columns — a regression here would silently mis-score.
        scores_a = predict(feature_frame)
        shuffled = feature_frame.loc[:, list(reversed(_TRAINING_FEATURE_NAMES))]
        scores_b = predict(shuffled)

        np.testing.assert_array_equal(scores_a, scores_b)

    def test_predict_empty_dataframe(self, trained_model_path: Path) -> None:
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
