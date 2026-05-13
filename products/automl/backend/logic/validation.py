"""Preflight validation for AutoML pipeline configs.

Runs before pipeline creation (and can be re-run any time against the same
config shape). Produces a structured report of findings tagged by severity,
plus a small quantitative summary the UI can show inline.

Two categories of check:

- **Structural** — config-shape, required keys, cadence ordering, naming
  conventions. Free, side-effect-free, always run.
- **Data-touching** — HogQL ``count()`` queries against the team's data for
  training/inference population size and the recent positive count. Each query
  is wrapped in try/except; failures degrade gracefully to an ``info`` finding
  rather than blocking validation outright.

Thresholds match the setup-time validation table in the AutoML skill's
``examples/user-event-prediction.md``.
"""

from __future__ import annotations

import re
from typing import Any

from posthog.hogql.query import execute_hogql_query

from posthog.models.team import Team

from ..facade import contracts
from ..facade.enums import Cadence, TaskType

# Volume thresholds. Mirrors the setup-time validation table in
# `/phs automl` -> examples/user-event-prediction.md.
_MIN_TRAINING_ROWS = 5_000
_DEFAULT_SAMPLING_CAP = 200_000
_MIN_POSITIVE_RATE = 0.005  # 0.5%
_MAX_INFERENCE_EVENTS_PER_DAY = 200_000

# Property naming convention from the skill's io-spec.md (lean: yes on $automl_prediction
# event, no on properties — but the prefix `automl_` keeps namespacing explicit).
_AUTOML_PROPERTY_PREFIX = "automl_"

# Ordinal for cadence "frequency" — used to compare inference vs retraining.
# Lower index = more frequent. NEVER means manual-only and is always allowed.
_CADENCE_RANK: dict[str, int] = {
    Cadence.HOURLY.value: 0,
    Cadence.DAILY.value: 1,
    Cadence.WEEKLY.value: 2,
    Cadence.MONTHLY.value: 3,
}

# Multiplier from inference cadence to events-per-day. NEVER omitted — no
# scheduled inference means we don't surface a per-day projection.
_CADENCE_PER_DAY: dict[str, float] = {
    Cadence.HOURLY.value: 24.0,
    Cadence.DAILY.value: 1.0,
    Cadence.WEEKLY.value: 1.0 / 7.0,
    Cadence.MONTHLY.value: 1.0 / 30.0,
}

# HogQL identifier surface for event names — letters, digits, $, _, space, dot, slash, hyphen.
# Anything else and we refuse to embed in the count query rather than try to escape it ourselves.
_SAFE_EVENT_NAME = re.compile(r"^[A-Za-z0-9_$ ./-]+$")

# HogQL identifier surface for series-key / column expressions in forecasting. Tighter than
# event names — only typical column / function-call shapes allowed before we'll embed.
_SAFE_HOGQL_EXPRESSION = re.compile(r"^[A-Za-z0-9_$ .,()\[\]'\"-]+$")

# Per-task enum allow-lists. Centralised here so the structural checks below stay terse —
# the source of truth is the skill's io-spec.md.
_CLASSIFICATION_FRAMINGS = {"adoption", "continuation"}
_CLASSIFICATION_CLASS_BALANCE = {"none", "undersample_negatives", "class_weights"}
_CLASSIFICATION_CALIBRATION = {"none", "sigmoid", "isotonic"}
_FORECASTING_GRAINS = {"hour", "day", "week", "month"}
_CLUSTERING_DISTANCE_METRICS = {"euclidean", "cosine", "manhattan"}
_CLUSTERING_DIM_REDUCTION = {"none", "umap", "pca"}

# Floor on rows-per-cluster. With fewer than this many entities per cluster the
# fit overfits and cluster IDs aren't stable across re-runs.
_MIN_ROWS_PER_CLUSTER = 50


