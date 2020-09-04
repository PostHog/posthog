import logging
import time

from celery import shared_task
from dateutil.relativedelta import relativedelta
from django.db.models import Q
from django.utils import timezone

from posthog.celery import app
from posthog.ee import check_ee_enabled
from posthog.models import Cohort

logger = logging.getLogger(__name__)


@shared_task
def calculate_cohort(cohort_id: int) -> None:
    start_time = time.time()
    cohort = Cohort.objects.get(pk=cohort_id)
    cohort.calculate_people()
    calculate_cohorts_ch(cohort)
    logger.info("Calculating cohort {} took {:.2f} seconds".format(cohort.pk, (time.time() - start_time)))


def calculate_cohorts() -> None:
    start_time = time.time()
    for cohort in Cohort.objects.filter(
        Q(is_calculating=False) | Q(last_calculation__lte=timezone.now() - relativedelta(minutes=15))
    ).order_by("id"):
        cohort_start = time.time()
        cohort.calculate_people()
        calculate_cohorts_ch(cohort)
        logger.info(" - Calculating cohort {} took {:.2f} seconds".format(cohort.pk, (time.time() - cohort_start)))

    logger.info("Calculating all cohorts took {:.2f} seconds".format(time.time() - start_time))


def calculate_cohorts_ch(cohort: Cohort) -> None:
    if check_ee_enabled():
        try:
            from ee.clickhouse.models.cohort import populate_cohort_person_table

            populate_cohort_person_table(cohort)
        except:
            logger.error("Could not update clickhouse cohort tables")
