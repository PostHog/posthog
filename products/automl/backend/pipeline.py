"""End-to-end orchestration: load → train (AutoGluon) → predict → write parquet."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from typing import Optional

import structlog

from products.automl.backend.data.loader import DataLoader
from products.automl.backend.inference.predictor import predict_batch
from products.automl.backend.training.trainer import TrainingResult, train

logger = structlog.get_logger(__name__)


@dataclass
class PipelineResult:
    model_path: str
    metrics: dict[str, float]
    predictions_path: str
    predictions_count: int


def run_end_to_end(
    *,
    train_parquet: str,
    target: str,
    predictions_output: str,
    id_column: str = "user_id",
    model_dir: Optional[str] = None,
    where: Optional[str] = None,
    time_limit_s: int = 60,
    val_fraction: float = 0.15,
    test_fraction: float = 0.15,
    presets: str = "medium_quality",
    eval_metric: Optional[str] = None,
    s3_region: Optional[str] = None,
) -> PipelineResult:
    if model_dir is None:
        model_dir = tempfile.mkdtemp(prefix="automl_model_")
    logger.info(
        "pipeline_start",
        train_parquet=train_parquet,
        target=target,
        predictions_output=predictions_output,
        model_dir=model_dir,
        time_limit_s=time_limit_s,
        presets=presets,
    )

    with DataLoader(s3_region=s3_region) as loader:
        logger.info("phase_load")
        df = loader.read_parquet(train_parquet, where=where)
        if id_column not in df.columns:
            raise ValueError(f"id_column {id_column!r} not in parquet columns {df.columns}")
        if target not in df.columns:
            raise ValueError(f"target {target!r} not in parquet columns {df.columns}")

        logger.info("phase_train")
        training_df = df.drop(id_column)
        result: TrainingResult = train(
            training_df,
            target=target,
            model_dir=model_dir,
            time_limit_s=time_limit_s,
            val_fraction=val_fraction,
            test_fraction=test_fraction,
            presets=presets,
            eval_metric=eval_metric,
        )

        logger.info("phase_predict")
        features = df.drop(target)
        preds = predict_batch(
            model_path=result.model_path,
            inputs=features,
            output_path=predictions_output,
            id_column=id_column,
            loader=loader,
        )

    logger.info(
        "pipeline_done",
        predictions_count=len(preds),
        model_path=result.model_path,
    )
    return PipelineResult(
        model_path=result.model_path,
        metrics=result.metrics,
        predictions_path=predictions_output,
        predictions_count=len(preds),
    )
