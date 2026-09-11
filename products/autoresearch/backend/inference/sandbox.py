"""
Sandbox execution of an artifact bundle, split by run type.

Train run and predict run are different run types with different data contracts:

- ``fit_champion_model`` (train run, called once at completion) materializes the
  LABELED training population, runs the bundle's ``train.py`` in a sandbox, smoke-tests
  ``predict.py`` against the holdout features, and persists the fitted ``model.pkl``
  alongside the bundle. This is where fitting happens.
- ``score_via_sandbox`` (predict run, called every scoring cadence) is pure
  inference: it loads the persisted ``model.pkl``, materializes ONLY the
  inference population (cutoff ``now()``, no labels, no holdout, no fold), runs
  the bundle's ``predict.py`` only, and hands scores to the emitter. It never
  fits. A missing ``model.pkl`` fails the run so the caller can retry once the
  completion-time fit has been repaired.

Unlike the in-process recipe path (inference._score_via_anchors), the model runs
as the agent-authored scripts inside a NOTEBOOK_BASE Tasks sandbox. The framework
owns everything around the scripts: materializing the leak-free feature matrices
(via labeling.py), serialization to parquet, sandbox lifecycle, and emitting. The
bundle never receives credentials or network egress.

The framework<->bundle interchange is parquet, which is typed, columnar, and compressed.
The sandbox image ships pyarrow, so the feature matrices move faster and smaller than CSV.
This is a contract change: bundles authored against the old CSV contract fail loudly here,
because a parquet read of a CSV path errors, and must be re-trained.

Everything the scripts produce is untrusted. Script stdout goes to a file and only a
bounded tail comes back; every file readback is size-gated before it leaves the sandbox;
metrics and scores are validated before anything is persisted or emitted.

Failure is loud: any materialization or sandbox error raises, the sandbox is destroyed,
and the caller fails the run. Unlike the legacy path, there is deliberately no stub fallback,
because a silent zero-information champion would poison the realized-AUC gold-standard gate.
"""

from __future__ import annotations

import io
import json
import math
import base64
import binascii
from dataclasses import field
from decimal import Decimal
from typing import Any, Protocol

import pandas as pd
import pyarrow as pa
import structlog
import pyarrow.parquet as pq

from posthog.schema import HogQLQuery

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.team.team import Team
from posthog.models.user import User

from products.autoresearch.backend.dataset.labeling import (
    LABELER_QUERY_MODIFIERS,
    build_inference_features_sql,
    build_training_features_sql,
)
from products.autoresearch.backend.models import AutoresearchModel, AutoresearchPipeline
from products.autoresearch.backend.query import run_hogql
from products.autoresearch.backend.training.artifacts import (
    MAX_ARTIFACT_BYTES,
    ArtifactBundle,
    BundleNotFound,
    read_artifact,
    read_bundle,
    read_model,
    write_artifact,
    write_model,
)
from products.autoresearch.backend.training.recipe_validation import (
    RecipeValidationError,
    validate_feature_sql,
    validate_unique_distinct_ids,
)
from products.tasks.backend.facade.sandbox import ExecutionResult, SandboxConfig, SandboxTemplate, get_sandbox_class

Sandbox = get_sandbox_class()


class SandboxExecutor(Protocol):
    """The slice of a sandbox the file readers below need."""

    def execute(self, command: str, timeout_seconds: int | None = None) -> ExecutionResult: ...

    def write_file(self, path: str, payload: bytes, timeout_seconds: int | None = None) -> ExecutionResult: ...


logger = structlog.get_logger(__name__)

# Internal columns added by labeling.build_training_features_sql.
_LABEL_COL = "__label"
_FOLD_COL = "__fold"
_HOLDOUT_FOLD = 0  # fold 0 is the holdout slice; folds 1..N-1 are training

