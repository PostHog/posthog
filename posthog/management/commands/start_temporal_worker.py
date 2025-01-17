import asyncio
import logging

import structlog
from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from django.conf import settings
    from django.core.management.base import BaseCommand

from posthog.constants import (
    BATCH_EXPORTS_TASK_QUEUE,
    DATA_WAREHOUSE_TASK_QUEUE,
    DATA_WAREHOUSE_TASK_QUEUE_V2,
    GENERAL_PURPOSE_TASK_QUEUE,
    SYNC_BATCH_EXPORTS_TASK_QUEUE,
)
from posthog.temporal.batch_exports import (
    ACTIVITIES as BATCH_EXPORTS_ACTIVITIES,
    WORKFLOWS as BATCH_EXPORTS_WORKFLOWS,
)
from posthog.temporal.common.worker import start_worker
from posthog.temporal.data_imports import ACTIVITIES as DATA_SYNC_ACTIVITIES, WORKFLOWS as DATA_SYNC_WORKFLOWS
from posthog.temporal.data_modeling import ACTIVITIES as DATA_MODELING_ACTIVITIES, WORKFLOWS as DATA_MODELING_WORKFLOWS
from posthog.temporal.delete_persons import (
    ACTIVITIES as DELETE_PERSONS_ACTIVITIES,
    WORKFLOWS as DELETE_PERSONS_WORKFLOWS,
)
from posthog.temporal.proxy_service import ACTIVITIES as PROXY_SERVICE_ACTIVITIES, WORKFLOWS as PROXY_SERVICE_WORKFLOWS

WORKFLOWS_DICT = {
    SYNC_BATCH_EXPORTS_TASK_QUEUE: BATCH_EXPORTS_WORKFLOWS,
    BATCH_EXPORTS_TASK_QUEUE: BATCH_EXPORTS_WORKFLOWS,
    DATA_WAREHOUSE_TASK_QUEUE: DATA_SYNC_WORKFLOWS + DATA_MODELING_WORKFLOWS,
    DATA_WAREHOUSE_TASK_QUEUE_V2: DATA_SYNC_WORKFLOWS + DATA_MODELING_WORKFLOWS,
    GENERAL_PURPOSE_TASK_QUEUE: PROXY_SERVICE_WORKFLOWS + DELETE_PERSONS_WORKFLOWS,
}
ACTIVITIES_DICT = {
    SYNC_BATCH_EXPORTS_TASK_QUEUE: BATCH_EXPORTS_ACTIVITIES,
    BATCH_EXPORTS_TASK_QUEUE: BATCH_EXPORTS_ACTIVITIES,
    DATA_WAREHOUSE_TASK_QUEUE: DATA_SYNC_ACTIVITIES + DATA_MODELING_ACTIVITIES,
    DATA_WAREHOUSE_TASK_QUEUE_V2: DATA_SYNC_ACTIVITIES + DATA_MODELING_ACTIVITIES,
    GENERAL_PURPOSE_TASK_QUEUE: PROXY_SERVICE_ACTIVITIES + DELETE_PERSONS_ACTIVITIES,
}


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
        parser.add_argument(
            "--max-concurrent-workflow-tasks",
            default=settings.MAX_CONCURRENT_WORKFLOW_TASKS,
            help="Maximum number of concurrent workflow tasks for this worker",
        )
        parser.add_argument(
            "--max-concurrent-activities",
            default=settings.MAX_CONCURRENT_ACTIVITIES,
            help="Maximum number of concurrent activity tasks for this worker",
        )

    def handle(self, *args, **options):
        temporal_host = options["temporal_host"]
        temporal_port = options["temporal_port"]
        namespace = options["namespace"]
        task_queue = options["task_queue"]
        server_root_ca_cert = options.get("server_root_ca_cert", None)
        client_cert = options.get("client_cert", None)
        client_key = options.get("client_key", None)
        max_concurrent_workflow_tasks = options.get("max_concurrent_workflow_tasks", None)
        max_concurrent_activities = options.get("max_concurrent_activities", None)

        try:
            workflows = WORKFLOWS_DICT[task_queue]
            activities = ACTIVITIES_DICT[task_queue]
        except KeyError:
            raise ValueError(f'Task queue "{task_queue}" not found in WORKFLOWS_DICT or ACTIVITIES_DICT')

        if options["client_key"]:
            options["client_key"] = "--SECRET--"
        logging.info(f"Starting Temporal Worker with options: {options}")

        structlog.reset_defaults()
        metrics_port = int(options["metrics_port"])

        asyncio.run(
            start_worker(
                temporal_host,
                temporal_port,
                metrics_port=metrics_port,
                namespace=namespace,
                task_queue=task_queue,
                server_root_ca_cert=server_root_ca_cert,
                client_cert=client_cert,
                client_key=client_key,
                workflows=workflows,
                activities=activities,
                max_concurrent_workflow_tasks=max_concurrent_workflow_tasks,
                max_concurrent_activities=max_concurrent_activities,
            )
        )
