import logging

from django.core.management.base import BaseCommand

import structlog

from posthog.tasks.tasks import clickhouse_clear_removed_data

logger = structlog.get_logger(__name__)
logger.setLevel(logging.INFO)


class Command(BaseCommand):
    help = (
        "Kick off the job to remove all data associated with a team."
        "Useful when you need data deleted asap (cannot wait for the scheduled job)"
    )

    def handle(self, *args, **options):
        run()


def run():
    logger.info("Starting deletion of data for teams")
    clickhouse_clear_removed_data()
    logger.info("Finished deletion of data for teams")
