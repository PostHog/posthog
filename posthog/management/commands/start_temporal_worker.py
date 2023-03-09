import asyncio

from django.core.management.base import BaseCommand

from posthog.temporal.worker import start_worker


class Command(BaseCommand):
    help = "Start Temporal Python Django-aware Worker"

    def add_arguments(self, parser):
        parser.add_argument("--temporal-host", action="store_true", help="Hostname for Temporal Scheduler")
        parser.add_argument("--temporal-port", action="store_true", help="Port for Temporal Scheduler")

    def handle(self, *args, **options):
        host = "127.0.0.1"
        port = "666"
        asyncio.run(start_worker(host, port))
