import time
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, Optional

from django.conf import settings
from django.db import InterfaceError, OperationalError
from django.db.models import Case, DurationField, ExpressionWrapper, F, Q, QuerySet, When
from django.utils import timezone

import grpc
import structlog
import posthoganalytics
from celery import Task, chain, shared_task
from celery.exceptions import Retry, SoftTimeLimitExceeded
from celery.utils.time import get_exponential_backoff_interval
from dateutil.relativedelta import relativedelta
from prometheus_client import Counter, Gauge, Histogram

from posthog.hogql.errors import ExposedHogQLError

from posthog.api.monitoring import Feature
from posthog.clickhouse import query_tagging
from posthog.clickhouse.query_tagging import QueryTags, update_tags
from posthog.errors import CH_TRANSIENT_ERRORS, CHQueryErrorQueryWasCancelled
from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.personhog_client.interceptor import is_transient_rpc_error
from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

from products.cohorts.backend.backfill.finalize import finalize_backfill_runs
from products.cohorts.backend.backfill.observe import publish_backfill_run_gauges
from products.cohorts.backend.backfill.runs import (
    BackfillRefusalReason,
    attempt_backfill_run_for_cohort,
    attempt_person_backfill_run_for_cohort,
    check_person_run_preconditions,
    check_run_preconditions,
)
from products.cohorts.backend.models.backfill import CohortBackfillKind
from products.cohorts.backend.models.calculation_history import CohortCalculationHistory
from products.cohorts.backend.models.cohort import Cohort, CohortOrEmpty, ImportResolution
from products.cohorts.backend.models.util import (
    COHORT_STATS_COLLECTION_DELAY_SECONDS,
    get_all_cohort_dependencies,
    get_all_cohort_dependents,
    get_clickhouse_query_stats,
    save_recovery_bookkeeping,
    sort_cohorts_topologically,
)
from products.cohorts.backend.realtime_teams import is_cohort_backfill_trigger_team

COHORT_RECALCULATION_MAX_RETRIES = 6
STATIC_POPULATION_MAX_RETRIES = 6
STATIC_POPULATION_RETRY_BACKOFF_SECONDS = 60
STATIC_POPULATION_RETRY_BACKOFF_MAX_SECONDS = 1800
STATIC_POPULATION_SOFT_TIME_LIMIT_SECONDS = 4 * 60 * 60

# The RetryInterceptor set plus RESOURCE_EXHAUSTED and INTERNAL, which an in-process retry must not
# hammer but a task backoff of minutes is the right answer to. Personhog sheds load with
# RESOURCE_EXHAUSTED and maps every Postgres query error (deadlock, lock or statement timeout, a
# read-only primary after a failover) to INTERNAL. UNKNOWN stays in because an HTTP/2 stream reset
# ("Stream removed") surfaces as UNKNOWN, and that is the outage shape that leaves a static cohort
# half-synced.
STATIC_POPULATION_RETRYABLE_RPC_CODES = frozenset(
    {
        grpc.StatusCode.UNAVAILABLE,
        grpc.StatusCode.DEADLINE_EXCEEDED,
        grpc.StatusCode.ABORTED,
        grpc.StatusCode.UNKNOWN,
        grpc.StatusCode.RESOURCE_EXHAUSTED,
        grpc.StatusCode.INTERNAL,
    }
)

# CH_TRANSIENT_ERRORS plus the Postgres errors the cohort tasks' own ORM statements can hit (e.g. a
# connection-pooler blip before the ClickHouse work even starts, or between two personhog batches).
# Recalculation and static population are background jobs nobody cancels by hand, so a cancelled
# query here means a deploy, not an operator shedding load - which is why they opt into 394 where
# the shared tuple leaves it out.
COHORT_RECALCULATION_TRANSIENT_ERRORS = (
    *CH_TRANSIENT_ERRORS,
    CHQueryErrorQueryWasCancelled,
    OperationalError,
    InterfaceError,
)

# The recalculation set plus the soft time limit, which static population opts into because it can
# resume: the ClickHouse insert excludes the actors it already wrote and personhog ignores existing
# membership. Recording the limit as terminal would strand a half-written cohort instead.
STATIC_POPULATION_TRANSIENT_ERRORS = (*COHORT_RECALCULATION_TRANSIENT_ERRORS, SoftTimeLimitExceeded)

COHORT_RECALCULATIONS_BACKLOG_GAUGE = Gauge(
    "cohort_recalculations_backlog",
    "Number of cohorts that are waiting to be calculated",
    multiprocess_mode="max",
)

COHORT_STALENESS_HOURS_GAUGE = Gauge(
    "cohort_staleness_hours",
    "Cohort's count of hours since last calculation",
    multiprocess_mode="max",
)

COHORTS_STALE_COUNT_GAUGE = Gauge(
    "cohorts_stale",
    "Number of cohorts that haven't been calculated in more than X hours",
    ["hours"],
    multiprocess_mode="max",
)

COHORTS_TOTAL_GAUGE = Gauge(
    "cohorts_total",
    "Total number of eligible cohorts for recalculation (non-static, non-deleted)",
    multiprocess_mode="max",
)

COHORT_STUCK_COUNT_GAUGE = Gauge(
    # TODO: rename to cohorts_stuck because this is a gauge not a counter
    "cohort_stuck_count",
    "Number of cohorts that are stuck calculating for more than 1 hour",
    multiprocess_mode="max",
)

COHORT_DEPENDENCY_CALCULATION_FAILURES_COUNTER = Counter(
    "cohort_dependency_calculation_failures_total",
    "Number of times dependent cohort calculations have failed",
)

COHORT_STUCK_RESETS_COUNTER = Counter("cohort_stuck_resets_total", "Number of stuck cohorts that have been reset")

COHORT_MAXED_ERRORS_GAUGE = Gauge(
    "cohort_maxed_errors",
    "Number of cohorts that have reached the maximum number of errors",
    multiprocess_mode="max",
)

COHORT_CALCULATION_STARTED_COUNTER = Counter(
    "cohort_calculation_started_total",
    "Cohort calculations started (tracks all attempts including those that may OOM)",
)

COHORT_CALCULATION_COMPLETED_COUNTER = Counter(
    "cohort_calculation_completed_total",
    "Cohort calculations that completed (either success or caught error)",
    ["status"],  # labels: "success", "error"
)

COHORT_CALCULATION_FAILURES_COUNTER = Counter(
    "cohort_calculation_failures_total",
    "Cohort calculation failures by type",
    ["failure_type"],  # labels: "exception", "clickhouse_error", etc.
)

