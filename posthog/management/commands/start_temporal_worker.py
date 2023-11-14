import asyncio
import logging

import structlog
from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from django.conf import settings
    from django.core.management.base import BaseCommand

from prometheus_client import start_http_server

from posthog.temporal.worker import start_worker


class Command(BaseCommand):
    help = "Start Temporal Python Django-aware Worker"

    def add_arguments(self, parser):
        parser.add_argument(
            "--temporal-host",
            default=settings.TEMPORAL_HOST,
            help="Hostname for Temporal Scheduler",
        )
        parser.add_argument(
            "--temporal-port",
            default=settings.TEMPORAL_PORT,
            help="Port for Temporal Scheduler",
        )
        parser.add_argument(
            "--namespace",
            default=settings.TEMPORAL_NAMESPACE,
            help="Namespace to connect to",
        )
        parser.add_argument(
            "--task-queue",
            default=settings.TEMPORAL_TASK_QUEUE,
            help="Task queue to service",
        )
        parser.add_argument(
            "--server-root-ca-cert",
            default=settings.TEMPORAL_CLIENT_ROOT_CA,
            help="Optional root server CA cert",
        )
        parser.add_argument(
            "--client-cert",
            default=settings.TEMPORAL_CLIENT_CERT,
            help="Optional client cert",
        )
        parser.add_argument(
            "--client-key",
            default=settings.TEMPORAL_CLIENT_KEY,
            help="Optional client key",
        )
        parser.add_argument(
            "--metrics-port",
            default=settings.PROMETHEUS_METRICS_EXPORT_PORT,
            help="Port to export Prometheus metrics on",
        )

    def handle(self, *args, **options):
        temporal_host = options["temporal_host"]
        temporal_port = options["temporal_port"]
        namespace = options["namespace"]
        task_queue = options["task_queue"]
        server_root_ca_cert = options.get("server_root_ca_cert", None)
        client_cert = options.get("client_cert", None)
        client_key = options.get("client_key", None)

        if options["client_key"]:
            options["client_key"] = "--SECRET--"
        logging.info(f"Starting Temporal Worker with options: {options}")

        structlog.reset_defaults()

        metrics_port = int(options["metrics_port"])
        start_http_server(port=metrics_port)

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
