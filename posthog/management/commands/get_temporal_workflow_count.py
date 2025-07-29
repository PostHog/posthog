import asyncio
import logging

from django.conf import settings
from django.core.management.base import BaseCommand
from prometheus_client import CollectorRegistry, Gauge, push_to_gateway

from posthog.temporal.common.client import connect


class Command(BaseCommand):
    help = "Get a count of Temporal Workflow executions"

    def add_arguments(self, parser):
        parser.add_argument(
            "--temporal-host",
            default=settings.TEMPORAL_HOST,
            help="Hostname for Temporal Server",
        )
        parser.add_argument(
            "--temporal-port",
            default=settings.TEMPORAL_PORT,
            help="Port for Temporal Server",
        )
        parser.add_argument(
            "--namespace",
            default=settings.TEMPORAL_NAMESPACE,
            help="Namespace to connect to",
        )
        parser.add_argument(
            "--task-queue",
            default=settings.TEMPORAL_TASK_QUEUE,
            help=("Temporal task queue where the Workflow executions to count reside in"),
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
            "--status",
            default="Running",
            help=(
                "Optionally, define which state the Workflow executions to count should "
                "be in. By default, we count 'Running' Workflow executions."
            ),
        )
        parser.add_argument(
            "--gauge",
            default=None,
            help=("Optionally, set a Prometheus gauge to track this count."),
        )

    def handle(self, *args, **options):
        """Get count of Temporal Workflow executions.

        Optionally, track the count in a Prometheus gauge if `--gauge` is set.
        """
        temporal_host = options["temporal_host"]
        temporal_port = options["temporal_port"]
        namespace = options["namespace"]
        task_queue = options["task_queue"]
        server_root_ca_cert = options.get("server_root_ca_cert", None)
        client_cert = options.get("client_cert", None)
        client_key = options.get("client_key", None)
        execution_status = options["status"]
        track_gauge = options.get("gauge", None)

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

        result = asyncio.run(
            client.count_workflows(query=f'`TaskQueue`="{task_queue}" AND `ExecutionStatus`="{execution_status}"')
        )

        if track_gauge and settings.PROM_PUSHGATEWAY_ADDRESS is not None:
            job = f"get_temporal_workflow_count_{task_queue}"
            logging.info(f"Tracking count in Gauge: {track_gauge}. job = {job}")

            registry = CollectorRegistry()
            gauge = Gauge(
                track_gauge,
                f"Number of current Temporal Workflow executions.",
                labelnames=["task_queue", "status"],
                registry=registry,
            )
            gauge.labels(task_queue=task_queue, status=execution_status.lower()).set(result.count)
            push_to_gateway(settings.PROM_PUSHGATEWAY_ADDRESS, job=job, registry=registry)

        logging.info(f"Count of '{execution_status.lower()}' workflows in '{task_queue}': {result.count}")

        return str(result.count)