_WORKDIR = "/tmp/workspace/autoresearch"
_SANDBOX_PYTHON = "python3"  # NOTEBOOK_BASE puts its venv first on PATH
_TRAIN_TIMEOUT_S = 300
_PREDICT_TIMEOUT_S = 120
# A sandbox that outlives its command is a worker that died mid-run. The TTL is the
# backstop that reclaims it: long enough for uploads, the command, and readback.
_SANDBOX_TTL_S = 20 * 60
# Without an explicit bound HogQL caps a query at its default of 100 rows, which would
# shrink the train, holdout, and score matrices to a tiny sample. Mirrors FEATURE_QUERY_LIMIT.
_MATERIALIZE_ROW_LIMIT = 50_000
_OUTPUT_JSON = "data/output.json"
_SCORES_PARQUET = "data/scores.parquet"
_SCRIPT_LOG = "data/script.log"
# The fitted model the train run produces and the predict run loads (relative to _WORKDIR).
_MODEL_PKL = "model.pkl"
_SMOKE_MODEL_PKL = "smoke_model.pkl"
# The feature columns the champion was fitted on, persisted next to model.pkl so every
# predict run sends the same columns in the same order, whatever the scoring population
# happens to contain.
_FEATURE_COLUMNS_JSON = "feature_columns.json"
_FILE_BEGIN = "<<<AUTORESEARCH_FILE_BEGIN>>>"
_FILE_END = "<<<AUTORESEARCH_FILE_END>>>"
# The scripts write files of any size inside the sandbox; the readback buffers the whole
# file (base64-encoded, then decoded) in the worker. The cap matches what the artifact
# store accepts, so a model that passes readback also passes persistence.
_MAX_READBACK_BYTES = MAX_ARTIFACT_BYTES
_MAX_SCRIPT_LOG_BYTES = 4000
# Keys train.py must write into output.json.
_REQUIRED_METRIC_KEYS = ("holdout_auc", "n_train", "n_features")
# The worker expands every feature column across every row before the matrix reaches the
# sandbox. The row cap alone does not bound that, because the agent's SQL chooses the
# column count.
_MAX_FEATURE_COLS = 512
_NUMERIC_TYPES = (int, float, Decimal)


class SandboxInferenceError(Exception):
    """Raised when materialization or the sandbox run fails. The caller fails the run."""


@frozen
class MaterializedData:
    """Labeled training matrix for a train run: train + holdout folds. Predict runs return a plain row list."""

    feature_cols: list[str]
    train_rows: list[dict[str, Any]] = field(default_factory=list)
    holdout_rows: list[dict[str, Any]] = field(default_factory=list)


@frozen
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
    user: User | None = None,
) -> dict[str, Any]:
    """
    Train run: fit the champion against the LABELED training population and persist
    the resulting ``model.pkl`` under ``prefix``. Idempotent: it overwrites any prior fit.

    ``predict.py`` runs once against the holdout features before the model is persisted,
    so a bundle whose two scripts disagree fails here rather than on the first cadence.

    Returns train.py's metrics (holdout_auc, n_train, n_features). Raises
    SandboxInferenceError on any materialization or sandbox failure.
    """
    if bundle is None:
        try:
            bundle = read_bundle(prefix)
        except Exception as exc:
            raise SandboxInferenceError(f"Could not read bundle at {prefix}: {exc}") from exc
    acting_user = _resolve_acting_user(team=team, pipeline=pipeline, user=user)
    _validate_bundle_feature_sql(bundle)

    data = materialize_training_data(team=team, pipeline=pipeline, feature_sql=bundle.features_sql, user=acting_user)
    if not data.train_rows:
        raise SandboxInferenceError("No training rows to fit on")
    if not data.feature_cols:
        raise SandboxInferenceError("No numeric feature columns produced by feature SQL")

    model_bytes, metrics = _run_train_in_sandbox(bundle=bundle, data=data, pipeline=pipeline)
    write_model(prefix, model_bytes)
    write_artifact(prefix, _FEATURE_COLUMNS_JSON, json.dumps(data.feature_cols).encode("utf-8"))
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
    user: User | None = None,
) -> SandboxScoreResult:
    """
    Predict run: score the inference population with the champion's persisted model.

    Pure inference: it loads ``model.pkl`` and runs only ``predict.py`` against the
    inference population (cutoff now(), no labels, no holdout). A missing model fails
    the run: fitting stays at training completion, so a cadence never becomes a
    five-minute fit that races other cadences for the same pickle.

    Raises SandboxInferenceError on any failure (missing bundle or model, no data,
    sandbox or script error). Never falls back to stub scoring.
    """
    if not model.artifact_prefix:
        raise SandboxInferenceError(f"Model {model.pk} has no artifact_prefix")
    prefix = model.artifact_prefix

    try:
        bundle = read_bundle(prefix)
    except Exception as exc:
        raise SandboxInferenceError(f"Could not read bundle at {prefix}: {exc}") from exc
    acting_user = _resolve_acting_user(team=team, pipeline=pipeline, user=user)
    _validate_bundle_feature_sql(bundle)

    model_bytes = read_model(prefix)
    if not model_bytes:
        raise SandboxInferenceError(
            f"Champion model.pkl is missing at {prefix}; the completion-time fit has not produced it"
        )

    score_rows = _materialize_score_data(
        team=team, pipeline=pipeline, feature_sql=bundle.features_sql, cutoff_ts=cutoff_ts, user=acting_user
    )
    feature_cols = _fitted_feature_cols(prefix) or _numeric_feature_cols(score_rows)
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