def run_validation(*, team_id: int, params: contracts.CreatePipelineInput) -> contracts.ValidationReport:
    """Run preflight checks on a proposed pipeline config.

    Returns a ``ValidationReport`` even on internal failure — exceptions raised
    during data-touching checks are converted into ``info`` findings so the
    caller always gets a structured response.
    """
    findings: list[contracts.ValidationFinding] = []
    summary_extras: dict[str, Any] = {}

    findings.extend(_check_task_specific_config(params))
    findings.extend(_check_cadence_ordering(params))
    findings.extend(_check_output_property_naming(params))
    findings.extend(_check_population_kind(params))

    team = Team.objects.filter(id=team_id).first()
    if team is None:
        findings.append(
            contracts.ValidationFinding(
                severity=contracts.ValidationSeverity.BLOCK,
                code="team_not_found",
                message=f"Team {team_id} not found.",
            )
        )
        return _assemble_report(params, findings, summary_extras)

    training_query = _hogql_query_or_none(params.training_population)
    if training_query is not None:
        rows, query_findings = _count_rows(team=team, query=training_query, kind="training_population")
        findings.extend(query_findings)
        if rows is not None:
            summary_extras["estimated_training_rows"] = rows
            findings.extend(_check_training_volume(params=params, training_rows=rows))

    inference_query = _hogql_query_or_none(params.inference_population)
    if inference_query is not None:
        rows, query_findings = _count_rows(team=team, query=inference_query, kind="inference_population")
        findings.extend(query_findings)
        if rows is not None:
            summary_extras["estimated_inference_rows"] = rows
            per_day = _estimated_inference_events_per_day(params=params, inference_rows=rows)
            if per_day is not None:
                summary_extras["estimated_inference_events_per_day"] = per_day
                if per_day > _MAX_INFERENCE_EVENTS_PER_DAY:
                    findings.append(
                        contracts.ValidationFinding(
                            severity=contracts.ValidationSeverity.WARN,
                            code="inference_volume_high",
                            message=(
                                f"Estimated {per_day:,} prediction events per day at "
                                f"{params.inference_cadence.value} cadence exceeds the {_MAX_INFERENCE_EVENTS_PER_DAY:,} default ceiling."
                            ),
                            details={"per_day": per_day, "threshold": _MAX_INFERENCE_EVENTS_PER_DAY},
                        )
                    )

    # Per-task dispatch. Each branch may emit findings, mutate summary_extras with
    # task-specific numbers, and (for classification/forecasting) issue extra
    # HogQL count queries to size labels / series.
    if params.task_type is TaskType.CLASSIFICATION:
        findings.extend(_check_classification_specific(params=params, team=team, summary_extras=summary_extras))
    elif params.task_type is TaskType.REGRESSION:
        findings.extend(_check_regression_specific(params=params))
    elif params.task_type is TaskType.FORECASTING:
        findings.extend(_check_forecasting_specific(params=params, team=team, summary_extras=summary_extras))
    elif params.task_type is TaskType.CLUSTERING:
        findings.extend(_check_clustering_specific(params=params, summary_extras=summary_extras))

    return _assemble_report(params, findings, summary_extras)


def _assemble_report(
    params: contracts.CreatePipelineInput,
    findings: list[contracts.ValidationFinding],
    summary_extras: dict[str, Any],
) -> contracts.ValidationReport:
    summary = contracts.ValidationSummary(
        task_type=params.task_type,
        training_population_kind=_population_kind(params.training_population),
        estimated_training_rows=summary_extras.get("estimated_training_rows"),
        estimated_inference_rows=summary_extras.get("estimated_inference_rows"),
        estimated_inference_events_per_day=summary_extras.get("estimated_inference_events_per_day"),
        estimated_positive_count=summary_extras.get("estimated_positive_count"),
        estimated_positive_rate=summary_extras.get("estimated_positive_rate"),
        target_event=summary_extras.get("target_event"),
        estimated_series_count=summary_extras.get("estimated_series_count"),
        estimated_rows_per_cluster=summary_extras.get("estimated_rows_per_cluster"),
    )
    ok = not any(f.severity is contracts.ValidationSeverity.BLOCK for f in findings)
    return contracts.ValidationReport(ok=ok, findings=findings, summary=summary)


# ----- structural checks ----------------------------------------------------


