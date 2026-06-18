"""XGBoost booster lifecycle for the session surfacing scorer.

The booster is loaded **once per worker process** and held as a module-level
singleton. XGBoost predict releases the GIL and is parallelized internally
by libomp; we want libomp to use the worker pod's full CPU budget on a
single chunk at a time, not split it across many concurrent activities (see
`README.md` for the OMP_NUM_THREADS guidance).

S3 is the single source of truth for the model (no bundled fallback). On
first load we fetch the booster, cache it in a tempfile, and run
`assert_serving_schema_parity` — SQL, FEATURE_RANGES, and the booster
cannot drift.
"""

from __future__ import annotations

import os
import tempfile
import threading
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import xgboost as xgb
import structlog

from posthog.storage import object_storage
from posthog.temporal.session_replay.surfacing_scoring_sweep.feature_schema import assert_serving_schema_parity
from posthog.temporal.session_replay.surfacing_scoring_sweep.features import feature_matrix

logger = structlog.get_logger(__name__)


_MODEL_S3_URI_ENV_VAR = "SESSION_SURFACING_MODEL_S3_URI"

_BOOSTER: xgb.Booster | None = None
# Cached tuple of `_BOOSTER.feature_names` to avoid the C++ → Python attribute
# lookup on the predict hot path. Set in lockstep with `_BOOSTER`; reset to
# None whenever `_BOOSTER` is reset (test fixtures clear both).
_FEATURE_NAMES: tuple[str, ...] | None = None
_S3_CACHED_PATH: str | None = None
_BOOSTER_LOCK = threading.Lock()


class ModelNotConfiguredError(RuntimeError):
    """`SESSION_SURFACING_MODEL_S3_URI` is not set."""


def _fetch_from_s3(uri: str) -> str:
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.lstrip("/"):
        raise ValueError(f"{_MODEL_S3_URI_ENV_VAR} must be 's3://bucket/key', got {uri!r}")
    bucket, key = parsed.netloc, parsed.path.lstrip("/")
    payload = object_storage.read_bytes(key, bucket=bucket)
    if payload is None:
        raise FileNotFoundError(f"{uri} returned no body")
    # delete=False: xgb.Booster.load_model reopens the path itself.
    with tempfile.NamedTemporaryFile(suffix=".ubj", delete=False) as fh:
        fh.write(payload)
        return fh.name


def _model_path() -> str:
    global _S3_CACHED_PATH
    s3_uri = os.environ.get(_MODEL_S3_URI_ENV_VAR)
    if not s3_uri:
        raise ModelNotConfiguredError(
            f"Set {_MODEL_S3_URI_ENV_VAR}=s3://bucket/key. "
            "See surfacing_scoring_sweep/README.md → 'Uploading a model to S3'."
        )
    if _S3_CACHED_PATH is None:
        _S3_CACHED_PATH = _fetch_from_s3(s3_uri)
        logger.info("surfacing_scoring_sweep.model_fetched_from_s3", uri=s3_uri, path=_S3_CACHED_PATH)
    return _S3_CACHED_PATH


def _load_booster() -> xgb.Booster:
    """Cache + return the booster; thread-safe under high `max_concurrent_activities`.

    Held under a lock only on first load. Subsequent calls hit the fast path
    (one global-not-None check), so the lock isn't on the per-predict path.

    On first load: runs assert_serving_schema_parity and caches feature_names.
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

    Call from the worker bootstrap so the first chunk doesn't pay the S3
    fetch latency. Also surfaces `ModelNotConfiguredError` /
    `FeatureSchemaDriftError` / `MissingFeatureRangeError` at boot rather
    than on the first chunk.

    Raises on any model problem — callers that must not crash (e.g. the shared
    session-replay worker, where surfacing is one of several workflows) should
    use `warmup_best_effort()` instead.
    """
    _load_booster()


def warmup_best_effort() -> bool:
    """`warmup()` that never raises — for the shared session-replay worker.

    Surfacing scoring runs alongside other replay workflows on that worker, so a
    model problem (env var unset, model missing from S3, schema drift) must not
    take the whole pod down. Logs and returns False instead; the scoring
    activities will then fail (and retry per their policy) until the model is
    fixed, while the rest of the worker keeps running. Returns True on success.
    """
    try:
        warmup()
        return True
    except Exception:
        logger.exception("surfacing_scoring_sweep.warmup_failed_worker_continuing")
        return False


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
