from celery import shared_task
from posthog.models import Cohort
from posthog.celery import app
import logging
import time

logger = logging.getLogger(__name__)


@shared_task
def calculate_cohort(cohort_id: int) -> None:
    start_time = time.time()
    cohort = Cohort.objects.get(pk=cohort_id)
    cohort.calculate_people()
    logger.info('Calculating cohort {} took {:.2f} seconds'.format(cohort.pk, (time.time() - start_time)))


def calculate_cohorts() -> None:
    print('blablab')
    start_time = time.time()
    for cohort in Cohort.objects.filter(is_calculating=False).order_by('id'):
        cohort_start = time.time()
        cohort.calculate_people()
        logger.info(' - Calculating cohort {} took {:.2f} seconds'.format(cohort.pk, (time.time() - cohort_start)))

    logger.info('Calculating all cohorts took {:.2f} seconds'.format(time.time() - start_time))