def _check_task_specific_config(params: contracts.CreatePipelineInput) -> list[contracts.ValidationFinding]:
    """Enforce the minimum required ``config`` keys per task type.

    Mirrors the per-task-type schema in `/phs automl` -> io-spec.md. v0 covers
    the bare-minimum fields the inference path actually needs.
    """
    config = params.config if isinstance(params.config, dict) else {}
    findings: list[contracts.ValidationFinding] = []

    required_per_task: dict[TaskType, tuple[str, ...]] = {
        TaskType.CLASSIFICATION: ("target_event", "horizon_days"),
        TaskType.REGRESSION: ("target_expression", "horizon_days"),
        TaskType.FORECASTING: ("series_expression", "grain", "horizon_steps"),
        TaskType.CLUSTERING: (),
    }
    missing = [key for key in required_per_task.get(params.task_type, ()) if not config.get(key)]
    if missing:
        findings.append(
            contracts.ValidationFinding(
                severity=contracts.ValidationSeverity.BLOCK,
                code="config_missing_required_keys",
                message=(f"Task type {params.task_type.value} requires config keys: {', '.join(missing)}."),
                details={"missing": missing, "task_type": params.task_type.value},
            )
        )

    horizon_days = config.get("horizon_days")
    if horizon_days is not None and (not isinstance(horizon_days, int) or horizon_days <= 0):
        findings.append(
            contracts.ValidationFinding(
                severity=contracts.ValidationSeverity.BLOCK,
                code="horizon_days_invalid",
                message="config.horizon_days must be a positive integer.",
                details={"horizon_days": horizon_days},
            )
        )

    return findings


def _check_cadence_ordering(params: contracts.CreatePipelineInput) -> list[contracts.ValidationFinding]:
    """Warn when retraining is less frequent than inference.

    The training set goes stale between retrains; an inference run that ticks
    faster than retraining is fine, but a retraining schedule slower than the
    inference one means the model can keep scoring against a long-out-of-date
    fit. Warn rather than block — some pipelines (forecasting, clustering)
    legitimately retrain monthly and infer daily.
    """
    inference_rank = _CADENCE_RANK.get(params.inference_cadence.value)
    retraining_rank = _CADENCE_RANK.get(params.retraining_cadence.value)
    if inference_rank is None or retraining_rank is None:
        # NEVER on either side — skip the comparison; it's a deliberate manual choice.
        return []
    if retraining_rank < inference_rank:
        return [
            contracts.ValidationFinding(
                severity=contracts.ValidationSeverity.INFO,
                code="retraining_more_frequent_than_inference",
                message=(
                    f"Retraining cadence {params.retraining_cadence.value} is more frequent "
                    f"than inference cadence {params.inference_cadence.value}. The model will refit "
                    "between every other inference run; this is allowed but unusual."
                ),
                details={
                    "inference_cadence": params.inference_cadence.value,
                    "retraining_cadence": params.retraining_cadence.value,
                },
            )
        ]
    return []


def _check_output_property_naming(params: contracts.CreatePipelineInput) -> list[contracts.ValidationFinding]:
    """Recommend the ``automl_`` prefix for output properties.

    The skill's io-spec.md leans toward namespacing automl-written properties
    with the ``automl_`` prefix to avoid collisions with user-set ones. Empty
    is allowed (event-only pipelines).
    """
    name = params.output_property_name
    if not name:
        return []
    if name.startswith("$"):
        return [
            contracts.ValidationFinding(
                severity=contracts.ValidationSeverity.BLOCK,
                code="output_property_reserved_prefix",
                message=(
                    "output_property_name cannot start with $. The $ prefix is reserved for PostHog system properties."
                ),
                details={"output_property_name": name},
            )
        ]
    if not name.startswith(_AUTOML_PROPERTY_PREFIX):
        return [
            contracts.ValidationFinding(
                severity=contracts.ValidationSeverity.WARN,
                code="output_property_unprefixed",
                message=(
                    f"output_property_name {name!r} doesn't use the {_AUTOML_PROPERTY_PREFIX!r} prefix. "
                    "The prefix is recommended to keep auto-written properties namespaced."
                ),
                details={"output_property_name": name, "recommended_prefix": _AUTOML_PROPERTY_PREFIX},
            )
        ]
    return []


