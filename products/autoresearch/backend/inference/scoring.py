"""
Inference: load the champion, score the inference population, and emit one
autoresearch_prediction event per person.

- ``run_inference_for_pipeline()`` is the entry point for the Temporal activity
  (temporal/workflows.py) and for ``autoresearch_score``: it records an
  AutoresearchRun, scores, and emits.
- ``score_population()`` is the scoring half on its own, for a dry run that wants
  the scores without the events.

Event shape:
    event: autoresearch_prediction
    distinct_id: <person distinct_id>
    properties:
        $autoresearch_pipeline_id:     str (UUID)
        $autoresearch_model_id:        str (UUID)
        $autoresearch_model_role:      "champion" | "challenger"
        $autoresearch_target_event:    str
        $autoresearch_horizon_days:    int
        $autoresearch_p_y:             float  (the score)
        $autoresearch_prediction_date: str (YYYY-MM-DD)
        $autoresearch_features_hash:   str (SHA-256 prefix of the feature row)
        $autoresearch_person_id:       str (the person_id every row is keyed on)
"""

import json
import math
import uuid
import hashlib
import inspect
import importlib
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
    LABELER_QUERY_MODIFIERS,
    PREDICTION_EVENT_NAME,
    _build_population_conditions,
    _build_population_kind_conditions,
    _identified_users_and_clause,
    _own_events_excluded_clause,
    _target_condition_for,
    build_inference_features_sql,
    build_training_features_sql,
)
from products.autoresearch.backend.inference.sandbox import (
    _FOLD_COL,
    _HOLDOUT_FOLD,
    _LABEL_COL,
    _MATERIALIZE_ROW_LIMIT,
    _MAX_FEATURE_COLS,
    SandboxInferenceError,
    _num,
    _numeric_feature_cols,
    _resolve_acting_user,
    count_inference_anchors,
    count_training_anchors,
    score_via_sandbox,
    validate_runnable_feature_sql,
)
from products.autoresearch.backend.models import AutoresearchModel, AutoresearchPipeline, AutoresearchRun
from products.autoresearch.backend.query import HogQLResult, run_hogql
from products.autoresearch.backend.training.recipe_validation import (
    RecipeValidationError,
    validate_model_class,
    validate_unique_distinct_ids,
)

logger = structlog.get_logger(__name__)

EVENT_SOURCE = "autoresearch_inference"


class InferenceRunError(Exception):
    """Raised when an inference run must fail (and be retried) rather than complete with wrong output."""


_RESERVED_COLS = frozenset({"distinct_id", _LABEL_COL, _FOLD_COL})


# Namespace for deterministic prediction event UUIDs, so a retried scoring activity
# re-emits the same UUID per (pipeline, model, date, person) instead of a duplicate.
_PREDICTION_UUID_NAMESPACE = uuid.UUID("6f9a4a24-0e5c-4a5a-9d0e-2f6a0f0b1c3d")


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


