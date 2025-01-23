import time
from typing import Any, Optional

from django.conf import settings

from posthog.models.team.team import Team
import structlog
from celery import shared_task
from dateutil.relativedelta import relativedelta
from django.db.models import F, ExpressionWrapper, DurationField, Q
from django.utils import timezone
from prometheus_client import Gauge
from sentry_sdk import set_tag

from datetime import timedelta

from posthog.exceptions import capture_exception
from posthog.api.monitoring import Feature
from posthog.models import Cohort
from posthog.models.cohort import get_and_update_pending_version
from posthog.models.cohort.util import clear_stale_cohortpeople, get_static_cohort_size
from posthog.models.user import User

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


def calculate_cohorts(parallel_count: int) -> None:
    """
    Calculates maximum N cohorts in parallel.

    Args:
        parallel_count: Maximum number of cohorts to calculate in parallel.
    """

    # This task will be run every minute
    # Every minute, grab a few cohorts off the list and execute them

    # calculate exponential backoff
    backoff_duration = ExpressionWrapper(
        timedelta(minutes=30) * (2 ** F("errors_calculating")),  # type: ignore
        output_field=DurationField(),
    )

    for cohort in (
        Cohort.objects.filter(
            deleted=False,
            is_calculating=False,
            last_calculation__lte=timezone.now() - relativedelta(minutes=MAX_AGE_MINUTES),
            errors_calculating__lte=20,
            # Exponential backoff, with the first one starting after 30 minutes
        )
        .filter(
            Q(last_error_at__lte=timezone.now() - backoff_duration)  # type: ignore
            | Q(last_error_at__isnull=True)  # backwards compatability cohorts before last_error_at was introduced
        )
        .exclude(is_static=True)
        .order_by(F("last_calculation").asc(nulls_first=True))[0:parallel_count]
    ):
        cohort = Cohort.objects.filter(pk=cohort.pk).get()
        update_cohort(cohort, initiating_user=None)

    # update gauge
    backlog = (
        Cohort.objects.filter(
            deleted=False,
            is_calculating=False,
            last_calculation__lte=timezone.now() - relativedelta(minutes=MAX_AGE_MINUTES),
            errors_calculating__lte=20,
        )
        .exclude(is_static=True)
        .count()
    )
    COHORT_RECALCULATIONS_BACKLOG_GAUGE.set(backlog)


def update_cohort(cohort: Cohort, *, initiating_user: Optional[User]) -> None:
    pending_version = get_and_update_pending_version(cohort)
    calculate_cohort_ch.delay(cohort.id, pending_version, initiating_user.id if initiating_user else None)


@shared_task(ignore_result=True)
def clear_stale_cohort(cohort_id: int, before_version: int) -> None:
    cohort: Cohort = Cohort.objects.get(pk=cohort_id)
    clear_stale_cohortpeople(cohort, before_version)


@shared_task(ignore_result=True, max_retries=2)
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