COHORT_CALCULATION_DURATION_SECONDS = Histogram(
    "cohort_calculation_duration_seconds",
    "Duration of cohort calculations in seconds",
    ["status"],  # labels: "success", "error"
    buckets=[1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600],
)

COHORT_STATIC_POPULATION_RETRIES_COUNTER = Counter(
    "cohort_static_population_retries_total",
    "Static cohort population attempts that failed transiently and scheduled a task retry",
    ["task", "error_type"],
)

logger = structlog.get_logger(__name__)

MAX_AGE_MINUTES = 15
MAX_ERRORS_CALCULATING = 20
MAX_STUCK_COHORTS_TO_RESET = 3
MAX_STUCK_STATIC_COHORTS_TO_SCAN = MAX_STUCK_COHORTS_TO_RESET * 10


def static_cohort_has_supported_population_source(cohort: Cohort) -> bool:
    from products.cohorts.backend.models.util import cohort_filters_have_values

    return bool(cohort.query or cohort_filters_have_values(cohort.filters))


def get_cohort_calculation_candidates_queryset() -> QuerySet:
    return Cohort.objects.filter(
        Q(last_calculation__lte=timezone.now() - relativedelta(minutes=MAX_AGE_MINUTES))
        | Q(last_calculation__isnull=True),
        deleted=False,
        is_calculating=False,
        errors_calculating__lte=MAX_ERRORS_CALCULATING,
    ).exclude(is_static=True)


def get_stuck_cohort_calculation_candidates_queryset() -> QuerySet:
    return Cohort.objects.filter(
        is_calculating=True,
        last_calculation__lte=timezone.now() - relativedelta(hours=1),
        last_calculation__isnull=False,
        deleted=False,
    ).exclude(is_static=True)


def get_stuck_static_cohort_candidates_queryset() -> QuerySet:
    """
    Static cohorts that are stuck in is_calculating state.
    These are never picked up by the normal reset_stuck_cohorts because they are excluded.
    A static cohort is stuck if:
    - is_calculating=True AND (last_calculation is null AND created > 1 hour ago)
      (initial population never completed)
    - OR is_calculating=True AND last_calculation > 1 hour ago
      (re-population never completed)
    - AND it has not errored within the last hour. A population task stamps last_error_at when
      it schedules a retry, and reset_stuck_cohorts stamps it when it re-dispatches, so a recent
      error means the run is alive and resetting it would dispatch a duplicate population.
    """
    one_hour_ago = timezone.now() - relativedelta(hours=1)
    return (
        Cohort.objects.filter(
            is_static=True,
            is_calculating=True,
            deleted=False,
            errors_calculating__lt=MAX_ERRORS_CALCULATING,
        )
        .filter(
            Q(last_calculation__isnull=True, created_at__lte=one_hour_ago)
            | Q(last_calculation__lte=one_hour_ago, last_calculation__isnull=False)
        )
        .filter(Q(last_error_at__isnull=True) | Q(last_error_at__lte=one_hour_ago))
        .filter(
            # Only fetch cohorts that have a retriggerable population source
            # (HogQL query or filter criteria). Excludes CSV-upload cohorts
            # that would always be discarded by the retry logic.
            # This may match old static cohorts with stale filter data that
            # predate criteria-based creation; those are caught and skipped
            # by static_cohort_has_supported_population_source in the loop body.
            Q(query__isnull=False)
            | (Q(filters__has_key="properties") & ~Q(filters__properties={}) & ~Q(filters__properties__values=[]))
        )
    )


def reset_stuck_cohorts() -> None:
    # A stuck cohort is a cohort that has is_calculating set to true but the query/task failed and
    # the field was never set back to false. These cohorts will never get pick up again for
    # recalculation by our periodic celery task and need to be reset.
    # After resetting, these cohorts will be picked up by the next cohort calculation but we need to limit the number
    # of stuck cohorts that are reset at once to avoid overwhelming ClickHouse with too many
    # calculations for stuck cohorts
    reset_cohort_ids = []
    for cohort in get_stuck_cohort_calculation_candidates_queryset().order_by(
        F("last_calculation").asc(nulls_first=True)
    )[0:MAX_STUCK_COHORTS_TO_RESET]:
        cohort.is_calculating = False

        # A stuck cohort never has its errors_calculating incremented, so we need to do it here
        # This will ensure that we don't keep retrying cohorts that will never calculate successfully
        cohort.errors_calculating = F("errors_calculating") + 1
        cohort.last_error_at = timezone.now()
        cohort.save(update_fields=["is_calculating", "errors_calculating", "last_error_at"])
        reset_cohort_ids.append(cohort.pk)

    COHORT_STUCK_RESETS_COUNTER.inc(len(reset_cohort_ids))
    logger.warning("reset_stuck_cohorts", cohort_ids=reset_cohort_ids, count=len(reset_cohort_ids))

    # Also reset stuck static cohorts and re-trigger their population task.
    # Static cohorts are excluded from the normal reset because they don't get periodic
    # recalculation — they need the one-time insert_cohort_from_query task re-dispatched.
    reset_static_cohort_ids = []
    retriggered_static_cohort_ids = []
    for cohort in get_stuck_static_cohort_candidates_queryset().order_by(F("created_at").asc())[
        0:MAX_STUCK_STATIC_COHORTS_TO_SCAN
    ]:
        cohort.is_calculating = False
        cohort.errors_calculating = F("errors_calculating") + 1
        cohort.last_error_at = timezone.now()
        cohort.save(update_fields=["is_calculating", "errors_calculating", "last_error_at"])
        reset_static_cohort_ids.append(cohort.pk)

        if not static_cohort_has_supported_population_source(cohort):
            logger.warning(
                "reset_unsupported_stuck_static_cohort",
                cohort_id=cohort.pk,
                team_id=cohort.team_id,
            )
            continue

        # Re-trigger the population task for static cohorts whose membership
        # can be reconstructed from persisted data.
        # Refresh from DB to get the actual errors_calculating integer value after the F() expression save.
        cohort.refresh_from_db(fields=["errors_calculating"])
        if cohort.errors_calculating <= MAX_ERRORS_CALCULATING:
            logger.warning(
                "retrigger_stuck_static_cohort",
                cohort_id=cohort.pk,
                team_id=cohort.team_id,
                errors_calculating=cohort.errors_calculating,
            )
            if cohort.query:
                insert_cohort_from_query.delay(cohort.pk, cohort.team_id)
            else:
                insert_cohort_from_filters.delay(cohort.pk, cohort.team_id)
            retriggered_static_cohort_ids.append(cohort.pk)

        if len(retriggered_static_cohort_ids) >= MAX_STUCK_COHORTS_TO_RESET:
            break

    if reset_static_cohort_ids:
        COHORT_STUCK_RESETS_COUNTER.inc(len(reset_static_cohort_ids))
        logger.warning(
            "reset_stuck_static_cohorts",
            cohort_ids=reset_static_cohort_ids,
            count=len(reset_static_cohort_ids),
        )


