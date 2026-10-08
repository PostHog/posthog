"""
Inference: load the champion, score the inference population, and emit one
autoresearch_prediction event per person.

- ``run_inference_for_pipeline()`` is the entry point for the Temporal activity
  (temporal/workflows.py) and for ``autoresearch_score``: it records an
  AutoresearchRun, scores, and emits.
- ``score_population()`` is the scoring half on its own, for a dry run that wants
  the scores without the events.
- After a live champion run completes, every other model in the shadow set scores the
  same people (``_score_shadow_set()``). A shadow model emits person-less events with the
  ``shadow`` role and no ``$set``, and records its own inference run.

Event shape:
    event: autoresearch_prediction
    distinct_id: <person distinct_id>
    properties:
        $autoresearch_pipeline_id:     str (UUID)
        $autoresearch_model_id:        str (UUID)
        $autoresearch_model_role:      "champion" | "shadow"
        $autoresearch_target_event:    str
        $autoresearch_horizon_days:    int
        $autoresearch_p_y:             float  (the score, prior-corrected for negative sampling)
        $autoresearch_p_y_raw:         float  (the model's score before the correction)
        $autoresearch_negative_sample_rate: float (the rate the correction used; 1.0 means none)
        $autoresearch_prediction_date: str (YYYY-MM-DD)
        $autoresearch_features_hash:   str (SHA-256 prefix of the feature row)
        $autoresearch_person_id:       str (the person_id every row is keyed on)
        $autoresearch_run_id:          str (UUID of the AutoresearchRun that emitted the batch)
"""

import json
import math
import time
import uuid
import hashlib
import inspect
import importlib
import dataclasses
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

from django.utils import timezone as django_timezone

import numpy as np
import structlog

from posthog.schema import HogQLQuery

from posthog.api.capture import capture_batch_internal
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.person.util import get_persons_by_uuids
from posthog.models.team.team import Team
from posthog.models.user import User

from products.autoresearch.backend.dataset.labeling import (
    IDENTIFIED_USERS_ONLY,
    LABELER_QUERY_MODIFIERS,
    PREDICTION_EVENT_NAME,
    SHADOW_MODEL_ROLE,
    RollingSelection,
    build_inference_anchors_sql,
    build_inference_features_sql,
    build_training_features_sql,
    rolling_selection,
)
from products.autoresearch.backend.inference.failures import classify_failure
from products.autoresearch.backend.inference.sandbox import (
    _FOLD_COL,
    _HOLDOUT_FOLD,
    _LABEL_COL,
    _MATERIALIZE_ROW_LIMIT,
    _MAX_FEATURE_COLS,
    InferenceRows,
    MaterializedFeatures,
    SandboxInferenceError,
    _materialize_score_data,
    _num,
    _numeric_feature_cols,
    _resolve_acting_user,
    _validate_bundle_feature_sql,
    count_inference_anchors,
    count_training_anchors,
    features_sql_digest,
    measure_training_sample,
    score_via_sandbox,
    validate_runnable_feature_sql,
)
from products.autoresearch.backend.models import AutoresearchModel, AutoresearchPipeline, AutoresearchRun
from products.autoresearch.backend.query import INTERACTIVE_QUERY, HogQLResult, QueryContext, run_hogql
from products.autoresearch.backend.training.artifacts import ArtifactBundle, read_bundle
from products.autoresearch.backend.training.recipe_validation import (
    RecipeValidationError,
    validate_model_class,
    validate_unique_distinct_ids,
)
from products.autoresearch.backend.training.shadow_set import shadow_set

logger = structlog.get_logger(__name__)

EVENT_SOURCE = "autoresearch_inference"


class InferenceRunError(Exception):
    """Raised when an inference run must fail (and be retried) rather than complete with wrong output."""


_RESERVED_COLS = frozenset({"distinct_id", _LABEL_COL, _FOLD_COL})
# The score columns scoring adds to a feature row, kept out of the features hash.
_SCORE_KEYS = frozenset({"p_y", "p_y_raw"})
# A capture error description can hold a URL and an exception repr, so the run error clips it.
_MAX_EMIT_ERROR_DESCRIPTION_CHARS = 200
# Shadow scoring starts no new model after this many seconds. The model in progress at the limit
# still finishes, so the inference activity timeout covers the budget plus one more model.
SHADOW_TIME_BUDGET_S = 20 * 60


# Namespace for deterministic prediction event UUIDs, so a retried scoring activity
# re-emits the same UUID per (pipeline, model, date, person) instead of a duplicate.
_PREDICTION_UUID_NAMESPACE = uuid.UUID("6f9a4a24-0e5c-4a5a-9d0e-2f6a0f0b1c3d")


def _clip_middle(text: str, limit: int) -> str:
    """
    Keep both ends of ``text``. A requests transport error starts with the target host and
    ends with the cause, such as ``[Errno 111] Connection refused``, so a head-only clip
    makes a refused connection and a failed DNS lookup look the same.
    """
    if len(text) <= limit:
        return text
    marker = "..."
    head = (limit - len(marker)) // 2
    tail = limit - len(marker) - head
    return f"{text[:head]}{marker}{text[-tail:]}"


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def _prediction_event_uuid(*, pipeline_id: str, model_id: str, prediction_date: str, person_id: str) -> str:
    return str(uuid.uuid5(_PREDICTION_UUID_NAMESPACE, f"{pipeline_id}:{model_id}:{prediction_date}:{person_id}"))


@frozen
class ScoredPopulation:
    """One scored row per person; each row keeps its feature columns plus ``p_y``."""

    rows: list[dict[str, Any]]
    # The holdout AUC the serving model advertises: computed on the fly for a recipe-only
    # champion, read from the model row for a bundle.
    holdout_auc: float | None
    # The fraction of negatives the scoring model was fitted on. 1.0 means no sampling.
    negative_sample_rate: float = 1.0
    # Persons in the inference population at the cutoff. Above len(rows) when the population
    # reached the cap and the run scored a rolling subset. None when the run did not count it.
    rows_eligible: int | None = None
    # The bundle's feature rows, so a shadow model with the same features.sql reuses them.
    features: MaterializedFeatures | None = None


def corrected_probability(p: float, negative_sample_rate: float) -> float:
    """
    The prior correction for case-control sampling, ``sigmoid(logit(p) + log(r))``.

    Kept negatives at rate ``r`` inflate the training odds by ``1 / r``, so the model's raw
    score overstates the probability. This closed form needs no logit, so 0 and 1 stay exact.
    """
    if negative_sample_rate == 1.0:
        return p
    return p * negative_sample_rate / (p * negative_sample_rate + (1.0 - p))


def _apply_prior_correction(scored: ScoredPopulation) -> ScoredPopulation:
    """Keep each row's raw score as ``p_y_raw`` and replace ``p_y`` with the corrected probability."""
    rate = scored.negative_sample_rate
    rows = [{**row, "p_y_raw": row["p_y"], "p_y": corrected_probability(row["p_y"], rate)} for row in scored.rows]
    return ScoredPopulation(
        rows=rows,
        holdout_auc=scored.holdout_auc,
        negative_sample_rate=rate,
        rows_eligible=scored.rows_eligible,
        features=scored.features,
    )


