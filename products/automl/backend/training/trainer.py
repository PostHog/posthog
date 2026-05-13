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
    eval_fraction: float = 0.2,
    seed: int = 42,
) -> TrainingResult:
    """Fit a TabularPredictor, log to MLflow, return paths + metrics."""
    if target not in df.columns:
        raise ValueError(f"target {target!r} not in dataframe columns {df.columns}")
    if not 0.0 < eval_fraction < 1.0:
        raise ValueError(f"eval_fraction must be in (0, 1), got {eval_fraction}")

    model_path = str(Path(model_dir).expanduser().resolve())

    pdf = df.to_pandas()
    shuffled = pdf.sample(frac=1.0, random_state=seed).reset_index(drop=True)
    eval_size = max(1, int(len(shuffled) * eval_fraction))
    eval_df = shuffled.iloc[:eval_size]
    train_df = shuffled.iloc[eval_size:]
    logger.info(
        "train_split",
        target=target,
        rows_train=len(train_df),
        rows_eval=len(eval_df),
        eval_fraction=eval_fraction,
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
                "rows_eval": len(eval_df),
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
            time_limit=time_limit_s,
            presets=presets,
        )
        logger.info("autogluon_fit_done", problem_type=predictor.problem_type, eval_metric=predictor.eval_metric.name)

        leaderboard = predictor.leaderboard(eval_df, silent=True)
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
