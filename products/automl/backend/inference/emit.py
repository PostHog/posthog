"""Emit ``$automl_prediction`` events from an inference run's predictions parquet.

Phase 2 of the AutoML inference flow. Called from
``logic.record_inference_outcome`` after a run flips to ``SUCCEEDED``: reads
the predictions parquet pointed at by ``run.inference_result['predictions_uri']``
from S3, and submits one ``$automl_prediction`` event per row via
``capture_internal``. Optionally sets the score onto the entity's person
profile via ``$set`` so cohorts and feature flags can read it.

Event shape::

    $automl_prediction
      distinct_id: <row's id_column value, typically person_id>
      properties:
        $automl_pipeline_id
        $automl_pipeline_name
        $automl_run_id              — AutoMLPipelineRun UUID (the inference run row)
        $automl_inference_run_id    — CLI's UTC timestamp inference id
        $automl_model_run_id        — CLI's UTC timestamp training id
        $automl_model_version_id    — Postgres AutoMLModelVersion id (if any)
        $automl_task_type           — classification / regression / ...
        $automl_id_column           — the column we keyed on
        $automl_prediction          — the predicted class (classification) or value (regression)
        $automl_proba_<class>       — per-class probability (classification only)
        $automl_score               — the "positive" proba (last sorted, classification only)
        $set:                       — only when pipeline.output_property_name is set
          <output_property_name>: $automl_score

Each emission is a synchronous HTTP POST to the local capture-rs endpoint.
For hackathon volumes (sub-thousand rows) this is fine; production runs at
millions of rows belong in a Temporal activity (Phase 3 / Temporal Schedule)
where the emission can fan out across workers.
"""

from __future__ import annotations

import os
from typing import Any

import structlog
import pyarrow.fs as pa_fs
import pyarrow.parquet as pq

from posthog.api.capture import capture_internal
from posthog.models import Team

from ..models import AutoMLModelVersion, AutoMLPipelineRun
from ..training.bootstrap import (
    _LOCAL_S3_AWS_ACCESS_KEY_ID,
    _LOCAL_S3_AWS_REGION,
    _LOCAL_S3_AWS_SECRET_ACCESS_KEY,
    _LOCAL_S3_ENDPOINT,
)

logger = structlog.get_logger(__name__)

_EVENT_NAME = "$automl_prediction"
_EVENT_SOURCE = "automl_inference"