def update_cohort_metrics() -> None:
    now = timezone.now()
    base_queryset = Cohort.objects.filter(
        Q(last_calculation__isnull=False),
        deleted=False,
        is_calculating=False,
        errors_calculating__lte=MAX_ERRORS_CALCULATING,
    ).exclude(is_static=True)

    COHORTS_TOTAL_GAUGE.set(base_queryset.count())

    for hours in [24, 36, 48]:
        stale_count = base_queryset.filter(last_calculation__lte=now - relativedelta(hours=hours)).count()
        COHORTS_STALE_COUNT_GAUGE.labels(hours=str(hours)).set(stale_count)

    stuck_count = (
        Cohort.objects.filter(
            is_calculating=True,
            last_calculation__lte=now - relativedelta(hours=1),
            last_calculation__isnull=False,
            deleted=False,
        )
        .exclude(is_static=True)
        .count()
    )

    COHORT_STUCK_COUNT_GAUGE.set(stuck_count)

    maxed_error_count = (
        Cohort.objects.filter(deleted=False, errors_calculating__gt=MAX_ERRORS_CALCULATING)
        .exclude(is_static=True)
        .count()
    )
    COHORT_MAXED_ERRORS_GAUGE.set(maxed_error_count)


def enqueue_cohorts_to_calculate(parallel_count: int) -> None:
    """
    Calculates maximum N cohorts in parallel.

    Args:
        parallel_count: Maximum number of cohorts to calculate in parallel.
    """
    # Exponential backoff, with the first one starting after 30 minutes
    backoff_duration = ExpressionWrapper(
        timedelta(minutes=30) * (2 ** F("errors_calculating")),  # type: ignore
        output_field=DurationField(),
    )

    cohort_ids = []
    for cohort in (
        get_cohort_calculation_candidates_queryset()
        .filter(
            Q(last_error_at__lte=timezone.now() - backoff_duration)  # type: ignore
            | Q(last_error_at__isnull=True)  # backwards compatability cohorts before last_error_at was introduced
        )
        .order_by(F("last_calculation").asc(nulls_first=True))[0:parallel_count]
    ):
        cohort = Cohort.objects.filter(pk=cohort.pk).get()
        try:
            increment_version_and_enqueue_calculate_cohort(cohort, initiating_user=None)
            cohort_ids.append(cohort.pk)
        except Exception as e:
            logger.exception(
                "enqueued_cohort_calculation_error",
                cohort_id=cohort.pk,
                team_id=cohort.team_id,
                error=str(e),
            )
            cohort.errors_calculating = F("errors_calculating") + 1
            cohort.last_error_at = timezone.now()
            cohort.save(update_fields=["errors_calculating", "last_error_at"])
            capture_exception(
                error=e,
                additional_properties={
                    "cohort_id": cohort.pk,
                    "team_id": cohort.team_id,
                },
            )
            # Skip this cohort and continue with others
            continue

    backlog = get_cohort_calculation_candidates_queryset().count()
    COHORT_RECALCULATIONS_BACKLOG_GAUGE.set(backlog)

    logger.warning(
        "enqueued_cohort_calculation",
        cohort_ids=cohort_ids,
        COHORT_RECALCULATIONS_BACKLOG_GAUGE=backlog,
    )

    try:
        update_cohort_metrics()
    except Exception as e:
        logger.exception("failed_to_update_cohort_metrics", error=str(e))


def increment_version_and_enqueue_calculate_cohort(cohort: Cohort, *, initiating_user: Optional[User]) -> bool:
    """
    Returns False if dependency resolution failed and only `cohort` itself was enqueued instead
    of its full dependency chain, so callers that need to (e.g. the staff recalculate endpoint)
    can tell a caller the request wasn't fully honored. Callers that don't care can ignore it.
    """
    dependent_cohorts = get_all_cohort_dependents(cohort)
    dependency_cohorts = get_all_cohort_dependencies(cohort)
    related_cohorts = dependent_cohorts + dependency_cohorts
    if related_cohorts:
        logger.info(
            "cohort_has_dependencies",
            cohort_id=cohort.id,
            related_cohort_count=len(related_cohorts),
        )

        all_cohort_ids = {dep.id for dep in related_cohorts}
        all_cohort_ids.add(cohort.id)

        # Sort cohorts (dependencies first)
        seen_cohorts_cache: dict[int, CohortOrEmpty] = {dep.id: dep for dep in related_cohorts}
        seen_cohorts_cache[cohort.id] = cohort

        try:
            sorted_cohort_ids = sort_cohorts_topologically(all_cohort_ids, seen_cohorts_cache)
        except Exception as e:
            COHORT_DEPENDENCY_CALCULATION_FAILURES_COUNTER.inc()
            logger.exception("cohort_dependency_resolution_failed", cohort_id=cohort.id, error=str(e))
            capture_exception()
            # Fall back to calculating just this cohort without dependencies
            logger.warning("cohort_fallback_to_single_calculation", cohort_id=cohort.id)
            _enqueue_single_cohort_calculation(cohort, initiating_user)
            return False

        # Create a chain of tasks to ensure sequential execution.
        # Non-first tasks get a 2s countdown to mitigate ClickHouse replica lag:
        # the preceding cohort's new rows may not have replicated yet. See #47618.
        task_chain: list = []
        prepared_cohort_ids: list[int] = []
        for cohort_id in sorted_cohort_ids:
            current_cohort = seen_cohorts_cache.get(cohort_id)
            if current_cohort and not current_cohort.is_static:
                _prepare_cohort_for_calculation(current_cohort)
                prepared_cohort_ids.append(current_cohort.id)
                task = calculate_cohort_ch.si(
                    current_cohort.id,
                    current_cohort.pending_version,
                    initiating_user.id if initiating_user else None,
                )
                if len(task_chain) > 0:
                    task = task.set(countdown=2)
                task_chain.append(task)

        if task_chain:
            try:
                chain(*task_chain).apply_async()
            except Exception:
                # apply_async() never actually enqueued anything, but _prepare_cohort_for_calculation
                # already flipped is_calculating on every cohort in the chain. Clear it so they aren't
                # stranded looking "in flight" until the hourly stuck-cohort reset catches them.
                Cohort.objects.filter(id__in=prepared_cohort_ids).update(is_calculating=False)
                raise
    else:
        logger.info("cohort_has_no_dependencies", cohort_id=cohort.id)
        _enqueue_single_cohort_calculation(cohort, initiating_user)

    return True