@frozen
class ScoringWindow:
    """
    The dates one run scores against, decided once at the entry point. A live run that
    started before midnight and finished after it would otherwise flip to a backfill halfway:
    person-less events at noon, no output property, and no cadence watermark.
    """

    prediction_date: date
    today: date
    now: datetime
    # The instant every query in the run binds to: the start of the prediction date in UTC,
    # for a live run as much as a backfill. A cutoff of now() would give a retry a different
    # population than the attempt it repeats, under the same event UUIDs, so one cadence would
    # hold scores from two populations; anchoring at midnight makes the run reproducible and
    # gives a backfill of the same date the same anchors.
    cutoff_ts: int

    @classmethod
    def for_date(cls, prediction_date: date | None = None) -> "ScoringWindow":
        now = django_timezone.now()
        today = date.today()
        prediction_date = prediction_date or today
        cutoff = datetime(prediction_date.year, prediction_date.month, prediction_date.day, tzinfo=UTC)
        return cls(prediction_date=prediction_date, today=today, now=now, cutoff_ts=int(cutoff.timestamp()))

    @property
    def is_backfill(self) -> bool:
        return self.prediction_date < self.today

    @property
    def is_future(self) -> bool:
        return self.prediction_date > self.today

    @property
    def emit_timestamp(self) -> datetime:
        return _backfill_timestamp(self.prediction_date) if self.is_backfill else self.now


@frozen
class _EmitResult:
    rows_emitted: int
    score_distribution: dict[str, Any]


def create_inference_run(
    *,
    pipeline: AutoresearchPipeline,
    model: AutoresearchModel,
    window: ScoringWindow,
    scheduled: bool = False,
    shadow: bool = False,
) -> AutoresearchRun:
    # Online validation discovers matured dates from these two keys instead of scanning
    # the events table, validates against the horizon scored here rather than the
    # pipeline's current one, and waits for a run that is still scoring the date.
    metrics: dict[str, Any] = {
        "prediction_date": window.prediction_date.isoformat(),
        "horizon_days": pipeline.horizon_days,
    }
    if shadow:
        # Readers of the champion's runs, such as the manual-scoring dedupe, skip a run with this key.
        metrics["shadow"] = True
    return AutoresearchRun.objects.create(
        pipeline=pipeline,
        model=model,
        run_type=AutoresearchRun.RunType.INFERENCE,
        scheduled=scheduled,
        status=AutoresearchRun.Status.RUNNING,
        started_at=django_timezone.now(),
        metrics=metrics,
    )


def run_inference_for_pipeline(
    pipeline: AutoresearchPipeline,
    model: AutoresearchModel,
    prediction_date: date | None = None,
    user: User | None = None,
    run: AutoresearchRun | None = None,
    query_context: QueryContext = INTERACTIVE_QUERY,
    scheduled: bool = False,
) -> AutoresearchRun:
    """
    Top-level inference entry point. Creates an AutoresearchRun, scores users,
    emits prediction events, and records metrics.

    ``prediction_date`` defaults to today (live scoring). Pass a past date to
    backfill: features are computed as of that date and the events carry that
    date's timestamp, so online validation can score them once the horizon has
    elapsed. A future date fails the run.

    ``user`` is who HogQL applies access control for; it defaults to the
    pipeline's creator.

    ``run`` is a row the caller created before it dispatched the scoring, so the caller
    can return it at once. A retry of the same attempt passes the same row again.

    ``query_context`` is the ClickHouse budget of every scoring query. The Temporal
    activity passes ``BATCH_QUERY``.

    ``scheduled`` marks a run the daily sweep started. Promotion counts only those runs when
    it decides that the champion cannot score.

    A live run that completes then scores the rest of the shadow set (``_score_shadow_set()``).
    Shadow scoring never fails this run or changes its outcome; the run records which shadow
    models completed, failed, or were skipped in ``metrics["shadow_models"]``.
    """
    window = ScoringWindow.for_date(prediction_date)
    if run is None:
        run = create_inference_run(pipeline=pipeline, model=model, window=window, scheduled=scheduled)
    else:
        run.model = model
        run.status = AutoresearchRun.Status.RUNNING
        run.error = ""
        run.metrics.pop("failure_kind", None)
        run.completed_at = None
        run.save(update_fields=["model", "status", "error", "metrics", "completed_at"])

    try:
        team = pipeline.team
        acting_user = _acting_user(team=team, pipeline=pipeline, user=user)
        scored = score_population(
            team=team, pipeline=pipeline, model=model, window=window, user=acting_user, query_context=query_context
        )
        emitted = _emit_predictions(
            team=team, pipeline=pipeline, model=model, run=run, scored=scored, window=window, user=acting_user
        )

        run.status = AutoresearchRun.Status.COMPLETED
        run.rows_scored = emitted.rows_emitted
        run.negative_sample_rate = scored.negative_sample_rate
        run.metrics.update(
            {
                "score_distribution": emitted.score_distribution,
                "stub": bool((model.model_recipe or {}).get("stub", False)),
                "sandbox": bool(model.artifact_prefix),
                "holdout_auc": scored.holdout_auc,
                # The coverage of a rolling run: rows_scored of rows_eligible were scored today.
                "rows_eligible": scored.rows_eligible,
            }
        )
        run.completed_at = django_timezone.now()
        run.save(update_fields=["status", "rows_scored", "negative_sample_rate", "metrics", "completed_at"])

        # Only a live run moves the cadence watermark. Backfilling a past date must not
        # make the coordinator think today's scoring already happened.
        if not window.is_backfill:
            pipeline.last_scored_at = run.completed_at
            pipeline.save(update_fields=["last_scored_at", "updated_at"])

        logger.info(
            "autoresearch_inference_complete",
            pipeline_id=str(pipeline.pk),
            model_id=str(model.pk),
            rows_scored=emitted.rows_emitted,
            rows_eligible=scored.rows_eligible,
        )

    except Exception as exc:
        run.status = AutoresearchRun.Status.FAILED
        run.error = str(exc)[:2000]
        run.metrics["failure_kind"] = classify_failure(exc)
        run.completed_at = django_timezone.now()
        run.save(update_fields=["status", "error", "metrics", "completed_at"])
        logger.exception(
            "autoresearch_inference_failed", pipeline_id=str(pipeline.pk), failure_kind=run.metrics["failure_kind"]
        )
        raise

    if not window.is_backfill:
        try:
            outcome = _score_shadow_set(
                team=team,
                pipeline=pipeline,
                champion=model,
                scored=scored,
                window=window,
                user=acting_user,
                query_context=query_context,
            )
        except Exception:
            # The champion's run is already complete. Nothing in the shadow phase may change that.
            logger.exception("autoresearch_shadow_scoring_failed", pipeline_id=str(pipeline.pk))
        else:
            if outcome is not None:
                run.metrics["shadow_models"] = outcome.as_metrics()
                run.save(update_fields=["metrics"])
    return run


def _acting_user(*, team: Team, pipeline: AutoresearchPipeline, user: User | None) -> User:
    try:
        return _resolve_acting_user(team=team, pipeline=pipeline, user=user)
    except SandboxInferenceError as exc:
        raise InferenceRunError(str(exc)) from exc


