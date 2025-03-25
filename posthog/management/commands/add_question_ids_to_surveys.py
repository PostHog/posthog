import uuid
import logging

from django.core.management.base import BaseCommand
from django.db import transaction

from posthog.models import Survey

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Add unique IDs to each question in existing surveys that don't have them"

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Number of surveys to process in each batch (default: 1000)",
        )
        parser.add_argument(
            "--really-run",
            action="store_true",
            help="Actually make changes to the database. Without this flag, runs in dry-run mode.",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Show detailed information about the process",
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        really_run = options["really_run"]
        verbose = options["verbose"]

        if not really_run:
            self.stdout.write(self.style.WARNING("Running in dry-run mode - no changes will be made"))
            self.stdout.write(self.style.WARNING("Use --really-run to actually make changes"))

        self.stdout.write(
            self.style.WARNING(
                "Note: This command may not be necessary for new surveys as IDs are automatically added via pre_save signal"
            )
        )
        self.stdout.write(
            self.style.WARNING(
                "It's primarily useful for older surveys created before the pre_save signal was implemented"
            )
        )

        self.add_question_ids_to_surveys(batch_size=batch_size, really_run=really_run, verbose=verbose)

    def add_question_ids_to_surveys(self, batch_size: int, really_run: bool, verbose: bool) -> None:
        """
        Add unique IDs to each question in existing surveys.
        This ensures all questions have an ID for tracking responses.

        Processes surveys in small batches to minimize memory usage.
        Uses proper row locking to prevent race conditions.
        """
        total_surveys = Survey.objects.filter(questions__isnull=False).count()
        total_modified = 0
        total_questions_updated = 0
        total_processed = 0

        self.stdout.write(f"Found {total_surveys} surveys to process")

        # Process in batches to minimize memory usage
        offset = 0

        while True:
            # Process one batch at a time
            with transaction.atomic():
                # Get a batch of surveys WITH ROW LOCKING
                # This ensures no one else can modify these rows while we're processing them
                surveys = list(
                    Survey.objects.filter(questions__isnull=False)
                    .order_by("pk")
                    .select_for_update(skip_locked=True)  # Add row locking
                    .only("id", "questions")[
                        # Only fetch fields we need
                        offset : offset + batch_size
                    ]
                )

                if not surveys:
                    # If we got no surveys, we're done
                    break

                batch_modified = 0
                batch_questions_updated = 0
                surveys_to_update = []

                for survey in surveys:
                    # Skip surveys with empty questions list
                    if not survey.questions:
                        continue

                    # Add IDs to questions that don't have them
                    modified = False
                    questions_updated = 0

                    for question in survey.questions:
                        if not question.get("id"):
                            question["id"] = str(uuid.uuid4())
                            modified = True
                            questions_updated += 1

                    # Add survey to update list if any questions were modified
                    if modified:
                        batch_modified += 1
                        batch_questions_updated += questions_updated
                        surveys_to_update.append(survey)

                        if verbose:
                            self.stdout.write(f"Survey {survey.id}: Added IDs to {questions_updated} questions")

                # Update all modified surveys in this batch
                if surveys_to_update and really_run:
                    Survey.objects.bulk_update(surveys_to_update, ["questions"])

                total_modified += batch_modified
                total_questions_updated += batch_questions_updated
                total_processed += len(surveys)

                # Report progress
                processed_so_far = offset + len(surveys)
                percent_complete = (processed_so_far / total_surveys) * 100 if total_surveys > 0 else 100

                self.stdout.write(
                    f"Processed batch of {len(surveys)} surveys: "
                    f"Modified {batch_modified} surveys, "
                    f"Updated {batch_questions_updated} questions. "
                    f"Progress: {processed_so_far}/{total_surveys} ({percent_complete:.1f}%)"
                )

            # Move to the next batch
            offset += len(surveys)  # Use actual number of surveys processed, not batch_size

        # Check if we processed all surveys
        if total_processed < total_surveys:
            self.stdout.write(
                self.style.WARNING(
                    f"Note: Only processed {total_processed} out of {total_surveys} surveys. "
                    f"The remaining {total_surveys - total_processed} surveys may have been locked "
                    f"by other processes. These surveys will likely get question IDs automatically "
                    f"via the pre_save signal when they are next updated."
                )
            )

        if not really_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f"DRY RUN COMPLETE: Would have modified {total_modified} surveys "
                    f"and updated {total_questions_updated} questions"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully modified {total_modified} surveys and updated {total_questions_updated} questions"
                )
            )
