import asyncio
import logging

from django.conf import settings
from django.core.management.base import BaseCommand

from posthog.temporal.runner import execute_noop_workflow


class Command(BaseCommand):
    help = "Execute Temporal Workflow"

    def add_arguments(self, parser):
        parser.add_argument(
            "--temporal_host", default=settings.TEMPORAL_SCHEDULER_HOST, help="Hostname for Temporal Scheduler"
        )
        parser.add_argument(
            "--temporal_port", default=settings.TEMPORAL_SCHEDULER_PORT, help="Port for Temporal Scheduler"
        )

    def handle(self, *args, **options):
        logging.info(f"Executing Temporal Workflow with options: {options}")
        output = asyncio.run(execute_noop_workflow(options["temporal_host"], options["temporal_port"]))
        logging.warning(f"Workflow output: {output}")
