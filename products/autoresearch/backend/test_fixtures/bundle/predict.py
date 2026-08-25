#!/usr/bin/env python3
"""
Reference autoresearch prediction script (fixture bundle, slice 1).

Contract with the framework:
    python predict.py <score_features.parquet> <model.pkl> <scores.parquet>

  - Loads the pickled {"model", "feature_cols"} produced by train.py.
  - Aligns the score features to the trained feature columns (missing -> 0).
  - Writes <scores.parquet> with columns `distinct_id,p_y`.
  - Prints NOTHING to stdout — the framework reads scores.parquet back (base64
    over `cat`), so stray stdout would corrupt the parse.
"""

from __future__ import annotations

import sys
import pickle

import pandas as pd


def main() -> int:
    score_features_path, model_path, scores_out = sys.argv[1], sys.argv[2], sys.argv[3]

    with open(model_path, "rb") as f:
        bundle = pickle.load(f)
    model = bundle["model"]
    feature_cols = bundle["feature_cols"]

    features = pd.read_parquet(score_features_path)
    x = features.reindex(columns=feature_cols, fill_value=0).fillna(0).astype(float)
    p_y = model.predict_proba(x.to_numpy())[:, 1]

    out = pd.DataFrame({"distinct_id": features["distinct_id"], "p_y": p_y.round(6)})
    out.to_parquet(scores_out, index=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
