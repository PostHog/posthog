"""Shared fixtures for the surfacing_scoring_sweep tests.

`feature_names_for_tests` (= `tuple(FEATURE_RANGES.keys())`) is the schema
for tests that don't load a real booster — the runtime range contract
doubles as the test schema so the two stay in lockstep.

`surfacing_booster_path` trains a tiny booster in-memory and wires it
behind a mocked S3 fetch so tests exercise the production code path
(scorer is S3-only — no local-file fallback).
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

import numpy as np
import pandas as pd
import xgboost as xgb

from posthog.temporal.session_replay.surfacing_scoring_sweep import scorer as scorer_mod
from posthog.temporal.session_replay.surfacing_scoring_sweep.features import FEATURE_RANGES


@pytest.fixture
def feature_names_for_tests() -> tuple[str, ...]:
    """Feature schema used by tests that don't load a real booster.

    Production gets this from `scorer.get_feature_names()` (= booster.feature_names).
    For unit tests of `validate_features` / `feature_matrix`, we use the
    `FEATURE_RANGES` dict's keys — that's the runtime range contract and is
    guaranteed to cover the booster (validated by `assert_ranges_cover` at
    warmup), so it's a safe stand-in here.
    """
    return tuple(FEATURE_RANGES.keys())


@pytest.fixture
def feature_frame(feature_names_for_tests: tuple[str, ...]) -> pd.DataFrame:
    """A small, valid feature DataFrame keyed by the test feature schema."""
    rng = np.random.default_rng(123)
    rows = 16
    data = rng.random((rows, len(feature_names_for_tests))).astype(np.float32)
    return pd.DataFrame(data, columns=list(feature_names_for_tests))


def reset_scorer_singleton() -> None:
    """Clear cached booster + feature names + S3 tempfile path. Public for test_scorer.py."""
    scorer_mod._BOOSTER = None
    scorer_mod._FEATURE_NAMES = None
    scorer_mod._S3_CACHED_PATH = None


@pytest.fixture(autouse=True)
def _scorer_singleton_clean_slate() -> Generator[None]:
    """Every test in this directory starts and ends with a fresh scorer singleton."""
    reset_scorer_singleton()
    yield
    reset_scorer_singleton()


def train_synthetic_booster(
    feature_names: tuple[str, ...],
    *,
    seed: int = 42,
    rows: int = 128,
) -> xgb.Booster:
    """Tiny 2-tree binary:logistic booster with feature_names baked in.

    Labels are `first_feature > 0.5` so the booster has real signal.
    For non-logistic objectives, build the DMatrix + train directly.
    """
    rng = np.random.default_rng(seed)
    data = rng.random((rows, len(feature_names))).astype(np.float32)
    df = pd.DataFrame(data, columns=list(feature_names))
    labels = (df[feature_names[0]] > 0.5).astype(np.int32).to_numpy()
    dmat = xgb.DMatrix(df, label=labels, feature_names=list(feature_names))
    return xgb.train(
        {"objective": "binary:logistic", "max_depth": 2, "eta": 0.5, "verbosity": 0},
        dmat,
        num_boost_round=2,
    )


def wire_booster_as_s3(
    monkeypatch: pytest.MonkeyPatch, booster_path: Path, uri: str = "s3://test-bucket/model.ubj"
) -> None:
    """Point the scorer at `booster_path` via a mocked S3 fetch.

    Sets the S3 URI env var and patches `object_storage.read_bytes` so the
    scorer's production path (`_fetch_from_s3` → tempfile) loads the bytes
    we already have on disk. Same code path as prod, zero network.
    """
    payload = booster_path.read_bytes()
    monkeypatch.setenv("SESSION_SURFACING_MODEL_S3_URI", uri)
    monkeypatch.setattr(
        "posthog.temporal.session_replay.surfacing_scoring_sweep.scorer.object_storage.read_bytes",
        lambda key, *, bucket=None: payload,
    )


@pytest.fixture
def surfacing_booster_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Trained booster on FEATURE_RANGES.keys(); wired behind a mocked S3 fetch."""
    booster = train_synthetic_booster(tuple(FEATURE_RANGES.keys()))
    path = tmp_path / "model.ubj"
    booster.save_model(str(path))
    wire_booster_as_s3(monkeypatch, path)
    return path