def _check_prediction_date(*, team: Team, pipeline: AutoresearchPipeline, window: ScoringWindow) -> None:
    """
    Refuse the dates that would complete a run with events nobody can use.

    A future date reads as live, so it would compute today's features, stamp a future
    prediction date on them, and advance the cadence. A backfill older than the team's
    ingestion threshold is accepted by capture and then dropped, so the run would record
    every row as scored with no event behind it. A backfill of a population filtered on
    person properties evaluates those properties as they are today, not as they were on
    that date, so the historical membership it claims is fiction.
    """
    prediction_date = window.prediction_date
    if window.is_future:
        raise InferenceRunError(f"Cannot score a future prediction date ({prediction_date.isoformat()})")
    if not window.is_backfill:
        return
    threshold = team.drop_events_older_than
    if threshold is not None and window.now - window.emit_timestamp > threshold:
        raise InferenceRunError(
            f"Cannot backfill {prediction_date.isoformat()}: ingestion drops this team's events older than "
            f"{threshold}, so the predictions would never be stored"
        )
    properties = (pipeline.inference_population or {}).get("properties") or []
    if any(str(prop.get("type", "person")) == "person" for prop in properties if isinstance(prop, dict)):
        raise InferenceRunError(
            "Cannot backfill a population filtered on person properties: membership would be decided on "
            "today's property values, not the values as of the prediction date"
        )


def _backfill_timestamp(prediction_date: date) -> datetime:
    # Noon UTC so the event lands in that day's window in every project timezone.
    return datetime(prediction_date.year, prediction_date.month, prediction_date.day, 12, tzinfo=UTC)


def score_population(
    *,
    team: Team,
    pipeline: AutoresearchPipeline,
    model: AutoresearchModel,
    window: ScoringWindow,
    user: User | None = None,
    query_context: QueryContext = INTERACTIVE_QUERY,
) -> ScoredPopulation:
    """
    Score the inference population with ``model`` and return the rows without emitting.

    A bundle-backed champion runs its ``predict.py`` in a sandbox against the persisted
    ``model.pkl``. A recipe-only champion has no persisted model: a stub recipe scores by
    a fixed engagement formula, and an agent recipe fits its allowlisted sklearn class on
    the anchored training population and predicts on the inference anchors, in process.
    The agent recipe's SQL goes through the same runnable-SQL validator as a bundle, so a
    recipe with a trailing LIMIT or with ``{anchors}`` only in a comment fails here
    instead of producing a query that runs without a cutoff.

    The prediction-date guards run here rather than in the emitting caller, so the dry run
    refuses exactly the dates the live run refuses.

    Every route returns its raw scores, and the prior correction for the model's negative
    sample rate is applied here, once, so no route can correct twice or not at all.
    """
    return _apply_prior_correction(
        _score_population_raw(
            team=team, pipeline=pipeline, model=model, window=window, user=user, query_context=query_context
        )
    )


def _score_population_raw(
    *,
    team: Team,
    pipeline: AutoresearchPipeline,
    model: AutoresearchModel,
    window: ScoringWindow,
    user: User | None = None,
    query_context: QueryContext = INTERACTIVE_QUERY,
) -> ScoredPopulation:
    _check_prediction_date(team=team, pipeline=pipeline, window=window)
    acting_user = _acting_user(team=team, pipeline=pipeline, user=user)
    cutoff_ts = window.cutoff_ts

    if model.artifact_prefix:
        result = score_via_sandbox(
            team=team,
            pipeline=pipeline,
            model=model,
            cutoff_ts=cutoff_ts,
            user=acting_user,
            query_context=query_context,
        )
        return ScoredPopulation(
            rows=result.scored_rows,
            holdout_auc=result.holdout_auc,
            negative_sample_rate=model.negative_sample_rate,
            rows_eligible=result.rows_eligible,
            features=result.features,
        )

    if window.is_backfill:
        # A recipe-only champion fits at scoring time, and its training labels are decided as of
        # now(), so a fit for a past date would learn from outcomes after that date and hand
        # online validation a lookahead score. Only a persisted model can be re-scored in the past.
        raise InferenceRunError(
            "Only a bundle-backed champion can be backfilled: a recipe-only champion fits at scoring time "
            "on labels decided as of today"
        )
    recipe = model.model_recipe or {}
    if recipe.get("stub"):
        stub_rows = _fetch_stub_feature_rows(
            team=team,
            pipeline=pipeline,
            recipe=recipe,
            cutoff_ts=cutoff_ts,
            user=acting_user,
            query_context=query_context,
        )
        return ScoredPopulation(
            rows=_score_rows(stub_rows.rows), holdout_auc=model.holdout_score, rows_eligible=stub_rows.eligible
        )

    feature_sql = str(recipe.get("feature_sql") or "")
    try:
        validate_runnable_feature_sql(feature_sql, source="Champion recipe feature_sql")
    except SandboxInferenceError as exc:
        raise InferenceRunError(str(exc)) from exc
    return _score_via_anchors(
        team=team,
        pipeline=pipeline,
        recipe=recipe,
        cutoff_ts=cutoff_ts,
        user=acting_user,
        query_context=query_context,
    )


