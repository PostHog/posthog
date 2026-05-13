"""Train an AutoGluon TabularPredictor and track it in MLflow."""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import mlflow
import polars as pl
import structlog
from autogluon.tabular import TabularPredictor

logger = structlog.get_logger(__name__)


@dataclass
class TrainingResult:
    model_path: str
    metrics: dict[str, float]
    mlflow_run_id: str
    leaderboard: list[dict[str, Any]]


def train(
    df: pl.DataFrame,
    *,
    target: str,
    model_dir: str | Path,
    eval_metric: Optional[str] = None,
    time_limit_s: int = 300,
    presets: str = "medium_quality",
    experiment_name: str = "automl-hackathon",
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

    mlflow.set_experiment(experiment_name)
    with mlflow.start_run() as run:
        logger.info("mlflow_run_started", run_id=run.info.run_id, experiment=experiment_name)
        mlflow.log_params(
            {
                "target": target,
                "rows_total": len(pdf),
                "rows_train": len(train_df),
                "rows_val": len(val_df),
                "rows_test": len(test_df),
                "val_fraction": val_fraction,
                "test_fraction": test_fraction,
                "presets": presets,
                "time_limit_s": time_limit_s,
                "eval_metric": eval_metric or "auto",
                "n_features": len(pdf.columns) - 1,
            }
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
        for col, val in scalar_metrics.items():
            mlflow.log_metric(f"best_{col}", val)

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(leaderboard_records, f, default=str, indent=2)
            leaderboard_artifact = f.name
        mlflow.log_artifact(leaderboard_artifact, artifact_path="leaderboard")
        mlflow.log_artifacts(model_path, artifact_path="autogluon_model")
        logger.info(
            "training_complete",
            best_model=str(best.get("model", "unknown")),
            **{f"best_{k}": v for k, v in scalar_metrics.items()},
        )

        return TrainingResult(
            model_path=model_path,
            metrics=scalar_metrics,
            mlflow_run_id=run.info.run_id,
            leaderboard=leaderboard_records,
        )