def _prepare_cohort_for_calculation(cohort: Cohort) -> None:
    """
    Prepare cohort for calculation by incrementing version and setting calculating state.
    When a new calculation is requested, we increment the pending_version which effectively
    supersedes any older calculations - they will complete but won't update the final version.
    """
    cohort.pending_version = Case(When(pending_version__isnull=True, then=1), default=F("pending_version") + 1)
    update_fields = ["pending_version"]

    if not cohort.is_static:
        cohort.is_calculating = True
        update_fields.append("is_calculating")

    cohort.save(update_fields=update_fields)
    cohort.refresh_from_db()


def _enqueue_single_cohort_calculation(cohort: Cohort, initiating_user: Optional[User]) -> None:
    """Helper function to enqueue a single cohort for calculation"""
    _prepare_cohort_for_calculation(cohort)
    try:
        calculate_cohort_ch.delay(
            cohort.id,
            cohort.pending_version,
            initiating_user.id if initiating_user else None,
        )
    except Exception:
        # .delay() never actually enqueued anything, but _prepare_cohort_for_calculation already
        # flipped is_calculating. Clear it so the cohort isn't stranded looking "in flight" until
        # the hourly stuck-cohort reset catches it.
        if not cohort.is_static:
            cohort.is_calculating = False
            cohort.save(update_fields=["is_calculating"])
        raise


@shared_task(
    bind=True,
    ignore_result=True,
    queue=CeleryQueue.LONG_RUNNING.value,
    # Auto-retry for transient ClickHouse and Postgres errors with exponential backoff
    autoretry_for=COHORT_RECALCULATION_TRANSIENT_ERRORS,
    retry_backoff=60,
    retry_backoff_max=1800,
    max_retries=COHORT_RECALCULATION_MAX_RETRIES,
)
@skip_team_scope_audit
def calculate_cohort_ch(
    self: Task, cohort_id: int, pending_version: int, initiating_user_id: Optional[int] = None
) -> None:
    with posthoganalytics.new_context():
        posthoganalytics.tag("feature", Feature.COHORT.value)
        posthoganalytics.tag("cohort_id", cohort_id)

        try:
            cohort: Cohort = Cohort.objects.get(pk=cohort_id)

            # Skip calculation if this version is now obsolete (superseded by newer save)
            if cohort.pending_version and pending_version < cohort.pending_version:
                logger.info(
                    "cohort_calculation_skipped_obsolete",
                    cohort_id=cohort_id,
                    task_version=pending_version,
                    current_pending_version=cohort.pending_version,
                )
                return

            posthoganalytics.tag("team_id", cohort.team_id)

            staleness_hours = 0.0
            if cohort.last_calculation is not None:
                staleness_hours = (timezone.now() - cohort.last_calculation).total_seconds() / 3600
            COHORT_STALENESS_HOURS_GAUGE.set(staleness_hours)

            tags = QueryTags(cohort_id=cohort_id, feature=query_tagging.Feature.COHORT)
            if initiating_user_id:
                tags.user_id = initiating_user_id
            if self.request.id:
                tags.celery_task_id = self.request.id
            update_tags(tags)
        except Exception as err:
            # Recalculation never started - calculate_people_ch's own bookkeeping (which handles
            # is_calculating/errors_calculating for failures during recalculation) never ran either.
            # When nothing will retry, clear is_calculating here rather than leaving the cohort
            # stranded "in flight" until the hourly reset_stuck_cohorts job, which would then charge
            # it an errors_calculating increment for a recalculation that never actually ran.
            if _is_final_attempt(self, isinstance(err, COHORT_RECALCULATION_TRANSIENT_ERRORS)):
                # pending_version guard extends _safe_reset_calculating_state with a null leg: never
                # clear the flag out from under a newer calculation that superseded this one. A null
                # pending_version means nothing newer is queued, so it clears too.
                #
                # errors_calculating and last_error_at are stamped alongside because they are the
                # only brakes on re-enqueueing: last_error_at drives the exponential backoff and
                # errors_calculating drives the MAX_ERRORS_CALCULATING cutoff. Clearing
                # is_calculating without them would make a cohort failing here eligible again every
                # cycle, forever. A later successful run resets both in calculate_people_ch.
                save_recovery_bookkeeping(
                    lambda: Cohort.objects.filter(
                        Q(pending_version__lte=pending_version) | Q(pending_version__isnull=True),
                        pk=cohort_id,
                        is_calculating=True,
                    ).update(
                        is_calculating=False,
                        errors_calculating=F("errors_calculating") + 1,
                        last_error_at=timezone.now(),
                    ),
                    cohort_id=cohort_id,
                )
            raise

        cohort.calculate_people_ch(
            pending_version,
            initiating_user_id=initiating_user_id,
            # calculate_people_ch charges errors_calculating in its own except block and cannot see
            # the retry machinery above it. Without this it would charge one increment per attempt,
            # so a single fully-failed run would push a cohort most of the way to the
            # MAX_ERRORS_CALCULATING cutoff that permanently drops it from recalculation.
            will_retry=lambda err: not _is_final_attempt(self, isinstance(err, COHORT_RECALCULATION_TRANSIENT_ERRORS)),
        )


def _is_transient_population_error(err: BaseException) -> bool:
    # Static population runs the same ORM statements as recalculation, so it shares the Postgres
    # legs: a pooler blip between two personhog batches must not be recorded as a permanent failure.
    return isinstance(err, STATIC_POPULATION_TRANSIENT_ERRORS) or is_transient_rpc_error(
        err, codes=STATIC_POPULATION_RETRYABLE_RPC_CODES
    )


def _is_final_attempt(task: Task, retryable: bool) -> bool:
    """Whether the caller must finalize failure state instead of leaving it for a retry."""
    if not retryable:
        return True
    if task.request.called_directly:
        return True
    return task.max_retries is not None and (task.request.retries or 0) >= task.max_retries


