import logging

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError

import structlog

from posthog.tasks.tasks import background_delete_model_task

logger = structlog.get_logger(__name__)
logger.setLevel(logging.INFO)


class Command(BaseCommand):
    help = "Start a background deletion task for a model with team_id field"

    def add_arguments(self, parser):
        parser.add_argument("model_name", type=str, help="Django model name (e.g., 'posthog.Person', 'posthog.Event')")
        parser.add_argument("--team-id", type=int, required=True, help="Team ID to filter records for deletion")
        parser.add_argument(
            "--batch-size", type=int, default=10000, help="Number of rows to delete per batch (default: 10000)"
        )
        parser.add_argument(
            "--max-delete-size",
            type=int,
            default=5000000,
            help="Maximum number of records to delete (default: 5000000)",
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="Show what would be deleted without actually deleting"
        )
        parser.add_argument("--synchronous", action="store_true", help="Run the task synchronously")

    def handle(self, *args, **options):
        model_name = args[0] if args else options.get("model_name")
        team_id = options["team_id"]
        batch_size = options.get("batch_size", 10000)
        max_delete_size = options.get("max_delete_size", 5000000)
        dry_run = options.get("dry_run", False)
        synchronous = options.get("synchronous", False)

        # Safety: Limit batch size to prevent memory issues
        max_batch_size = 50000
        if batch_size > max_batch_size:
            logger.warning(f"Batch size {batch_size} exceeds maximum of {max_batch_size}. Using {max_batch_size}.")
            batch_size = max_batch_size

        # Parse model name
        try:
            app_label, model_label = model_name.split(".")
            model = apps.get_model(app_label, model_label)
        except ValueError:
            raise CommandError(f"Model name must be in format 'app_label.model_name', got: {model_name}")
        except LookupError as e:
            raise CommandError(f"Model not found: {e}")

        # Check if model has team_id field
        team_field = None
        if "team_id" in [field.name for field in model._meta.get_fields()]:
            team_field = "team_id"
        elif "team" in [field.name for field in model._meta.get_fields()]:
            team_field = "team"
        else:
            raise CommandError(f"Model {model_name} does not have a team_id or team field")

        # Count total records for this team
        total_count = model.objects.filter(**{team_field: team_id}).count()

        logger.info(f"Found {total_count} records to delete for {model_name} with {team_field}={team_id}")

        # Determine how many records will actually be deleted
        records_to_delete = min(total_count, max_delete_size)

        if total_count > max_delete_size:
            logger.warning(
                f"⚠️  WARNING: Found {total_count:,} total records, but will only delete the first {max_delete_size:,} due to max_delete_size limit."
            )
            logger.warning(f"   Remaining {total_count - max_delete_size:,} records will not be deleted.")

        if dry_run:
            logger.info("DRY RUN: Would start background deletion task")
            logger.info(f"  Model: {model_name}")
            logger.info(f"  Team ID: {team_id}")
            logger.info(f"  Total records found: {total_count}")
            logger.info(f"  Records to delete: {records_to_delete}")
            logger.info(f"  Batch size: {batch_size}")
            return

        # Safety checks and confirmation
        if total_count == 0:
            logger.info("No records found to delete. Exiting.")
            return

        logger.warning(f"⚠️  WARNING: About to delete {records_to_delete:,} records!")
        logger.warning(f"   This is a large deletion operation.")
        logger.warning(f"   Model: {model_name}")
        logger.warning(f"   Team ID: {team_id}")
        logger.warning(f"   Total records found: {total_count}")
        logger.warning(f"   Records to delete: {records_to_delete}")
        logger.warning(f"   Batch size: {batch_size}")

        # Require explicit confirmation for large deletions
        confirm_large = input(f"\nType 'DELETE {records_to_delete:,} RECORDS' to confirm this large deletion: ")
        if confirm_large != f"DELETE {records_to_delete:,} RECORDS":
            logger.info("Large deletion cancelled by user.")
            return

        # Start the background task
        if synchronous:
            logger.info("Running task synchronously")
            background_delete_model_task(
                model_name=model_name, team_id=team_id, batch_size=batch_size, records_to_delete=records_to_delete
            )
            logger.info("Task completed")
        else:
            task = background_delete_model_task.delay(
                model_name=model_name, team_id=team_id, batch_size=batch_size, records_to_delete=records_to_delete
            )
            logger.info(f"Started background deletion task: {task.id}")
            logger.info(f"Model: {model_name}")
            logger.info(f"Team ID: {team_id}")
            logger.info(f"Total records found: {total_count}")
            logger.info(f"Records to delete: {records_to_delete}")
            logger.info(f"Batch size: {batch_size}")
            logger.info(f"Task ID: {task.id}")
