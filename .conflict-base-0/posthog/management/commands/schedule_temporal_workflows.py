from django.core.management.base import BaseCommand

import structlog

from posthog.temporal.schedule import init_schedules

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Schedule Temporal Workflows"

    def handle(self, *args, **options):
        logger.info("Scheduling Temporal Workflows...")
        init_schedules()
        logger.info("Done")
