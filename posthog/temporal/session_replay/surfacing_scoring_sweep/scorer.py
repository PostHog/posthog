"""XGBoost booster lifecycle for the session surfacing scorer.

The booster is loaded **once per worker process** and held as a module-level
singleton. XGBoost predict releases the GIL and is parallelized internally
by libomp; we want libomp to use the worker pod's full CPU budget on a
single chunk at a time, not split it across many concurrent activities (see
`README.md` for the OMP_NUM_THREADS guidance).

Loading from disk is paid on first use; pin the model file in the worker
container image so the load is local + fast.

The booster is the **single source of truth for the feature schema** —
`get_feature_names()` returns the booster's embedded `feature_names`, and
`feature_schema.assert_serving_schema_parity` runs at load time to fail loud if
SQL, ``FEATURE_RANGES``, or the booster drift apart.
"""

from __future__ import annotations

import os
import threading

import numpy as np
import pandas as pd
import xgboost as xgb
import structlog

from posthog.temporal.session_replay.surfacing_scoring_sweep.feature_schema import assert_serving_schema_parity
from posthog.temporal.session_replay.surfacing_scoring_sweep.features import feature_matrix

logger = structlog.get_logger(__name__)


# Path on disk where the trained booster is mounted/baked. Override with
# `SESSION_INTERESTINGNESS_MODEL_PATH` in an environment-specific settings file
# or container spec — keeps this module portable across local / staging / prod.
# The default points at the booster file that ships in this package
# (`model.ubj` next to `scorer.py`), so dev/test/CI all use the same
# checked-in model the SQL/booster parity test pins against. Production
# overrides this via the env var to point at the prod-trained model.
_MODEL_PATH_ENV_VAR = "SESSION_INTERESTINGNESS_MODEL_PATH"
_BUNDLED_MODEL_PATH = os.path.join(os.path.dirname(__file__), "model.ubj")
_DEFAULT_MODEL_PATH = _BUNDLED_MODEL_PATH

_BOOSTER: xgb.Booster | None = None
# Cached tuple of `_BOOSTER.feature_names` to avoid the C++ → Python attribute
# lookup on the predict hot path. Set in lockstep with `_BOOSTER`; reset to
# None whenever `_BOOSTER` is reset (test fixtures clear both).
_FEATURE_NAMES: tuple[str, ...] | None = None
_BOOSTER_LOCK = threading.Lock()


def _model_path() -> str:
    return os.environ.get(_MODEL_PATH_ENV_VAR, _DEFAULT_MODEL_PATH)


def _load_booster() -> xgb.Booster:
    """Cache + return the booster; thread-safe under high `max_concurrent_activities`.

    Held under a lock only on first load. Subsequent calls hit the fast path
    (one global-not-None check), so the lock isn't on the per-predict path.

    On first load: validates `booster.feature_names` against `FEATURE_RANGES`
    via `assert_ranges_cover` and caches the names tuple. A model whose
    feature set isn't covered by `FEATURE_RANGES` fails loud here, before
    any chunk is dispatched.
    """
    global _BOOSTER, _FEATURE_NAMES
    cached_booster = _BOOSTER
    if cached_booster is not None:
        return cached_booster

    with _BOOSTER_LOCK:
        cached_booster = _BOOSTER
        if cached_booster is not None:
            return cached_booster

        path = _model_path()
        loaded_booster = xgb.Booster()
        loaded_booster.load_model(path)

        # `booster.feature_names` is set when training passed `feature_names=`
        # to DMatrix. None / empty here means the model was trained without
        # explicit names, which serving cannot work with — the SELECT aliases
        # have nothing to match against. assert_serving_schema_parity surfaces
        # SQL / FEATURE_RANGES / booster drift at boot.
        names: tuple[str, ...] = tuple(loaded_booster.feature_names or ())
        assert_serving_schema_parity(names)

        logger.info(
            "surfacing_scoring_sweep.model_loaded",
            path=path,
            num_features=len(names),
            feature_names=list(names),
        )
        _BOOSTER = loaded_booster
        _FEATURE_NAMES = names
        return loaded_booster


def warmup() -> None:
    """Eagerly load the booster on worker startup.

    Call from the worker bootstrap so the first activity doesn't pay the
    load cost (typically tens of ms but spikes badly if the model file is
    on a slow mount). Also surfaces `MissingFeatureRangeError` at boot
    rather than on the first chunk.
    """
    _load_booster()


def get_feature_names() -> tuple[str, ...]:
    """Return the booster's `feature_names` tuple — the serving feature schema.

    Triggers a load if the booster hasn't been loaded yet (idempotent).
    This is what activities call to drive `validate_features` and to log the
    feature count, instead of importing a hard-coded constant from
    `features.py`. Booster file = single source of truth for which features
    the model takes.
    """
    cached_names = _FEATURE_NAMES
    if cached_names is not None:
        return cached_names
    _load_booster()
    cached_names = _FEATURE_NAMES
    if cached_names is None:
        raise RuntimeError("Booster loaded but feature names cache is empty")
    return cached_names


class ScoreRangeError(Exception):
    """Booster returned scores outside [0, 1] — model is likely misconfigured."""


def predict(df: pd.DataFrame) -> np.ndarray:
    """Score a chunk's feature DataFrame and return a 1-D float32 array in [0, 1].

    `df` must already have passed `validate_features` — predict is the hot
    path and skips re-validation. Returned array is positionally aligned
    with `df.index`.
    """
    booster = _load_booster()
    feature_names = get_feature_names()

    # Empty input — short-circuit before DMatrix, which doesn't accept zero-row
    # frames whose columns have `object` dtype (the pandas default for empties).
    if df.empty:
        return np.empty(0, dtype=np.float32)

    features = feature_matrix(df, feature_names=feature_names)
    dmat = xgb.DMatrix(features, feature_names=list(feature_names))
    raw = booster.predict(dmat)

    scores = np.asarray(raw, dtype=np.float32).reshape(-1)
    # Scores below 0 or above 1 indicate a model mismatch (e.g. trained as
    # regression when it should be probability) — easier to debug here than
    # downstream in CH.
    if scores.size and (scores.min() < 0.0 or scores.max() > 1.0):
        raise ScoreRangeError(
            f"Booster returned scores outside [0, 1]: min={scores.min()}, max={scores.max()}. "
            "Model is likely not configured for probability output (objective should be "
            "binary:logistic / reg:logistic, or the booster needs an inverse_link wrapper)."
        )
    return scores