def _schedule_population_retry(
    task: Task, cohort_id: int, err: Exception, *, team_id: int | None, kwargs: dict[str, Any] | None = None
) -> Retry:
    """Schedule the next attempt and return the Retry for the caller to raise.

    Returns instead of raising so the caller can note that a retry is pending before it raises.
    When the broker publish fails, Celery raises Reject from here instead of returning, and the
    caller then finalizes the failure like any other terminal outcome. Takes the id rather than the
    cohort because the first read of the task is itself retryable: CONN_MAX_AGE is 0, so a pooler
    blip lands on the connection that read opens. ``kwargs`` carries progress the next attempt can
    resume from.
    """
    retries = task.request.retries or 0
    countdown = get_exponential_backoff_interval(
        factor=STATIC_POPULATION_RETRY_BACKOFF_SECONDS,
        retries=retries,
        maximum=STATIC_POPULATION_RETRY_BACKOFF_MAX_SECONDS,
        full_jitter=True,
    )
    # reset_stuck_cohorts treats a static cohort that errored within the hour as alive. Without the
    # stamp it reads the backoff window as a stalled run and dispatches a duplicate population.
    save_recovery_bookkeeping(
        lambda: Cohort.objects.filter(pk=cohort_id).update(last_error_at=timezone.now()),
        cohort_id=cohort_id,
        team_id=team_id,
    )
    error_type = type(err).__name__
    COHORT_STATIC_POPULATION_RETRIES_COUNTER.labels(task=task.name, error_type=error_type).inc()
    logger.warning(
        "static_cohort_population_retry",
        cohort_id=cohort_id,
        team_id=team_id,
        task=task.name,
        retries=retries,
        max_retries=task.max_retries,
        countdown=countdown,
        error_type=error_type,
        error=str(err),
    )
    # Merge, because task.retry(kwargs=...) replaces the whole set and would drop whatever the
    # dispatch site passed by keyword.
    retry_kwargs = {**(task.request.kwargs or {}), **kwargs} if kwargs else None
    return task.retry(exc=err, countdown=countdown, throw=False, kwargs=retry_kwargs)


def _tag_population_queries(task: Task, *, cohort_id: int, team_id: int) -> None:
    tags = QueryTags(cohort_id=cohort_id, team_id=team_id)
    if task.request.id:
        tags.celery_task_id = task.request.id
    update_tags(tags)


def _static_population_obsolete(task: Task, cohort: Cohort) -> bool:
    """Whether the cohort was deleted or flipped to dynamic while this attempt waited in a backoff.

    A flip enqueues calculate_cohort_ch, which owns is_calculating and count from then on. A late
    static attempt would clear the flag under that calculation and overwrite count with the static
    member count, so it must not write anything, including its own final state.
    """
    if not cohort.deleted and cohort.is_static:
        return False
    logger.info(
        "static_cohort_population_skipped",
        cohort_id=cohort.pk,
        team_id=cohort.team_id,
        task=task.name,
        deleted=cohort.deleted,
        is_static=cohort.is_static,
    )
    return True


@shared_task(
    bind=True,
    ignore_result=True,
    max_retries=STATIC_POPULATION_MAX_RETRIES,
)
@skip_team_scope_audit
def calculate_cohort_from_list(
    self: Task,
    cohort_id: int,
    items: list[str],
    team_id: Optional[int] = None,
    id_type: str = "distinct_id",
    email_property_key: Optional[str] = None,
) -> None:
    """
    team_id is only optional for backwards compatibility with the old celery task signature.
    All new tasks should pass team_id explicitly.
    """
    start_time = time.time()
    import_resolution = ImportResolution()
    if id_type not in ("distinct_id", "person_id", "email"):
        raise ValueError(f"Unsupported id_type: {id_type}")

    cohort: Cohort | None = None
    processing_error: BaseException | None = None
    retry: Retry | None = None
    # Whole-list retries are safe because both stores ignore members already in the cohort.
    # raise_on_error lets this task distinguish a retryable partial insert from final success.
    try:
        cohort = Cohort.objects.get(pk=cohort_id)
        if team_id is None:
            team_id = cohort.team_id
        if _static_population_obsolete(self, cohort):
            return

        if id_type == "distinct_id":
            batch_count = cohort.insert_users_by_list(
                items, team_id=team_id, raise_on_error=True, import_resolution=import_resolution
            )
        elif id_type == "person_id":
            batch_count = cohort.insert_users_list_by_uuid(
                items, team_id=team_id, raise_on_error=True, import_resolution=import_resolution
            )
        else:
            batch_count = cohort.insert_users_by_email(
                items,
                team_id=team_id,
                email_property_key=email_property_key,
                raise_on_error=True,
                import_resolution=import_resolution,
            )

        cohort.last_import_total_count = import_resolution.total
        cohort.last_import_unmatched_count = import_resolution.unmatched
        cohort.save(update_fields=["last_import_total_count", "last_import_unmatched_count"])
        if import_resolution.unmatched:
            logger.warning(
                "cohort_import_unmatched_ids",
                cohort_id=cohort.id,
                team_id=team_id,
                total=import_resolution.total,
                unmatched=import_resolution.unmatched,
            )
    except Exception as err:
        processing_error = err
        if _is_final_attempt(self, _is_transient_population_error(err)):
            raise
        retry = _schedule_population_retry(self, cohort_id, err, team_id=team_id)
        raise retry
    except BaseException as err:
        # A run the worker cut short (shutdown, revoke) failed; it must not stay in flight.
        processing_error = err
        raise
    finally:
        # The batching helper finalizes success itself and leaves failure to this task, which has
        # to record it on every exit but a scheduled retry. That includes a retry whose broker
        # publish failed, where Celery raises Reject in place of Retry.
        if cohort is not None and processing_error is not None and retry is None:
            cohort._safe_save_cohort_state(team_id=cohort.team_id, processing_error=processing_error)
    logger.warn(
        "Cohort {}: {:,} items in {} batches from CSV completed in {:.2f}s".format(
            cohort_id, len(items), batch_count, (time.time() - start_time)
        )
    )


