"""
Inference in a sandbox: run an artifact bundle's train.py + predict.py against
framework-materialized feature data, read scores back, hand them to the emitter.

This is the artifact-architecture inference path. Unlike the in-process recipe
path (inference._score_via_anchors), the model's fit and predict run as the
agent-authored scripts inside a NOTEBOOK_BASE Tasks sandbox — re-fit every run
(the intentional drift signal). The framework owns everything around the
scripts: materializing the leak-free feature matrices (via labeling.py), the
train/holdout fold split, serialization to CSV, sandbox lifecycle, and emitting
prediction events. The bundle never receives credentials or network egress.

Failure is loud: any materialization or sandbox error raises, the sandbox is
destroyed, and the caller fails the run. There is deliberately no stub fallback
(unlike the legacy path) — a silent zero-information champion would poison the
realized-AUC gold-standard gate.
"""

from __future__ import annotations

import io
import csv
import json
from dataclasses import dataclass, field
from typing import Any

import structlog

from posthog.schema import HogQLQuery

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.team.team import Team

from products.autoresearch.backend.artifacts import ArtifactBundle, read_bundle
from products.autoresearch.backend.labeling import build_inference_features_sql, build_training_features_sql
from products.autoresearch.backend.models import AutoresearchModel, AutoresearchPipeline
from products.tasks.backend.services.sandbox import Sandbox, SandboxConfig, SandboxTemplate

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
_SCORES_CSV = "data/scores.csv"
_FILE_BEGIN = "<<<AUTORESEARCH_FILE_BEGIN>>>"
_FILE_END = "<<<AUTORESEARCH_FILE_END>>>"
# Keys train.py must write into output.json.
_REQUIRED_METRIC_KEYS = ("holdout_auc", "n_train", "n_features")


class SandboxInferenceError(Exception):
    """Raised when materialization or the sandbox run fails. The caller fails the run."""


@dataclass
class MaterializedData:
    feature_cols: list[str]
    train_rows: list[dict[str, Any]] = field(default_factory=list)
    holdout_rows: list[dict[str, Any]] = field(default_factory=list)
    score_rows: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SandboxScoreResult:
    scored_rows: list[dict[str, Any]]  # score rows with an added "p_y"
    holdout_auc: float | None
    n_train: int
    n_features: int


# ── Public entry point ─────────────────────────────────────────────────────────


def score_via_sandbox(
    *,
    team: Team,
    pipeline: AutoresearchPipeline,
    model: AutoresearchModel,
) -> SandboxScoreResult:
    """
    Score the inference population by running the model's bundle in a sandbox.

    Raises SandboxInferenceError on any failure (missing bundle, no data, sandbox
    or script error). Never falls back to stub scoring.
    """
    if not model.artifact_prefix:
        raise SandboxInferenceError(f"Model {model.pk} has no artifact_prefix")

    try:
        bundle = read_bundle(model.artifact_prefix)
    except Exception as exc:
        raise SandboxInferenceError(f"Could not read bundle at {model.artifact_prefix}: {exc}") from exc

    data = _materialize_data(team=team, pipeline=pipeline, feature_sql=bundle.features_sql)

    # Cheap guards before paying for a sandbox.
    if not data.score_rows:
        raise SandboxInferenceError("No inference rows to score")
    if not data.train_rows:
        raise SandboxInferenceError("No training rows to fit on")
    if not data.feature_cols:
        raise SandboxInferenceError("No numeric feature columns produced by feature SQL")

    return _run_bundle_in_sandbox(bundle=bundle, data=data, pipeline=pipeline)


# ── Data materialization (framework-owned, reuses labeling.py) ───────────────────


def _materialize_data(*, team: Team, pipeline: AutoresearchPipeline, feature_sql: str) -> MaterializedData:
    """
    Run the bundle's feature SQL against training anchors (per-user T0, with
    __label + __fold) and inference anchors (cutoff_ts = now()), reusing the same
    labeling helpers the in-process path uses. Splits train/holdout by fold here
    so the bundle never sees __fold.
    """
    # Same window contract as inference._score_via_anchors: the feature-window
    # {lookback_days} is 4x horizon (min 30); the labeler window is the pipeline's
    # configured training_lookback_days.
    feature_lookback_days = max(30, pipeline.horizon_days * 4)
    feature_sql_resolved = feature_sql.replace("{lookback_days}", str(feature_lookback_days))

    train_sql, train_values = build_training_features_sql(
        feature_sql=feature_sql_resolved,
        target_event=pipeline.target_event,
        horizon_days=pipeline.horizon_days,
        lookback_days=pipeline.training_lookback_days,
        training_population=pipeline.training_population,
    )
    score_sql, score_values = build_inference_features_sql(
        feature_sql=feature_sql_resolved,
        lookback_days=feature_lookback_days,
        inference_population=pipeline.inference_population,
    )

    training_rows = _run_hogql(team=team, sql=train_sql, values=train_values)
    score_rows = _run_hogql(team=team, sql=score_sql, values=score_values)

    feature_cols = _numeric_feature_cols(training_rows)
    train_rows = [r for r in training_rows if (r.get(_FOLD_COL) or 0) != _HOLDOUT_FOLD]
    holdout_rows = [r for r in training_rows if (r.get(_FOLD_COL) or 0) == _HOLDOUT_FOLD]

    logger.info(
        "autoresearch_sandbox_materialized",
        pipeline_id=str(pipeline.pk),
        n_train=len(train_rows),
        n_holdout=len(holdout_rows),
        n_score=len(score_rows),
        n_features=len(feature_cols),
    )
    return MaterializedData(
        feature_cols=feature_cols,
        train_rows=train_rows,
        holdout_rows=holdout_rows,
        score_rows=score_rows,
    )


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


