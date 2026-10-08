"""
Online validation: join autoresearch_prediction events to realized target outcomes
after the prediction horizon has elapsed.

Computes per model: realized AUC with a 95% interval, Brier score, expected calibration
error (ECE), quantile calibration bins, mean predicted probability, and lift@k, for every
model that emitted predictions on a date.

Architecture:
- Pure activity functions called by AutoresearchValidationWorkflow (Temporal)
  and the autoresearch_validate_online management command.
- All heavy work (HogQL queries + sklearn metrics) happens inside a single activity;
  nothing large passes through Temporal payloads.
- Candidate dates come from the completed inference runs in Postgres, never from a
  scan of the events table, and every ClickHouse query is bounded by what those runs
  say was emitted.
"""

import math
from datetime import UTC, date, datetime, timedelta
from typing import Any

from django.db import transaction
from django.db.models import Q
from django.utils import timezone as django_timezone

import numpy as np
import structlog

from posthog.schema import HogQLQuery

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.team.team import Team
from posthog.models.user import User

from products.autoresearch.backend.dataset.labeling import (
    LABELER_QUERY_MODIFIERS,
    PREDICTION_EVENT_NAME,
    _own_events_excluded_clause,
    build_target_condition,
)
from products.autoresearch.backend.inference.sandbox import SandboxInferenceError, _resolve_acting_user
from products.autoresearch.backend.models import AutoresearchModel, AutoresearchPipeline, AutoresearchRun
from products.autoresearch.backend.query import INTERACTIVE_QUERY, HogQLResult, QueryContext, run_hogql

logger = structlog.get_logger(__name__)

# A validation run does one bounded query per model plus the labels query, and a scoring run
# is bounded by its sandbox timeouts, so a RUNNING row older than this belongs to a worker that
# died mid-run and the exception handler never ran. Neither kind may hold a date forever.
STALE_RUN_AFTER = timedelta(hours=6)

# An outcome event timestamped just before the window closes can still be in the ingestion
# queue when the window closes. Maturity waits this long past the window end so it lands
# first; a completed date is never revisited, so a positive that arrives later than this
# reads as a negative.
OUTCOME_INGESTION_GRACE = timedelta(hours=1)

# A live run stamps its events at emission time, which can cross midnight UTC before the
# batch goes out; a backfill stamps noon UTC of the date. Both fall within this many days
# of the start of the prediction date, so the fetch can bound `timestamp` for pruning.
_EMISSION_WINDOW_DAYS = 2


class OnlineValidationError(Exception):
    """The date must fail, and be retried on a later pass, instead of completing with metrics from bad data."""


@frozen
class PendingValidationDate:
    """A matured prediction date with no completed validation, and what its inference runs emitted."""

    prediction_date: date
    horizon_days: int
    # rows_scored of the latest completed inference run per model id. The prediction
    # events for the date must match these counts exactly before metrics are trusted.
    expected_rows_by_model: dict[str, int]

    @property
    def window_start(self) -> datetime:
        # Scoring binds every run to the start of its prediction date in UTC, so the
        # outcome window opens at the same instant whatever the project's timezone.
        return datetime(self.prediction_date.year, self.prediction_date.month, self.prediction_date.day, tzinfo=UTC)

    @property
    def window_end(self) -> datetime:
        return self.window_start + timedelta(days=self.horizon_days)

    @property
    def emitted_before(self) -> datetime:
        return self.window_start + timedelta(days=_EMISSION_WINDOW_DAYS)

    @property
    def expected_rows(self) -> int:
        return sum(self.expected_rows_by_model.values())

    @property
    def key(self) -> tuple[date, int]:
        return (self.prediction_date, self.horizon_days)


@frozen
class _ModelPredictions:
    emitted_role: str
    p_y_by_person: dict[str, float]


@frozen
class _AucInterval:
    low: float
    high: float


@frozen
class _ModelValidation:
    emitted_role: str
    metrics: dict[str, Any]


