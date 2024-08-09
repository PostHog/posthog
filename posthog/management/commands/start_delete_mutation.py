import logging

import structlog
from django.core.management.base import BaseCommand

from posthog.tasks.tasks import clickhouse_clear_removed_data

logger = structlog.get_logger(__name__)
logger.setLevel(logging.INFO)


class Command(BaseCommand):
    help = (
        "Kick off the job to remove all data associated with a team."
        "Useful when you need data deleted asap (cannot wait for the scheduled job)"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", default=False, type=bool, help="Don't run the delete, just print out the delete statement"
        )

    def handle(self, *args, **kwargs):
        run(**kwargs)


def run(dry_run):
    logger.info("Starting deletion of data for teams")
    clickhouse_clear_removed_data(dry_run)
    logger.info("Finished deletion of data for teams")