def _check_population_kind(params: contracts.CreatePipelineInput) -> list[contracts.ValidationFinding]:
    """Surface populations we can't yet count from (cohort references, etc.).

    The model accepts arbitrary JSON for ``training_population`` /
    ``inference_population``; v0 only counts ``kind: hogql`` populations. Other
    shapes are accepted but flagged so the user knows we couldn't size them.
    """
    findings: list[contracts.ValidationFinding] = []
    for label, population in (
        ("training", params.training_population),
        ("inference", params.inference_population),
    ):
        kind = _population_kind(population)
        if kind == "missing":
            findings.append(
                contracts.ValidationFinding(
                    severity=contracts.ValidationSeverity.BLOCK,
                    code=f"{label}_population_missing",
                    message=f"{label}_population is empty.",
                )
            )
            continue
        if kind == "hogql":
            continue
        findings.append(
            contracts.ValidationFinding(
                severity=contracts.ValidationSeverity.INFO,
                code=f"{label}_population_kind_not_counted",
                message=(
                    f"{label}_population kind {kind!r} is accepted but not yet sized by validation. "
                    "Volume and base-rate estimates require a hogql kind."
                ),
                details={"kind": kind},
            )
        )
    return findings


def _check_training_volume(
    *, params: contracts.CreatePipelineInput, training_rows: int
) -> list[contracts.ValidationFinding]:
    """Block when training is below the noise floor; info when above the cap."""
    findings: list[contracts.ValidationFinding] = []
    config = params.config if isinstance(params.config, dict) else {}
    sampling_cap = config.get("sampling_cap")
    if not isinstance(sampling_cap, int) or sampling_cap <= 0:
        sampling_cap = _DEFAULT_SAMPLING_CAP

    if training_rows < _MIN_TRAINING_ROWS:
        findings.append(
            contracts.ValidationFinding(
                severity=contracts.ValidationSeverity.BLOCK,
                code="training_volume_too_low",
                message=(
                    f"Training population has {training_rows:,} entities, below the {_MIN_TRAINING_ROWS:,} minimum. "
                    "Broaden the population or pick a different target."
                ),
                details={"training_rows": training_rows, "threshold": _MIN_TRAINING_ROWS},
            )
        )
    elif training_rows > sampling_cap:
        findings.append(
            contracts.ValidationFinding(
                severity=contracts.ValidationSeverity.INFO,
                code="training_volume_exceeds_sampling_cap",
                message=(
                    f"Training population has {training_rows:,} entities; will be uniformly sampled to {sampling_cap:,} for training."
                ),
                details={"training_rows": training_rows, "sampling_cap": sampling_cap},
            )
        )
    return findings


# ----- per-task checks -------------------------------------------------------


