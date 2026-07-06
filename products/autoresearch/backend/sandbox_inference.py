"""
Sandbox execution of an artifact bundle, split by run type.

Train run and predict run are different run types with different data contracts:

- ``fit_champion_model`` (train run, called once at completion) materializes the
  LABELED training population, runs the bundle's ``train.py`` in a sandbox, and
  persists the fitted ``model.pkl`` alongside the bundle. This is where fitting
  happens.
- ``score_via_sandbox`` (predict run, called every scoring cadence) is pure
  inference: it loads the persisted ``model.pkl``, materializes ONLY the
  inference population (cutoff ``now()``, no labels, no holdout, no fold), runs
  the bundle's ``predict.py`` only, and hands scores to the emitter. It never
  re-fits. If the model is somehow absent (legacy champion, or a completion-time
  fit that failed), it self-heals by fitting once and caching the pickle.

Unlike the in-process recipe path (inference._score_via_anchors), the model runs
as the agent-authored scripts inside a NOTEBOOK_BASE Tasks sandbox. The framework
owns everything around the scripts: materializing the leak-free feature matrices
(via labeling.py), serialization to parquet, sandbox lifecycle, and emitting. The
bundle never receives credentials or network egress.

The framework<->bundle interchange is parquet (typed, columnar, compressed) — the
sandbox image ships pyarrow, so the 23k+-row feature matrices move far faster and
smaller than CSV. This is a contract change: bundles authored against the old CSV
contract will fail loudly here (parquet read of a CSV path errors) and must be
re-trained.

Failure is loud: any materialization or sandbox error raises, the sandbox is
destroyed, and the caller fails the run. There is deliberately no stub fallback
(unlike the legacy path) — a silent zero-information champion would poison the
realized-AUC gold-standard gate.
"""

from __future__ import annotations

import io
import json
import base64
import binascii
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
import structlog

from posthog.schema import HogQLQuery

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.team.team import Team

from products.autoresearch.backend.artifacts import ArtifactBundle, read_bundle, read_model, write_model
from products.autoresearch.backend.labeling import build_inference_features_sql, build_training_features_sql
from products.autoresearch.backend.models import AutoresearchModel, AutoresearchPipeline
from products.tasks.backend.facade.sandbox import SandboxConfig, SandboxTemplate, get_sandbox_class

Sandbox = get_sandbox_class()

logger = structlog.get_logger(__name__)

# Internal columns added by labeling.build_training_features_sql.
_LABEL_COL = "__label"
_FOLD_COL = "__fold"
_HOLDOUT_FOLD = 0  # fold 0 is the holdout slice; folds 1..N-1 are training

# Sandbox layout + execution.
_WORKDIR = "/tmp/workspace/autoresearch"
_SANDBOX_PYTHON = "python3"  # NOTEBOOK_BASE puts its venv first on PATH
_TRAIN_TIMEOUT_S = 300
_PREDICT_TIMEOUT_S = 120
# Bundle scripts communicate only through files written into the workspace; the
# framework reads them back via cat. Sentinels bracket the readback so any stray
# shell output can't corrupt the parse. Nothing is parsed from script stdout.
# HogQL applies a low default row limit (100) when a query has no LIMIT. Without an
# explicit bound the train/holdout/score matrices would be silently capped at 100 rows —
# a tiny, high-variance sample. Mirror inference.FEATURE_QUERY_LIMIT and bound explicitly.
_MATERIALIZE_ROW_LIMIT = 50_000
_OUTPUT_JSON = "data/output.json"
_SCORES_PARQUET = "data/scores.parquet"
# The fitted model the train run produces and the predict run loads (relative to _WORKDIR).
_MODEL_PKL = "model.pkl"
_FILE_BEGIN = "<<<AUTORESEARCH_FILE_BEGIN>>>"
_FILE_END = "<<<AUTORESEARCH_FILE_END>>>"
# Keys train.py must write into output.json.
_REQUIRED_METRIC_KEYS = ("holdout_auc", "n_train", "n_features")


class SandboxInferenceError(Exception):
    """Raised when materialization or the sandbox run fails. The caller fails the run."""


