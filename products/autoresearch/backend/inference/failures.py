"""Classify a failed scoring run, and tell when a model's runs show it cannot score."""

from collections import defaultdict
from collections.abc import Iterable, Iterator
from datetime import date, timedelta
from enum import StrEnum
from uuid import UUID

from django.db.models import F, Q, QuerySet, Window
from django.db.models.functions import RowNumber
from django.utils import timezone as django_timezone

import structlog

from posthog.dataclasses import frozen
from posthog.errors import QueryErrorCategory, classify_query_error

from products.autoresearch.backend.inference.sandbox import ModelLoadError
from products.autoresearch.backend.models import AutoresearchModel, AutoresearchPipeline, AutoresearchRun

logger = structlog.get_logger(__name__)

# The inference workflow's execution timeout. It covers both activity attempts plus their backoff,
# so an inference run still RUNNING after this long lost its worker and no attempt can close it.
INFERENCE_WORKFLOW_TIMEOUT = timedelta(hours=5)


class FailureKind(StrEnum):
    LIMIT_EXCEEDED = "limit_exceeded"
    QUERY_FAILED = "query_failed"
    MODEL_LOAD_FAILED = "model_load_failed"
    # Transport, capture, cluster capacity, and every error this module does not recognize.
    OTHER = "other"


# These kinds fail again on the next run with the same champion. The other kinds can pass on a retry.
REPEATABLE_FAILURE_KINDS = frozenset(
    {FailureKind.LIMIT_EXCEEDED, FailureKind.QUERY_FAILED, FailureKind.MODEL_LOAD_FAILED}
)

# The number of consecutive scheduled scoring days with a repeatable failure that make a champion unscorable.
UNSCORABLE_AFTER_FAILED_DAYS = 2
# The scheduled runs one check reads. An activity retry adds a second run for the same day.
_RUNS_TO_SCAN = 20


def _exception_chain(exc: BaseException) -> Iterator[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__


def classify_failure(exc: BaseException) -> FailureKind:
    """The kind of a scoring failure. The scoring code wraps query errors, so this reads the whole cause chain."""
    for error in _exception_chain(exc):
        if isinstance(error, ModelLoadError):
            return FailureKind.MODEL_LOAD_FAILED
        if not isinstance(error, Exception):
            continue
        category = classify_query_error(error)
        if category == QueryErrorCategory.QUERY_PERFORMANCE_ERROR:
            return FailureKind.LIMIT_EXCEEDED
        if category == QueryErrorCategory.USER_ERROR:
            return FailureKind.QUERY_FAILED
        if category != QueryErrorCategory.ERROR:
            # The wrapper decided first: cluster memory pressure keeps a raw MEMORY_LIMIT_EXCEEDED as its cause.
            return FailureKind.OTHER
    return FailureKind.OTHER


@frozen
class UnscorableChampion:
    failure_kind: str
    onset: date


def _run_date(run: AutoresearchRun) -> date:
    prediction_date = (run.metrics or {}).get("prediction_date")
    return date.fromisoformat(prediction_date) if prediction_date else run.created_at.date()


def find_unscorable_champion(champion: AutoresearchModel | None) -> UnscorableChampion | None:
    """
    Return the failure when the champion's scheduled runs failed with a repeatable kind on the
    last ``UNSCORABLE_AFTER_FAILED_DAYS`` scoring days, with no success after the first of them.

    Manual runs do not count, because a person can start them many times in one day. Failures of
    other kinds do not count, and do not break the streak either. The onset is the prediction date
    of the oldest repeatable failure after the last success.
    """
    if champion is None:
        return None
    runs = _scoring_runs(champion.team_id, champion.pipeline_id, Q(scheduled=True)).filter(model=champion)
    failed_days = _repeatable_failure_days(runs.order_by("-created_at")[:_RUNS_TO_SCAN])
    if len(failed_days) < UNSCORABLE_AFTER_FAILED_DAYS:
        return None
    newest_day = max(failed_days)
    return UnscorableChampion(failure_kind=failed_days[newest_day], onset=min(failed_days))


def models_failing_repeatably_in_shadow(pipeline: AutoresearchPipeline, model_ids: Iterable[UUID]) -> set[UUID]:
    """
    Return the shadow candidates that cannot score. The rule is the one ``find_unscorable_champion``
    applies, read over each model's shadow runs and the scheduled runs it had as a champion.
    One query reads the newest ``_RUNS_TO_SCAN`` runs of every model.
    """
    model_ids = set(model_ids)
    if not model_ids:
        return set()
    runs = (
        _scoring_runs(pipeline.team_id, pipeline.pk, Q(scheduled=True) | Q(metrics__shadow=True))
        .filter(model_id__in=model_ids)
        .annotate(recency=Window(RowNumber(), partition_by=F("model_id"), order_by=F("created_at").desc()))
        .filter(recency__lte=_RUNS_TO_SCAN)
        .order_by("model_id", "-created_at")
    )
    runs_by_model: dict[UUID, list[AutoresearchRun]] = defaultdict(list)
    for run in runs:
        if run.model_id is not None:
            runs_by_model[run.model_id].append(run)
    return {
        model_id
        for model_id, model_runs in runs_by_model.items()
        if len(_repeatable_failure_days(model_runs)) >= UNSCORABLE_AFTER_FAILED_DAYS
    }


def _scoring_runs(team_id: int, pipeline_id: UUID, runs_filter: Q) -> QuerySet[AutoresearchRun]:
    return AutoresearchRun.objects.for_team(team_id).filter(
        runs_filter,
        pipeline_id=pipeline_id,
        run_type=AutoresearchRun.RunType.INFERENCE,
        status__in=(AutoresearchRun.Status.COMPLETED, AutoresearchRun.Status.FAILED),
    )


def _repeatable_failure_days(newest_first: Iterable[AutoresearchRun]) -> dict[date, str]:
    """The newest repeatable failure kind of each scoring day after the last completed run."""
    failed_days: dict[date, str] = {}
    for run in newest_first:
        if run.status == AutoresearchRun.Status.COMPLETED:
            break
        kind = (run.metrics or {}).get("failure_kind")
        if kind in REPEATABLE_FAILURE_KINDS:
            # The newest failure of a day wins, so the kind reported is the latest one.
            failed_days.setdefault(_run_date(run), kind)
    return failed_days


def fail_stale_inference_runs() -> int:
    """
    Fail every inference run, across all teams, that is still RUNNING after ``INFERENCE_WORKFLOW_TIMEOUT``.

    A lost worker, a heartbeat timeout, or a cancellation ends the attempt before the scoring code
    records an outcome. The kind is ``other``, so ``find_unscorable_champion`` does not count the run.
    """
    now = django_timezone.now()
    stale = AutoresearchRun.objects.unscoped().filter(
        run_type=AutoresearchRun.RunType.INFERENCE,
        status=AutoresearchRun.Status.RUNNING,
        started_at__lt=now - INFERENCE_WORKFLOW_TIMEOUT,
    )
    failed = 0
    for run in stale:
        run.status = AutoresearchRun.Status.FAILED
        run.error = "Scoring stopped without a result. The worker was lost or the attempt timed out."
        run.metrics["failure_kind"] = FailureKind.OTHER
        run.completed_at = now
        run.save(update_fields=["status", "error", "metrics", "completed_at"])
        failed += 1
    if failed:
        logger.warning("autoresearch_stale_inference_runs_failed", count=failed)
    return failed