def _check_classification_specific(
    *,
    params: contracts.CreatePipelineInput,
    team: Team,
    summary_extras: dict[str, Any],
) -> list[contracts.ValidationFinding]:
    """Classification-only checks.

    Adds the positive-rate data point (used by both the summary and the
    base-rate gate) and validates framing/balance/calibration enums. The
    adoption-framing and censoring reminders are intentionally INFO — we can't
    parse the user's HogQL query to assert these, but we want the user prompted
    to verify before pipeline creation.
    """
    findings: list[contracts.ValidationFinding] = []
    config = params.config if isinstance(params.config, dict) else {}

    target_event = config.get("target_event")
    horizon_days = config.get("horizon_days")
    framing = config.get("framing")
    class_balance = config.get("class_balance")
    calibration = config.get("calibration")

    if not isinstance(target_event, str):
        # Multi-class with target_event as a list isn't supported in v0 — the
        # io-spec models target_event as a single event. Flag rather than allow
        # silently coercing to string.
        if target_event is not None:
            findings.append(
                contracts.ValidationFinding(
                    severity=contracts.ValidationSeverity.BLOCK,
                    code="target_event_must_be_string",
                    message=(
                        "config.target_event must be a single event name string. "
                        "Multi-class classification isn't supported in this release."
                    ),
                    details={"target_event": target_event},
                )
            )
    else:
        summary_extras["target_event"] = target_event

    if framing is not None and framing not in _CLASSIFICATION_FRAMINGS:
        findings.append(
            contracts.ValidationFinding(
                severity=contracts.ValidationSeverity.BLOCK,
                code="framing_invalid",
                message=(f"config.framing must be one of {sorted(_CLASSIFICATION_FRAMINGS)}, got {framing!r}."),
                details={"framing": framing, "allowed": sorted(_CLASSIFICATION_FRAMINGS)},
            )
        )

    if class_balance is not None and class_balance not in _CLASSIFICATION_CLASS_BALANCE:
        findings.append(
            contracts.ValidationFinding(
                severity=contracts.ValidationSeverity.BLOCK,
                code="class_balance_invalid",
                message=(
                    f"config.class_balance must be one of {sorted(_CLASSIFICATION_CLASS_BALANCE)}, got {class_balance!r}."
                ),
                details={"class_balance": class_balance, "allowed": sorted(_CLASSIFICATION_CLASS_BALANCE)},
            )
        )

    if calibration is not None and calibration not in _CLASSIFICATION_CALIBRATION:
        findings.append(
            contracts.ValidationFinding(
                severity=contracts.ValidationSeverity.BLOCK,
                code="calibration_invalid",
                message=(
                    f"config.calibration must be one of {sorted(_CLASSIFICATION_CALIBRATION)}, got {calibration!r}."
                ),
                details={"calibration": calibration, "allowed": sorted(_CLASSIFICATION_CALIBRATION)},
            )
        )

    # Adoption framing is a semantic property of the training population query
    # we can't verify by inspection — emit an INFO reminder so the user explicitly
    # confirms instead of finding out post-bootstrap.
    if framing == "adoption":
        findings.append(
            contracts.ValidationFinding(
                severity=contracts.ValidationSeverity.INFO,
                code="adoption_framing_requires_exclusion",
                message=(
                    "Adoption framing predicts a first-time event fire. Verify your training "
                    "population query excludes entities that have already fired the target_event."
                ),
            )
        )

    # Same idea for censoring — recent signups can't have an observable label.
    if isinstance(horizon_days, int) and horizon_days > 0:
        findings.append(
            contracts.ValidationFinding(
                severity=contracts.ValidationSeverity.INFO,
                code="censoring_reminder",
                message=(
                    f"Verify your training population excludes entities whose first-seen is "
                    f"within the last {horizon_days} days. Their labels can't be observed within the horizon."
                ),
                details={"horizon_days": horizon_days},
            )
        )

    # Positive count + base-rate gate.
    if isinstance(target_event, str) and isinstance(horizon_days, int) and horizon_days > 0:
        positives, positive_findings = _count_recent_positives(
            team=team, target_event=target_event, horizon_days=horizon_days
        )
        findings.extend(positive_findings)
        if positives is not None:
            summary_extras["estimated_positive_count"] = positives
            training_rows = summary_extras.get("estimated_training_rows")
            if training_rows and training_rows > 0:
                rate = positives / training_rows
                summary_extras["estimated_positive_rate"] = rate
                if rate < _MIN_POSITIVE_RATE:
                    findings.append(
                        contracts.ValidationFinding(
                            severity=contracts.ValidationSeverity.BLOCK,
                            code="positive_rate_too_low",
                            message=(
                                f"Estimated positive rate {rate:.2%} is below the "
                                f"{_MIN_POSITIVE_RATE:.2%} floor. The classifier will likely learn the majority class only."
                            ),
                            details={"rate": rate, "threshold": _MIN_POSITIVE_RATE},
                        )
                    )

    return findings


def _check_regression_specific(
    *,
    params: contracts.CreatePipelineInput,
) -> list[contracts.ValidationFinding]:
    """Regression-only checks.

    No data-side label count for v0 — ``target_expression`` semantics vary
    too much to validate reliably without binding it to a concrete training row
    schema. Flagged as a follow-up in the AutoML skill's TODO instead. Structural
    checks (expression shape, prediction_intervals bool, horizon, censoring
    reminder) ship today.
    """
    findings: list[contracts.ValidationFinding] = []
    config = params.config if isinstance(params.config, dict) else {}

    target_expression = config.get("target_expression")
    if isinstance(target_expression, str) and not target_expression.strip():
        findings.append(
            contracts.ValidationFinding(
                severity=contracts.ValidationSeverity.BLOCK,
                code="target_expression_empty",
                message="config.target_expression must be a non-empty HogQL expression.",
            )
        )

    intervals = config.get("prediction_intervals")
    if intervals is not None and not isinstance(intervals, bool):
        findings.append(
            contracts.ValidationFinding(
                severity=contracts.ValidationSeverity.BLOCK,
                code="prediction_intervals_invalid",
                message="config.prediction_intervals must be a boolean.",
                details={"prediction_intervals": intervals},
            )
        )

    horizon_days = config.get("horizon_days")
    if isinstance(horizon_days, int) and horizon_days > 0:
        findings.append(
            contracts.ValidationFinding(
                severity=contracts.ValidationSeverity.INFO,
                code="censoring_reminder",
                message=(
                    f"Verify your training population excludes entities whose first-seen is "
                    f"within the last {horizon_days} days. Their realized target values can't be observed within the horizon."
                ),
                details={"horizon_days": horizon_days},
            )
        )

    findings.append(
        contracts.ValidationFinding(
            severity=contracts.ValidationSeverity.INFO,
            code="regression_label_volume_unchecked",
            message=(
                "Regression label volume isn't separately sized by validation in this release — "
                "rely on the training population size estimate plus a manual spot-check of target_expression on a sample."
            ),
        )
    )

    return findings