def run_online_validation_for_pipeline(
    pipeline: AutoresearchPipeline,
    *,
    user: User | None = None,
    query_context: QueryContext = INTERACTIVE_QUERY,
    claim_deadline: datetime | None = None,
) -> list[AutoresearchRun]:
    """
    Validate every matured prediction date that has no completed validation yet.

    A date is matured when its outcome window, ``[prediction_date, prediction_date +
    horizon_days)`` in UTC, has closed. Each date is claimed with an ``AutoresearchRun``
    before any query runs, so two validators cannot score the same date. Returns one run
    per date processed, COMPLETED or FAILED, and updates ``realized_score`` and
    ``calibration_error`` on each model that emitted predictions.

    ``user`` is who HogQL applies access control for; it defaults to the pipeline's creator.
    ``query_context`` is the ClickHouse budget of every query. The Temporal activity passes
    ``BATCH_QUERY``, and the API request path keeps the interactive limit.

    After ``claim_deadline`` the pass claims no more dates, but it always claims at least one,
    so a pass makes progress whatever the deadline. The dates it does not reach stay pending
    for the next pass. The Temporal activity sets the deadline so that the last date it claims
    still finishes inside the attempt timeout.
    """
    team = pipeline.team
    acting_user = _acting_user(team=team, pipeline=pipeline, user=user)
    pending = find_pending_validation_dates(pipeline)
    if not pending:
        logger.info("autoresearch_validation_no_mature_dates", pipeline_id=str(pipeline.pk))
        return []

    results: list[AutoresearchRun] = []
    for index, item in enumerate(pending):
        if results and claim_deadline is not None and django_timezone.now() >= claim_deadline:
            logger.info(
                "autoresearch_validation_dates_deferred",
                pipeline_id=str(pipeline.pk),
                dates_deferred=len(pending) - index,
            )
            break
        run = _claim_date(pipeline, item)
        if run is None:
            continue
        results.append(
            _validate_claimed_date(
                team=team, pipeline=pipeline, run=run, pending=item, user=acting_user, query_context=query_context
            )
        )
    return results


def _acting_user(*, team: Team, pipeline: AutoresearchPipeline, user: User | None) -> User:
    try:
        return _resolve_acting_user(team=team, pipeline=pipeline, user=user)
    except SandboxInferenceError as exc:
        raise OnlineValidationError(str(exc)) from exc


# ── Date selection and claiming ───────────────────────────────────────────────────


def find_pending_validation_dates(pipeline: AutoresearchPipeline) -> list[PendingValidationDate]:
    """
    Matured (date, horizon) groups whose validation does not match their inference runs, oldest first.

    Candidates come from the completed inference runs, which record the prediction date and
    the horizon they scored against; models scored on one date under different horizons form
    separate groups with their own outcome windows. A group waits while an inference run for
    it is still scoring, and for ``OUTCOME_INGESTION_GRACE`` after its window closes. It is
    done once a COMPLETED validation run holds the same per-model counts as its inference
    runs, so a later rescore or a new model on the date makes it pending again. A FAILED
    validation run does not count; a RUNNING one, like a RUNNING inference run, counts only
    while it is younger than ``STALE_RUN_AFTER``.
    """
    now = django_timezone.now()
    scoring = _groups_still_scoring(pipeline, now=now)
    state = _validation_state(pipeline, now=now)
    return [
        item
        for item in _scored_groups(pipeline)
        if item.key not in scoring and not _is_blocked(item, state) and item.window_end + OUTCOME_INGESTION_GRACE <= now
    ]


