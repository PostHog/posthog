#!/usr/bin/env python3
"""Regenerate the checked-in placeholder ``model.ubj`` without Django/DB.

Run from repo root:

    flox activate -- bash -c "python bin/generate_surfacing_placeholder_model.py"
"""

from __future__ import annotations

import sys
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

REPO_ROOT = Path(__file__).resolve().parents[1]
SWEEP_PKG = REPO_ROOT / "posthog/temporal/session_replay/surfacing_scoring_sweep"
MODEL_PATH = SWEEP_PKG / "model.ubj"
_PKG_PREFIX = "posthog.temporal.session_replay.surfacing_scoring_sweep"


def _load_module(name: str, filename: str):
    module_name = f"{_PKG_PREFIX}.{name}"
    spec = importlib.util.spec_from_file_location(module_name, SWEEP_PKG / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    features_mod = _load_module("features", "features.py")
    _load_module("sql", "sql.py")
    feature_schema_mod = _load_module("feature_schema", "feature_schema.py")

    feature_names = tuple(features_mod.FEATURE_RANGES.keys())
    rng = np.random.default_rng(0)
    rows = 128
    data = rng.random((rows, len(feature_names))).astype(np.float32)
    df = pd.DataFrame(data, columns=list(feature_names))
    df["__label__"] = (df[feature_names[0]] > 0.5).astype(np.int32)

    dmat = xgb.DMatrix(df[list(feature_names)], label=df["__label__"], feature_names=list(feature_names))
    booster = xgb.train(
        {"objective": "binary:logistic", "max_depth": 2, "eta": 0.5, "verbosity": 0},
        dmat,
        num_boost_round=2,
    )
    booster.save_model(str(MODEL_PATH))

    names = tuple(booster.feature_names or ())
    feature_schema_mod.assert_serving_schema_parity(names)
    sys.stdout.write(f"Wrote {MODEL_PATH} with {len(names)} features\n")


if __name__ == "__main__":
    main()