def emit_predictions_for_run(run: AutoMLPipelineRun) -> int:
    """Emit one ``$automl_prediction`` event per row of the run's predictions parquet.

    Idempotency is enforced at the ``logic.record_inference_outcome`` level —
    once a run is terminal, this is never called again. So no de-dup is needed
    here.

    Returns the count of events submitted. Returns ``0`` (no-op) if the run
    has no manifest yet, no ``predictions_uri``, or zero rows. Capture errors
    on individual events are logged and counted but don't abort emission —
    one bad row shouldn't drop the whole batch.
    """
    manifest = run.inference_result or {}
    predictions_uri = manifest.get("predictions_uri")
    if not predictions_uri:
        logger.info("emit_predictions_no_uri", run_id=str(run.id))
        return 0

    pipeline = run.pipeline  # FK in-memory; safe to dereference here
    team = Team.objects.get(id=pipeline.team_id)

    id_column = manifest.get("id_column", "person_id")

    table = _read_predictions(predictions_uri)
    if table.num_rows == 0:
        logger.info("emit_predictions_zero_rows", run_id=str(run.id), uri=predictions_uri)
        return 0
    if id_column not in table.column_names:
        logger.warning(
            "emit_predictions_missing_id_column",
            run_id=str(run.id),
            id_column=id_column,
            columns=table.column_names,
        )
        return 0

    proba_cols = [c for c in table.column_names if c.startswith("proba_")]
    # AutoGluon's binary convention sorts proba_0 / proba_1; the last sorted
    # column is the "positive" class. For multiclass, the convention is less
    # clear — picking the highest-named class is arbitrary but deterministic.
    score_col = sorted(proba_cols)[-1] if proba_cols else None

    # Pre-compute pipeline-wide metadata once (every event carries it).
    base_props: dict[str, Any] = {
        "$automl_pipeline_id": str(pipeline.id),
        "$automl_pipeline_name": pipeline.name,
        "$automl_run_id": str(run.id),
        "$automl_inference_run_id": manifest.get("inference_run_id", ""),
        "$automl_model_run_id": manifest.get("model_run_id", ""),
        "$automl_task_type": pipeline.task_type,
        "$automl_id_column": id_column,
    }
    if score_col is not None:
        base_props["$automl_score_column"] = score_col

    # Resolve the current champion model version id for provenance. Best-effort;
    # the run's created_model_version_id is the *training* version, not the
    # serving champion (could differ if a retrain landed between scoring and now).
    champion = (
        AutoMLModelVersion.objects.filter(
            team_id=pipeline.team_id,
            pipeline_id=pipeline.id,
            role="champion",
        )
        .order_by("-created_at")
        .first()
    )
    if champion:
        base_props["$automl_model_version_id"] = str(champion.id)

    output_property = pipeline.output_property_name or None

    emitted = 0
    failed = 0
    rows = table.to_pylist()
    for row in rows:
        distinct_id_raw = row.get(id_column)
        if distinct_id_raw is None:
            continue
        distinct_id = str(distinct_id_raw)

        properties = dict(base_props)
        if "prediction" in row:
            properties["$automl_prediction"] = row["prediction"]
        for col in proba_cols:
            properties[f"$automl_{col}"] = row[col]
        if score_col is not None:
            score = row.get(score_col)
            if score is not None:
                properties["$automl_score"] = score
                if output_property:
                    # `$set` updates the person profile so the score is queryable
                    # as `person.properties.<output_property_name>` for cohort
                    # gates and feature-flag conditions.
                    properties["$set"] = {output_property: score}

        try:
            resp = capture_internal(
                token=team.api_token,
                event_name=_EVENT_NAME,
                event_source=_EVENT_SOURCE,
                distinct_id=distinct_id,
                timestamp=None,  # capture-rs stamps now() UTC
                properties=properties,
                process_person_profile=bool(output_property and score_col is not None),
            )
            resp.raise_for_status()
            emitted += 1
        except Exception:
            failed += 1
            logger.warning(
                "emit_predictions_row_failed",
                run_id=str(run.id),
                distinct_id=distinct_id,
                exc_info=True,
            )

    logger.info(
        "emit_predictions_done",
        run_id=str(run.id),
        pipeline_id=str(pipeline.id),
        emitted=emitted,
        failed=failed,
        total_rows=len(rows),
        predictions_uri=predictions_uri,
    )
    return emitted


def _read_predictions(uri: str) -> pq.pyarrow.Table:  # type: ignore[name-defined]
    """Load a predictions parquet from S3 or a local path.

    Local paths are mostly for tests; the production path is always ``s3://``.
    """
    if uri.startswith("s3://"):
        fs = _build_s3_fs()
        path = uri[len("s3://") :]
        return pq.read_table(path, filesystem=fs)
    return pq.read_table(uri)


def _build_s3_fs() -> pa_fs.S3FileSystem:
    """S3 client honoring the local-MinIO endpoint + creds defaulted from bootstrap.

    Env vars win when set; otherwise we fall back to the hackathon defaults
    that already live in ``bootstrap.py``. Production wiring would source these
    from settings/secrets manager — that's a Phase 3 concern, not Phase 2.
    """
    endpoint = _LOCAL_S3_ENDPOINT  # http://host.docker.internal:19000
    scheme = "https" if endpoint.startswith("https://") else "http"
    host = endpoint.removeprefix("https://").removeprefix("http://")

    return pa_fs.S3FileSystem(
        access_key=os.environ.get("AWS_ACCESS_KEY_ID", _LOCAL_S3_AWS_ACCESS_KEY_ID),
        secret_key=os.environ.get("AWS_SECRET_ACCESS_KEY", _LOCAL_S3_AWS_SECRET_ACCESS_KEY),
        region=os.environ.get("AWS_DEFAULT_REGION", _LOCAL_S3_AWS_REGION),
        endpoint_override=host,
        scheme=scheme,
        allow_bucket_creation=False,
    )
