import logging
import traceback

from django.core.management.base import BaseCommand

from posthog.models import Cohort
from posthog.tasks.calculate_cohort import calculate_cohort_ch, increment_version_and_enqueue_calculate_cohort

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Manually calculate cohort to keep it up to date or catch an exception"

    def add_arguments(self, parser):
        parser.add_argument(
            "--cohort-id",
            type=int,
            required=True,
            help="Cohort ID to calculate",
        )

    def handle(self, *args, **options):
        cohort_id = options["cohort_id"]
        self.calculate_cohort(cohort_id=cohort_id)

    def calculate_cohort(self, cohort_id: int) -> None:
        """
        Manually calculate a cohort to keep it up to date or catch an exception
        """
        try:
            c = Cohort.objects.get(pk=cohort_id)
            increment_version_and_enqueue_calculate_cohort(c, initiating_user=None)
            calculate_cohort_ch(c.id, c.pending_version, None)
            self.stdout.write(self.style.SUCCESS(f"Successfully calculated cohort {cohort_id}"))
        except Exception as e:
            error_msg = f"Error calculating cohort: {e}\n\nFull traceback:\n{traceback.format_exc()}"
            self.stdout.write(self.style.ERROR(error_msg))