# ── Guards on the bundle and the acting user ──────────────────────────────────────


def _resolve_acting_user(*, team: Team, pipeline: AutoresearchPipeline, user: User | None) -> User:
    """
    The user HogQL applies access control for. An explicit ``user`` wins (a management
    command); otherwise the pipeline's creator. With no user HogQL fails closed and can
    mask the pipeline from data its creator may read, so a creator who has left the
    project fails the run instead of silently narrowing it. The coordinator pauses such
    a pipeline before it dispatches a run.
    """
    candidate = user or pipeline.created_by
    if candidate is None:
        raise SandboxInferenceError(f"Pipeline {pipeline.pk} has no creator to run its queries as")
    if not team.all_users_with_access().filter(pk=candidate.pk).exists():
        raise SandboxInferenceError(
            f"Pipeline {pipeline.pk}: user {candidate.pk} no longer has access to team {team.pk}"
        )
    return candidate


def _validate_bundle_feature_sql(bundle: ArtifactBundle) -> None:
    """
    The recipe snapshot was validated at upload; the bundle's ``features.sql`` is what
    actually runs, so it goes through the same validator here. A trailing LIMIT, OFFSET,
    or SETTINGS clause is refused as well: inference runs the feature SQL as the top-level
    query and appends the framework's own LIMIT after it.
    """
    try:
        validate_feature_sql(bundle.features_sql)
    except RecipeValidationError as exc:
        raise SandboxInferenceError(f"Bundle features.sql failed validation: {exc}") from exc
    node = parse_select(bundle.features_sql)
    if not isinstance(node, ast.SelectQuery):
        raise SandboxInferenceError("Bundle features.sql must be a single SELECT")
    if node.limit is not None or node.offset is not None or node.limit_by is not None or node.settings is not None:
        raise SandboxInferenceError(
            "Bundle features.sql must not end with LIMIT, OFFSET, or SETTINGS; the framework bounds the result"
        )


def _fitted_feature_cols(prefix: str) -> list[str] | None:
    """The columns the champion was fitted on, or None for a champion fitted before they were persisted."""
    try:
        raw = read_artifact(prefix, _FEATURE_COLUMNS_JSON)
    except BundleNotFound:
        return None
    try:
        columns = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SandboxInferenceError(f"{_FEATURE_COLUMNS_JSON} at {prefix} is not readable: {exc}") from exc
    if not isinstance(columns, list) or not all(isinstance(c, str) for c in columns):
        raise SandboxInferenceError(f"{_FEATURE_COLUMNS_JSON} at {prefix} must be a list of column names")
    return columns


# ── Data materialization (framework-owned, reuses labeling.py) ───────────────────


def _feature_lookback_days(pipeline: AutoresearchPipeline) -> int:
    # Same window contract as inference._score_via_anchors: the feature-window
    # {lookback_days} is 4x horizon (min 30). Shared by train and predict so a user's
    # features are computed over the same window length on either side of T0.
    return max(30, pipeline.horizon_days * 4)


