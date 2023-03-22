import asyncio
import logging
from datetime import datetime
from uuid import uuid4

from django.conf import settings
from django.core.management.base import BaseCommand

from posthog.temporal.client import connect
from posthog.temporal.workflows import NoOpWorkflow


class Command(BaseCommand):
    help = "Execute Temporal Workflow"

    def add_arguments(self, parser):
        parser.add_argument(
            "--temporal_host", default=settings.TEMPORAL_SCHEDULER_HOST, help="Hostname for Temporal Scheduler"
        )
        parser.add_argument(
            "--temporal_port", default=settings.TEMPORAL_SCHEDULER_PORT, help="Port for Temporal Scheduler"
        )
        parser.add_argument(
            "--task_queue", default=settings.TEMPORAL_TASK_QUEUE, help="Task queue to submit your workflow to"
        )
        parser.add_argument("--namespace", default=settings.TEMPORAL_NAMESPACE, help="Namespace to connect to")
        parser.add_argument("--server-root-ca-cert", help="Optional path to root server CA cert")
        parser.add_argument("--client-cert", help="Optional path to client cert")
        parser.add_argument("--client-key", help="Optional path to client key")

    def handle(self, *args, **options):
        logging.info(f"Executing Temporal Workflow with options: {options}")

        temporal_host = options["temporal_host"]
        temporal_port = options["temporal_port"]
        task_queue = options["task_queue"]
        namespace = options["namespace"]
        server_root_ca_cert = None
        client_cert = None
        client_key = None
        workflow_id = str(uuid4())
        ts = datetime.now().isoformat()

        if options.get("server_root_ca_cert", False):
            with open(options["server_root_ca_cert"], "rb") as f:
                server_root_ca_cert = f.read()
        if options.get("client_cert", False):
            with open(options["client_cert"], "rb") as f:
                client_cert = f.read()
        if options.get("client_key", False):
            with open(options["client_key"], "rb") as f:
                client_key = f.read()

        client = asyncio.run(
            connect(
                temporal_host,
                temporal_port,
                namespace,
                server_root_ca_cert=server_root_ca_cert,
                client_cert=client_cert,
                client_key=client_key,
            )
        )
        result = asyncio.run(client.execute_workflow(NoOpWorkflow.run, ts, id=workflow_id, task_queue=task_queue))
        logging.warning(f"Workflow output: {result}")
