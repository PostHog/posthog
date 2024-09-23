import time
from typing import Any, Optional

import structlog
from celery import shared_task
from dateutil.relativedelta import relativedelta
from django.db.models import F
from django.utils import timezone
from prometheus_client import Gauge
from sentry_sdk import set_tag

from posthog.api.monitoring import Feature
from posthog.models import Cohort
from posthog.models.cohort import get_and_update_pending_version
from posthog.models.cohort.util import clear_stale_cohortpeople
from posthog.models.user import User

COHORT_RECALCULATIONS_BACKLOG_GAUGE = Gauge(
    "cohort_recalculations_backlog",
    "Number of cohorts that are waiting to be calculated",
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
    for cohort in (
        Cohort.objects.filter(
            deleted=False,
            is_calculating=False,
            last_calculation__lte=timezone.now() - relativedelta(minutes=MAX_AGE_MINUTES),
            errors_calculating__lte=20,
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

    cohort.calculate_people_ch(pending_version, initiating_user_id=initiating_user_id)


@shared_task(ignore_result=True, max_retries=1)
def calculate_cohort_from_list(cohort_id: int, items: list[str]) -> None:
    start_time = time.time()
    cohort = Cohort.objects.get(pk=cohort_id)

    cohort.insert_users_by_list(items)
    logger.warn("Calculating cohort {} from CSV took {:.2f} seconds".format(cohort.pk, (time.time() - start_time)))


@shared_task(ignore_result=True, max_retries=1)
def insert_cohort_from_insight_filter(cohort_id: int, filter_data: dict[str, Any]) -> None:
    from posthog.api.cohort import (
        insert_cohort_actors_into_ch,
        insert_cohort_people_into_pg,
    )

    cohort = Cohort.objects.get(pk=cohort_id)

    insert_cohort_actors_into_ch(cohort, filter_data)
    insert_cohort_people_into_pg(cohort=cohort)


@shared_task(ignore_result=True, max_retries=1)
def insert_cohort_from_query(cohort_id: int) -> None:
    from posthog.api.cohort import (
        insert_cohort_people_into_pg,
        insert_cohort_query_actors_into_ch,
    )

    cohort = Cohort.objects.get(pk=cohort_id)
    insert_cohort_query_actors_into_ch(cohort)
    insert_cohort_people_into_pg(cohort=cohort)


@shared_task(ignore_result=True, max_retries=1)
def insert_cohort_from_feature_flag(cohort_id: int, flag_key: str, team_id: int) -> None:
    from posthog.api.cohort import get_cohort_actors_for_feature_flag

    get_cohort_actors_for_feature_flag(cohort_id, flag_key, team_id, batchsize=10_000)
