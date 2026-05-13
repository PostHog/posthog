"""Batch inference: load a saved AutoGluon model and write predictions to parquet."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import polars as pl
import structlog
from autogluon.tabular import TabularPredictor

from products.automl.backend.data.loader import DataLoader

logger = structlog.get_logger(__name__)


def predict_batch(
    *,
    model_path: str | Path,
    inputs: pl.DataFrame,
    output_path: str,
    id_column: str = "user_id",
    loader: Optional[DataLoader] = None,
) -> pl.DataFrame:
    """Run a saved AutoGluon model over ``inputs`` and write predictions parquet.

    The id column is preserved in the output; everything else is treated as
    features and passed to the predictor. For classification problems we also
    emit one ``proba_<class>`` column per class.
    """
    if id_column not in inputs.columns:
        raise ValueError(f"id_column {id_column!r} not in inputs columns {inputs.columns}")

    logger.info("predictor_load", model_path=str(model_path))
    predictor = TabularPredictor.load(str(model_path))
    logger.info(
        "predictor_loaded",
        problem_type=predictor.problem_type,
        eval_metric=predictor.eval_metric.name,
        rows_to_predict=len(inputs),
    )
    pdf = inputs.to_pandas()
    feature_pdf = pdf.drop(columns=[id_column])

    predictions = predictor.predict(feature_pdf)
    columns: dict[str, Any] = {
        id_column: inputs[id_column].to_list(),
        "prediction": predictions.tolist(),
    }
    if predictor.problem_type in ("binary", "multiclass"):
        proba = predictor.predict_proba(feature_pdf)
        for class_label in proba.columns:
            columns[f"proba_{class_label}"] = proba[class_label].tolist()
        logger.info("predict_done", rows=len(predictions), proba_classes=list(proba.columns))
    else:
        logger.info("predict_done", rows=len(predictions))

    out = pl.DataFrame(columns)

    owns_loader = loader is None
    active_loader = loader if loader is not None else DataLoader()
    try:
        active_loader.write_parquet(out, output_path)
    finally:
        if owns_loader:
            active_loader.close()

    return out