def materialize_training_data(
    *, team: Team, pipeline: AutoresearchPipeline, feature_sql: str, user: User | None = None
) -> MaterializedData:
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
    training_rows = _materialize_rows(team=team, sql=train_sql, values=train_values, user=user)
    _validate_rows_key_one_person(training_rows, source="training feature_sql")
    # The training wrapper LEFT JOINs the labels onto the feature rows. A feature row
    # whose distinct_id matched no anchor comes back with NULL label and fold, and the
    # fold split below would file it as a negative holdout example.
    unlabeled = sum(1 for r in training_rows if r.get(_LABEL_COL) is None or r.get(_FOLD_COL) is None)
    if unlabeled:
        raise SandboxInferenceError(
            f"{unlabeled} feature row(s) matched no labeled anchor; distinct_id must be the anchor person_id"
        )
    feature_cols = _numeric_feature_cols(training_rows)
    train_rows = [r for r in training_rows if r[_FOLD_COL] != _HOLDOUT_FOLD]
    holdout_rows = [r for r in training_rows if r[_FOLD_COL] == _HOLDOUT_FOLD]
    logger.info(
        "autoresearch_training_materialized",
        pipeline_id=str(pipeline.pk),
        n_train=len(train_rows),
        n_holdout=len(holdout_rows),
        n_features=len(feature_cols),
    )
    return MaterializedData(feature_cols=feature_cols, train_rows=train_rows, holdout_rows=holdout_rows)


def _materialize_score_data(
    *,
    team: Team,
    pipeline: AutoresearchPipeline,
    feature_sql: str,
    cutoff_ts: int | None = None,
    user: User | None = None,
) -> list[dict[str, Any]]:
    """
    Predict run materialization: the bundle's feature SQL against the inference anchors
    (cutoff_ts = now() per user, or a backdated instant when ``cutoff_ts`` is given for a
    historical backfill). One row per eligible scoring user with the agent's feature
    columns, with no labels and no fold. Touches only the inference population.
    """
    feature_sql_resolved = feature_sql.replace("{lookback_days}", str(_feature_lookback_days(pipeline)))
    score_sql, score_values = build_inference_features_sql(
        feature_sql=feature_sql_resolved,
        lookback_days=_feature_lookback_days(pipeline),
        inference_population=pipeline.inference_population,
        cutoff_ts=cutoff_ts,
        target_event=pipeline.target_event,
        target_definition=pipeline.target_definition,
        team=team,
    )
    score_rows = _materialize_rows(team=team, sql=score_sql, values=score_values, user=user)
    _validate_rows_key_one_person(score_rows, source="inference feature_sql")
    logger.info(
        "autoresearch_score_materialized", pipeline_id=str(pipeline.pk), n_score=len(score_rows), cutoff_ts=cutoff_ts
    )
    return score_rows


def _validate_rows_key_one_person(rows: list[dict[str, Any]], *, source: str) -> None:
    try:
        validate_unique_distinct_ids(rows, source=source)
    except RecipeValidationError as exc:
        raise SandboxInferenceError(str(exc)) from exc


def _materialize_rows(
    *, team: Team, sql: str, values: dict[str, Any], user: User | None = None
) -> list[dict[str, Any]]:
    """Run a HogQL query and return rows as dicts, coercing person_id (distinct_id) to str."""
    bounded_sql = sql.rstrip().rstrip(";") + f"\nLIMIT {_MATERIALIZE_ROW_LIMIT}"
    try:
        tag_queries(product=Product.AUTORESEARCH, feature=Feature.QUERY)
        # The query text is identical from one cadence to the next and reads now(), so a
        # cached result would score a stale population at a stale cutoff.
        result = run_hogql(
            team=team,
            query=HogQLQuery(query=bounded_sql, values=values, modifiers=LABELER_QUERY_MODIFIERS),
            user=user,
            execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
        )
    except Exception as exc:
        raise SandboxInferenceError(f"Feature query failed: {exc}") from exc

    if not result.rows or not result.columns:
        return []
    # as_dicts() zips column names onto values, so two columns of the same name keep only
    # the last value. The agent's SQL can produce that with unaliased joined fields, and
    # the matrix would then hold fewer features than the SQL declares.
    duplicates = sorted({str(c) for c in result.columns if list(result.columns).count(c) > 1})
    if duplicates:
        raise SandboxInferenceError(f"Feature SQL returned duplicate output columns: {', '.join(duplicates)}")
    rows = result.as_dicts()
    # A result that fills the bound is almost certainly truncated, and completing anyway
    # would advance last_scored_at while skipping the users past the cap. Pagination is
    # follow-up work; until then, fail loudly.
    if result.has_more or len(rows) >= _MATERIALIZE_ROW_LIMIT:
        raise SandboxInferenceError(
            f"Materialization hit the {_MATERIALIZE_ROW_LIMIT}-row limit; "
            "the population is likely truncated, refusing to score a partial population"
        )
    for r in rows:
        if r.get("distinct_id") is not None:
            r["distinct_id"] = str(r["distinct_id"])
    return rows


