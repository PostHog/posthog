"""Classify a failed scoring run, and tell when the champion's scheduled runs show it cannot score."""

from collections.abc import Iterator
from datetime import date, timedelta
from enum import StrEnum

from django.utils import timezone as django_timezone

import structlog

from posthog.dataclasses import frozen
from posthog.errors import QueryErrorCategory, classify_query_error

from products.autoresearch.backend.inference.sandbox import ModelLoadError
from products.autoresearch.backend.models import AutoresearchModel, AutoresearchRun

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
    runs = (
        AutoresearchRun.objects.for_team(champion.team_id)
        .filter(
            pipeline_id=champion.pipeline_id,
            model=champion,
            run_type=AutoresearchRun.RunType.INFERENCE,
            scheduled=True,
            status__in=(AutoresearchRun.Status.COMPLETED, AutoresearchRun.Status.FAILED),
        )
        .order_by("-created_at")[:_RUNS_TO_SCAN]
    )
    failed_days: dict[date, str] = {}
    for run in runs:
        if run.status == AutoresearchRun.Status.COMPLETED:
            break
        kind = (run.metrics or {}).get("failure_kind")
        if kind in REPEATABLE_FAILURE_KINDS:
            # The newest failure of a day wins, so the kind reported is the latest one.
            failed_days.setdefault(_run_date(run), kind)
    if len(failed_days) < UNSCORABLE_AFTER_FAILED_DAYS:
        return None
    newest_day = max(failed_days)
    return UnscorableChampion(failure_kind=failed_days[newest_day], onset=min(failed_days))


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
