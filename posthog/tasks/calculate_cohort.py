import time
from typing import Any, Dict, List

import structlog
from celery import shared_task
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.db.models import F
from django.utils import timezone

from posthog.models import Cohort
from posthog.models.cohort import get_and_update_pending_version

logger = structlog.get_logger(__name__)

MAX_AGE_MINUTES = 15


def calculate_cohorts() -> None:
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
        .order_by(F("last_calculation").asc(nulls_first=True))[0 : settings.CALCULATE_X_COHORTS_PARALLEL]
    ):

        cohort = Cohort.objects.filter(pk=cohort.pk).get()
        update_cohort(cohort)


def update_cohort(cohort: Cohort) -> None:
    pending_version = get_and_update_pending_version(cohort)
    calculate_cohort_ch.delay(cohort.id, pending_version)


@shared_task(ignore_result=True, max_retries=2)
def calculate_cohort_ch(cohort_id: int, pending_version: int) -> None:
    cohort: Cohort = Cohort.objects.get(pk=cohort_id)
    cohort.calculate_people_ch(pending_version)


@shared_task(ignore_result=True, max_retries=1)
def calculate_cohort_from_list(cohort_id: int, items: List[str]) -> None:
    start_time = time.time()
    cohort = Cohort.objects.get(pk=cohort_id)

    cohort.insert_users_by_list(items)
    logger.info("Calculating cohort {} from CSV took {:.2f} seconds".format(cohort.pk, (time.time() - start_time)))


@shared_task(ignore_result=True, max_retries=1)
def insert_cohort_from_insight_filter(cohort_id: int, filter_data: Dict[str, Any]) -> None:
    from posthog.api.cohort import insert_cohort_actors_into_ch, insert_cohort_people_into_pg

    cohort = Cohort.objects.get(pk=cohort_id)

    insert_cohort_actors_into_ch(cohort, filter_data)
    insert_cohort_people_into_pg(cohort=cohort)