def _populate_static_cohort(
    task: Task,
    *,
    cohort_id: int,
    team_id: Optional[int],
    ch_insert_done: bool,
    insert_actors_into_ch: Callable[..., None],
    log_prefix: str,
) -> None:
    """Run one static population attempt: claim the cohort, fill ClickHouse, then sync Postgres.

    Both population tasks delegate here, so the claim, retry and finalize protocol has one home
    and cannot drift between them.
    """
    from products.cohorts.backend.models.util import insert_cohort_people_into_pg

    # The cohort this attempt marked is_calculating. Only that attempt finalizes the flag, so a
    # skipped or never-started attempt leaves whoever owns it (the API, a newer calculation) alone.
    claimed: Cohort | None = None
    processing_error: BaseException | None = None
    retry: Retry | None = None
    try:
        if team_id is not None:
            cohort = Cohort.objects.get(pk=cohort_id, team_id=team_id)
        else:
            cohort = Cohort.objects.get(pk=cohort_id)
            team_id = cohort.team_id
        if _static_population_obsolete(task, cohort):
            return
        team = Team.objects.get(pk=team_id)
        _tag_population_queries(task, cohort_id=cohort_id, team_id=team_id)
        logger.info(
            f"{log_prefix}_started",
            cohort_id=cohort_id,
            team_id=team_id,
            query=cohort.query,
            filters=cohort.filters,
        )

        cohort.is_calculating = True
        cohort.save(update_fields=["is_calculating"])
        claimed = cohort
        cohort.refresh_from_db()

        # The CH insert is idempotent: it excludes person_ids already in the cohort.
        # This handles both the retry-after-OOM case (no duplicates) and the
        # add-more-people-via-query case (only new people inserted). A retry whose earlier attempt
        # finished this phase skips it, because re-evaluating the source query costs the same hours
        # again and inserts nothing.
        if not ch_insert_done:
            insert_actors_into_ch(cohort, team=team)
            ch_insert_done = True
            logger.info(
                f"{log_prefix}_ch_complete",
                cohort_id=cohort_id,
                team_id=team_id,
            )

        # Re-running the sync is safe because InsertCohortMembers ignores existing membership.
        insert_cohort_people_into_pg(cohort, team_id=team_id)
        logger.info(
            f"{log_prefix}_pg_complete",
            cohort_id=cohort_id,
            team_id=team_id,
        )
    except Exception as err:
        processing_error = err
        if not _is_final_attempt(task, _is_transient_population_error(err)):
            retry = _schedule_population_retry(
                task, cohort_id, err, team_id=team_id, kwargs={"ch_insert_done": ch_insert_done}
            )
            raise retry
        logger.exception(
            f"{log_prefix}_failed",
            cohort_id=cohort_id,
            team_id=team_id,
            error=str(err),
        )
        # ExposedHogQLError is a user validation failure, so do not send it to error tracking.
        if not isinstance(err, ExposedHogQLError):
            capture_exception()
    except BaseException as err:
        # A run the worker cut short (shutdown, revoke) failed; it must not be saved as a success.
        processing_error = err
        raise
    finally:
        # Every exit but a scheduled retry finalizes state, so a retry whose broker publish failed
        # (Celery raises Reject in place of Retry) records the failure instead of stranding the
        # cohort in flight. A scheduled retry keeps is_calculating set for the next attempt.
        if claimed is not None and retry is None:
            claimed._safe_save_cohort_state(team_id=claimed.team_id, processing_error=processing_error)
            claimed.refresh_from_db(fields=["is_calculating", "errors_calculating"])
            logger.info(
                f"{log_prefix}_finished",
                cohort_id=cohort_id,
                team_id=claimed.team_id,
                is_calculating=claimed.is_calculating,
                errors_calculating=claimed.errors_calculating,
            )
    if settings.DEBUG and processing_error is not None:
        raise processing_error


@shared_task(
    bind=True,
    ignore_result=True,
    max_retries=STATIC_POPULATION_MAX_RETRIES,
    queue=CeleryQueue.LONG_RUNNING.value,
    soft_time_limit=STATIC_POPULATION_SOFT_TIME_LIMIT_SECONDS,
)
@skip_team_scope_audit
def insert_cohort_from_query(
    self: Task, cohort_id: int, team_id: Optional[int] = None, ch_insert_done: bool = False
) -> None:
    """
    One-time population task for static cohorts created from a HogQL query
    (e.g. duplicating a dynamic cohort as static).

    Inserts actors into ClickHouse person_static_cohort, then syncs to Postgres.

    team_id is only optional for backwards compatibility with the old celery task signature.
    All new tasks should pass team_id explicitly. Only a retry sets ch_insert_done.
    """
    from products.cohorts.backend.models.util import insert_cohort_query_actors_into_ch

    _populate_static_cohort(
        self,
        cohort_id=cohort_id,
        team_id=team_id,
        ch_insert_done=ch_insert_done,
        insert_actors_into_ch=insert_cohort_query_actors_into_ch,
        log_prefix="insert_cohort_from_query",
    )


@shared_task(
    bind=True,
    ignore_result=True,
    max_retries=STATIC_POPULATION_MAX_RETRIES,
    queue=CeleryQueue.LONG_RUNNING.value,
    soft_time_limit=STATIC_POPULATION_SOFT_TIME_LIMIT_SECONDS,
)
@skip_team_scope_audit
def insert_cohort_from_filters(
    self: Task, cohort_id: int, team_id: Optional[int] = None, ch_insert_done: bool = False
) -> None:
    """
    One-time population task for static cohorts created from saved cohort criteria.

    Only a retry sets ch_insert_done.
    """
    from products.cohorts.backend.models.util import insert_cohort_filter_actors_into_ch

    _populate_static_cohort(
        self,
        cohort_id=cohort_id,
        team_id=team_id,
        ch_insert_done=ch_insert_done,
        insert_actors_into_ch=insert_cohort_filter_actors_into_ch,
        log_prefix="insert_cohort_from_filters",
    )


# No task-level retry. The per-page backoff inside get_cohort_actors_for_feature_flag covers the
# call to the flags service and nothing else, so a transient personhog or ClickHouse error from the
# member insert is terminal here, unlike in the sibling static population tasks. By the time any
# exception propagates to this task, get_cohort_actors_for_feature_flag has recorded final error
# state (calculation history, errors_calculating, is_calculating=False), and a Celery retry would
# contradict what the cohort already reports.
# Runs on the long-running queue (like the sibling cohort tasks) so a large paging run
# can't clog the default workers, with a generous soft limit as a backstop ceiling.
# SoftTimeLimitExceeded subclasses Exception, so get_cohort_actors_for_feature_flag's
# except block records error state and re-raises it like any other failure.
@shared_task(
    ignore_result=True,
    max_retries=0,
    queue=CeleryQueue.LONG_RUNNING.value,
    soft_time_limit=4 * 60 * 60,
)
def insert_cohort_from_feature_flag(cohort_id: int, flag_key: str, team_id: int) -> None:
    from posthog.api.cohort import get_cohort_actors_for_feature_flag

    # batchsize is also the per-page `limit` sent to the flags service, which evaluates a
    # page sequentially under a 120s request timeout. The service's hard cap is 10_000, but
    # paging at the cap risks a deterministic, retry-immune timeout on large or
    # condition-heavy flags, so page well below it.
    get_cohort_actors_for_feature_flag(cohort_id, flag_key, team_id, batchsize=2_000)