def _check_forecasting_specific(
    *,
    params: contracts.CreatePipelineInput,
    team: Team,
    summary_extras: dict[str, Any],
) -> list[contracts.ValidationFinding]:
    """Forecasting-only checks.

    Structural: grain in allowed set, horizon_steps positive int, prediction_intervals
    bool, series_expression non-empty. Data-touching: count distinct series in the
    inference population when ``series_key`` is configured.
    """
    findings: list[contracts.ValidationFinding] = []
    config = params.config if isinstance(params.config, dict) else {}

    grain = config.get("grain")
    if grain is not None and grain not in _FORECASTING_GRAINS:
        findings.append(
            contracts.ValidationFinding(
                severity=contracts.ValidationSeverity.BLOCK,
                code="grain_invalid",
                message=(f"config.grain must be one of {sorted(_FORECASTING_GRAINS)}, got {grain!r}."),
                details={"grain": grain, "allowed": sorted(_FORECASTING_GRAINS)},
            )
        )

    horizon_steps = config.get("horizon_steps")
    if horizon_steps is not None and (not isinstance(horizon_steps, int) or horizon_steps <= 0):
        findings.append(
            contracts.ValidationFinding(
                severity=contracts.ValidationSeverity.BLOCK,
                code="horizon_steps_invalid",
                message="config.horizon_steps must be a positive integer.",
                details={"horizon_steps": horizon_steps},
            )
        )

    intervals = config.get("prediction_intervals")
    if intervals is not None and not isinstance(intervals, bool):
        findings.append(
            contracts.ValidationFinding(
                severity=contracts.ValidationSeverity.BLOCK,
                code="prediction_intervals_invalid",
                message="config.prediction_intervals must be a boolean.",
                details={"prediction_intervals": intervals},
            )
        )

    series_expression = config.get("series_expression")
    if isinstance(series_expression, str) and not series_expression.strip():
        findings.append(
            contracts.ValidationFinding(
                severity=contracts.ValidationSeverity.BLOCK,
                code="series_expression_empty",
                message="config.series_expression must be a non-empty HogQL expression.",
            )
        )

    # Optional distinct-series count for sized populations with a series_key.
    series_key = config.get("series_key")
    inference_query = _hogql_query_or_none(params.inference_population)
    if isinstance(series_key, str) and series_key.strip() and inference_query is not None:
        if _SAFE_HOGQL_EXPRESSION.match(series_key):
            wrapped = f"SELECT count(DISTINCT {series_key}) FROM ({inference_query})"
            try:
                response = execute_hogql_query(query=wrapped, team=team)
                series_count = _first_int(response.results)
                if series_count is not None:
                    summary_extras["estimated_series_count"] = series_count
                    if series_count <= 1:
                        findings.append(
                            contracts.ValidationFinding(
                                severity=contracts.ValidationSeverity.INFO,
                                code="forecasting_single_series",
                                message=(
                                    f"Inference population resolves to {series_count} distinct series. "
                                    "This pipeline will produce a single forecast each run."
                                ),
                                details={"series_count": series_count},
                            )
                        )
            except Exception as exc:
                findings.append(
                    contracts.ValidationFinding(
                        severity=contracts.ValidationSeverity.INFO,
                        code="series_count_failed",
                        message=(f"Could not count distinct series: {type(exc).__name__}. Series-count check skipped."),
                        details={"error": str(exc)[:200]},
                    )
                )
        else:
            findings.append(
                contracts.ValidationFinding(
                    severity=contracts.ValidationSeverity.INFO,
                    code="series_key_unsafe_for_count",
                    message=(
                        f"Skipping distinct-series count: series_key {series_key!r} contains "
                        "characters we don't safely embed in a count query."
                    ),
                )
            )

    return findings


