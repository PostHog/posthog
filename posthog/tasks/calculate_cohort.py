import posthoganalytics
import structlog
import time

from django.conf import settings

from posthog.models.team.team import Team
from celery import shared_task, chain, current_task
from datetime import timedelta
from dateutil.relativedelta import relativedelta
from typing import Any, Optional

from django.db.models import Case, F, ExpressionWrapper, DurationField, Q, QuerySet, When
from django.utils import timezone
from prometheus_client import Gauge, Counter

from posthog.clickhouse.query_tagging import tag_queries
from posthog.exceptions_capture import capture_exception
from posthog.api.monitoring import Feature
from posthog.models import Cohort
from posthog.models.cohort import CohortOrEmpty
from posthog.models.cohort.util import get_static_cohort_size, get_dependent_cohorts, sort_cohorts_topologically
from posthog.models.user import User
from posthog.tasks.utils import CeleryQueue

COHORT_RECALCULATIONS_BACKLOG_GAUGE = Gauge(
    "cohort_recalculations_backlog",
    "Number of cohorts that are waiting to be calculated",
)

COHORT_STALENESS_HOURS_GAUGE = Gauge(
    "cohort_staleness_hours",
    "Cohort's count of hours since last calculation",
)

COHORTS_STALE_COUNT_GAUGE = Gauge(
    "cohorts_stale", "Number of cohorts that haven't been calculated in more than X hours", ["hours"]
)

COHORT_STUCK_COUNT_GAUGE = Gauge(
    "cohort_stuck_count", "Number of cohorts that are stuck calculating for more than 1 hour"
)

COHORT_DEPENDENCY_CALCULATION_FAILURES_COUNTER = Counter(
    "cohort_dependency_calculation_failures_total", "Number of times dependent cohort calculations have failed"
)

logger = structlog.get_logger(__name__)

MAX_AGE_MINUTES = 15
MAX_ERRORS_CALCULATING = 20


def get_cohort_calculation_candidates_queryset() -> QuerySet:
    return Cohort.objects.filter(
        Q(last_calculation__lte=timezone.now() - relativedelta(minutes=MAX_AGE_MINUTES))
        | Q(last_calculation__isnull=True),
        deleted=False,
        is_calculating=False,
        errors_calculating__lte=MAX_ERRORS_CALCULATING,
    ).exclude(is_static=True)


def update_stale_cohort_metrics() -> None:
    now = timezone.now()
    base_queryset = Cohort.objects.filter(
        Q(last_calculation__isnull=False),
        deleted=False,
        is_calculating=False,
        errors_calculating__lte=20,
    ).exclude(is_static=True)

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

    for cohort in (
        get_cohort_calculation_candidates_queryset()
        .filter(
            Q(last_error_at__lte=timezone.now() - backoff_duration)  # type: ignore
            | Q(last_error_at__isnull=True)  # backwards compatability cohorts before last_error_at was introduced
        )
        .order_by(F("last_calculation").asc(nulls_first=True))[0:parallel_count]
    ):
        cohort = Cohort.objects.filter(pk=cohort.pk).get()
        logger.info("Enqueuing cohort calculation", cohort_id=cohort.pk, last_calculation=cohort.last_calculation)
        increment_version_and_enqueue_calculate_cohort(cohort, initiating_user=None)

    backlog = get_cohort_calculation_candidates_queryset().count()
    COHORT_RECALCULATIONS_BACKLOG_GAUGE.set(backlog)

    try:
        update_stale_cohort_metrics()
    except Exception as e:
        logger.exception("Failed to update stale cohort metrics", error=str(e))


def increment_version_and_enqueue_calculate_cohort(cohort: Cohort, *, initiating_user: Optional[User]) -> None:
    dependent_cohorts = get_dependent_cohorts(cohort)
    if dependent_cohorts:
        logger.info("cohort_has_dependencies", cohort_id=cohort.id, dependent_count=len(dependent_cohorts))

        all_cohort_ids = {dep.id for dep in dependent_cohorts}
        all_cohort_ids.add(cohort.id)

        # Sort cohorts (dependencies first)
        seen_cohorts_cache: dict[int, CohortOrEmpty] = {dep.id: dep for dep in dependent_cohorts}
        seen_cohorts_cache[cohort.id] = cohort

        try:
            sorted_cohort_ids = sort_cohorts_topologically(all_cohort_ids, seen_cohorts_cache)
        except Exception as e:
            COHORT_DEPENDENCY_CALCULATION_FAILURES_COUNTER.inc()
            logger.exception("cohort_dependency_resolution_failed", cohort_id=cohort.id, error=str(e))
            capture_exception()
            # Fall back to calculating just this cohort without dependencies
            logger.info("cohort_fallback_to_single_calculation", cohort_id=cohort.id)
            _enqueue_single_cohort_calculation(cohort, initiating_user)
            return

        # Create a chain of tasks to ensure sequential execution
        task_chain = []
        for cohort_id in sorted_cohort_ids:
            current_cohort = seen_cohorts_cache.get(cohort_id)
            if current_cohort and not current_cohort.is_static:
                _prepare_cohort_for_calculation(current_cohort)
                task_chain.append(
                    calculate_cohort_ch.si(
                        current_cohort.id,
                        current_cohort.pending_version,
                        initiating_user.id if initiating_user else None,
                    )
                )

        if task_chain:
            chain(*task_chain).apply_async()
    else:
        logger.info("cohort_has_no_dependencies", cohort_id=cohort.id)
        _enqueue_single_cohort_calculation(cohort, initiating_user)


