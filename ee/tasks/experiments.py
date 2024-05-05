from ee.clickhouse.views.experiment_results import calculate_experiment_results
from posthog.models.experiment import Experiment
import structlog
from celery import shared_task

from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.EMAIL.value)
def send_experiment_finished_email_results(experiment, results) -> None:
    try:
        from ee.tasks.send_experiment_email import send_experiment_email

        send_experiment_email(experiment, results)
    except ImportError:
        pass
    except Exception as e:
        logger.error("Failed to send email results for experiment", error=e, exc_info=True)


@shared_task(ignore_result=True)
def schedule_results_email(pk) -> None:
    experiment: Experiment = Experiment.objects.get(pk=pk)
    results = calculate_experiment_results(experiment, True)
    send_experiment_finished_email_results(experiment, results)