def _numeric_feature_cols(rows: list[dict[str, Any]]) -> list[str]:
    """
    Sorted numeric feature columns, excluding distinct_id and the label/fold columns.

    A column counts as numeric when every non-null value in every row is a number. The
    first row alone cannot decide it: a nullable string column that is null there would
    be serialized as zeros, and the column set would differ between train and predict
    whenever the first row's nullness differs.
    """
    if not rows:
        return []
    excluded = {"distinct_id", _LABEL_COL, _FOLD_COL}
    candidates = {col for col in rows[0] if col not in excluded}
    for row in rows:
        for col in list(candidates):
            value = row.get(col)
            if value is not None and not isinstance(value, _NUMERIC_TYPES):
                candidates.discard(col)
    return sorted(candidates)


# ── Sandbox execution ────────────────────────────────────────────────────────────


def _sandbox_config(pipeline: AutoresearchPipeline, kind: str, timeout_seconds: int) -> SandboxConfig:
    return SandboxConfig(
        name=f"autoresearch-{kind}-{pipeline.pk}",
        template=SandboxTemplate.NOTEBOOK_BASE,
        environment_variables=None,  # no credentials
        # An empty allowlist means UNRESTRICTED egress; no-egress must be stated
        # explicitly. train.py/predict.py are pure local compute over parquet.
        block_network=True,
        default_execution_timeout_seconds=timeout_seconds,
        ttl_seconds=_SANDBOX_TTL_S,
        # One sandbox per cadence per pipeline: reserve a small floor and burst to the
        # limit for the fit instead of holding the full shape through upload and readback.
        burstable_resources=True,
        metadata={"product": "autoresearch", "pipeline_id": str(pipeline.pk)},
    )


def _script_command(script: str, args: str) -> str:
    # Script output is unbounded agent output; it goes to a file the framework reads back
    # bounded, never into the worker through execute().stdout.
    return f"cd {_WORKDIR} && {_SANDBOX_PYTHON} bundle/{script} {args} > {_SCRIPT_LOG} 2>&1"


def _prepare_workspace(sandbox: SandboxExecutor, bundle: ArtifactBundle) -> None:
    # The Modal provider writes files without creating parent directories.
    result = sandbox.execute(f"mkdir -p {_WORKDIR}/bundle {_WORKDIR}/data", timeout_seconds=60)
    if result.exit_code != 0:
        raise SandboxInferenceError(f"could not create the sandbox workspace (exit {result.exit_code})")
    for name, content in bundle.as_files().items():
        _write_file(sandbox, f"{_WORKDIR}/bundle/{name}", content.encode("utf-8"))


def _write_file(sandbox: SandboxExecutor, path: str, payload: bytes) -> None:
    # The providers report a failed write through the exit code instead of raising. A
    # discarded result lets a script run against a missing or half-written input, and a
    # bundle that tolerates a missing model would emit complete-looking scores.
    result = sandbox.write_file(path, payload)
    if result.exit_code != 0:
        raise SandboxInferenceError(f"could not write {path} into the sandbox (exit {result.exit_code})")


def _run_script(sandbox: SandboxExecutor, *, script: str, args: str, timeout_seconds: int) -> None:
    result = sandbox.execute(_script_command(script, args), timeout_seconds=timeout_seconds)
    if result.exit_code != 0:
        raise SandboxInferenceError(f"{script} failed (exit {result.exit_code}): {_read_log_tail(sandbox)}")


