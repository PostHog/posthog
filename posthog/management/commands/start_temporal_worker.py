import asyncio

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from django.core.management.base import BaseCommand
    from django.conf import settings

from posthog.temporal.worker import start_worker


class Command(BaseCommand):
    help = "Start Temporal Python Django-aware Worker"
    host = "127.0.0.1"
    port = "7233"

    def _get_django_settings(self):
        self.host = settings.TEMPORAL_SCHEDULER_HOST
        self.port = settings.TEMPORAL_SCHEDULER_PORT

    def add_arguments(self, parser):
        parser.add_argument("--temporal_host", default=self.host, help="Hostname for Temporal Scheduler")
        parser.add_argument("--temporal_port", default=self.port, help="Port for Temporal Scheduler")

    def handle(self, *args, **options):
        asyncio.run(
            start_worker(options["temporal_host"], options["temporal_port"], task_queue=settings.TEMPORAL_TASK_QUEUE)
        )