def _collect_cohort_calculation_metrics(history: CohortCalculationHistory, start_time: datetime) -> None:
    """
    Collect Prometheus metrics for cohort calculation based on the history record.
    This is called from collect_cohort_query_stats to ensure metrics are captured even if OOM occurred.

    Args:
        history: CohortCalculationHistory instance
        start_time: datetime when the calculation started (used as fallback)
    """
    # Determine if calculation completed
    if not history.finished_at:
        # Calculation never finished - likely OOM or worker crash
        COHORT_CALCULATION_FAILURES_COUNTER.labels(failure_type="stuck_inferred_oom").inc()
        COHORT_CALCULATION_COMPLETED_COUNTER.labels(status="error").inc()
        logger.warning(
            "cohort_calculation_stuck_detected",
            cohort_id=history.cohort_id,
            history_id=str(history.id),
        )
        return

    # Get actual query duration from ClickHouse query_log (most accurate)
    # Fallback to wall-clock time if query stats aren't available
    duration_seconds = None
    if history.total_query_ms:
        duration_seconds = history.total_query_ms / 1000.0
    else:
        # Fallback: use wall-clock time
        duration_seconds = (history.finished_at - start_time).total_seconds()

    if history.error:
        # Calculation finished with error
        COHORT_CALCULATION_COMPLETED_COUNTER.labels(status="error").inc()
        if duration_seconds is not None:
            COHORT_CALCULATION_DURATION_SECONDS.labels(status="error").observe(duration_seconds)

        # Categorize failure type
        failure_type = "exception"
        error_lower = history.error.lower()
        if "clickhouse" in error_lower or "code:" in error_lower:
            failure_type = "clickhouse_error"
        elif "memory" in error_lower or "oom" in error_lower:
            failure_type = "memory_error"
        elif "timeout" in error_lower or "timed out" in error_lower:
            failure_type = "timeout_error"

        COHORT_CALCULATION_FAILURES_COUNTER.labels(failure_type=failure_type).inc()
        logger.warning(
            "cohort_calculation_failed_with_error",
            cohort_id=history.cohort_id,
            history_id=str(history.id),
            failure_type=failure_type,
            duration_seconds=duration_seconds,
        )
    else:
        # Calculation succeeded
        COHORT_CALCULATION_COMPLETED_COUNTER.labels(status="success").inc()
        if duration_seconds is not None:
            COHORT_CALCULATION_DURATION_SECONDS.labels(status="success").observe(duration_seconds)
        logger.info(
            "cohort_calculation_completed_successfully",
            cohort_id=history.cohort_id,
            history_id=str(history.id),
            duration_seconds=duration_seconds,
            count=history.count,
        )


@shared_task(ignore_result=True, max_retries=3)
@skip_team_scope_audit
def collect_cohort_query_stats(
    tag_matcher: str, cohort_id: int, start_time_iso: str, history_id: str, query: str
) -> None:
    """
    Delayed task to collect cohort query statistics and observability metrics

    Args:
        tag_matcher: Query tag to match in query_log_archive
        cohort_id: Cohort ID for the calculation
        start_time_iso: Start time in ISO format
        history_id: CohortCalculationHistory UUID to update
        query: The SQL query that was executed
    """
    try:
        from dateutil import parser

        try:
            history = CohortCalculationHistory.objects.get(id=history_id)
        except CohortCalculationHistory.DoesNotExist:
            logger.warning("CohortCalculationHistory not found", history_id=history_id)
            return

        start_time = parser.parse(start_time_iso)
        query_stats = get_clickhouse_query_stats(tag_matcher, cohort_id, start_time, history.team.id)

        if query_stats:  # Skip if stats already collected (check if queries field is non-empty)
            if history.queries:
                logger.warning(
                    "Query stats already collected, skipping duplicate collection",
                    history_id=history_id,
                    cohort_id=cohort_id,
                )
                return

            update_fields = []

            # Only update history if it's still in progress (no finished_at)
            if "exception" in query_stats and not history.finished_at:
                history.finished_at = timezone.now()
                history.error = query_stats.get("exception")
                update_fields.append("finished_at")
                update_fields.append("error")

            history.add_query_info(
                query=query,
                query_id=query_stats.get("query_id"),
                query_ms=query_stats.get("query_duration_ms"),
                memory_mb=query_stats.get("memory_mb"),
                read_rows=query_stats.get("read_rows"),
                written_rows=query_stats.get("written_rows"),
            )
            update_fields.append("queries")
            history.save(update_fields=update_fields)
        else:
            logger.warning(
                "No query stats found for cohort calculation, will retry",
                tag_matcher=tag_matcher,
                cohort_id=cohort_id,
                history_id=history_id,
            )
            # Retry the task with 60 second countdown
            raise collect_cohort_query_stats.retry(countdown=COHORT_STATS_COLLECTION_DELAY_SECONDS)

        # Collect observability metrics based on the calculation result
        # This runs even if the worker OOM'd, since this task was scheduled before the calculation
        _collect_cohort_calculation_metrics(history, start_time)

    except Exception as e:
        logger.exception(
            "Failed to collect delayed cohort query stats",
            tag_matcher=tag_matcher,
            cohort_id=cohort_id,
            history_id=history_id,
            error=str(e),
        )
        raise


COHORT_BACKFILL_TRIGGER_TASK_COUNTER = Counter(
    "posthog_cohort_backfill_trigger_task_total",
    "Outcomes of debounced cohort backfill run-creation tasks",
    labelnames=["backfill_kind", "outcome"],
)