def _scored_groups(pipeline: AutoresearchPipeline) -> list[PendingValidationDate]:
    """Every (date, horizon) with a completed inference run, oldest first, with the rows each model's latest run emitted."""
    runs = (
        AutoresearchRun.objects.filter(
            pipeline=pipeline,
            run_type=AutoresearchRun.RunType.INFERENCE,
            status=AutoresearchRun.Status.COMPLETED,
            model__isnull=False,
            rows_scored__gt=0,
        )
        # Ascending, so the latest run for a (group, model) is the one whose counts survive.
        .order_by("completed_at", "created_at")
        .values_list("model_id", "rows_scored", "metrics")
    )
    expected_by_group: dict[tuple[date, int], dict[str, int]] = {}
    for model_id, rows_scored, metrics in runs:
        key = _group_key(metrics)
        if key is None or rows_scored is None:
            continue
        expected_by_group.setdefault(key, {})[str(model_id)] = int(rows_scored)
    return [
        PendingValidationDate(
            prediction_date=prediction_date, horizon_days=horizon_days, expected_rows_by_model=expected
        )
        for (prediction_date, horizon_days), expected in sorted(expected_by_group.items())
    ]


def _group_key(metrics: dict[str, Any]) -> tuple[date, int] | None:
    stamp = metrics.get("prediction_date")
    horizon_days = metrics.get("horizon_days")
    if not isinstance(stamp, str) or not isinstance(horizon_days, int):
        return None
    return (date.fromisoformat(stamp), horizon_days)


def _groups_still_scoring(pipeline: AutoresearchPipeline, *, now: datetime) -> set[tuple[date, int]]:
    in_flight = AutoresearchRun.objects.filter(
        pipeline=pipeline,
        run_type=AutoresearchRun.RunType.INFERENCE,
        status__in=(AutoresearchRun.Status.PENDING, AutoresearchRun.Status.RUNNING),
        created_at__gte=now - STALE_RUN_AFTER,
    ).values_list("metrics", flat=True)
    return {key for key in (_group_key(m) for m in in_flight) if key is not None}


def _validation_state(
    pipeline: AutoresearchPipeline, *, now: datetime
) -> dict[tuple[date, int], list[dict[str, int] | None]]:
    """Per group: the per-model counts each COMPLETED validation run scored, and None for each live claim."""
    runs = (
        AutoresearchRun.objects.filter(pipeline=pipeline, run_type=AutoresearchRun.RunType.VALIDATION)
        .filter(
            Q(status=AutoresearchRun.Status.COMPLETED)
            | Q(status=AutoresearchRun.Status.RUNNING, started_at__gte=now - STALE_RUN_AFTER)
        )
        .values_list("status", "metrics")
    )
    state: dict[tuple[date, int], list[dict[str, int] | None]] = {}
    for status, metrics in runs:
        key = _group_key(metrics)
        if key is None:
            continue
        if status == AutoresearchRun.Status.RUNNING:
            state.setdefault(key, []).append(None)
            continue
        per_model = metrics.get("per_model") or {}
        state.setdefault(key, []).append(
            {
                model_id: int(m["n_scored"])
                for model_id, m in per_model.items()
                if isinstance(m, dict) and "n_scored" in m
            }
        )
    return state


def _is_blocked(item: PendingValidationDate, state: dict[tuple[date, int], list[dict[str, int] | None]]) -> bool:
    # A completed validation may hold counts for a model deleted since; a deleted model never
    # returns, so only a model the validation has not seen at these counts reopens the group.
    return any(
        counts is None or all(counts.get(model_id) == n for model_id, n in item.expected_rows_by_model.items())
        for counts in state.get(item.key, [])
    )


def _claim_date(pipeline: AutoresearchPipeline, pending: PendingValidationDate) -> AutoresearchRun | None:
    """
    Record a RUNNING validation run for the group, or return None when another validator
    already holds it or has validated these exact runs. The check and the insert happen
    under the pipeline row's lock, so the scheduled activity and a manual command cannot
    both score the same group. FOR NO KEY UPDATE leaves the KEY SHARE locks an inference
    run's insert takes on the same row unblocked.
    """
    now = django_timezone.now()
    with transaction.atomic():
        AutoresearchPipeline.objects.select_for_update(no_key=True).get(pk=pipeline.pk, team_id=pipeline.team_id)
        if _is_blocked(pending, _validation_state(pipeline, now=now)):
            return None
        return AutoresearchRun.objects.create(
            pipeline=pipeline,
            run_type=AutoresearchRun.RunType.VALIDATION,
            status=AutoresearchRun.Status.RUNNING,
            started_at=now,
            metrics={"prediction_date": pending.prediction_date.isoformat(), "horizon_days": pending.horizon_days},
        )


