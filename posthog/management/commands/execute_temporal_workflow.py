import asyncio
import logging
from uuid import uuid4

from django.conf import settings
from django.core.management.base import BaseCommand

from posthog.temporal.client import connect
from posthog.temporal.workflows import WORKFLOWS


class Command(BaseCommand):
    help = "Execute Temporal Workflow"

    def add_arguments(self, parser):
        parser.add_argument("workflow", metavar="<WORKFLOW>", help="The name of the workflow to execute")
        parser.add_argument(
            "inputs",
            metavar="INPUTS",
            nargs="*",
            help="Inputs for the workflow to execute",
        )
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
        workflow_name = options["workflow"]

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

        try:
            workflow = [workflow for workflow in WORKFLOWS if workflow.is_named(workflow_name)][0]
        except IndexError:
            raise ValueError(f"No workflow with name '{workflow_name}'")
        except AttributeError:
            raise TypeError(
                f"Workflow '{workflow_name}' is not a CommandableWorkflow that can invoked by execute_temporal_workflow."
            )

        result = asyncio.run(
            client.execute_workflow(
                workflow_name, workflow.parse_inputs(options["inputs"]), id=workflow_id, task_queue=task_queue
            )
        )
        logging.warning(f"Workflow output: {result}")