def _check_clustering_specific(
    *,
    params: contracts.CreatePipelineInput,
    summary_extras: dict[str, Any],
) -> list[contracts.ValidationFinding]:
    """Clustering-only checks.

    Validates ``cluster_count`` shape (``"auto"`` or positive int), checks the
    distance metric / dimensionality-reduction enums, and warns when too many
    clusters are requested relative to training-set size (fit overfits + cluster
    IDs become unstable across re-runs).
    """
    findings: list[contracts.ValidationFinding] = []
    config = params.config if isinstance(params.config, dict) else {}

    cluster_count = config.get("cluster_count")
    if cluster_count is not None:
        if cluster_count == "auto":
            pass
        elif isinstance(cluster_count, int) and cluster_count >= 2:
            training_rows = summary_extras.get("estimated_training_rows")
            if isinstance(training_rows, int) and training_rows > 0:
                rows_per_cluster = training_rows / cluster_count
                summary_extras["estimated_rows_per_cluster"] = rows_per_cluster
                if rows_per_cluster < _MIN_ROWS_PER_CLUSTER:
                    findings.append(
                        contracts.ValidationFinding(
                            severity=contracts.ValidationSeverity.WARN,
                            code="cluster_count_too_high_for_volume",
                            message=(
                                f"Requested {cluster_count} clusters across {training_rows:,} training rows "
                                f"({rows_per_cluster:.0f} rows per cluster, below the {_MIN_ROWS_PER_CLUSTER}-row floor). "
                                "Cluster IDs are likely to be unstable across re-runs."
                            ),
                            details={
                                "cluster_count": cluster_count,
                                "training_rows": training_rows,
                                "rows_per_cluster": rows_per_cluster,
                                "threshold": _MIN_ROWS_PER_CLUSTER,
                            },
                        )
                    )
        else:
            findings.append(
                contracts.ValidationFinding(
                    severity=contracts.ValidationSeverity.BLOCK,
                    code="cluster_count_invalid",
                    message='config.cluster_count must be "auto" or an integer >= 2.',
                    details={"cluster_count": cluster_count},
                )
            )

    distance_metric = config.get("distance_metric")
    if distance_metric is not None and distance_metric not in _CLUSTERING_DISTANCE_METRICS:
        findings.append(
            contracts.ValidationFinding(
                severity=contracts.ValidationSeverity.BLOCK,
                code="distance_metric_invalid",
                message=(
                    f"config.distance_metric must be one of {sorted(_CLUSTERING_DISTANCE_METRICS)}, got {distance_metric!r}."
                ),
                details={"distance_metric": distance_metric, "allowed": sorted(_CLUSTERING_DISTANCE_METRICS)},
            )
        )

    dim_reduction = config.get("dimensionality_reduction")
    if dim_reduction is not None and dim_reduction not in _CLUSTERING_DIM_REDUCTION:
        findings.append(
            contracts.ValidationFinding(
                severity=contracts.ValidationSeverity.BLOCK,
                code="dimensionality_reduction_invalid",
                message=(
                    f"config.dimensionality_reduction must be one of {sorted(_CLUSTERING_DIM_REDUCTION)}, got {dim_reduction!r}."
                ),
                details={"dimensionality_reduction": dim_reduction, "allowed": sorted(_CLUSTERING_DIM_REDUCTION)},
            )
        )

    return findings


# ----- data-touching checks --------------------------------------------------


