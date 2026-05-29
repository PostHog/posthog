#!/usr/bin/env python3
"""
Reference autoresearch training script (fixture bundle, slice 1).

Contract with the framework:
    python train.py <train_features.csv> <train_labels.csv> <model.pkl> <output.json> \
                    [<holdout_features.csv> <holdout_labels.csv>] [--random-state N]

  - Features CSVs: first column `distinct_id`, remaining columns numeric features.
  - Labels CSVs:  columns `distinct_id`, `__label` (0/1).
  - Fits a sklearn pipeline on (train features ⋈ train labels), pickles it to <model.pkl>.
  - If holdout files are given and the holdout has >=2 label classes, computes holdout AUC.
  - Writes a structured metrics file to <output.json>:
        {"holdout_auc": <float|null>, "n_train": <int>, "n_features": <int>}
    The framework reads and validates this file — nothing is parsed from stdout.
  - Exits non-zero on degenerate data (too few positives/negatives) so the framework
    fails the run instead of shipping a useless model.

The framework runs the feature SQL and grades realized AUC; this script only fits + reports.
"""

from __future__ import annotations

import sys
import json
import pickle
import argparse

import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

MIN_PER_CLASS = 5


def _load_xy(features_path: str, labels_path: str) -> tuple[pd.DataFrame, pd.Series, list[str]]:
    features = pd.read_csv(features_path)
    labels = pd.read_csv(labels_path)
    merged = features.merge(labels[["distinct_id", "__label"]], on="distinct_id", how="inner")
    feature_cols = [c for c in features.columns if c != "distinct_id"]
    x = pd.DataFrame(merged[feature_cols]).fillna(0).astype(float)
    y = pd.Series(merged["__label"]).fillna(0).astype(int)
    return x, y, feature_cols


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("train_features")
    parser.add_argument("train_labels")
    parser.add_argument("model_out")
    parser.add_argument("output_json")
    parser.add_argument("holdout_features", nargs="?", default=None)
    parser.add_argument("holdout_labels", nargs="?", default=None)
    parser.add_argument("--random-state", type=int, default=42)
    args = parser.parse_args()

    x_train, y_train, feature_cols = _load_xy(args.train_features, args.train_labels)

    n_pos = int(y_train.sum())
    n_neg = int(len(y_train) - n_pos)
    if n_pos < MIN_PER_CLASS or n_neg < MIN_PER_CLASS:
        print(f"degenerate training data: n_pos={n_pos} n_neg={n_neg}", file=sys.stderr)  # noqa: T201
        return 1

    model = LogisticRegression(C=1.0, max_iter=200, random_state=args.random_state)
    model.fit(x_train.to_numpy(), y_train.to_numpy())

    with open(args.model_out, "wb") as f:
        pickle.dump({"model": model, "feature_cols": feature_cols}, f)

    holdout_auc: float | None = None
    if args.holdout_features and args.holdout_labels:
        x_hold, y_hold, _ = _load_xy(args.holdout_features, args.holdout_labels)
        if len(x_hold) and y_hold.nunique() >= 2:
            x_hold = x_hold.reindex(columns=feature_cols, fill_value=0)
            p_hold = model.predict_proba(x_hold.to_numpy())[:, 1]
            holdout_auc = float(roc_auc_score(y_hold.to_numpy(), p_hold))

    with open(args.output_json, "w") as f:
        json.dump(
            {
                "holdout_auc": round(holdout_auc, 4) if holdout_auc is not None else None,
                "n_train": int(len(y_train)),
                "n_features": len(feature_cols),
            },
            f,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