# ── Validating one date ───────────────────────────────────────────────────────────


def _validate_claimed_date(
    *,
    team: Team,
    pipeline: AutoresearchPipeline,
    run: AutoresearchRun,
    pending: PendingValidationDate,
    user: User,
    query_context: QueryContext = INTERACTIVE_QUERY,
) -> AutoresearchRun:
    """
    Compute realized metrics for every model that emitted predictions on the date, then
    persist the model updates and the run in one transaction.

    Any failure marks the run FAILED with nothing written to the models, so the date stays
    eligible for the next pass and the other dates in this pass are unaffected.
    """
    try:
        predictions = _fetch_predictions(
            team=team, pipeline=pipeline, pending=pending, user=user, query_context=query_context
        )
        n_predicted = sum(len(model.p_y_by_person) for model in predictions.values())
        realized = _fetch_realized_labels(
            team=team,
            pipeline=pipeline,
            pending=pending,
            n_predicted=n_predicted,
            user=user,
            query_context=query_context,
        )
        per_model = {
            model_id: _ModelValidation(
                emitted_role=model.emitted_role,
                metrics=_compute_validation_metrics(
                    model.p_y_by_person, realized, prediction_date=pending.prediction_date
                ),
            )
            for model_id, model in predictions.items()
        }
        _persist_completed(
            pipeline=pipeline, run=run, pending=pending, per_model=per_model, realized_count=len(realized)
        )
        logger.info(
            "autoresearch_validation_complete",
            pipeline_id=str(pipeline.pk),
            prediction_date=pending.prediction_date.isoformat(),
            models_validated=len(per_model),
            total_rows=n_predicted,
        )
    except Exception as exc:
        run.status = AutoresearchRun.Status.FAILED
        run.error = str(exc)[:2000]
        run.completed_at = django_timezone.now()
        run.save(update_fields=["status", "error", "completed_at"])
        logger.exception(
            "autoresearch_validation_failed",
            pipeline_id=str(pipeline.pk),
            prediction_date=pending.prediction_date.isoformat(),
        )
    return run


def _persist_completed(
    *,
    pipeline: AutoresearchPipeline,
    run: AutoresearchRun,
    pending: PendingValidationDate,
    per_model: dict[str, _ModelValidation],
    realized_count: int,
) -> None:
    run_metrics: dict[str, Any] = {}
    total_rows = 0
    with transaction.atomic():
        # A run that completed or started for this group while the queries ran is missing from
        # the counts the fetch was checked against. A model deleted meanwhile takes its run out
        # of the group; its evidence is still written below, so that alone does not fail it.
        now = django_timezone.now()
        current = {item.key: item.expected_rows_by_model for item in _scored_groups(pipeline)}.get(pending.key, {})
        changed = any(pending.expected_rows_by_model.get(model_id) != n for model_id, n in current.items())
        vanished = set(pending.expected_rows_by_model) - set(current)
        vanished_but_present = (
            AutoresearchModel.objects.filter(pk__in=vanished, pipeline=pipeline, team_id=pipeline.team_id).exists()
            if vanished
            else False
        )
        if changed or vanished_but_present or pending.key in _groups_still_scoring(pipeline, now=now):
            raise OnlineValidationError(
                f"The inference runs for {pending.prediction_date.isoformat()} changed while it was being validated; "
                "retrying on the next pass"
            )
        for model_id, validation in per_model.items():
            # Locked so two validators on different dates cannot race the newest-date guard.
            model = (
                AutoresearchModel.objects.select_for_update()
                .filter(pk=model_id, pipeline=pipeline, team_id=pipeline.team_id)
                .first()
            )
            if model is not None:
                _update_model_realized_metrics(model, validation.metrics, prediction_date=pending.prediction_date)
            run_metrics[model_id] = {
                # Promotion can change the role before the horizon closes, so both are kept.
                "emitted_role": validation.emitted_role,
                "model_role": model.role if model is not None else "deleted",
                **validation.metrics,
            }
            total_rows += int(validation.metrics["n_scored"])
        run.status = AutoresearchRun.Status.COMPLETED
        run.rows_scored = total_rows
        run.completed_at = django_timezone.now()
        run.metrics.update({"realized_labels_count": realized_count, "per_model": run_metrics})
        run.save(update_fields=["status", "rows_scored", "completed_at", "metrics"])


