import asyncio
import logging
from uuid import uuid4

from django.conf import settings
from django.core.management.base import BaseCommand
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

from posthog.temporal.batch_exports import WORKFLOWS as BATCH_EXPORT_WORKFLOWS
from posthog.temporal.common.client import connect
from posthog.temporal.data_imports.settings import WORKFLOWS as DATA_IMPORT_WORKFLOWS
from posthog.temporal.delete_persons import WORKFLOWS as DELETE_PERSONS_WORKFLOWS
from posthog.temporal.proxy_service import WORKFLOWS as PROXY_SERVICE_WORKFLOWS
from posthog.temporal.usage_reports import WORKFLOWS as USAGE_REPORTS_WORKFLOWS
from posthog.temporal.quota_limiting import WORKFLOWS as QUOTA_LIMITING_WORKFLOWS
from posthog.temporal.ai import WORKFLOWS as AI_WORKFLOWS


class Command(BaseCommand):
    help = "Start Temporal Workflow"

    def add_arguments(self, parser):
        parser.add_argument("workflow", metavar="<WORKFLOW>", help="The name of the workflow to start")
        parser.add_argument(
            "inputs",
            metavar="INPUTS",
            nargs="*",
            help="Inputs for the workflow to start",
        )
        parser.add_argument(
            "--workflow-id",
            default=str(uuid4()),
            help=(
                "Optionally, set an id for this workflow. If the ID is already in use, "
                "the workflow will not start unless it failed. If not used, a random UUID "
                "will be used as the workflow ID, which means the workflow will always start. "
                "Set an ID in order to limit concurrency."
            ),
        )
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
            help=(
                "Temporal task queue that will handle the Workflow. This should be a "
                "task queue that is configured to run the Workflow, as different task "
                "queues are used for different workflows."
            ),
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
            "--max-attempts",
            default=settings.TEMPORAL_WORKFLOW_MAX_ATTEMPTS,
            help="Number of max attempts",
        )

    def handle(self, *args, **options):
        temporal_host = options["temporal_host"]
        temporal_port = options["temporal_port"]
        namespace = options["namespace"]
        task_queue = options["task_queue"]
        server_root_ca_cert = options.get("server_root_ca_cert", None)
        client_cert = options.get("client_cert", None)
        client_key = options.get("client_key", None)
        workflow_id = options["workflow_id"]
        workflow_name = options["workflow"]

        if options["client_key"]:
            options["client_key"] = "--SECRET--"

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
        retry_policy = RetryPolicy(maximum_attempts=int(options["max_attempts"]))

        WORKFLOWS = (
            BATCH_EXPORT_WORKFLOWS
            + DATA_IMPORT_WORKFLOWS
            + PROXY_SERVICE_WORKFLOWS
            + DELETE_PERSONS_WORKFLOWS
            + USAGE_REPORTS_WORKFLOWS
            + QUOTA_LIMITING_WORKFLOWS
            + AI_WORKFLOWS
        )
        try:
            workflow = next(workflow for workflow in WORKFLOWS if workflow.is_named(workflow_name))
        except StopIteration:
            raise ValueError(f"No workflow with name '{workflow_name}'")
        except AttributeError:
            raise TypeError(
                f"Workflow '{workflow_name}' is not a `PostHogWorkflow` that can invoked by `start_temporal_workflow`."
            )

        logging.info("Starting Temporal Workflow %s with ID %s", workflow_name, workflow_id)
        asyncio.run(
            client.start_workflow(
                workflow_name,
                workflow.parse_inputs(options["inputs"]),
                id=workflow_id,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                task_queue=task_queue,
                retry_policy=retry_policy,
            )
        )
