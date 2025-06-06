import time
from typing import Any, Optional

from django.conf import settings

from posthog.models.team.team import Team
import structlog
from celery import shared_task, chain
from dateutil.relativedelta import relativedelta
from django.db.models import Case, F, ExpressionWrapper, DurationField, Q, QuerySet, When
from django.utils import timezone
from prometheus_client import Gauge
from sentry_sdk import set_tag

from datetime import timedelta

from posthog.exceptions_capture import capture_exception
from posthog.api.monitoring import Feature
from posthog.models import Cohort
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

logger = structlog.get_logger(__name__)

MAX_AGE_MINUTES = 15
CALCULATE_COHORT_TIME_LIMIT_MINUTES = 60 * 60 * 10


def get_cohort_calculation_candidates_queryset() -> QuerySet:
    return Cohort.objects.filter(
        Q(last_calculation__lte=timezone.now() - relativedelta(minutes=MAX_AGE_MINUTES))
        | Q(last_calculation__isnull=True),
        Q(deleted=False),
        # Include cohorts that are either not calculating,
        # OR are calculating but stuck (>24 hours)
        # This will help us catch cohorts where they failed to calculate and
        # never had is_calculating set back False due to the process crashing
        Q(is_calculating=False)
        | Q(is_calculating=True, last_calculation__lte=timezone.now() - relativedelta(hours=24)),
        Q(errors_calculating__lte=20),
    ).exclude(Q(is_static=True))


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
        increment_version_and_enqueue_calculate_cohort(cohort, initiating_user=None)

    backlog = get_cohort_calculation_candidates_queryset().count()
    COHORT_RECALCULATIONS_BACKLOG_GAUGE.set(backlog)


def increment_version_and_enqueue_calculate_cohort(cohort: Cohort, *, initiating_user: Optional[User]) -> None:
    dependent_cohorts = get_dependent_cohorts(cohort)
    if dependent_cohorts:
        logger.info("cohort_has_dependencies", cohort_id=cohort.id, dependent_count=len(dependent_cohorts))

        all_cohort_ids = {dep.id for dep in dependent_cohorts}
        all_cohort_ids.add(cohort.id)

        # Sort cohorts (dependencies first)
        seen_cohorts_cache = {dep.id: dep for dep in dependent_cohorts}
        seen_cohorts_cache[cohort.id] = cohort
        sorted_cohort_ids = sort_cohorts_topologically(all_cohort_ids, seen_cohorts_cache)

        # Create a chain of tasks to ensure sequential execution
        task_chain = []
        for cohort_id in sorted_cohort_ids:
            current_cohort = seen_cohorts_cache[cohort_id]
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


@shared_task(
    ignore_result=True,
    max_retries=2,
    queue=CeleryQueue.LONG_RUNNING.value,
    time_limit=CALCULATE_COHORT_TIME_LIMIT_MINUTES,
)
def calculate_cohort_ch(cohort_id: int, pending_version: int, initiating_user_id: Optional[int] = None) -> None:
    cohort: Cohort = Cohort.objects.get(pk=cohort_id)

    set_tag("feature", Feature.COHORT.value)
    set_tag("cohort_id", cohort.id)
    set_tag("team_id", cohort.team.id)

    staleness_hours = 0.0
    if cohort.last_calculation is not None:
        staleness_hours = (timezone.now() - cohort.last_calculation).total_seconds() / 3600
    COHORT_STALENESS_HOURS_GAUGE.set(staleness_hours)

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