def _prepare_cohort_for_calculation(cohort: Cohort) -> None:
    cohort.pending_version = Case(When(pending_version__isnull=True, then=1), default=F("pending_version") + 1)
    update_fields = ["pending_version"]

    if not cohort.is_static:
        # avoid starting another cohort calculation if one is already expected to be in progress
        # XXX: it is possible for a job to fail without resetting this field and need to be manually recovered
        cohort.is_calculating = True
        update_fields.append("is_calculating")

    cohort.save(update_fields=update_fields)
    cohort.refresh_from_db()


def _enqueue_single_cohort_calculation(cohort: Cohort, initiating_user: Optional[User]) -> None:
    """Helper function to enqueue a single cohort for calculation"""
    _prepare_cohort_for_calculation(cohort)
    calculate_cohort_ch.delay(cohort.id, cohort.pending_version, initiating_user.id if initiating_user else None)


@shared_task(ignore_result=True, max_retries=2, queue=CeleryQueue.LONG_RUNNING.value)
def calculate_cohort_ch(cohort_id: int, pending_version: int, initiating_user_id: Optional[int] = None) -> None:
    with posthoganalytics.new_context():
        posthoganalytics.tag("feature", Feature.COHORT.value)
        posthoganalytics.tag("cohort_id", cohort_id)

        cohort: Cohort = Cohort.objects.get(pk=cohort_id)

        posthoganalytics.tag("team_id", cohort.team.id)

        staleness_hours = 0.0
        if cohort.last_calculation is not None:
            staleness_hours = (timezone.now() - cohort.last_calculation).total_seconds() / 3600
        COHORT_STALENESS_HOURS_GAUGE.set(staleness_hours)

        tags = {"cohort_id": cohort_id, "feature": Feature.COHORT.value}
        if initiating_user_id:
            tags["user_id"] = initiating_user_id
        if current_task and current_task.request and current_task.request.id:
            tags["celery_task_id"] = current_task.request.id
        tag_queries(**tags)

        cohort.calculate_people_ch(pending_version, initiating_user_id=initiating_user_id)


@shared_task(ignore_result=True, max_retries=1)
def calculate_cohort_from_list(cohort_id: int, items: list[str], team_id: Optional[int] = None) -> None:
    """
    team_id is only optional for backwards compatibility with the old celery task signature.
    All new tasks should pass team_id explicitly.
    """
    start_time = time.time()
    cohort = Cohort.objects.get(pk=cohort_id)
    if team_id is None:
        team_id = cohort.team_id

    cohort.insert_users_by_list(items, team_id=team_id)
    logger.warn("Calculating cohort {} from CSV took {:.2f} seconds".format(cohort.pk, (time.time() - start_time)))


@shared_task(ignore_result=True, max_retries=1)
def insert_cohort_from_insight_filter(
    cohort_id: int, filter_data: dict[str, Any], team_id: Optional[int] = None
) -> None:
    """
    team_id is only optional for backwards compatibility with the old celery task signature.
    All new tasks should pass team_id explicitly.
    """
    from posthog.api.cohort import insert_cohort_actors_into_ch, insert_cohort_people_into_pg

    cohort = Cohort.objects.get(pk=cohort_id)
    if team_id is None:
        team_id = cohort.team_id

    insert_cohort_actors_into_ch(cohort, filter_data, team_id=team_id)
    insert_cohort_people_into_pg(cohort, team_id=team_id)


@shared_task(ignore_result=True, max_retries=1)
def insert_cohort_from_query(cohort_id: int, team_id: Optional[int] = None) -> None:
    """
    team_id is only optional for backwards compatibility with the old celery task signature.
    All new tasks should pass team_id explicitly.
    """
    from posthog.api.cohort import insert_cohort_people_into_pg, insert_cohort_query_actors_into_ch

    cohort = Cohort.objects.get(pk=cohort_id)
    if team_id is None:
        team_id = cohort.team_id
    team = Team.objects.get(pk=team_id)
    try:
        insert_cohort_query_actors_into_ch(cohort, team=team)
        insert_cohort_people_into_pg(cohort, team_id=team_id)
        cohort.count = get_static_cohort_size(cohort_id=cohort.id, team_id=cohort.team_id)
        cohort.errors_calculating = 0
        cohort.last_calculation = timezone.now()
    except:
        cohort.errors_calculating = F("errors_calculating") + 1
        cohort.last_error_at = timezone.now()
        capture_exception()
        if settings.DEBUG:
            raise
    finally:
        cohort.is_calculating = False
        cohort.save()


@shared_task(ignore_result=True, max_retries=1)
def insert_cohort_from_feature_flag(cohort_id: int, flag_key: str, team_id: int) -> None:
    from posthog.api.cohort import get_cohort_actors_for_feature_flag

    get_cohort_actors_for_feature_flag(cohort_id, flag_key, team_id, batchsize=10_000)
