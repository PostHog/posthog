import logging
import traceback

from django.core.management.base import BaseCommand, CommandError

from posthog.models import Cohort
from posthog.models.cohort.util import CohortValidationError, validate_cohort_for_recalculation
from posthog.tasks.calculate_cohort import increment_version_and_enqueue_calculate_cohort

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Recalculate a specific cohort to keep it up to date"

    def add_arguments(self, parser):
        parser.add_argument(
            "cohort_id",
            type=int,
            help="Cohort ID to recalculate",
        )

        parser.add_argument(
            "--force",
            action="store_true",
            help="Force recalculation even if cohort is currently calculating",
        )

    def handle(self, *args, **options):
        cohort_id = options["cohort_id"]

        try:
            cohort = Cohort.objects.get(pk=cohort_id)
        except Cohort.DoesNotExist:
            raise CommandError(f"Cohort with ID {cohort_id} does not exist")

        try:
            validate_cohort_for_recalculation(cohort, force=options["force"])
        except CohortValidationError as e:
            raise CommandError(str(e))

        self._recalculate_cohort(cohort, options)

    def _recalculate_cohort(self, cohort: Cohort, options):
        """Recalculate the specified cohort"""
        try:
            self.stdout.write(f"Recalculating cohort {cohort.id}: {cohort.name}")

            # Force reset if needed
            if options["force"] and cohort.is_calculating:
                cohort.is_calculating = False
                cohort.save(update_fields=["is_calculating"])
                self.stdout.write(self.style.WARNING(f"Forced reset of calculating status for cohort {cohort.id}"))

            # Recalculate
            increment_version_and_enqueue_calculate_cohort(cohort, initiating_user=None)

            self.stdout.write(self.style.SUCCESS(f"Successfully enqueued recalculation for cohort {cohort.id}"))

        except Exception as e:
            error_msg = f"Error recalculating cohort {cohort.id}: {e}"
            self.stdout.write(self.style.ERROR(error_msg))

            if options.get("verbosity", 1) >= 2:
                self.stdout.write(f"Full traceback:\n{traceback.format_exc()}")

            raise CommandError(f"Failed to recalculate cohort {cohort.id}: {e}")
