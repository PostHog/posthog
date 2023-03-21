import asyncio
import logging

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from django.core.management.base import BaseCommand
    from django.conf import settings

from posthog.temporal.worker import start_worker


class Command(BaseCommand):
    help = "Start Temporal Python Django-aware Worker"

    def add_arguments(self, parser):
        parser.add_argument(
            "--temporal_host", default=settings.TEMPORAL_SCHEDULER_HOST, help="Hostname for Temporal Scheduler"
        )
        parser.add_argument(
            "--temporal_port", default=settings.TEMPORAL_SCHEDULER_PORT, help="Port for Temporal Scheduler"
        )

    def handle(self, *args, **options):
        logging.info(f"Starting Temporal Worker with options: {options}")
        asyncio.run(
            start_worker(options["temporal_host"], options["temporal_port"], task_queue=settings.TEMPORAL_TASK_QUEUE)
        )