def _run_bundle_in_sandbox(
    *,
    bundle: ArtifactBundle,
    data: MaterializedData,
    pipeline: AutoresearchPipeline,
) -> SandboxScoreResult:
    config = SandboxConfig(
        name=f"autoresearch-inference-{pipeline.pk}",
        template=SandboxTemplate.NOTEBOOK_BASE,
        environment_variables=None,  # no credentials, no egress — pure local compute
        metadata={"product": "autoresearch", "pipeline_id": str(pipeline.pk)},
    )

    with Sandbox.create(config) as sandbox:
        _upload_inputs(sandbox, bundle=bundle, data=data)

        train_cmd = (
            f"cd {_WORKDIR} && {_SANDBOX_PYTHON} bundle/train.py "
            f"data/train_features.csv data/train_labels.csv model.pkl {_OUTPUT_JSON} "
            "data/holdout_features.csv data/holdout_labels.csv --random-state 42"
        )
        train_result = sandbox.execute(train_cmd, timeout_seconds=_TRAIN_TIMEOUT_S)
        if train_result.exit_code != 0:
            raise SandboxInferenceError(
                f"train.py failed (exit {train_result.exit_code}): {train_result.stderr[:1000]}"
            )
        train_meta = _read_metrics(sandbox)

        predict_cmd = (
            f"cd {_WORKDIR} && {_SANDBOX_PYTHON} bundle/predict.py data/score_features.csv model.pkl {_SCORES_CSV}"
        )
        predict_result = sandbox.execute(predict_cmd, timeout_seconds=_PREDICT_TIMEOUT_S)
        if predict_result.exit_code != 0:
            raise SandboxInferenceError(
                f"predict.py failed (exit {predict_result.exit_code}): {predict_result.stderr[:1000]}"
            )

        scores = _read_scores(sandbox)

    scored_rows = _join_scores(score_rows=data.score_rows, scores=scores)
    return SandboxScoreResult(
        scored_rows=scored_rows,
        holdout_auc=train_meta.get("holdout_auc"),
        n_train=int(train_meta.get("n_train") or 0),
        n_features=int(train_meta.get("n_features") or len(data.feature_cols)),
    )


def _upload_inputs(sandbox: Sandbox, *, bundle: ArtifactBundle, data: MaterializedData) -> None:
    """Write the bundle scripts and the materialized CSVs into the sandbox workspace."""
    for name, content in bundle.as_files().items():
        sandbox.write_file(f"{_WORKDIR}/bundle/{name}", content.encode("utf-8"))

    cols = data.feature_cols
    sandbox.write_file(f"{_WORKDIR}/data/train_features.csv", _features_csv(data.train_rows, cols).encode("utf-8"))
    sandbox.write_file(f"{_WORKDIR}/data/train_labels.csv", _labels_csv(data.train_rows).encode("utf-8"))
    sandbox.write_file(f"{_WORKDIR}/data/holdout_features.csv", _features_csv(data.holdout_rows, cols).encode("utf-8"))
    sandbox.write_file(f"{_WORKDIR}/data/holdout_labels.csv", _labels_csv(data.holdout_rows).encode("utf-8"))
    sandbox.write_file(f"{_WORKDIR}/data/score_features.csv", _features_csv(data.score_rows, cols).encode("utf-8"))


def _features_csv(rows: list[dict[str, Any]], feature_cols: list[str]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["distinct_id", *feature_cols])
    for r in rows:
        writer.writerow([r.get("distinct_id", ""), *[_num(r.get(c)) for c in feature_cols]])
    return out.getvalue()


def _labels_csv(rows: list[dict[str, Any]]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["distinct_id", _LABEL_COL])
    for r in rows:
        writer.writerow([r.get("distinct_id", ""), int(r.get(_LABEL_COL) or 0)])
    return out.getvalue()


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
    """Read scores.csv back, returning {distinct_id: p_y}."""
    body = _read_file(sandbox, _SCORES_CSV)
    scores: dict[str, float] = {}
    for row in csv.DictReader(io.StringIO(body)):
        distinct_id = (row.get("distinct_id") or "").strip()
        if not distinct_id:
            continue
        try:
            scores[distinct_id] = float(row["p_y"])
        except (KeyError, TypeError, ValueError):
            continue
    if not scores:
        raise SandboxInferenceError("scores.csv produced no parseable rows")
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
