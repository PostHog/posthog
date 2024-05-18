from celery import shared_task

from ee.clickhouse.views.experiment_results import calculate_experiment_results

from posthog.models.experiment import Experiment
from posthog.tasks.utils import CeleryQueue

import structlog

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.EMAIL.value)
def send_experiment_finished_email_results(experiment, results) -> None:
    try:
        from ee.tasks.send_experiment_email import send_experiment_email

        send_experiment_email(experiment, results)
    except ImportError:
        pass
    except Exception as e:
        logger.error("sending email results failed for experiment", error=e, experiment_id=experiment.pk, exc_info=True)


@shared_task(ignore_result=True, queue=CeleryQueue.EMAIL.value)
def schedule_results_email(pk) -> None:
    try:
        experiment: Experiment = Experiment.objects.get(pk=pk)
        results = calculate_experiment_results(experiment, True)
        send_experiment_finished_email_results(experiment, results)
    except Exception as e:
        logger.error("scheduling email results for experiment failed", error=e, experiment_id=pk, exc_info=True)