def _run_train_in_sandbox(
    *,
    bundle: ArtifactBundle,
    data: MaterializedData,
    pipeline: AutoresearchPipeline,
) -> tuple[bytes, dict[str, Any]]:
    """Fit the bundle's train.py on the materialized training data; return (model.pkl bytes, metrics)."""
    cols = data.feature_cols
    # The smoke test scores the holdout; with no holdout the training rows stand in, so
    # the scripts' contract is still exercised before the model is persisted.
    smoke_rows = data.holdout_rows or data.train_rows
    with Sandbox.create(_sandbox_config(pipeline, "train", _TRAIN_TIMEOUT_S)) as sandbox:
        _prepare_workspace(sandbox, bundle)
        _write_file(sandbox, f"{_WORKDIR}/data/train_features.parquet", features_parquet(data.train_rows, cols))
        _write_file(sandbox, f"{_WORKDIR}/data/train_labels.parquet", labels_parquet(data.train_rows))
        _write_file(sandbox, f"{_WORKDIR}/data/holdout_features.parquet", features_parquet(data.holdout_rows, cols))
        _write_file(sandbox, f"{_WORKDIR}/data/holdout_labels.parquet", labels_parquet(data.holdout_rows))
        _write_file(sandbox, f"{_WORKDIR}/data/smoke_features.parquet", features_parquet(smoke_rows, cols))

        _run_script(
            sandbox,
            script="train.py",
            args=(
                f"data/train_features.parquet data/train_labels.parquet {_MODEL_PKL} {_OUTPUT_JSON} "
                "data/holdout_features.parquet data/holdout_labels.parquet --random-state 42"
            ),
            timeout_seconds=_TRAIN_TIMEOUT_S,
        )
        metrics = _read_metrics(sandbox)
        model_bytes = _read_binary_file(sandbox, _MODEL_PKL)

        # Smoke-test the bytes the caller persists, not the path train.py wrote. The two
        # differ if the script leaves anything still writing model.pkl, and the persisted
        # model would then be one predict.py never loaded.
        _write_file(sandbox, f"{_WORKDIR}/{_SMOKE_MODEL_PKL}", model_bytes)
        _run_script(
            sandbox,
            script="predict.py",
            args=f"data/smoke_features.parquet {_SMOKE_MODEL_PKL} {_SCORES_PARQUET}",
            timeout_seconds=_PREDICT_TIMEOUT_S,
        )
        _join_scores(score_rows=smoke_rows, scores=_read_scores(sandbox, expected_rows=len(smoke_rows)))

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
    with Sandbox.create(_sandbox_config(pipeline, "predict", _PREDICT_TIMEOUT_S)) as sandbox:
        _prepare_workspace(sandbox, bundle)
        _write_file(sandbox, f"{_WORKDIR}/{_MODEL_PKL}", model_bytes)
        _write_file(sandbox, f"{_WORKDIR}/data/score_features.parquet", features_parquet(score_rows, feature_cols))

        _run_script(
            sandbox,
            script="predict.py",
            args=f"data/score_features.parquet {_MODEL_PKL} {_SCORES_PARQUET}",
            timeout_seconds=_PREDICT_TIMEOUT_S,
        )
        scores = _read_scores(sandbox, expected_rows=len(score_rows))

    return _join_scores(score_rows=score_rows, scores=scores)


def features_parquet(rows: list[dict[str, Any]], feature_cols: list[str]) -> bytes:
    """Serialize the feature matrix to parquet bytes: string `distinct_id` + float feature columns."""
    if len(feature_cols) > _MAX_FEATURE_COLS:
        raise SandboxInferenceError(
            f"Feature SQL produced {len(feature_cols)} feature columns, over the {_MAX_FEATURE_COLS} column cap"
        )
    data: dict[str, list[Any]] = {"distinct_id": [str(r.get("distinct_id", "")) for r in rows]}
    for col in feature_cols:
        data[col] = [_num(r.get(col), col=col) for r in rows]
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


def _num(value: Any, *, col: str) -> float:
    # An absent or null cell is a zero-filled feature. A present cell that is not a number
    # means the population drifted away from the fitted schema, because the fitted columns
    # bypass _numeric_feature_cols. Zero-filling it would emit a plausible wrong prediction.
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise SandboxInferenceError(
            f"Feature column {col!r} holds the non-numeric value {value!r}; "
            "the scoring population no longer matches the fitted schema"
        ) from exc


def _read_metrics(sandbox: SandboxExecutor) -> dict[str, Any]:
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
    # json.loads accepts NaN and Infinity, and a string or a bool passes a key check, so
    # every value is typed and ranged here before it reaches the model row.
    auc = parsed["holdout_auc"]
    if auc is not None and (
        isinstance(auc, bool) or not isinstance(auc, int | float) or not math.isfinite(auc) or not 0.0 <= auc <= 1.0
    ):
        raise SandboxInferenceError(f"output.json holdout_auc must be null or a probability in [0, 1], got {auc!r}")
    for key in ("n_train", "n_features"):
        count = parsed[key]
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise SandboxInferenceError(f"output.json {key} must be a non-negative integer, got {count!r}")
    if parsed["n_features"] == 0:
        raise SandboxInferenceError("output.json reports n_features 0; train.py fit on no features")
    return parsed


