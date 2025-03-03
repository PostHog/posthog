import logging

from django.core.management.base import BaseCommand

from posthog.temporal.schedule import init_schedules


class Command(BaseCommand):
    help = "Schedule Temporal Workflows"

    def handle(self, *args, **options):
        logging.info("Scheduling Temporal Workflows...")
        init_schedules()
        logging.info("Done")