def _count_rows(*, team: Team, query: str, kind: str) -> tuple[int | None, list[contracts.ValidationFinding]]:
    """Run ``SELECT count() FROM (<query>)`` and return the row count.

    Failures convert to an ``info`` finding rather than raising — preflight is
    best-effort. The wrapped query is parenthesized so any ORDER BY / LIMIT in
    the inner query stays valid.
    """
    wrapper = f"SELECT count() FROM ({query})"
    try:
        response = execute_hogql_query(query=wrapper, team=team)
    except Exception as exc:
        return None, [
            contracts.ValidationFinding(
                severity=contracts.ValidationSeverity.INFO,
                code=f"{kind}_count_failed",
                message=(
                    f"Could not size {kind}: {type(exc).__name__}. Volume- and rate-based checks will be skipped."
                ),
                details={"error": str(exc)[:200]},
            )
        ]
    rows = _first_int(response.results)
    if rows is None:
        return None, [
            contracts.ValidationFinding(
                severity=contracts.ValidationSeverity.INFO,
                code=f"{kind}_count_empty",
                message=f"Count query for {kind} returned no rows.",
            )
        ]
    return rows, []


def _count_recent_positives(
    *, team: Team, target_event: str, horizon_days: int
) -> tuple[int | None, list[contracts.ValidationFinding]]:
    """Count distinct persons who fired ``target_event`` in the trailing horizon.

    Used as a proxy for the positive base rate at training time. Conservative
    — anchor-date semantics make the real label set more complex, but a
    trailing-window count is enough to flag clearly label-poor pipelines.
    """
    if not _SAFE_EVENT_NAME.match(target_event):
        return None, [
            contracts.ValidationFinding(
                severity=contracts.ValidationSeverity.INFO,
                code="target_event_unsafe_for_count",
                message=(
                    f"Skipping positive-rate check: target_event {target_event!r} contains characters we don't safely embed in a HogQL literal."
                ),
            )
        ]
    quoted = target_event.replace("'", "''")
    query = (
        f"SELECT count(DISTINCT person_id) FROM events "
        f"WHERE event = '{quoted}' "
        f"AND timestamp >= now() - INTERVAL {horizon_days} DAY"
    )
    try:
        response = execute_hogql_query(query=query, team=team)
    except Exception as exc:
        return None, [
            contracts.ValidationFinding(
                severity=contracts.ValidationSeverity.INFO,
                code="positive_count_failed",
                message=(f"Could not size positive class: {type(exc).__name__}. Base-rate check skipped."),
                details={"error": str(exc)[:200]},
            )
        ]
    return _first_int(response.results), []


# ----- helpers ---------------------------------------------------------------


def _hogql_query_or_none(population: Any) -> str | None:
    """Extract the HogQL query string from a population spec, if present.

    Returns ``None`` for non-hogql kinds, missing/empty queries, or non-string
    values — keeps the caller from re-implementing the same guard everywhere.
    ``Any`` instead of ``dict[str, Any]`` because the input comes from raw JSON
    on the wire: trust no claim about its shape until we've checked it.
    """
    if not isinstance(population, dict):
        return None
    if population.get("kind") != "hogql":
        return None
    query = population.get("query")
    if isinstance(query, str) and query.strip():
        return query
    return None


def _population_kind(population: Any) -> str:
    """Return the population's declared ``kind``, or ``"missing"`` if absent."""
    if not isinstance(population, dict) or not population:
        return "missing"
    kind = population.get("kind")
    return kind if isinstance(kind, str) and kind else "unknown"


def _estimated_inference_events_per_day(*, params: contracts.CreatePipelineInput, inference_rows: int) -> int | None:
    """Project events-per-day from cadence and inference population size.

    Returns ``None`` for cadences we don't project (e.g. ``never``). Forecasting
    pipelines emit one event per horizon step per run — multiply by
    ``config.horizon_steps`` when present.
    """
    multiplier = _CADENCE_PER_DAY.get(params.inference_cadence.value)
    if multiplier is None:
        return None
    per_run = inference_rows
    if params.task_type is TaskType.FORECASTING:
        config = params.config if isinstance(params.config, dict) else {}
        horizon_steps = config.get("horizon_steps")
        if isinstance(horizon_steps, int) and horizon_steps > 0:
            per_run = per_run * horizon_steps
    return int(per_run * multiplier)


def _first_int(results: Any) -> int | None:
    """Pull the first scalar value out of a HogQL response's ``.results`` list."""
    if not results:
        return None
    first_row = results[0]
    if not first_row:
        return None
    value = first_row[0]
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None