def _read_scores(sandbox: SandboxExecutor, *, expected_rows: int) -> dict[str, float]:
    """
    Read scores.parquet back (binary, base64 over the sentinel cat), returning {distinct_id: p_y}.

    The footer is checked before the table is decoded: a compressed file under the
    readback cap can still expand to millions of rows, and only the two contract columns
    are read.
    """
    raw = _read_binary_file(sandbox, _SCORES_PARQUET)
    try:
        parquet = pq.ParquetFile(io.BytesIO(raw))
    except Exception as exc:
        raise SandboxInferenceError(f"scores.parquet was not readable: {exc}") from exc
    _check_scores_footer(parquet, expected_rows=expected_rows)
    try:
        df = parquet.read(columns=["distinct_id", "p_y"]).to_pandas()
    except Exception as exc:
        raise SandboxInferenceError(f"scores.parquet was not readable: {exc}") from exc
    scores: dict[str, float] = {}
    for distinct_id, p_y in zip(df["distinct_id"], df["p_y"]):
        did = str(distinct_id).strip()
        if not did:
            continue
        if did in scores:
            raise SandboxInferenceError(f"scores.parquet scores {did!r} more than once")
        scores[did] = _probability(did, p_y)
    if not scores:
        raise SandboxInferenceError("scores.parquet produced no parseable rows")
    return scores


def _check_scores_footer(parquet: pq.ParquetFile, *, expected_rows: int) -> None:
    """Reject a scores.parquet from its metadata alone, before any column is decoded."""
    schema = parquet.schema_arrow
    if "distinct_id" not in schema.names or "p_y" not in schema.names:
        raise SandboxInferenceError("scores.parquet must have columns distinct_id, p_y")
    id_type, p_type = schema.field("distinct_id").type, schema.field("p_y").type
    if not (pa.types.is_string(id_type) or pa.types.is_large_string(id_type)):
        raise SandboxInferenceError(f"scores.parquet distinct_id must be a string column, got {id_type}")
    if not (pa.types.is_floating(p_type) or pa.types.is_integer(p_type)):
        raise SandboxInferenceError(f"scores.parquet p_y must be a numeric column, got {p_type}")
    # The compressed file passed the readback cap; the decoded columns must fit it too, or
    # a highly compressible table expands in the worker before any value is checked.
    metadata = parquet.metadata
    decoded_bytes = sum(
        metadata.row_group(g).column(c).total_uncompressed_size
        for g in range(metadata.num_row_groups)
        for c in range(metadata.num_columns)
        if metadata.row_group(g).column(c).path_in_schema in ("distinct_id", "p_y")
    )
    if decoded_bytes > _MAX_READBACK_BYTES:
        raise SandboxInferenceError(f"scores.parquet decodes to {decoded_bytes} bytes, over the readback cap")
    if metadata.num_rows > expected_rows:
        raise SandboxInferenceError(
            f"scores.parquet has {metadata.num_rows} rows for {expected_rows} input rows; "
            "predict.py must score each input once"
        )


def _probability(did: str, p_y: Any) -> float:
    # predict.py is agent-authored and untrusted, so a NaN, inf, or out-of-range
    # probability would flow straight into emitted prediction events.
    try:
        score = float(p_y)
    except (TypeError, ValueError) as exc:
        raise SandboxInferenceError(f"scores.parquet has a non-numeric p_y ({p_y!r}) for {did!r}") from exc
    if not math.isfinite(score) or not (0.0 <= score <= 1.0):
        raise SandboxInferenceError(f"scores.parquet has an invalid probability p_y ({score!r}) for {did!r}")
    return score