@dataclass
class MaterializedData:
    """Labeled training matrix for a train run: train + holdout folds. Predict runs return a plain row list."""

    feature_cols: list[str]
    train_rows: list[dict[str, Any]] = field(default_factory=list)
    holdout_rows: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SandboxScoreResult:
    scored_rows: list[dict[str, Any]]  # score rows with an added "p_y"
    holdout_auc: float | None
    n_train: int
    n_features: int


# ── Public entry point ─────────────────────────────────────────────────────────


def fit_champion_model(
    *,
    team: Team,
    pipeline: AutoresearchPipeline,
    prefix: str,
    bundle: ArtifactBundle | None = None,
) -> dict[str, Any]:
    """
    Train run: fit the champion against the LABELED training population and persist
    the resulting ``model.pkl`` under ``prefix``. Idempotent — overwrites any prior fit.

    Returns train.py's metrics (holdout_auc, n_train, n_features). Raises
    SandboxInferenceError on any materialization or sandbox failure.
    """
    if bundle is None:
        try:
            bundle = read_bundle(prefix)
        except Exception as exc:
            raise SandboxInferenceError(f"Could not read bundle at {prefix}: {exc}") from exc

    data = materialize_training_data(team=team, pipeline=pipeline, feature_sql=bundle.features_sql)
    if not data.train_rows:
        raise SandboxInferenceError("No training rows to fit on")
    if not data.feature_cols:
        raise SandboxInferenceError("No numeric feature columns produced by feature SQL")

    model_bytes, metrics = _run_train_in_sandbox(bundle=bundle, data=data, pipeline=pipeline)
    write_model(prefix, model_bytes)
    logger.info(
        "autoresearch_champion_fitted",
        pipeline_id=str(pipeline.pk),
        prefix=prefix,
        model_bytes=len(model_bytes),
        holdout_auc=metrics.get("holdout_auc"),
    )
    return metrics


def score_via_sandbox(
    *,
    team: Team,
    pipeline: AutoresearchPipeline,
    model: AutoresearchModel,
    cutoff_ts: int | None = None,
) -> SandboxScoreResult:
    """
    Predict run: score the inference population with the champion's persisted model.

    Pure inference — loads ``model.pkl`` and runs only ``predict.py`` against the
    inference population (cutoff now(), no labels, no holdout). If the model has not
    been fit yet (legacy champion, or a completion-time fit that failed), it
    self-heals by fitting once and caching the pickle.

    Raises SandboxInferenceError on any failure (missing bundle, no data, sandbox
    or script error). Never falls back to stub scoring.
    """
    if not model.artifact_prefix:
        raise SandboxInferenceError(f"Model {model.pk} has no artifact_prefix")
    prefix = model.artifact_prefix

    try:
        bundle = read_bundle(prefix)
    except Exception as exc:
        raise SandboxInferenceError(f"Could not read bundle at {prefix}: {exc}") from exc

    model_bytes = read_model(prefix)
    if model_bytes is None:
        # The train run should have produced this; self-heal so a predict run never
        # silently no-ops. The one-time fit is cached for every subsequent run.
        logger.warning("autoresearch_model_missing_fitting_now", pipeline_id=str(pipeline.pk), prefix=prefix)
        fit_champion_model(team=team, pipeline=pipeline, prefix=prefix, bundle=bundle)
        model_bytes = read_model(prefix)
        if model_bytes is None:
            raise SandboxInferenceError(f"Champion model still missing after fit at {prefix}")

    score_rows = _materialize_score_data(
        team=team, pipeline=pipeline, feature_sql=bundle.features_sql, cutoff_ts=cutoff_ts
    )
    feature_cols = _numeric_feature_cols(score_rows)
    # Cheap guards before paying for a sandbox.
    if not score_rows:
        raise SandboxInferenceError("No inference rows to score")
    if not feature_cols:
        raise SandboxInferenceError("No numeric feature columns produced by feature SQL")

    scored_rows = _run_predict_in_sandbox(
        bundle=bundle, model_bytes=model_bytes, score_rows=score_rows, feature_cols=feature_cols, pipeline=pipeline
    )
    return SandboxScoreResult(
        scored_rows=scored_rows,
        holdout_auc=model.holdout_score,
        n_train=int((model.metrics or {}).get("n_train") or 0),
        n_features=len(feature_cols),
    )


# ── Data materialization (framework-owned, reuses labeling.py) ───────────────────