def _emit_predictions(
    *,
    team: Team,
    pipeline: AutoresearchPipeline,
    model: AutoresearchModel,
    run: AutoresearchRun,
    scored: ScoredPopulation,
    window: ScoringWindow,
    user: User,
    shadow: bool = False,
) -> _EmitResult:
    """
    Send one prediction event per scored row in one batch. Any failed event fails the run:
    the event UUIDs are deterministic, so the retry re-sends every row and ingestion keeps
    one copy, whereas completing with a partial batch would advance the cadence past the
    people who never received their prediction or output property.

    A ``shadow`` batch is person-less, like a backfill: no person processing and no ``$set``,
    so a shadow score never reaches the output person property or the person's timeline.
    """
    if not scored.rows:
        logger.warning("autoresearch_no_scored_rows", pipeline_id=str(pipeline.pk), team_id=team.pk)
        return _EmitResult(rows_emitted=0, score_distribution={})

    is_backfill = window.is_backfill
    prediction_date_str = window.prediction_date.isoformat()
    emit_timestamp = window.emit_timestamp

    person_less = is_backfill or shadow
    if shadow:
        _require_still_in_shadow_set(pipeline=pipeline, model=model)
    else:
        _require_still_champion(model)
    # Live runs attach each prediction to the real person: a real distinct_id, a processed
    # person profile, and a $set of the output property. Backfills and shadow scores stay
    # person-less (they exist for online validation, which keys on $autoresearch_person_id)
    # so a past-dated or shadow $set cannot clobber the champion's live score.
    distinct_id_by_person = (
        {}
        if person_less
        else _resolve_distinct_ids(
            team=team, pipeline=pipeline, person_ids=[str(row["distinct_id"]) for row in scored.rows], user=user
        )
    )
    output_property = pipeline.output_person_property

    events: list[dict[str, Any]] = []
    for row in scored.rows:
        # Every row is keyed on person_id (the feature/score SQL aliases it "distinct_id").
        person_id = str(row["distinct_id"])
        real_distinct_id = distinct_id_by_person.get(person_id)
        attach_to_person = bool(real_distinct_id)
        # Feature values can be datetimes, Decimals, or UUIDs the model ignored; default=str
        # keeps the hash stable for them instead of failing the whole batch.
        features_hash = hashlib.sha256(
            json.dumps({k: v for k, v in row.items() if k not in _SCORE_KEYS}, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]
        props: dict[str, Any] = {
            "$autoresearch_pipeline_id": str(pipeline.pk),
            "$autoresearch_model_id": str(model.pk),
            "$autoresearch_model_role": SHADOW_MODEL_ROLE if shadow else model.role,
            "$autoresearch_target_event": pipeline.target_event,
            "$autoresearch_horizon_days": pipeline.horizon_days,
            "$autoresearch_p_y": row["p_y"],
            "$autoresearch_p_y_raw": row["p_y_raw"],
            "$autoresearch_negative_sample_rate": scored.negative_sample_rate,
            "$autoresearch_prediction_date": prediction_date_str,
            "$autoresearch_features_hash": features_hash,
            "$autoresearch_person_id": person_id,
            "$autoresearch_run_id": str(run.pk),
        }
        if attach_to_person and output_property:
            props["$set"] = {output_property: row["p_y"]}
        events.append(
            {
                "event": PREDICTION_EVENT_NAME,
                "distinct_id": _shadow_distinct_id(model_id=str(model.pk), person_id=person_id)
                if shadow
                else real_distinct_id or person_id,
                "timestamp": emit_timestamp,
                "properties": props,
                "options": {"process_person_profile": attach_to_person},
                "event_uuid": _prediction_event_uuid(
                    pipeline_id=str(pipeline.pk),
                    model_id=str(model.pk),
                    prediction_date=prediction_date_str,
                    person_id=person_id,
                ),
            }
        )

    try:
        # The batch-level flag is a safety rail that forces every event person-less when
        # False; a live run needs it on so each event's own option decides.
        result = capture_batch_internal(
            events=events,
            token=team.api_token,
            event_source=EVENT_SOURCE,
            process_person_profile=not person_less,
        )
    except Exception as exc:
        logger.exception("autoresearch_prediction_emit_failed", pipeline_id=str(pipeline.pk))
        raise InferenceRunError(f"Prediction events could not be sent: {exc}") from exc
    # A warning is an event capture stored with something switched off, such as person
    # processing for a rate-limited distinct id, so its $set never reaches the person.
    # succeeded() ignores warnings on purpose; this run cannot.
    if not result.succeeded() or result.warnings:
        logger.warning(
            "autoresearch_prediction_emit_partial",
            pipeline_id=str(pipeline.pk),
            dropped=len(result.dropped),
            retried=len(result.retried),
            unaccounted=len(result.unaccounted),
            warnings=len(result.warnings),
            error=result.error,
        )
        sample = [result.results.get(uid) for uid in result.warnings[:3]]
        error_detail = ""
        if result.error:
            error_detail = f", {result.error.get('error')}"
            if description := result.error.get("error_description"):
                error_detail += f": {_clip_middle(str(description), _MAX_EMIT_ERROR_DESCRIPTION_CHARS)}"
        raise InferenceRunError(
            f"Prediction events were not all accepted ({len(result.dropped)} dropped, "
            f"{len(result.retried)} exhausted retries, {len(result.unaccounted)} unaccounted, "
            f"{len(result.warnings)} stored with a warning{f' e.g. {sample!r}' if sample else ''}"
            f"{error_detail}); failing the run so it is retried"
        )

    return _EmitResult(
        rows_emitted=len(events), score_distribution=_summarize_scores([row["p_y"] for row in scored.rows])
    )


def _shadow_distinct_id(*, model_id: str, person_id: str) -> str:
    """
    Ingestion deduplicates events on timestamp, distinct_id, token, and event name, not on the UUID.
    Every shadow event of a run shares one timestamp, so each model needs its own distinct_id per
    person, or one model's prediction would drop another's, or the champion's for an unresolved person.
    """
    return f"autoresearch-shadow:{model_id}:{person_id}"


def _require_still_champion(model: AutoresearchModel) -> None:
    """
    Promotion can swap the champion while a run is scoring with the old one. Re-reading the
    role right before the events go out stops a superseded model from writing its scores
    over the new champion's; the window between this read and capture is the residue.
    """
    if model.role != AutoresearchModel.Role.CHAMPION:
        return
    if not AutoresearchModel.objects.filter(pk=model.pk, role=AutoresearchModel.Role.CHAMPION).exists():
        raise InferenceRunError(
            f"Model {model.pk} stopped being the champion while this run was scoring; the new champion's next "
            "cadence supersedes it"
        )


def _require_still_in_shadow_set(*, pipeline: AutoresearchPipeline, model: AutoresearchModel) -> None:
    """The shadow counterpart of ``_require_still_champion()``: a model that left the set does not emit."""
    shadow_ids = {member.pk for member in shadow_set(pipeline) if member.role != AutoresearchModel.Role.CHAMPION}
    if model.pk not in shadow_ids:
        raise InferenceRunError(f"Model {model.pk} left the shadow set while this run was scoring")


# ── Shadow set ─────────────────────────────────────────────────────────────────────


@frozen
class ShadowScoringOutcome:
    completed: list[str]
    failed: list[str]
    # Models the time budget left unscored this cadence.
    skipped: list[str]

    def as_metrics(self) -> dict[str, list[str]]:
        return {"completed": self.completed, "failed": self.failed, "skipped": self.skipped}


def _score_shadow_set(
    *,
    team: Team,
    pipeline: AutoresearchPipeline,
    champion: AutoresearchModel,
    scored: ScoredPopulation,
    window: ScoringWindow,
    user: User,
    query_context: QueryContext = INTERACTIVE_QUERY,
    clock: Callable[[], float] = time.monotonic,
) -> ShadowScoringOutcome | None:
    """
    Score every shadow-set model other than the champion against the people the champion's run
    scored, so online validation compares the models on the same people on the same date.

    One feature query runs per distinct ``features.sql``: the champion's rows are reused when a
    shadow model shares its SQL, and each other SQL materializes once for every model that uses
    it. Each model records its own inference run, and its failure fails only that run. No new
    model starts after ``SHADOW_TIME_BUDGET_S``. Returns None when there is nothing to score.
    """
    members = [model for model in shadow_set(pipeline) if model.pk != champion.pk]
    if not members or not scored.rows:
        return None
    persons = {str(row["distinct_id"]) for row in scored.rows}
    materialized: dict[str, InferenceRows | Exception] = {}
    if scored.features is not None:
        materialized[scored.features.sql_digest] = scored.features.data

    completed: list[str] = []
    failed: list[str] = []
    skipped: list[str] = []
    started = clock()
    bundles = [_read_shadow_bundle(model) for model in members]
    digests = [
        None if isinstance(bundle, Exception) else features_sql_digest(bundle.features_sql) for bundle in bundles
    ]
    last_use = {digest: index for index, digest in enumerate(digests) if digest is not None}
    for index, model in enumerate(members):
        if clock() - started >= SHADOW_TIME_BUDGET_S:
            skipped.append(str(model.pk))
            continue
        ok = _score_shadow_model(
            team=team,
            pipeline=pipeline,
            model=model,
            bundle=bundles[index],
            persons=persons,
            materialized=materialized,
            window=window,
            user=user,
            query_context=query_context,
        )
        (completed if ok else failed).append(str(model.pk))
        digest = digests[index]
        if digest is not None and last_use[digest] == index:
            # Each result can hold tens of thousands of wide rows, so the phase keeps only the
            # results a later model still needs, not one result per distinct SQL.
            materialized.pop(digest, None)
    if skipped:
        logger.warning("autoresearch_shadow_scoring_over_budget", pipeline_id=str(pipeline.pk), skipped=len(skipped))
    return ShadowScoringOutcome(completed=completed, failed=failed, skipped=skipped)


def _read_shadow_bundle(model: AutoresearchModel) -> ArtifactBundle | Exception:
    """The model's runnable bundle, or the error that fails its run. The error never stops the other models."""
    try:
        bundle = read_bundle(model.artifact_prefix)
        _validate_bundle_feature_sql(bundle)
    except Exception as exc:
        return exc
    return bundle


def _score_shadow_model(
    *,
    team: Team,
    pipeline: AutoresearchPipeline,
    model: AutoresearchModel,
    bundle: ArtifactBundle | Exception,
    persons: set[str],
    materialized: dict[str, InferenceRows | Exception],
    window: ScoringWindow,
    user: User,
    query_context: QueryContext,
) -> bool:
    """
    Score one shadow model and record its run. The run is never ``scheduled``, so it cannot
    count toward or break an unscorable streak, even after the model becomes the champion.
    """
    run = create_inference_run(pipeline=pipeline, model=model, window=window, shadow=True)
    try:
        if isinstance(bundle, Exception):
            raise InferenceRunError(
                f"Could not read a runnable bundle at {model.artifact_prefix}: {bundle}"
            ) from bundle
        score_data = _shadow_score_data(
            team=team,
            pipeline=pipeline,
            feature_sql=bundle.features_sql,
            persons=persons,
            materialized=materialized,
            window=window,
            user=user,
            query_context=query_context,
        )
        result = score_via_sandbox(
            team=team,
            pipeline=pipeline,
            model=model,
            cutoff_ts=window.cutoff_ts,
            user=user,
            query_context=query_context,
            bundle=bundle,
            score_data=score_data,
        )
        scored = _apply_prior_correction(
            ScoredPopulation(
                rows=result.scored_rows,
                holdout_auc=result.holdout_auc,
                negative_sample_rate=model.negative_sample_rate,
                rows_eligible=result.rows_eligible,
            )
        )
        emitted = _emit_predictions(
            team=team, pipeline=pipeline, model=model, run=run, scored=scored, window=window, user=user, shadow=True
        )
    except Exception as exc:
        run.status = AutoresearchRun.Status.FAILED
        run.error = str(exc)[:2000]
        run.metrics["failure_kind"] = classify_failure(exc)
        run.completed_at = django_timezone.now()
        run.save(update_fields=["status", "error", "metrics", "completed_at"])
        logger.exception(
            "autoresearch_shadow_model_failed",
            pipeline_id=str(pipeline.pk),
            model_id=str(model.pk),
            failure_kind=run.metrics["failure_kind"],
        )
        return False

    run.status = AutoresearchRun.Status.COMPLETED
    run.rows_scored = emitted.rows_emitted
    run.negative_sample_rate = scored.negative_sample_rate
    run.metrics.update(
        {
            "score_distribution": emitted.score_distribution,
            "stub": False,
            "sandbox": True,
            "holdout_auc": scored.holdout_auc,
            "rows_eligible": scored.rows_eligible,
        }
    )
    run.completed_at = django_timezone.now()
    run.save(update_fields=["status", "rows_scored", "negative_sample_rate", "metrics", "completed_at"])
    return True


def _shadow_score_data(
    *,
    team: Team,
    pipeline: AutoresearchPipeline,
    feature_sql: str,
    persons: set[str],
    materialized: dict[str, InferenceRows | Exception],
    window: ScoringWindow,
    user: User,
    query_context: QueryContext,
) -> InferenceRows:
    """
    The feature rows for ``feature_sql``, materialized once per digest. A failure is cached too,
    so a second model with the same broken SQL fails without a second query.

    The anchors bind the run's cutoff, so the selection repeats the champion's. Rows that key a
    different set of people (an event that landed late moved the rolling ranking) fail the
    models that use them, because unpaired scores would not compare with the champion's.
    """
    digest = features_sql_digest(feature_sql)
    if digest not in materialized:
        try:
            data = _materialize_score_data(
                team=team,
                pipeline=pipeline,
                feature_sql=feature_sql,
                cutoff_ts=window.cutoff_ts,
                user=user,
                query_context=query_context,
            )
            if {str(row["distinct_id"]) for row in data.rows} != persons:
                raise InferenceRunError(
                    "The shadow feature query did not select the people the champion scored; "
                    "refusing to emit scores that do not pair with the champion's"
                )
            materialized[digest] = data
        except Exception as exc:
            materialized[digest] = exc
    cached = materialized[digest]
    if isinstance(cached, Exception):
        raise cached
    return cached


# ── Queries ────────────────────────────────────────────────────────────────────────


def _query(
    *,
    team: Team,
    sql: str,
    values: dict[str, Any],
    user: User | None,
    what: str,
    query_context: QueryContext = INTERACTIVE_QUERY,
) -> HogQLResult:
    """
    Run a person-keyed query as the acting user, fresh, bounded at ``_MATERIALIZE_ROW_LIMIT``.

    HogQL caps a bare SELECT at 100 rows without an error, so every query here carries an
    explicit bound, and a result that fills it is treated as truncated: completing would
    advance the cadence past the people beyond the cap. A scoring population that large takes a
    rolling subset below the bound, so only a query that misbehaves reaches it. The persons-on-events modifiers
    keep ``person_id`` resolving the way the labeler's queries do, and the always-calculate mode stops a
    cadence reusing a cached population at a stale cutoff.
    """
    bounded_sql = sql.rstrip().rstrip(";") + f"\nLIMIT {_MATERIALIZE_ROW_LIMIT}"
    try:
        tag_queries(product=Product.AUTORESEARCH, feature=Feature.QUERY)
        result = run_hogql(
            team=team,
            query=HogQLQuery(query=bounded_sql, values=values, modifiers=LABELER_QUERY_MODIFIERS),
            user=user,
            execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
            query_context=query_context,
        )
    except Exception as exc:
        logger.exception("autoresearch_inference_query_failed", team_id=team.pk, what=what)
        raise InferenceRunError(
            f"{what} query failed; failing the run rather than completing it against a partial or unrestricted "
            "population"
        ) from exc
    if result.has_more or len(result.rows) >= _MATERIALIZE_ROW_LIMIT:
        raise InferenceRunError(
            f"{what} query hit the {_MATERIALIZE_ROW_LIMIT}-row limit; the population is likely truncated, "
            "refusing to score a partial population"
        )
    return result


def _person_rows(result: HogQLResult) -> list[dict[str, Any]]:
    """Rows as dicts with the person key coerced to str, so it is JSON-serializable and joins to str-keyed sets."""
    if not result.rows or not result.columns:
        return []
    # as_dicts() keeps only the last value of a repeated column name, so the matrix would hold
    # fewer features than the SQL declares.
    duplicates = sorted({c for c in result.columns if result.columns.count(c) > 1})
    if duplicates:
        raise InferenceRunError(f"Feature SQL returned duplicate output columns: {', '.join(duplicates)}")
    # Counted before any column is typed: the numeric filter discards non-numeric columns, so
    # a result padded with string aliases would pass the matrix cap after being materialized.
    output_cols = [c for c in result.columns if c not in _RESERVED_COLS]
    if len(output_cols) > _MAX_FEATURE_COLS:
        raise InferenceRunError(
            f"Feature SQL returned {len(output_cols)} output columns; at most {_MAX_FEATURE_COLS} are allowed"
        )
    rows = result.as_dicts()
    for row in rows:
        if row.get("distinct_id") is not None:
            row["distinct_id"] = str(row["distinct_id"])
    return rows


def _require_one_row_per_person(rows: list[dict[str, Any]], *, source: str, expected_count: int | None) -> None:
    try:
        validate_unique_distinct_ids(rows, source=source, expected_count=expected_count)
    except RecipeValidationError as exc:
        raise InferenceRunError(str(exc)) from exc


def _feature_lookback_days(pipeline: AutoresearchPipeline) -> int:
    # Same window as sandbox._feature_lookback_days: 4x horizon, at least 30 days.
    return max(30, pipeline.horizon_days * 4)


def _fetch_stub_feature_rows(
    *,
    team: Team,
    pipeline: AutoresearchPipeline,
    recipe: dict[str, Any],
    cutoff_ts: int,
    user: User,
    query_context: QueryContext = INTERACTIVE_QUERY,
) -> InferenceRows:
    """
    Run a stub recipe's feature SQL restricted to the inference population.

    The stub's SQL is templated in ``training/stub.py``, evaluates at now(), and carries
    no ``{anchors}``, so it does not go through the anchors builders. The population is
    applied inside the query rather than on the returned rows, so the row bound measures
    the population being scored and not every person on the team. The rows are checked
    against the population count, as the anchored paths check theirs against the anchors,
    because stub SQL that drops a member leaves every returned row looking valid. A population
    at or above the cap scores a rolling subset, as the anchored paths do. The population and the
    rolling ranking bind the run's ``cutoff_ts``, so a retry selects the same people, while the
    stub SQL itself keeps reading at now().
    """
    feature_sql = str(recipe.get("feature_sql") or "")
    if not feature_sql:
        logger.warning("autoresearch_empty_feature_sql", pipeline_id=str(pipeline.pk))
        return InferenceRows(rows=[], eligible=0)
    lookback_days = _feature_lookback_days(pipeline)
    feature_sql = feature_sql.replace("{lookback_days}", str(lookback_days)).rstrip().rstrip(";")
    population = _population_query(
        population=pipeline.inference_population,
        lookback_days=lookback_days,
        cutoff_ts=cutoff_ts,
        target_event=pipeline.target_event,
        target_definition=pipeline.target_definition,
        team=team,
    )
    if population is None:
        rows = _person_rows(
            _query(team=team, sql=feature_sql, values={}, user=user, what="Feature", query_context=query_context)
        )
        _require_one_row_per_person(rows, source="stub feature_sql", expected_count=None)
        return InferenceRows(rows=rows, eligible=len(rows))
    eligible = _count_population(team=team, population=population, user=user, query_context=query_context)
    rolling = rolling_selection(eligible=eligible, pipeline_id=str(pipeline.pk), cadence_days=pipeline.cadence_days)
    if rolling is not None:
        population = (
            _population_query(
                population=pipeline.inference_population,
                lookback_days=lookback_days,
                cutoff_ts=cutoff_ts,
                target_event=pipeline.target_event,
                target_definition=pipeline.target_definition,
                team=team,
                rolling=rolling,
            )
            or population
        )
    sql = f"SELECT * FROM ({feature_sql}) AS f WHERE f.distinct_id IN ({population.sql})"
    rows = _person_rows(
        _query(team=team, sql=sql, values=population.values, user=user, what="Feature", query_context=query_context)
    )
    _require_one_row_per_person(
        rows, source="stub feature_sql", expected_count=eligible if rolling is None else rolling.limit
    )
    return InferenceRows(rows=rows, eligible=eligible)


@frozen
class _PopulationQuery:
    sql: str
    values: dict[str, Any]


def _population_query(
    *,
    population: dict[str, Any] | None,
    lookback_days: int,
    cutoff_ts: int | None = None,
    target_event: str = "",
    target_definition: dict[str, Any] | None = None,
    team: Team | None = None,
    rolling: RollingSelection | None = None,
) -> _PopulationQuery | None:
    """
    A ``SELECT person_id`` for the people in the inference population, one row each, from the
    scorer's own anchor query, so it is restricted to identified users under the v1 scope. None only when nothing restricts the population.
    A configured filter that cannot be compiled raises, because widening to everyone is
    the failure being prevented. ``rolling`` keeps only a rolling subset of the people.
    """
    if not IDENTIFIED_USERS_ONLY and not (population or {}).get("properties") and not (population or {}).get("kind"):
        return None
    anchors_sql, values = build_inference_anchors_sql(
        lookback_days=lookback_days,
        inference_population=population,
        cutoff_ts=cutoff_ts,
        target_event=target_event,
        target_definition=target_definition,
        team=team,
        rolling=rolling,
    )
    return _PopulationQuery(sql=f"SELECT person_id FROM ({anchors_sql.strip()})", values=values)


def _count_population(
    *, team: Team, population: _PopulationQuery, user: User, query_context: QueryContext = INTERACTIVE_QUERY
) -> int:
    result = _query(
        team=team,
        sql=f"SELECT count() FROM ({population.sql})",
        values=population.values,
        user=user,
        what="Population count",
        query_context=query_context,
    )
    if len(result.rows) != 1 or not result.rows[0]:
        raise InferenceRunError("Population count query did not return a single row")
    return int(result.rows[0][0])


def _resolve_distinct_ids(
    *, team: Team, pipeline: AutoresearchPipeline, person_ids: list[str], user: User
) -> dict[str, str]:
    """
    Map each person_id to one of that person's current distinct_ids.

    Every row is keyed on person_id, but a live event attaches to a person through a
    distinct_id, so the event goes out under one of the person's real ids rather than the
    person UUID. The mapping comes from personhog, the identity source of truth: an id read
    off event history can belong to someone else after a merge or split. A person with no
    resolvable id is emitted person-less by the caller.
    """
    resolvable = [p for p in person_ids if _is_uuid(p)]
    if len(resolvable) != len(person_ids):
        logger.warning(
            "autoresearch_unresolvable_person_ids",
            pipeline_id=str(pipeline.pk),
            skipped=len(person_ids) - len(resolvable),
        )
    if not resolvable:
        return {}
    try:
        persons = get_persons_by_uuids(team.pk, resolvable, distinct_id_limit=1)
    except Exception as exc:
        logger.exception("autoresearch_identity_resolution_failed", pipeline_id=str(pipeline.pk))
        raise InferenceRunError(
            "Identity resolution failed; failing the run rather than emitting every prediction person-less"
        ) from exc
    return {str(person.uuid): person.distinct_ids[0] for person in persons if person.distinct_ids}


# ── Recipe-only champions ─────────────────────────────────────────────────────────


def _score_via_anchors(
    *,
    team: Team,
    pipeline: AutoresearchPipeline,
    recipe: dict[str, Any],
    cutoff_ts: int | None,
    user: User,
    query_context: QueryContext = INTERACTIVE_QUERY,
) -> ScoredPopulation:
    """
    Score with an agent recipe that has no bundle.

    The recipe's feature SQL runs twice: against the labeled training anchors (per-user
    random T0, label, fold) and against the inference anchors (cutoff now(), or the
    backfill instant). The model fits on the training folds, reports a holdout AUC on
    fold 0, and predicts on the inference rows. Without training rows the stub formula
    scores the inference rows, so a half-broken recipe still emits zero-information
    predictions instead of nothing.
    """
    feature_sql = str(recipe.get("feature_sql") or "").replace("{lookback_days}", str(_feature_lookback_days(pipeline)))
    training_rows, negative_sample_rate = _fetch_training_rows(
        team=team, pipeline=pipeline, feature_sql=feature_sql, user=user, query_context=query_context
    )
    inference = _fetch_inference_rows(
        team=team,
        pipeline=pipeline,
        feature_sql=feature_sql,
        cutoff_ts=cutoff_ts,
        user=user,
        query_context=query_context,
    )
    if not inference.rows:
        logger.warning("autoresearch_no_inference_rows", pipeline_id=str(pipeline.pk))
        return ScoredPopulation(rows=[], holdout_auc=None, rows_eligible=inference.eligible)
    if not training_rows:
        logger.warning("autoresearch_no_training_rows_anchored_fallback_stub", pipeline_id=str(pipeline.pk))
        return ScoredPopulation(rows=_score_rows(inference.rows), holdout_auc=None, rows_eligible=inference.eligible)
    scored = _fit_on_training_predict_on_inference(
        training_rows=training_rows,
        inference_rows=inference.rows,
        recipe=recipe,
        pipeline_id=str(pipeline.pk),
        negative_sample_rate=negative_sample_rate,
    )
    return dataclasses.replace(scored, rows_eligible=inference.eligible)


def _fetch_training_rows(
    *,
    team: Team,
    pipeline: AutoresearchPipeline,
    feature_sql: str,
    user: User,
    query_context: QueryContext = INTERACTIVE_QUERY,
) -> tuple[list[dict[str, Any]], float]:
    """
    The recipe's feature SQL against the labeled anchors: one row per person with ``__label``
    and ``__fold``, and the negative sample rate the rows were drawn at.
    """
    anchor_ts = int(django_timezone.now().timestamp())
    try:
        sample = measure_training_sample(
            team=team, pipeline=pipeline, anchor_ts=anchor_ts, user=user, query_context=query_context
        )
    except SandboxInferenceError as exc:
        raise InferenceRunError(str(exc)) from exc
    sql, values = build_training_features_sql(
        feature_sql=feature_sql,
        target_event=pipeline.target_event,
        target_definition=pipeline.target_definition,
        team=team,
        horizon_days=pipeline.horizon_days,
        lookback_days=pipeline.training_lookback_days,
        training_population=pipeline.training_population,
        anchor_ts=anchor_ts,
        negative_sample_rate=sample.negative_sample_rate,
    )
    rows = _person_rows(
        _query(team=team, sql=sql, values=values, user=user, what="Training features", query_context=query_context)
    )
    try:
        expected = count_training_anchors(
            team=team,
            pipeline=pipeline,
            anchor_ts=anchor_ts,
            user=user,
            negative_sample_rate=sample.negative_sample_rate,
            query_context=query_context,
        )
    except SandboxInferenceError as exc:
        raise InferenceRunError(str(exc)) from exc
    _require_one_row_per_person(rows, source="training feature_sql", expected_count=expected)
    # The wrapper LEFT JOINs the labels onto the feature rows; a row that matched no anchor
    # would be filed as a negative holdout example.
    unlabeled = sum(1 for r in rows if r.get(_LABEL_COL) is None or r.get(_FOLD_COL) is None)
    if unlabeled:
        raise InferenceRunError(
            f"{unlabeled} training feature row(s) matched no labeled anchor; distinct_id must be the anchor person_id"
        )
    return rows, sample.negative_sample_rate


def _fetch_inference_rows(
    *,
    team: Team,
    pipeline: AutoresearchPipeline,
    feature_sql: str,
    cutoff_ts: int | None,
    user: User,
    query_context: QueryContext = INTERACTIVE_QUERY,
) -> InferenceRows:
    """
    The recipe's feature SQL against the inference anchors: one row per eligible person, or
    per person in the rolling subset when the population reached the cap.

    The row count is checked against the anchor count, because feature SQL that inner
    joins or filters a joined table drops people without any row looking wrong. The training
    rows get the same check against the labeled anchors.
    """
    try:
        eligible = count_inference_anchors(
            team=team, pipeline=pipeline, cutoff_ts=cutoff_ts, user=user, query_context=query_context
        )
    except SandboxInferenceError as exc:
        raise InferenceRunError(str(exc)) from exc
    rolling = rolling_selection(eligible=eligible, pipeline_id=str(pipeline.pk), cadence_days=pipeline.cadence_days)
    sql, values = build_inference_features_sql(
        feature_sql=feature_sql,
        lookback_days=_feature_lookback_days(pipeline),
        inference_population=pipeline.inference_population,
        cutoff_ts=cutoff_ts,
        target_event=pipeline.target_event,
        target_definition=pipeline.target_definition,
        team=team,
        rolling=rolling,
    )
    rows = _person_rows(
        _query(team=team, sql=sql, values=values, user=user, what="Inference features", query_context=query_context)
    )
    _require_one_row_per_person(
        rows, source="inference feature_sql", expected_count=eligible if rolling is None else rolling.limit
    )
    return InferenceRows(rows=rows, eligible=eligible)


def _fit_on_training_predict_on_inference(
    *,
    training_rows: list[dict[str, Any]],
    inference_rows: list[dict[str, Any]],
    recipe: dict[str, Any],
    pipeline_id: str,
    negative_sample_rate: float = 1.0,
) -> ScoredPopulation:
    """
    Fit the recipe's allowlisted sklearn class on the training folds, score the holdout
    fold for the AUC the run records, and predict on the inference rows. A fit or predict
    failure falls back to the stub formula so the cadence still emits. Only the fitted
    scores carry ``negative_sample_rate``; the stub formula never saw the sample.
    """
    # Feature SQL without an ORDER BY returns rows in any order, and an estimator that
    # samples row indices fits a different model on a different order despite its seed.
    training_rows = sorted(training_rows, key=lambda r: str(r.get("distinct_id")))
    feature_cols = _numeric_feature_cols(training_rows)
    if not feature_cols:
        logger.warning("autoresearch_no_numeric_features", pipeline_id=pipeline_id)
        return ScoredPopulation(rows=_score_rows(inference_rows), holdout_auc=None)
    if len(feature_cols) > _MAX_FEATURE_COLS:
        # The row bound does not bound the matrix: the agent's SQL chooses the column count.
        raise InferenceRunError(
            f"Recipe feature SQL returned {len(feature_cols)} numeric columns; at most {_MAX_FEATURE_COLS} are allowed"
        )

    train_rows = [r for r in training_rows if (r.get(_FOLD_COL) or 0) != _HOLDOUT_FOLD]
    holdout_rows = [r for r in training_rows if (r.get(_FOLD_COL) or 0) == _HOLDOUT_FOLD]
    if not train_rows:
        logger.warning("autoresearch_no_train_fold_rows", pipeline_id=pipeline_id)
        return ScoredPopulation(rows=_score_rows(inference_rows), holdout_auc=None)

    X_train = _matrix(train_rows, feature_cols)
    y_train = _labels(train_rows)
    n_pos = int(y_train.sum())
    n_neg = int(len(y_train) - n_pos)
    if n_pos < 5 or n_neg < 5:
        logger.warning("autoresearch_insufficient_labels", pipeline_id=pipeline_id, n_pos=n_pos, n_neg=n_neg)
        return ScoredPopulation(rows=_score_rows(inference_rows), holdout_auc=None)

    model_class_path = str(recipe.get("model_class", "sklearn.linear_model.LogisticRegression"))
    try:
        estimator = _estimator_for(recipe, seed=_stable_seed(pipeline_id))
        estimator.fit(X_train, y_train)
    except Exception:
        logger.exception("autoresearch_anchored_fit_failed", pipeline_id=pipeline_id, model_class=model_class_path)
        return ScoredPopulation(rows=_score_rows(inference_rows), holdout_auc=None)

    holdout_auc = _holdout_auc(estimator, holdout_rows, feature_cols, pipeline_id=pipeline_id)

    # A present non-numeric value in a fitted column fails the run: zero-filling it would
    # emit a plausible wrong prediction, the same rule the sandbox path applies.
    X_score = _matrix(inference_rows, feature_cols)
    try:
        proba = estimator.predict_proba(X_score)[:, 1]
    except Exception:
        logger.exception("autoresearch_anchored_predict_failed", pipeline_id=pipeline_id, model_class=model_class_path)
        return ScoredPopulation(rows=_score_rows(inference_rows), holdout_auc=holdout_auc)

    logger.info(
        "autoresearch_anchored_fit_complete",
        pipeline_id=pipeline_id,
        model_class=model_class_path,
        n_train=len(y_train),
        n_pos=n_pos,
        n_features=len(feature_cols),
        holdout_auc=holdout_auc,
    )
    # Full precision, as _join_scores keeps for a bundle: rounding would tie predictions that
    # online validation ranks against each other.
    scored = [{**row, "p_y": float(p)} for row, p in zip(inference_rows, proba)]
    return ScoredPopulation(rows=scored, holdout_auc=holdout_auc, negative_sample_rate=negative_sample_rate)


def _stable_seed(pipeline_id: str) -> int:
    return int(hashlib.sha256(pipeline_id.encode()).hexdigest()[:8], 16)


def check_recipe_estimator(recipe: dict[str, Any]) -> None:
    """Raise ``RecipeValidationError`` when the recipe's class and params cannot build an estimator.

    Promotion calls this before a recipe-only champion is installed: the constructor is the
    only place an unknown hyperparameter is refused, and a champion that fails there would fail
    every scoring run instead of this one completion.
    """
    try:
        _estimator_for(recipe, seed=0)
    except RecipeValidationError:
        raise
    except Exception as exc:
        raise RecipeValidationError(f"model_params cannot construct {recipe.get('model_class')!r}: {exc}") from exc


def _estimator_for(recipe: dict[str, Any], *, seed: int) -> Any:
    """
    Instantiate the recipe's allowlisted sklearn class. This is the one in-process importlib
    surface, and the allowlist is the only defense, because a recipe-only champion has no
    sandbox around its model class.

    A stochastic estimator gets a seed derived from the pipeline unless the recipe sets one:
    a retry after a partial capture refits, and two fits that disagree would leave one
    cadence with scores from both, because the event UUIDs are the same either way.
    """
    model_class_path = str(recipe.get("model_class", "sklearn.linear_model.LogisticRegression"))
    validate_model_class(model_class_path)
    module_path, class_name = model_class_path.rsplit(".", 1)
    model_class = getattr(importlib.import_module(module_path), class_name)
    params = dict(recipe.get("model_params") or {})
    accepted = inspect.signature(model_class.__init__).parameters
    if "random_state" in accepted and params.get("random_state") is None:
        # An explicit null would otherwise suppress the seed and make a retry refit differently.
        params["random_state"] = seed
    if "n_jobs" in accepted:
        # The fit runs in the worker process; an agent's n_jobs=-1 would take every core it has.
        params["n_jobs"] = 1
    return model_class(**params)


def _matrix(rows: list[dict[str, Any]], feature_cols: list[str]) -> np.ndarray:
    try:
        return np.array([[_num(r.get(c), col=c) for c in feature_cols] for r in rows], dtype=np.float64)
    except SandboxInferenceError as exc:
        raise InferenceRunError(str(exc)) from exc


def _labels(rows: list[dict[str, Any]]) -> np.ndarray:
    return np.array([int(r.get(_LABEL_COL) or 0) for r in rows], dtype=np.int32)


def _holdout_auc(
    estimator: Any, holdout_rows: list[dict[str, Any]], feature_cols: list[str], *, pipeline_id: str
) -> float | None:
    """AUC on fold 0, or None when the holdout is empty, single-class, or fails to score."""
    if not holdout_rows:
        return None
    try:
        # Deferred to keep the heavy dependency off the import path.
        from sklearn.metrics import roc_auc_score  # noqa: PLC0415

        y_holdout = _labels(holdout_rows)
        if len(set(y_holdout.tolist())) < 2:
            return None
        p_holdout = estimator.predict_proba(_matrix(holdout_rows, feature_cols))[:, 1]
        return round(float(roc_auc_score(y_holdout, p_holdout)), 4)
    except Exception:
        logger.exception("autoresearch_holdout_auc_failed", pipeline_id=pipeline_id)
        return None


def _score_rows(feature_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    The stub formula: a sigmoid of event volume against recency, as a proxy for engagement.
    Serves stub champions, and any recipe-only champion whose fit could not run.
    """
    if not feature_rows:
        return []

    # The stub SQL names the column by its window ("events_total_30d"); the fixture SQL
    # names it "events_total".
    total_col = next(
        (col for col in feature_rows[0].keys() if col.startswith("events_total_") or col == "events_total"),
        None,
    )
    days_col = next((col for col in feature_rows[0].keys() if "days_since_last" in col), None)

    def _sigmoid(x: float) -> float:
        return 1.0 / (1.0 + math.exp(-x))

    def _stub_score(row: dict[str, Any]) -> float:
        activity = float(row.get(total_col) or 0) if total_col else 0.0
        # Zero days since the last event is the most recent a person can be; only an
        # absent value falls back to a month.
        recency_value = row.get(days_col) if days_col else None
        recency = float(recency_value) if recency_value is not None else 30.0
        raw = (activity / 20.0) - (recency / 14.0)
        return round(_sigmoid(raw), 4)

    return [{**row, "p_y": _stub_score(row)} for row in feature_rows if row.get("distinct_id")]


def _summarize_scores(scores: list[float]) -> dict[str, Any]:
    if not scores:
        return {}
    n = len(scores)
    sorted_scores = sorted(scores)
    return {
        "count": n,
        "mean": round(sum(scores) / n, 4),
        "p10": round(sorted_scores[int(n * 0.10)], 4),
        "p50": round(sorted_scores[int(n * 0.50)], 4),
        "p90": round(sorted_scores[int(n * 0.90)], 4),
        "min": round(sorted_scores[0], 4),
        "max": round(sorted_scores[-1], 4),
    }