# ── Queries ────────────────────────────────────────────────────────────────────────


def _prediction_filter() -> str:
    return (
        " event = {event_name}"
        " AND properties['$autoresearch_pipeline_id'] = {pipeline_id}"
        " AND properties['$autoresearch_prediction_date'] = {prediction_date}"
        " AND properties['$autoresearch_model_id'] IN {model_ids}"
        " AND properties['$autoresearch_horizon_days'] = {horizon_days}"
        " AND properties['$autoresearch_person_id'] != ''"
        " AND timestamp >= {emitted_from} AND timestamp < {emitted_before}"
    )


def _prediction_values(pipeline: AutoresearchPipeline, pending: PendingValidationDate) -> dict[str, Any]:
    return {
        "event_name": PREDICTION_EVENT_NAME,
        "pipeline_id": str(pipeline.pk),
        "prediction_date": pending.prediction_date.isoformat(),
        "model_ids": tuple(pending.expected_rows_by_model),
        # Property values read back as strings, whatever type scoring emitted.
        "horizon_days": str(pending.horizon_days),
        "emitted_from": pending.window_start,
        "emitted_before": pending.emitted_before,
    }


def _fetch_predictions(
    *,
    team: Team,
    pipeline: AutoresearchPipeline,
    pending: PendingValidationDate,
    user: User,
    query_context: QueryContext = INTERACTIVE_QUERY,
) -> dict[str, _ModelPredictions]:
    """
    ``{model_id: predictions}`` for every model the inference runs say scored the date.

    Keyed on ``$autoresearch_person_id``, the person key every scored row carries, so the
    join to realized labels compares the same key space. Only models with a completed
    inference run are fetched, and each model's row count must equal that run's
    ``rows_scored``: fewer means ingestion has not caught up with a backfill yet, more
    means events the run did not emit. Either way the metrics would be wrong, so the date
    fails and is retried.

    Each model is fetched in its own query. HogQL returns at most 50,000 rows whatever
    LIMIT the query asks for. One run scores fewer people than that, but the champion and
    its shadow models together can score more.
    """
    # argMax picks the latest emission per (model, person). Backfills stamp every event of
    # a date at the same instant, so the event UUID breaks those ties rather than leaving
    # them to merge order.
    sql = (
        "SELECT"
        " properties['$autoresearch_model_id'] AS model_id,"
        " properties['$autoresearch_person_id'] AS person_id,"
        " argMax(toFloatOrNull(properties['$autoresearch_p_y']), (timestamp, uuid)) AS p_y,"
        " any(properties['$autoresearch_model_role']) AS emitted_role"
        " FROM events"
        f" WHERE{_prediction_filter()}"
        " GROUP BY model_id, person_id"
    )
    roles: dict[str, str] = {}
    scores: dict[str, dict[str, float]] = {}
    for model_id, expected in pending.expected_rows_by_model.items():
        result = _query(
            team=team,
            sql=sql,
            values={**_prediction_values(pipeline, pending), "model_ids": (model_id,)},
            user=user,
            limit=expected + 1,
            what="Predictions",
            query_context=query_context,
        )
        for row_model_id, person_id, p_y, emitted_role in result.rows:
            if p_y is None:
                raise OnlineValidationError(
                    f"Prediction for person {person_id} of model {row_model_id} carries a non-numeric "
                    "$autoresearch_p_y; refusing to compute metrics from it"
                )
            scores.setdefault(str(row_model_id), {})[str(person_id)] = float(p_y)
            roles.setdefault(str(row_model_id), str(emitted_role or ""))

        found = len(scores.get(model_id, {}))
        if found < expected:
            raise OnlineValidationError(
                f"Found {found} of the {expected} predictions model {model_id} emitted for "
                f"{pending.prediction_date.isoformat()}; ingestion may not have caught up, retrying on the next pass"
            )
        if found > expected:
            raise OnlineValidationError(
                f"Found {found} predictions for model {model_id} on {pending.prediction_date.isoformat()} but its "
                f"inference run emitted {expected}; refusing to compute metrics from events the run did not emit"
            )
    return {
        model_id: _ModelPredictions(emitted_role=roles[model_id], p_y_by_person=p_y_by_person)
        for model_id, p_y_by_person in scores.items()
    }