def _feature_lookback_days(pipeline: AutoresearchPipeline) -> int:
    # Same window contract as inference._score_via_anchors: the feature-window
    # {lookback_days} is 4x horizon (min 30). Shared by train and predict so a user's
    # features are computed over the same window length on either side of T0.
    return max(30, pipeline.horizon_days * 4)


def materialize_training_data(*, team: Team, pipeline: AutoresearchPipeline, feature_sql: str) -> MaterializedData:
    """
    Train run materialization: the bundle's feature SQL against the LABELED training
    anchors (per-user random T0, with __label + __fold). Splits train/holdout by fold
    so the bundle never sees __fold. The labeler window is the pipeline's configured
    training_lookback_days.
    """
    feature_sql_resolved = feature_sql.replace("{lookback_days}", str(_feature_lookback_days(pipeline)))
    train_sql, train_values = build_training_features_sql(
        feature_sql=feature_sql_resolved,
        target_event=pipeline.target_event,
        target_definition=pipeline.target_definition,
        team=team,
        horizon_days=pipeline.horizon_days,
        lookback_days=pipeline.training_lookback_days,
        training_population=pipeline.training_population,
    )
    training_rows = _run_hogql(team=team, sql=train_sql, values=train_values)
    feature_cols = _numeric_feature_cols(training_rows)
    train_rows = [r for r in training_rows if (r.get(_FOLD_COL) or 0) != _HOLDOUT_FOLD]
    holdout_rows = [r for r in training_rows if (r.get(_FOLD_COL) or 0) == _HOLDOUT_FOLD]
    logger.info(
        "autoresearch_training_materialized",
        pipeline_id=str(pipeline.pk),
        n_train=len(train_rows),
        n_holdout=len(holdout_rows),
        n_features=len(feature_cols),
    )
    return MaterializedData(feature_cols=feature_cols, train_rows=train_rows, holdout_rows=holdout_rows)


def _materialize_score_data(
    *, team: Team, pipeline: AutoresearchPipeline, feature_sql: str, cutoff_ts: int | None = None
) -> list[dict[str, Any]]:
    """
    Predict run materialization: the bundle's feature SQL against the inference anchors
    (cutoff_ts = now() per user, or a backdated instant when ``cutoff_ts`` is given for a
    historical backfill). One row per eligible scoring user with the agent's feature
    columns — no labels, no fold. Touches only the inference population.
    """
    feature_sql_resolved = feature_sql.replace("{lookback_days}", str(_feature_lookback_days(pipeline)))
    score_sql, score_values = build_inference_features_sql(
        feature_sql=feature_sql_resolved,
        lookback_days=_feature_lookback_days(pipeline),
        inference_population=pipeline.inference_population,
        cutoff_ts=cutoff_ts,
    )
    score_rows = _run_hogql(team=team, sql=score_sql, values=score_values)
    logger.info(
        "autoresearch_score_materialized", pipeline_id=str(pipeline.pk), n_score=len(score_rows), cutoff_ts=cutoff_ts
    )
    return score_rows


def _run_hogql(*, team: Team, sql: str, values: dict[str, Any]) -> list[dict[str, Any]]:
    """Run a HogQL query and return rows as dicts, coercing person_id (distinct_id) to str."""
    # Bound explicitly — without a LIMIT, HogQL caps results at 100, silently shrinking
    # the training/holdout/score matrices to a tiny sample.
    bounded_sql = sql.rstrip().rstrip(";") + f"\nLIMIT {_MATERIALIZE_ROW_LIMIT}"
    try:
        tag_queries(product=Product.AUTORESEARCH, feature=Feature.QUERY)
        runner = HogQLQueryRunner(query=HogQLQuery(query=bounded_sql, values=values), team=team)
        result = runner.run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)
    except Exception as exc:
        raise SandboxInferenceError(f"Feature query failed: {exc}") from exc

    if not result.results or not result.columns:
        return []
    rows = [dict(zip(result.columns, row)) for row in result.results]
    for r in rows:
        if r.get("distinct_id") is not None:
            r["distinct_id"] = str(r["distinct_id"])
    return rows


def _numeric_feature_cols(rows: list[dict[str, Any]]) -> list[str]:
    """Sorted numeric feature columns, excluding distinct_id and the label/fold columns."""
    if not rows:
        return []
    sample = rows[0]
    return sorted(
        col
        for col, value in sample.items()
        if col not in {"distinct_id", _LABEL_COL, _FOLD_COL} and isinstance(value, (int, float, type(None)))
    )