# Refusals grouped by the operator response they call for, not one label per reason: a budget
# refusal means raise the budget or wait for in-flight runs, an occupied slot means an active run
# already covers the cohort, and the rest are the cohort not being a candidate for this trigger.
# Collapsing them into a single `refused`, as this used to, made the first two indistinguishable.
# The full reason stays on the log line, so cardinality does not have to carry it.
#
# An occupied slot is the expected outcome of an ordinary backfill, not a wedge: a team-enablement
# run covers every cohort on the team, and each cohort saved during one refuses this way. Read
# `posthog_cohort_backfill_oldest_active_run_age_seconds` to tell a stuck run from normal progress.
COHORT_BACKFILL_REFUSAL_OUTCOMES: dict[BackfillRefusalReason, str] = {
    BackfillRefusalReason.OVER_BUDGET: "refused_over_budget",
    BackfillRefusalReason.RUN_SLOT_OCCUPIED: "refused_slot_occupied",
    BackfillRefusalReason.PARTICIPATION_ACTIVE: "refused_slot_occupied",
    BackfillRefusalReason.SLOT_RACE: "refused_slot_occupied",
    BackfillRefusalReason.TEAM_NOT_REALTIME: "refused_ineligible",
    BackfillRefusalReason.COHORT_MISSING: "refused_ineligible",
    BackfillRefusalReason.COHORT_INELIGIBLE: "refused_ineligible",
    BackfillRefusalReason.INVALID_HORIZON: "refused_ineligible",
    BackfillRefusalReason.PINNING_CAP_EXCEEDED: "refused_ineligible",
    # Not transient: the sizing scan's read and time caps are deterministic, so a cohort that trips
    # one trips it again on every later trigger until someone raises the limit. Nothing clears on
    # its own.
    BackfillRefusalReason.SIZING_SCAN_CAP_EXCEEDED: "refused_ineligible",
    BackfillRefusalReason.DEFINITION_CHANGED: "refused_transient",
}


# acks_late: a countdown message acked on receipt sits in one worker's memory for the whole window
# and dies with it, after the edit's supersession already ran. The creators refuse duplicates, so
# the redelivery this trades into is harmless. The queue matches the module's other
# ClickHouse-touching tasks: the person creator runs a sizing scan bounded by
# `BEHAVIORAL_BACKFILL_PERSON_SIZING_MAX_SECONDS`.
@shared_task(
    ignore_result=True,
    acks_late=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    queue=CeleryQueue.LONG_RUNNING.value,
)
def trigger_cohort_backfill_run_task(team_id: int, cohort_id: int, trigger_kind: str, backfill_kind: str) -> None:
    """Create the run a debounced cohort save asked for, reading the cohort's current definition.

    The creators re-check eligibility under a row lock, so a cohort that was edited again, deleted,
    or made static during the debounce window returns None here. That is a normal outcome, not a
    failure, and must not raise: a raise burns the task's retries re-deciding the same refusal.

    A missing operator attestation is the same kind of outcome on this path. The creators record a
    `blocked` row when called directly, which is right for operator-driven runs, but a blocked row
    holds the per-cohort uniqueness slot and nothing ever advances it, so the signal path skips
    instead of parking one on every cohort a freshly allowlisted team saves.
    """
    try:
        if not is_cohort_backfill_trigger_team(team_id):
            # The enqueue-side check ran up to the debounce countdown ago; re-checking here makes
            # shrinking the allowlist stop tasks already in flight, not only new enqueues.
            COHORT_BACKFILL_TRIGGER_TASK_COUNTER.labels(backfill_kind=backfill_kind, outcome="not_allowlisted").inc()
            logger.info(
                "skipping_cohort_backfill_run_task_team_not_allowlisted",
                cohort_id=cohort_id,
                team_id=team_id,
                trigger_kind=trigger_kind,
                backfill_kind=backfill_kind,
            )
            return
        person = backfill_kind == CohortBackfillKind.PERSON_PROPERTY
        _, missing = check_person_run_preconditions() if person else check_run_preconditions()
        if missing:
            COHORT_BACKFILL_TRIGGER_TASK_COUNTER.labels(
                backfill_kind=backfill_kind, outcome="missing_attestations"
            ).inc()
            logger.info(
                "skipping_cohort_backfill_run_task_missing_attestations",
                cohort_id=cohort_id,
                team_id=team_id,
                trigger_kind=trigger_kind,
                backfill_kind=backfill_kind,
                missing=missing,
            )
            return
        attempt = (
            attempt_person_backfill_run_for_cohort(team_id, cohort_id, trigger_kind)
            if person
            else attempt_backfill_run_for_cohort(team_id, cohort_id, trigger_kind)
        )
        run = attempt.run
        if run is None:
            # An unmapped reason falls back to the old flat `refused` rather than vanishing, so
            # adding an enum member can never silently drop refusals out of the metric.
            outcome = COHORT_BACKFILL_REFUSAL_OUTCOMES.get(attempt.reason, "refused") if attempt.reason else "refused"
            COHORT_BACKFILL_TRIGGER_TASK_COUNTER.labels(backfill_kind=backfill_kind, outcome=outcome).inc()
            logger.info(
                "skipping_cohort_backfill_run_task",
                cohort_id=cohort_id,
                team_id=team_id,
                trigger_kind=trigger_kind,
                backfill_kind=backfill_kind,
                refusal_reason=attempt.reason,
            )
            return
        COHORT_BACKFILL_TRIGGER_TASK_COUNTER.labels(backfill_kind=backfill_kind, outcome="created").inc()
        logger.info(
            "created_cohort_backfill_run",
            run_id=str(run.id),
            cohort_id=cohort_id,
            team_id=team_id,
            trigger_kind=trigger_kind,
            backfill_kind=backfill_kind,
            status=run.status,
        )
    except Exception as error:
        COHORT_BACKFILL_TRIGGER_TASK_COUNTER.labels(backfill_kind=backfill_kind, outcome="error").inc()
        logger.exception(
            "failed_to_trigger_cohort_backfill_run_task",
            cohort_id=cohort_id,
            team_id=team_id,
            trigger_kind=trigger_kind,
            backfill_kind=backfill_kind,
            error=str(error),
        )
        raise


@shared_task(ignore_result=True)
def publish_cohort_backfill_run_gauges() -> None:
    """Publish backfill run/chunk state for alerting.

    Ungated on purpose, unlike ``finalize_cohort_backfill_runs``: a stalled run has to be alertable
    while the finalizer is still dark, and the seeder's own metrics cannot see the transitions
    Django owns.
    """
    publish_backfill_run_gauges()


@shared_task(ignore_result=True)
def finalize_cohort_backfill_runs() -> None:
    """Terminalize behavioral backfill runs the Rust seeder has fully observed. Gated off by
    ``BEHAVIORAL_BACKFILL_FINALIZER_ENABLED`` (checked inside ``finalize_backfill_runs``, which
    returns before touching the DB when disabled)."""
    finalize_backfill_runs()