def run_inference_for_pipeline(
    pipeline: AutoresearchPipeline,
    model: AutoresearchModel,
    prediction_date: date | None = None,
    user: User | None = None,
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
    """
    window = ScoringWindow.for_date(prediction_date)
    run = AutoresearchRun.objects.create(
        pipeline=pipeline,
        model=model,
        run_type=AutoresearchRun.RunType.INFERENCE,
        status=AutoresearchRun.Status.RUNNING,
        started_at=django_timezone.now(),
    )

    try:
        team = pipeline.team
        acting_user = _acting_user(team=team, pipeline=pipeline, user=user)
        scored = score_population(team=team, pipeline=pipeline, model=model, window=window, user=acting_user)
        emitted = _emit_predictions(
            team=team, pipeline=pipeline, model=model, scored=scored, window=window, user=acting_user
        )

        run.status = AutoresearchRun.Status.COMPLETED
        run.rows_scored = emitted.rows_emitted
        run.metrics = {
            "score_distribution": emitted.score_distribution,
            "stub": bool((model.model_recipe or {}).get("stub", False)),
            "sandbox": bool(model.artifact_prefix),
            "holdout_auc": scored.holdout_auc,
        }
        run.completed_at = django_timezone.now()
        run.save(update_fields=["status", "rows_scored", "metrics", "completed_at"])

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
        )
        return run

    except Exception as exc:
        run.status = AutoresearchRun.Status.FAILED
        run.error = str(exc)[:2000]
        run.completed_at = django_timezone.now()
        run.save(update_fields=["status", "error", "completed_at"])
        logger.exception("autoresearch_inference_failed", pipeline_id=str(pipeline.pk))
        raise


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
    """
    _check_prediction_date(team=team, pipeline=pipeline, window=window)
    acting_user = _acting_user(team=team, pipeline=pipeline, user=user)
    cutoff_ts = window.cutoff_ts

    if model.artifact_prefix:
        result = score_via_sandbox(team=team, pipeline=pipeline, model=model, cutoff_ts=cutoff_ts, user=acting_user)
        return ScoredPopulation(rows=result.scored_rows, holdout_auc=result.holdout_auc)

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
        rows = _fetch_stub_feature_rows(team=team, pipeline=pipeline, recipe=recipe, user=acting_user)
        return ScoredPopulation(rows=_score_rows(rows), holdout_auc=model.holdout_score)

    feature_sql = str(recipe.get("feature_sql") or "")
    try:
        validate_runnable_feature_sql(feature_sql, source="Champion recipe feature_sql")
    except SandboxInferenceError as exc:
        raise InferenceRunError(str(exc)) from exc
    return _score_via_anchors(team=team, pipeline=pipeline, recipe=recipe, cutoff_ts=cutoff_ts, user=acting_user)


def _emit_predictions(
    *,
    team: Team,
    pipeline: AutoresearchPipeline,
    model: AutoresearchModel,
    scored: ScoredPopulation,
    window: ScoringWindow,
    user: User,
) -> _EmitResult:
    """
    Send one prediction event per scored row in one batch. Any failed event fails the run:
    the event UUIDs are deterministic, so the retry re-sends every row and ingestion keeps
    one copy, whereas completing with a partial batch would advance the cadence past the
    people who never received their prediction or output property.
    """
    if not scored.rows:
        logger.warning("autoresearch_no_scored_rows", pipeline_id=str(pipeline.pk), team_id=team.pk)
        return _EmitResult(rows_emitted=0, score_distribution={})

    is_backfill = window.is_backfill
    prediction_date_str = window.prediction_date.isoformat()
    emit_timestamp = window.emit_timestamp

    _require_still_champion(model)
    # Live runs attach each prediction to the real person: a real distinct_id, a processed
    # person profile, and a $set of the output property. Backfills stay person-less (they
    # exist for online validation, which keys on $autoresearch_person_id) so a past-dated
    # $set cannot clobber a live score.
    distinct_id_by_person = (
        {}
        if is_backfill
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
            json.dumps({k: v for k, v in row.items() if k != "p_y"}, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]
        props: dict[str, Any] = {
            "$autoresearch_pipeline_id": str(pipeline.pk),
            "$autoresearch_model_id": str(model.pk),
            "$autoresearch_model_role": model.role,
            "$autoresearch_target_event": pipeline.target_event,
            "$autoresearch_horizon_days": pipeline.horizon_days,
            "$autoresearch_p_y": row["p_y"],
            "$autoresearch_prediction_date": prediction_date_str,
            "$autoresearch_features_hash": features_hash,
            "$autoresearch_person_id": person_id,
        }
        if attach_to_person and output_property:
            props["$set"] = {output_property: row["p_y"]}
        events.append(
            {
                "event": PREDICTION_EVENT_NAME,
                "distinct_id": real_distinct_id or person_id,
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
            process_person_profile=not is_backfill,
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
        raise InferenceRunError(
            f"Prediction events were not all accepted ({len(result.dropped)} dropped, "
            f"{len(result.retried)} exhausted retries, {len(result.unaccounted)} unaccounted, "
            f"{len(result.warnings)} stored with a warning{f' e.g. {sample!r}' if sample else ''}"
            f"{', ' + str(result.error.get('error')) if result.error else ''}); failing the run so it is retried"
        )

    return _EmitResult(
        rows_emitted=len(events), score_distribution=_summarize_scores([row["p_y"] for row in scored.rows])
    )


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


# ── Queries ────────────────────────────────────────────────────────────────────────


def _query(*, team: Team, sql: str, values: dict[str, Any], user: User | None, what: str) -> HogQLResult:
    """
    Run a person-keyed query as the acting user, fresh, bounded at ``_MATERIALIZE_ROW_LIMIT``.

    HogQL caps a bare SELECT at 100 rows without an error, so every query here carries an
    explicit bound, and a result that fills it is treated as truncated: completing would
    advance the cadence past the people beyond the cap. The persons-on-events modifiers
    are what make ``person.is_identified`` resolve, and the always-calculate mode stops a
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
    *, team: Team, pipeline: AutoresearchPipeline, recipe: dict[str, Any], user: User
) -> list[dict[str, Any]]:
    """
    Run a stub recipe's feature SQL restricted to the inference population.

    The stub's SQL is templated in ``training/stub.py``, evaluates at now(), and carries
    no ``{anchors}``, so it does not go through the anchors builders. The population is
    applied inside the query rather than on the returned rows, so the row bound measures
    the population being scored and not every person on the team. The rows are checked
    against the population count, as the anchored paths check theirs against the anchors,
    because stub SQL that drops a member leaves every returned row looking valid.
    """
    feature_sql = str(recipe.get("feature_sql") or "")
    if not feature_sql:
        logger.warning("autoresearch_empty_feature_sql", pipeline_id=str(pipeline.pk))
        return []
    lookback_days = _feature_lookback_days(pipeline)
    feature_sql = feature_sql.replace("{lookback_days}", str(lookback_days)).rstrip().rstrip(";")
    population = _population_query(
        population=pipeline.inference_population,
        lookback_days=lookback_days,
        target_event=pipeline.target_event,
        target_definition=pipeline.target_definition,
        team=team,
    )
    sql, values = feature_sql, {}
    if population is not None:
        sql = f"SELECT * FROM ({feature_sql}) AS f WHERE f.distinct_id IN ({population.sql})"
        values = population.values
    rows = _person_rows(_query(team=team, sql=sql, values=values, user=user, what="Feature"))
    expected = _count_population(team=team, population=population, user=user) if population is not None else None
    _require_one_row_per_person(rows, source="stub feature_sql", expected_count=expected)
    return rows


@frozen
class _PopulationQuery:
    sql: str
    values: dict[str, Any]


def _population_query(
    *,
    population: dict[str, Any] | None,
    lookback_days: int,
    target_event: str = "",
    target_definition: dict[str, Any] | None = None,
    team: Team | None = None,
) -> _PopulationQuery | None:
    """
    A ``SELECT DISTINCT person_id`` for the people in the inference population, restricted
    to identified users under the v1 scope. None only when nothing restricts the population.
    A configured filter that cannot be compiled raises, because widening to everyone is
    the failure being prevented.
    """
    properties = (population or {}).get("properties", [])
    parts, values = _build_population_conditions(properties)
    target_cond, target_values = _target_condition_for(
        population, target_event=target_event, target_definition=target_definition, team=team
    )
    compiled_kind = _build_population_kind_conditions(population, target_cond=target_cond)
    parts.extend(compiled_kind.where_parts)
    values.update(target_values)
    values.update(compiled_kind.values)
    identified_clause = _identified_users_and_clause()

    if not parts and not identified_clause:
        return None

    values["lookback"] = lookback_days
    # The upper bound keeps a future-dated or imported event from making someone eligible today.
    where_clause = (
        f"timestamp >= now() - toIntervalDay({{lookback}}) AND timestamp < now(){_own_events_excluded_clause()}"
    )
    if parts:
        where_clause += " AND " + " AND ".join(parts)
    where_clause += identified_clause
    return _PopulationQuery(sql=f"SELECT DISTINCT person_id FROM events WHERE {where_clause}", values=values)


def _count_population(*, team: Team, population: _PopulationQuery, user: User) -> int:
    result = _query(
        team=team,
        sql=f"SELECT count() FROM ({population.sql})",
        values=population.values,
        user=user,
        what="Population count",
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
    training_rows = _fetch_training_rows(team=team, pipeline=pipeline, feature_sql=feature_sql, user=user)
    inference_rows = _fetch_inference_rows(
        team=team, pipeline=pipeline, feature_sql=feature_sql, cutoff_ts=cutoff_ts, user=user
    )
    if not inference_rows:
        logger.warning("autoresearch_no_inference_rows", pipeline_id=str(pipeline.pk))
        return ScoredPopulation(rows=[], holdout_auc=None)
    if not training_rows:
        logger.warning("autoresearch_no_training_rows_anchored_fallback_stub", pipeline_id=str(pipeline.pk))
        return ScoredPopulation(rows=_score_rows(inference_rows), holdout_auc=None)
    return _fit_on_training_predict_on_inference(
        training_rows=training_rows, inference_rows=inference_rows, recipe=recipe, pipeline_id=str(pipeline.pk)
    )


def _fetch_training_rows(
    *, team: Team, pipeline: AutoresearchPipeline, feature_sql: str, user: User
) -> list[dict[str, Any]]:
    """The recipe's feature SQL against the labeled anchors: one row per person with ``__label`` and ``__fold``."""
    sql, values = build_training_features_sql(
        feature_sql=feature_sql,
        target_event=pipeline.target_event,
        target_definition=pipeline.target_definition,
        team=team,
        horizon_days=pipeline.horizon_days,
        lookback_days=pipeline.training_lookback_days,
        training_population=pipeline.training_population,
    )
    rows = _person_rows(_query(team=team, sql=sql, values=values, user=user, what="Training features"))
    try:
        expected = count_training_anchors(team=team, pipeline=pipeline, user=user)
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
    return rows


def _fetch_inference_rows(
    *, team: Team, pipeline: AutoresearchPipeline, feature_sql: str, cutoff_ts: int | None, user: User
) -> list[dict[str, Any]]:
    """
    The recipe's feature SQL against the inference anchors: one row per eligible person.

    The row count is checked against the anchor count, because feature SQL that inner
    joins or filters a joined table drops people without any row looking wrong. The training
    rows get the same check against the labeled anchors.
    """
    sql, values = build_inference_features_sql(
        feature_sql=feature_sql,
        lookback_days=_feature_lookback_days(pipeline),
        inference_population=pipeline.inference_population,
        cutoff_ts=cutoff_ts,
        target_event=pipeline.target_event,
        target_definition=pipeline.target_definition,
        team=team,
    )
    rows = _person_rows(_query(team=team, sql=sql, values=values, user=user, what="Inference features"))
    try:
        expected = count_inference_anchors(team=team, pipeline=pipeline, cutoff_ts=cutoff_ts, user=user)
    except SandboxInferenceError as exc:
        raise InferenceRunError(str(exc)) from exc
    _require_one_row_per_person(rows, source="inference feature_sql", expected_count=expected)
    return rows


def _fit_on_training_predict_on_inference(
    *,
    training_rows: list[dict[str, Any]],
    inference_rows: list[dict[str, Any]],
    recipe: dict[str, Any],
    pipeline_id: str,
) -> ScoredPopulation:
    """
    Fit the recipe's allowlisted sklearn class on the training folds, score the holdout
    fold for the AUC the run records, and predict on the inference rows. A fit or predict
    failure falls back to the stub formula so the cadence still emits.
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
    return ScoredPopulation(rows=scored, holdout_auc=holdout_auc)


def _stable_seed(pipeline_id: str) -> int:
    return int(hashlib.sha256(pipeline_id.encode()).hexdigest()[:8], 16)


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
    if "random_state" in accepted:
        params.setdefault("random_state", seed)
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
