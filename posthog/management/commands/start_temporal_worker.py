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
        parser.add_argument("--namespace", default=settings.TEMPORAL_NAMESPACE, help="Namespace to connect to")
        parser.add_argument("--task-queue", default=settings.TEMPORAL_TASK_QUEUE, help="Task queue to service")
        parser.add_argument("--server-root-ca-cert", help="Optional path to root server CA cert")
        parser.add_argument("--client-cert", help="Optional path to client cert")
        parser.add_argument("--client-key", help="Optional path to client key")

    def handle(self, *args, **options):
        logging.info(f"Starting Temporal Worker with options: {options}")

        temporal_host = options["temporal_host"]
        temporal_port = options["temporal_port"]
        namespace = options["namespace"]
        task_queue = options["task_queue"]
        server_root_ca_cert = None
        client_cert = None
        client_key = None

        if options.get("server_root_ca_cert", False):
            with open(options["server_root_ca_cert"], "rb") as f:
                server_root_ca_cert = f.read()
        if options.get("client_cert", False):
            with open(options["client_cert"], "rb") as f:
                client_cert = f.read()
        if options.get("client_key", False):
            with open(options["client_key"], "rb") as f:
                client_key = f.read()

        asyncio.run(
            start_worker(
                temporal_host,
                temporal_port,
                namespace=namespace,
                task_queue=task_queue,
                server_root_ca_cert=server_root_ca_cert,
                client_cert=client_cert,
                client_key=client_key,
            )
        )