# ── Sandbox execution ────────────────────────────────────────────────────────────


def _sandbox_config(pipeline: AutoresearchPipeline, kind: str) -> SandboxConfig:
    return SandboxConfig(
        name=f"autoresearch-{kind}-{pipeline.pk}",
        template=SandboxTemplate.NOTEBOOK_BASE,
        environment_variables=None,  # no credentials, no egress — pure local compute
        metadata={"product": "autoresearch", "pipeline_id": str(pipeline.pk)},
    )


def _run_train_in_sandbox(
    *,
    bundle: ArtifactBundle,
    data: MaterializedData,
    pipeline: AutoresearchPipeline,
) -> tuple[bytes, dict[str, Any]]:
    """Fit the bundle's train.py on the materialized training data; return (model.pkl bytes, metrics)."""
    cols = data.feature_cols
    with Sandbox.create(_sandbox_config(pipeline, "train")) as sandbox:
        for name, content in bundle.as_files().items():
            sandbox.write_file(f"{_WORKDIR}/bundle/{name}", content.encode("utf-8"))
        sandbox.write_file(f"{_WORKDIR}/data/train_features.parquet", features_parquet(data.train_rows, cols))
        sandbox.write_file(f"{_WORKDIR}/data/train_labels.parquet", labels_parquet(data.train_rows))
        sandbox.write_file(f"{_WORKDIR}/data/holdout_features.parquet", features_parquet(data.holdout_rows, cols))
        sandbox.write_file(f"{_WORKDIR}/data/holdout_labels.parquet", labels_parquet(data.holdout_rows))

        train_cmd = (
            f"cd {_WORKDIR} && {_SANDBOX_PYTHON} bundle/train.py "
            f"data/train_features.parquet data/train_labels.parquet {_MODEL_PKL} {_OUTPUT_JSON} "
            "data/holdout_features.parquet data/holdout_labels.parquet --random-state 42"
        )
        train_result = sandbox.execute(train_cmd, timeout_seconds=_TRAIN_TIMEOUT_S)
        if train_result.exit_code != 0:
            raise SandboxInferenceError(
                f"train.py failed (exit {train_result.exit_code}): {train_result.stderr[:1000]}"
            )
        metrics = _read_metrics(sandbox)
        model_bytes = _read_binary_file(sandbox, _MODEL_PKL)

    return model_bytes, metrics


def _run_predict_in_sandbox(
    *,
    bundle: ArtifactBundle,
    model_bytes: bytes,
    score_rows: list[dict[str, Any]],
    feature_cols: list[str],
    pipeline: AutoresearchPipeline,
) -> list[dict[str, Any]]:
    """Run only the bundle's predict.py against the persisted model + score features."""
    with Sandbox.create(_sandbox_config(pipeline, "predict")) as sandbox:
        for name, content in bundle.as_files().items():
            sandbox.write_file(f"{_WORKDIR}/bundle/{name}", content.encode("utf-8"))
        sandbox.write_file(f"{_WORKDIR}/{_MODEL_PKL}", model_bytes)
        sandbox.write_file(f"{_WORKDIR}/data/score_features.parquet", features_parquet(score_rows, feature_cols))

        predict_cmd = (
            f"cd {_WORKDIR} && {_SANDBOX_PYTHON} bundle/predict.py "
            f"data/score_features.parquet {_MODEL_PKL} {_SCORES_PARQUET}"
        )
        predict_result = sandbox.execute(predict_cmd, timeout_seconds=_PREDICT_TIMEOUT_S)
        if predict_result.exit_code != 0:
            raise SandboxInferenceError(
                f"predict.py failed (exit {predict_result.exit_code}): {predict_result.stderr[:1000]}"
            )
        scores = _read_scores(sandbox)

    return _join_scores(score_rows=score_rows, scores=scores)


def features_parquet(rows: list[dict[str, Any]], feature_cols: list[str]) -> bytes:
    """Serialize the feature matrix to parquet bytes: string `distinct_id` + float feature columns."""
    data: dict[str, list[Any]] = {"distinct_id": [str(r.get("distinct_id", "")) for r in rows]}
    for col in feature_cols:
        data[col] = [_num(r.get(col)) for r in rows]
    return _to_parquet_bytes(pd.DataFrame(data))


