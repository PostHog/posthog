"""Shared fixtures for the surfacing_scoring_sweep tests.

The xgboost-dependent fixtures (`trained_model_path`, `regression_model_path`)
live alongside their only consumer in `test_scorer.py`.

The booster is the source of truth for `feature_names` in production. Tests
that exercise `validate_features` / `feature_matrix` without a real booster
use `feature_names_for_tests` (= `tuple(FEATURE_RANGES.keys())`) — the
runtime range contract doubles as the test schema, which keeps the two
in lockstep without a separate hard-coded list.
"""

from __future__ import annotations

import pytest

import numpy as np
import pandas as pd

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
