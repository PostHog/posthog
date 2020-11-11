import logging
import time

from celery import shared_task
from dateutil.relativedelta import relativedelta
from django.db.models import Q
from django.db.models.query import QuerySet
from django.utils import timezone

from posthog.celery import app
from posthog.ee import check_ee_enabled
from posthog.models import Cohort

logger = logging.getLogger(__name__)


def calculate_cohorts(max_age_minutes: int = 15) -> None:
    start_time = time.time()
    for cohort in unprocessed_cohorts(max_age_minutes):
        calculate_cohort.delay(cohort.id, max_age_minutes)


@shared_task(ignore_result=True)
def calculate_cohort(cohort_id: int, max_age_minutes: int = 15) -> None:
    start_time = time.time()
    cohort = unprocessed_cohorts(max_age_minutes).filter(pk=cohort_id).first()
    if cohort:
        cohort.calculate_people()
        logger.info("Calculating cohort {} took {:.2f} seconds".format(cohort.pk, (time.time() - start_time)))


def unprocessed_cohorts(max_age_minutes: int) -> QuerySet:
    return Cohort.objects.filter(
        Q(is_calculating=False) | Q(last_calculation__lte=timezone.now() - relativedelta(minutes=max_age_minutes))
    ).order_by("id")