def labels_parquet(rows: list[dict[str, Any]]) -> bytes:
    """Serialize the label vector to parquet bytes: string `distinct_id` + int `__label`."""
    df = pd.DataFrame(
        {
            "distinct_id": [str(r.get("distinct_id", "")) for r in rows],
            _LABEL_COL: [int(r.get(_LABEL_COL) or 0) for r in rows],
        }
    )
    return _to_parquet_bytes(df)


def _to_parquet_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    return buf.getvalue()


def _num(value: Any) -> float:
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _read_metrics(sandbox: Sandbox) -> dict[str, Any]:
    """Read + validate train.py's output.json. Nothing is parsed from stdout."""
    body = _read_file(sandbox, _OUTPUT_JSON)
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise SandboxInferenceError(f"output.json is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SandboxInferenceError("output.json must be a JSON object")
    missing = [k for k in _REQUIRED_METRIC_KEYS if k not in parsed]
    if missing:
        raise SandboxInferenceError(f"output.json missing keys: {', '.join(missing)}")
    return parsed


def _read_scores(sandbox: Sandbox) -> dict[str, float]:
    """Read scores.parquet back (binary, base64 over the sentinel cat), returning {distinct_id: p_y}."""
    raw = _read_binary_file(sandbox, _SCORES_PARQUET)
    try:
        df = pd.read_parquet(io.BytesIO(raw))
    except Exception as exc:
        raise SandboxInferenceError(f"scores.parquet was not readable: {exc}") from exc
    if "distinct_id" not in df.columns or "p_y" not in df.columns:
        raise SandboxInferenceError("scores.parquet must have columns distinct_id, p_y")
    scores: dict[str, float] = {}
    for distinct_id, p_y in zip(df["distinct_id"], df["p_y"]):
        did = str(distinct_id).strip()
        if not did:
            continue
        try:
            scores[did] = float(p_y)
        except (TypeError, ValueError):
            continue
    if not scores:
        raise SandboxInferenceError("scores.parquet produced no parseable rows")
    return scores


def _read_file(sandbox: Sandbox, rel_path: str) -> str:
    """
    Read a file the bundle wrote into the workspace, via a sentinel-bracketed cat.
    write_file is the only input channel and execute→stdout the only output channel,
    so we cat the file and slice between sentinels to survive any stray shell output.
    """
    cmd = f"echo '{_FILE_BEGIN}'; cat {_WORKDIR}/{rel_path}; echo '{_FILE_END}'"
    result = sandbox.execute(cmd, timeout_seconds=60)
    if result.exit_code != 0:
        raise SandboxInferenceError(f"reading {rel_path} failed (exit {result.exit_code}): {result.stderr[:500]}")
    return _between_sentinels(result.stdout)


def _read_binary_file(sandbox: Sandbox, rel_path: str) -> bytes:
    """Read a binary file (e.g. model.pkl) the bundle wrote, base64-encoded over the sentinel-bracketed cat."""
    cmd = f"echo '{_FILE_BEGIN}'; base64 -w0 {_WORKDIR}/{rel_path}; echo; echo '{_FILE_END}'"
    result = sandbox.execute(cmd, timeout_seconds=120)
    if result.exit_code != 0:
        raise SandboxInferenceError(f"reading {rel_path} failed (exit {result.exit_code}): {result.stderr[:500]}")
    encoded = "".join(_between_sentinels(result.stdout).split())
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SandboxInferenceError(f"{rel_path} base64 readback was not decodable: {exc}") from exc


def _between_sentinels(stdout: str) -> str:
    start = stdout.find(_FILE_BEGIN)
    end = stdout.find(_FILE_END)
    if start == -1 or end == -1 or end < start:
        raise SandboxInferenceError("file sentinels not found in sandbox stdout")
    return stdout[start + len(_FILE_BEGIN) : end].strip("\n")


def _join_scores(*, score_rows: list[dict[str, Any]], scores: dict[str, float]) -> list[dict[str, Any]]:
    scored: list[dict[str, Any]] = []
    for row in score_rows:
        distinct_id = row.get("distinct_id")
        if not distinct_id or distinct_id not in scores:
            continue
        scored.append({**row, "p_y": round(scores[distinct_id], 4)})
    return scored