def _fetch_realized_labels(
    *,
    team: Team,
    pipeline: AutoresearchPipeline,
    pending: PendingValidationDate,
    n_predicted: int,
    user: User,
    query_context: QueryContext = INTERACTIVE_QUERY,
) -> frozenset[str]:
    """
    The predicted persons who performed the pipeline's target inside the outcome window.

    The target predicate is ``build_target_condition``, the same one that labeled the
    training data, and the window is the UTC one scoring bound the run to. The scan is
    restricted to the persons the prediction events name, so its size is bounded by the
    predictions and not by how many people on the team performed the target. The
    product's own prediction event is excluded, so a target that matches it does not turn
    every scored person into a positive.
    """
    target_cond, target_values = build_target_condition(
        target_event=pipeline.target_event, target_definition=pipeline.target_definition, team=team
    )
    sql = (
        "SELECT DISTINCT toString(person_id) AS person_id"
        " FROM events"
        f" WHERE {target_cond}{_own_events_excluded_clause()}"
        " AND timestamp >= {window_start} AND timestamp < {window_end}"
        " AND toString(person_id) IN ("
        "SELECT DISTINCT properties['$autoresearch_person_id'] FROM events"
        f" WHERE{_prediction_filter()}"
        ")"
    )
    values: dict[str, Any] = {
        **_prediction_values(pipeline, pending),
        **target_values,
        "window_start": pending.window_start,
        "window_end": pending.window_end,
    }
    result = _query(
        team=team,
        sql=sql,
        values=values,
        user=user,
        limit=n_predicted + 1,
        what="Realized labels",
        query_context=query_context,
    )
    return frozenset(str(row[0]) for row in result.rows if row[0])


def _query(
    *,
    team: Team,
    sql: str,
    values: dict[str, Any],
    user: User,
    limit: int,
    what: str,
    query_context: QueryContext = INTERACTIVE_QUERY,
) -> HogQLResult:
    """
    Run a query as the acting user, fresh, with an explicit bound.

    HogQL caps a bare SELECT at 100 rows without an error, so every query here carries a
    LIMIT one above the rows the caller can account for, and a result that reaches it is
    refused. The persons-on-events modifiers keep ``person_id`` resolving the way the
    labeler's queries do, and the always-calculate mode stops a retry reading a cached
    result from before ingestion caught up.
    """
    bounded_sql = sql.rstrip().rstrip(";") + "\nLIMIT {limit}"
    try:
        tag_queries(product=Product.AUTORESEARCH, feature=Feature.QUERY)
        result = run_hogql(
            team=team,
            query=HogQLQuery(query=bounded_sql, values={**values, "limit": limit}, modifiers=LABELER_QUERY_MODIFIERS),
            user=user,
            execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
            query_context=query_context,
        )
    except Exception as exc:
        logger.exception("autoresearch_validation_query_failed", team_id=team.pk, what=what)
        raise OnlineValidationError(f"{what} query failed; failing the date so it is retried") from exc
    if result.has_more or len(result.rows) >= limit:
        raise OnlineValidationError(
            f"{what} query returned more rows than the inference runs account for ({limit - 1}); "
            "refusing to compute metrics from them"
        )
    return result


