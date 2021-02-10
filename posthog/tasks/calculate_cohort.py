import logging
import os
import time
from typing import List

from celery import shared_task
from dateutil.relativedelta import relativedelta
from django.db.models import F
from django.utils import timezone

from posthog.models import Cohort

logger = logging.getLogger(__name__)

MAX_AGE_MINUTES = 15
PARALLEL_COHORTS = int(os.environ.get("PARALLEL_COHORTS", 5))


def calculate_cohorts() -> None:
    # This task will be run every minute
    # Every minute, grab a few cohorts off the list and execute them
    for cohort in (
        Cohort.objects.filter(
            is_calculating=False,
            last_calculation__lte=timezone.now() - relativedelta(minutes=MAX_AGE_MINUTES),
            errors_calculating__lte=2,
        )
        .exclude(is_static=True)
        .order_by(F("last_calculation").asc(nulls_first=True))[0:PARALLEL_COHORTS]
    ):
        calculate_cohort.delay(cohort.id)


@shared_task(ignore_result=True, max_retries=1)
def calculate_cohort(cohort_id: int) -> None:
    start_time = time.time()
    cohort = Cohort.objects.get(pk=cohort_id)
    cohort.calculate_people()
    logger.info("Calculating cohort {} took {:.2f} seconds".format(cohort.pk, (time.time() - start_time)))


@shared_task(ignore_result=True, max_retries=1)
def calculate_cohort_from_csv(cohort_id: int, items: List[str]) -> None:
    start_time = time.time()
    cohort = Cohort.objects.get(pk=cohort_id)

    cohort.insert_users_by_list(items)

    logger.info("Calculating cohort {} from CSV took {:.2f} seconds".format(cohort.pk, (time.time() - start_time)))