def _readback_command(rel_path: str, *, encode: bool) -> str:
    """
    A shell command that emits the file between sentinels, or exits non-zero.

    The file must exist and fit under the readback cap before a byte of it is emitted,
    and at most cap-plus-one bytes are emitted however large it becomes. Without the
    guard a missing file would read back as empty output with exit 0, since the trailing
    echo decides the exit code, and an oversized file would be buffered whole in the worker.
    """
    # head bounds the bytes that leave the sandbox even if the file grows after the stat
    # check; the caller rejects a readback that reaches the extra byte.
    emit = (
        f'head -c {_MAX_READBACK_BYTES + 1} "$f" | base64 -w0; echo'
        if encode
        else f'head -c {_MAX_READBACK_BYTES + 1} "$f"'
    )
    return (
        f'f="{_WORKDIR}/{rel_path}"; '
        '[ -f "$f" ] || { echo "missing $f" >&2; exit 3; }; '
        's=$(stat -c %s "$f"); '
        f'[ "$s" -le {_MAX_READBACK_BYTES} ] || {{ echo "$f is $s bytes, over the {_MAX_READBACK_BYTES}-byte cap" >&2; exit 4; }}; '
        f"echo '{_FILE_BEGIN}'; {emit}; echo '{_FILE_END}'"
    )


def _read_file(sandbox: SandboxExecutor, rel_path: str) -> str:
    """
    Read a file the bundle wrote into the workspace, via a sentinel-bracketed cat.
    write_file is the only input channel and execute→stdout the only output channel,
    so we cat the file and slice between sentinels to survive any stray shell output.
    """
    result = sandbox.execute(_readback_command(rel_path, encode=False), timeout_seconds=60)
    if result.exit_code != 0:
        raise SandboxInferenceError(f"reading {rel_path} failed (exit {result.exit_code}): {result.stderr[:500]}")
    body = _between_sentinels(result.stdout)
    if len(body.encode("utf-8")) > _MAX_READBACK_BYTES:
        raise SandboxInferenceError(f"{rel_path} is over the {_MAX_READBACK_BYTES}-byte readback cap")
    return body


def _read_binary_file(sandbox: SandboxExecutor, rel_path: str) -> bytes:
    """Read a binary file (e.g. model.pkl) the bundle wrote, base64-encoded over the sentinel-bracketed cat."""
    result = sandbox.execute(_readback_command(rel_path, encode=True), timeout_seconds=120)
    if result.exit_code != 0:
        raise SandboxInferenceError(f"reading {rel_path} failed (exit {result.exit_code}): {result.stderr[:500]}")
    encoded = "".join(_between_sentinels(result.stdout).split())
    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SandboxInferenceError(f"{rel_path} base64 readback was not decodable: {exc}") from exc
    if not content:
        raise SandboxInferenceError(f"{rel_path} is empty")
    if len(content) > _MAX_READBACK_BYTES:
        raise SandboxInferenceError(f"{rel_path} is over the {_MAX_READBACK_BYTES}-byte readback cap")
    return content


def _read_log_tail(sandbox: SandboxExecutor) -> str:
    result = sandbox.execute(f"tail -c {_MAX_SCRIPT_LOG_BYTES} {_WORKDIR}/{_SCRIPT_LOG}", timeout_seconds=60)
    return result.stdout if result.exit_code == 0 else "(script log unavailable)"


def _between_sentinels(stdout: str) -> str:
    start = stdout.find(_FILE_BEGIN)
    end = stdout.find(_FILE_END)
    if start == -1 or end == -1 or end < start:
        raise SandboxInferenceError("file sentinels not found in sandbox stdout")
    return stdout[start + len(_FILE_BEGIN) : end].strip("\n")


def _join_scores(*, score_rows: list[dict[str, Any]], scores: dict[str, float]) -> list[dict[str, Any]]:
    """Join predict.py's scores back onto the input rows. Every input row must be scored,
    because a silently skipped user would never be scored again once last_scored_at advances.
    The probability keeps its full precision; rounding is the emitter's call, and
    rounding here would tie distinct predictions before online validation ranks them."""
    scored: list[dict[str, Any]] = []
    missing: list[str] = []
    for row in score_rows:
        distinct_id = row.get("distinct_id")
        if not distinct_id or distinct_id not in scores:
            missing.append(str(distinct_id))
            continue
        scored.append({**row, "p_y": scores[distinct_id]})
    if missing:
        raise SandboxInferenceError(
            f"scores.parquet covered only {len(scored)} of {len(score_rows)} input rows; missing e.g. {missing[:5]!r}"
        )
    return scored