# ── Metrics ────────────────────────────────────────────────────────────────────────


def _compute_validation_metrics(
    predictions: dict[str, float],
    realized_labels: frozenset[str],
    *,
    prediction_date: date,
) -> dict[str, Any]:
    """
    AUC with its 95% interval, Brier score, ECE, quantile calibration bins, and lift@k
    from scored predictions against realized labels.

    Only the AUC and its interval need both classes. The other metrics are computed for a
    single-class date too, because an all-negative day is exactly where calibration
    matters for a rare target.
    """
    person_ids = list(predictions.keys())
    y_score = np.array([predictions[pid] for pid in person_ids], dtype=np.float64)
    y_true = np.array([1 if pid in realized_labels else 0 for pid in person_ids], dtype=np.int32)

    n = len(y_true)
    n_pos = int(y_true.sum())
    n_neg = n - n_pos

    metrics: dict[str, Any] = {
        "n_scored": n,
        "n_positive": n_pos,
        "n_negative": n_neg,
        "base_rate": round(n_pos / n, 4) if n > 0 else 0.0,
        "weekday": prediction_date.isoweekday(),
    }
    if n == 0:
        return metrics
    metrics["mean_p_y"] = round(float(y_score.mean()), 4)

    # Deferred to keep the heavy dependency off the import path.
    from sklearn.metrics import brier_score_loss, roc_auc_score  # noqa: PLC0415

    if n_pos == 0 or n_neg == 0:
        metrics["warning"] = "single_class_no_auc"
    else:
        auc = float(roc_auc_score(y_true, y_score))
        interval = _auc_confidence_interval(auc, n_pos=n_pos, n_neg=n_neg)
        metrics["realized_auc"] = round(auc, 4)
        metrics["realized_auc_ci_low"] = round(interval.low, 4)
        metrics["realized_auc_ci_high"] = round(interval.high, 4)
    metrics["brier_score"] = round(float(brier_score_loss(y_true, y_score)), 4)
    metrics["calibration_error"] = round(_expected_calibration_error(y_true, y_score), 4)
    metrics["calibration_bins"] = _quantile_calibration_bins(y_true, y_score)
    metrics["lift_at_10"] = round(_lift_at_k(y_true, y_score, k=0.10), 4)
    metrics["lift_at_20"] = round(_lift_at_k(y_true, y_score, k=0.20), 4)
    return metrics


def _expected_calibration_error(y_true: np.ndarray, y_score: np.ndarray, n_bins: int = 10) -> float:
    """
    Expected Calibration Error (ECE): fraction-weighted mean absolute difference
    between mean predicted probability and actual positive rate within each decile bin.
    """
    n = len(y_true)
    bin_boundaries = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    for i in range(n_bins):
        lo, hi = bin_boundaries[i], bin_boundaries[i + 1]
        mask = (y_score >= lo) & (y_score <= hi) if i == n_bins - 1 else (y_score >= lo) & (y_score < hi)
        if not mask.any():
            continue
        bin_n = int(mask.sum())
        avg_pred = float(y_score[mask].mean())
        actual_rate = float(y_true[mask].mean())
        ece += (bin_n / n) * abs(avg_pred - actual_rate)
    return ece


def _auc_confidence_interval(auc: float, *, n_pos: int, n_neg: int, z: float = 1.96) -> _AucInterval:
    """
    95% interval for an AUC from the Hanley-McNeil (1982) standard error.

    The width depends on the class counts, so a date with a few dozen positives gets a
    wide interval and a date with thousands gets a narrow one.
    """
    q1 = auc / (2 - auc)
    q2 = 2 * auc**2 / (1 + auc)
    variance = (auc * (1 - auc) + (n_pos - 1) * (q1 - auc**2) + (n_neg - 1) * (q2 - auc**2)) / (n_pos * n_neg)
    se = math.sqrt(max(variance, 0.0))
    return _AucInterval(low=max(0.0, auc - z * se), high=min(1.0, auc + z * se))


