import logging
import time

from celery import shared_task
from dateutil.relativedelta import relativedelta
from django.db.models import Q
from django.db.models.query import QuerySet
from django.utils import timezone

from posthog.celery import app
from posthog.ee import is_ee_enabled
from posthog.models import Cohort

logger = logging.getLogger(__name__)

MAX_AGE_MINUTES = 15


def calculate_cohorts() -> None:
    # This task will be run every minute
    # Every minute, grab a few cohorts off the list and execute them
    for cohort in Cohort.objects.filter(
        Q(is_calculating=False) | Q(last_calculation__lte=timezone.now() - relativedelta(minutes=MAX_AGE_MINUTES))
    ).order_by("last_calculation")[0:15]:
        calculate_cohort.delay(cohort.id)


@shared_task(ignore_result=True)
def calculate_cohort(cohort_id: int) -> None:
    start_time = time.time()
    cohort = Cohort.objects.get(pk=cohort_id)
    cohort.calculate_people()
    logger.info("Calculating cohort {} took {:.2f} seconds".format(cohort.pk, (time.time() - start_time)))
