"""Train an AutoGluon TabularPredictor and return the metrics + leaderboard.

Pure in-process trainer — no external experiment-tracker. The artifact is
saved by AutoGluon to ``model_dir`` via the predictor's ``path=`` kwarg.
The productization side persists the run via ``AutoMLModelVersion`` rather
than an MLflow run; if/when an external tracker lands, plumb its run id
through ``AutoMLModelVersion.tracking_metadata`` and not through this
return shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import polars as pl
import structlog
from autogluon.tabular import TabularPredictor

logger = structlog.get_logger(__name__)


@dataclass
class TrainingResult:
    model_path: str
    metrics: dict[str, float]
    leaderboard: list[dict[str, Any]]
    problem_type: str
    eval_metric: str
    rows_train: int
    rows_val: int
    rows_test: int


def train(
    df: pl.DataFrame,
    *,
    target: str,
    model_dir: str | Path,
    eval_metric: Optional[str] = None,
    time_limit_s: int = 300,
    presets: str = "medium_quality",
    val_fraction: float = 0.15,
    test_fraction: float = 0.15,
    seed: int = 42,
) -> TrainingResult:
    """Fit a TabularPredictor with a 3-way train/val/test split.

    val (passed to AutoGluon as ``tuning_data``) is used for HPO / model
    selection / stacking decisions. test is held out completely and only
    used to score the final leaderboard reported in the result.
    """
    if target not in df.columns:
        raise ValueError(f"target {target!r} not in dataframe columns {df.columns}")
    if not 0.0 < val_fraction < 1.0:
        raise ValueError(f"val_fraction must be in (0, 1), got {val_fraction}")
    if not 0.0 < test_fraction < 1.0:
        raise ValueError(f"test_fraction must be in (0, 1), got {test_fraction}")
    if val_fraction + test_fraction >= 1.0:
        raise ValueError(f"val_fraction + test_fraction must be < 1.0, got {val_fraction + test_fraction}")

    model_path = str(Path(model_dir).expanduser().resolve())

    pdf = df.to_pandas()
    shuffled = pdf.sample(frac=1.0, random_state=seed).reset_index(drop=True)
    n = len(shuffled)
    test_size = max(1, int(n * test_fraction))
    val_size = max(1, int(n * val_fraction))
    test_df = shuffled.iloc[:test_size]
    val_df = shuffled.iloc[test_size : test_size + val_size]
    train_df = shuffled.iloc[test_size + val_size :]

    train_class_counts = {str(k): int(v) for k, v in train_df[target].value_counts().to_dict().items()}
    logger.info(
        "train_split",
        target=target,
        rows_train=len(train_df),
        rows_val=len(val_df),
        rows_test=len(test_df),
        val_fraction=val_fraction,
        test_fraction=test_fraction,
        train_class_counts=train_class_counts,
        seed=seed,
    )

    logger.info(
        "autogluon_fit_start",
        presets=presets,
        time_limit_s=time_limit_s,
        eval_metric=eval_metric or "auto",
        model_path=model_path,
    )
    predictor = TabularPredictor(
        label=target,
        path=model_path,
        eval_metric=eval_metric,
    ).fit(
        train_data=train_df,
        tuning_data=val_df,
        time_limit=time_limit_s,
        presets=presets,
    )
    logger.info("autogluon_fit_done", problem_type=predictor.problem_type, eval_metric=predictor.eval_metric.name)

    leaderboard = predictor.leaderboard(test_df, silent=True)
    leaderboard_records: list[dict[str, Any]] = leaderboard.to_dict(orient="records")

    best = leaderboard.iloc[0].to_dict()
    scalar_metrics: dict[str, float] = {}
    for col, val in best.items():
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            scalar_metrics[str(col)] = float(val)

    logger.info(
        "training_complete",
        best_model=str(best.get("model", "unknown")),
        **{f"best_{k}": v for k, v in scalar_metrics.items()},
    )

    return TrainingResult(
        model_path=model_path,
        metrics=scalar_metrics,
        leaderboard=leaderboard_records,
        problem_type=str(predictor.problem_type),
        eval_metric=predictor.eval_metric.name,
        rows_train=len(train_df),
        rows_val=len(val_df),
        rows_test=len(test_df),
    )