def _quantile_calibration_bins(y_true: np.ndarray, y_score: np.ndarray, n_bins: int = 10) -> list[dict[str, Any]]:
    """
    Calibration table with up to ``n_bins`` bins cut at score quantiles, lowest scores first.

    Equal-width bins put almost every person in the first bin for a rare target; quantile
    bins hold roughly equal counts. Equal scores always share a bin, so heavy ties give
    fewer bins rather than a split that depends on row order.
    """
    # A score's bin comes from how many scores sit below it, so every user with that score shares it.
    rank = np.searchsorted(np.sort(y_score), y_score, side="left")
    bin_index = rank * n_bins // len(y_score)
    bins: list[dict[str, Any]] = []
    for i in np.unique(bin_index):
        mask = bin_index == i
        bins.append(
            {
                "n": int(mask.sum()),
                "mean_p_y": round(float(y_score[mask].mean()), 4),
                "positive_rate": round(float(y_true[mask].mean()), 4),
            }
        )
    return bins


def _lift_at_k(y_true: np.ndarray, y_score: np.ndarray, k: float) -> float:
    """
    Lift@k: positives captured in the top-k fraction of scored users, relative to random.

    A lift of 2.0 at k=10% means the top 10% by score contains twice the positives a
    random 10% sample would. Rows tied at the boundary score are counted fractionally,
    so the number does not depend on the order ClickHouse returned the tied persons in.
    """
    n_pos_total = int(y_true.sum())
    n = len(y_true)
    if n == 0 or n_pos_total == 0 or k <= 0:
        return 0.0
    cutoff = max(1, math.ceil(n * k))
    boundary = float(np.sort(y_score)[::-1][cutoff - 1])
    above = y_score > boundary
    tied = y_score == boundary
    tie_share = (cutoff - int(above.sum())) / int(tied.sum())
    positives_captured = float(y_true[above].sum()) + tie_share * float(y_true[tied].sum())
    # Normalize by the fraction actually selected, not the requested k: rounding up to a
    # whole user would otherwise overstate lift on small validation sets.
    random_expected = (cutoff / n) * n_pos_total
    return positives_captured / random_expected


def _update_model_realized_metrics(model: AutoresearchModel, metrics: dict[str, Any], *, prediction_date: date) -> None:
    """
    Persist a date's realized metrics onto the model row.

    The first realized AUC clears ``is_preliminary``. Later dates replace the model-level
    numbers only when they are newer than what is stored: a retry of an older date that
    failed earlier must not overwrite the evidence a newer date already left.
    """
    existing = dict(model.metrics or {})
    stored_date = (existing.get("realized") or {}).get("prediction_date")
    if isinstance(stored_date, str) and stored_date > prediction_date.isoformat():
        logger.info(
            "autoresearch_model_realized_metrics_kept_newer",
            model_id=str(model.pk),
            stored_prediction_date=stored_date,
            prediction_date=prediction_date.isoformat(),
        )
        return

    auc = metrics.get("realized_auc")
    cal_error = metrics.get("calibration_error")
    existing["realized"] = {**metrics, "prediction_date": prediction_date.isoformat()}
    model.metrics = existing
    update_fields = ["metrics", "updated_at"]

    if auc is not None:
        model.realized_score = auc
        update_fields.append("realized_score")
        if model.is_preliminary:
            model.is_preliminary = False
            update_fields.append("is_preliminary")

    if cal_error is not None:
        model.calibration_error = cal_error
        update_fields.append("calibration_error")

    model.save(update_fields=update_fields)

    logger.info(
        "autoresearch_model_realized_metrics_updated",
        model_id=str(model.pk),
        role=model.role,
        realized_auc=auc,
        calibration_error=cal_error,
        is_preliminary=model.is_preliminary,
    )
