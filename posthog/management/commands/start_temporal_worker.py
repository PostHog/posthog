import signal
import asyncio
import datetime as dt
import functools
import faulthandler
from collections import defaultdict

import structlog
from temporalio import workflow
from temporalio.worker import Worker

with workflow.unsafe.imports_passed_through():
    from django.conf import settings
    from django.core.management.base import BaseCommand

from posthog.clickhouse.query_tagging import tag_queries
from posthog.temporal.ai import (
    ACTIVITIES as AI_ACTIVITIES,
    WORKFLOWS as AI_WORKFLOWS,
)
from posthog.temporal.common.logger import configure_logger, get_logger
from posthog.temporal.common.worker import create_worker
from posthog.temporal.data_imports.settings import (
    ACTIVITIES as DATA_SYNC_ACTIVITIES,
    WORKFLOWS as DATA_SYNC_WORKFLOWS,
)
from posthog.temporal.data_modeling import (
    ACTIVITIES as DATA_MODELING_ACTIVITIES,
    WORKFLOWS as DATA_MODELING_WORKFLOWS,
)
from posthog.temporal.delete_persons import (
    ACTIVITIES as DELETE_PERSONS_ACTIVITIES,
    WORKFLOWS as DELETE_PERSONS_WORKFLOWS,
)
from posthog.temporal.delete_recordings import (
    ACTIVITIES as DELETE_RECORDING_ACTIVITIES,
    WORKFLOWS as DELETE_RECORDING_WORKFLOWS,
)
from posthog.temporal.enforce_max_replay_retention import (
    ACTIVITIES as ENFORCE_MAX_REPLAY_RETENTION_ACTIVITIES,
    WORKFLOWS as ENFORCE_MAX_REPLAY_RETENTION_WORKFLOWS,
)
from posthog.temporal.exports_video import (
    ACTIVITIES as VIDEO_EXPORT_ACTIVITIES,
    WORKFLOWS as VIDEO_EXPORT_WORKFLOWS,
)
from posthog.temporal.llm_analytics import (
    ACTIVITIES as LLM_ANALYTICS_ACTIVITIES,
    WORKFLOWS as LLM_ANALYTICS_WORKFLOWS,
)
from posthog.temporal.messaging import (
    ACTIVITIES as MESSAGING_ACTIVITIES,
    WORKFLOWS as MESSAGING_WORKFLOWS,
)
from posthog.temporal.product_analytics import (
    ACTIVITIES as PRODUCT_ANALYTICS_ACTIVITIES,
    WORKFLOWS as PRODUCT_ANALYTICS_WORKFLOWS,
)
from posthog.temporal.proxy_service import (
    ACTIVITIES as PROXY_SERVICE_ACTIVITIES,
    WORKFLOWS as PROXY_SERVICE_WORKFLOWS,
)
from posthog.temporal.quota_limiting import (
    ACTIVITIES as QUOTA_LIMITING_ACTIVITIES,
    WORKFLOWS as QUOTA_LIMITING_WORKFLOWS,
)
from posthog.temporal.salesforce_enrichment import (
    ACTIVITIES as SALESFORCE_ENRICHMENT_ACTIVITIES,
    WORKFLOWS as SALESFORCE_ENRICHMENT_WORKFLOWS,
)
from posthog.temporal.subscriptions import (
    ACTIVITIES as SUBSCRIPTION_ACTIVITIES,
    WORKFLOWS as SUBSCRIPTION_WORKFLOWS,
)
from posthog.temporal.tests.utils.workflow import (
    ACTIVITIES as TEST_ACTIVITIES,
    WORKFLOWS as TEST_WORKFLOWS,
)
from posthog.temporal.usage_reports import (
    ACTIVITIES as USAGE_REPORTS_ACTIVITIES,
    WORKFLOWS as USAGE_REPORTS_WORKFLOWS,
)
from posthog.temporal.weekly_digest import (
    ACTIVITIES as WEEKLY_DIGEST_ACTIVITIES,
    WORKFLOWS as WEEKLY_DIGEST_WORKFLOWS,
)

from products.batch_exports.backend.temporal import (
    ACTIVITIES as BATCH_EXPORTS_ACTIVITIES,
    WORKFLOWS as BATCH_EXPORTS_WORKFLOWS,
)
from products.tasks.backend.temporal import (
    ACTIVITIES as TASKS_ACTIVITIES,
    WORKFLOWS as TASKS_WORKFLOWS,
)

# Note: When running locally, many task queues resolve to the same queue name.
# If we used plain dict literals, later entries would overwrite earlier ones for
# the same queue. We aggregate with defaultdict(set) so all workflows/activities
# registered for a shared queue name are combined, ensuring the worker registers
# everything it should.
_workflows = defaultdict(set)
_workflows[settings.SYNC_BATCH_EXPORTS_TASK_QUEUE].update(BATCH_EXPORTS_WORKFLOWS)
_workflows[settings.BATCH_EXPORTS_TASK_QUEUE].update(BATCH_EXPORTS_WORKFLOWS)
_workflows[settings.DATA_WAREHOUSE_TASK_QUEUE].update(DATA_SYNC_WORKFLOWS + DATA_MODELING_WORKFLOWS)
_workflows[settings.DATA_WAREHOUSE_COMPACTION_TASK_QUEUE].update(DATA_SYNC_WORKFLOWS + DATA_MODELING_WORKFLOWS)
_workflows[settings.DATA_MODELING_TASK_QUEUE].update(DATA_MODELING_WORKFLOWS)
_workflows[settings.GENERAL_PURPOSE_TASK_QUEUE].update(
    PROXY_SERVICE_WORKFLOWS
    + DELETE_PERSONS_WORKFLOWS
    + USAGE_REPORTS_WORKFLOWS
    + SALESFORCE_ENRICHMENT_WORKFLOWS
    + PRODUCT_ANALYTICS_WORKFLOWS
    + LLM_ANALYTICS_WORKFLOWS
)
_workflows[settings.ANALYTICS_PLATFORM_TASK_QUEUE].update(SUBSCRIPTION_WORKFLOWS)
_workflows[settings.TASKS_TASK_QUEUE].update(TASKS_WORKFLOWS)
_workflows[settings.MAX_AI_TASK_QUEUE].update(AI_WORKFLOWS)
_workflows[settings.TEST_TASK_QUEUE].update(TEST_WORKFLOWS)
_workflows[settings.BILLING_TASK_QUEUE].update(QUOTA_LIMITING_WORKFLOWS + SALESFORCE_ENRICHMENT_WORKFLOWS)
_workflows[settings.VIDEO_EXPORT_TASK_QUEUE].update(VIDEO_EXPORT_WORKFLOWS)
_workflows[settings.SESSION_REPLAY_TASK_QUEUE].update(
    DELETE_RECORDING_WORKFLOWS + ENFORCE_MAX_REPLAY_RETENTION_WORKFLOWS
)
_workflows[settings.MESSAGING_TASK_QUEUE].update(MESSAGING_WORKFLOWS)
_workflows[settings.WEEKLY_DIGEST_TASK_QUEUE].update(WEEKLY_DIGEST_WORKFLOWS)
WORKFLOWS_DICT = dict(_workflows)

_activities = defaultdict(set)
_activities[settings.SYNC_BATCH_EXPORTS_TASK_QUEUE].update(BATCH_EXPORTS_ACTIVITIES)
_activities[settings.BATCH_EXPORTS_TASK_QUEUE].update(BATCH_EXPORTS_ACTIVITIES)
_activities[settings.DATA_WAREHOUSE_TASK_QUEUE].update(DATA_SYNC_ACTIVITIES + DATA_MODELING_ACTIVITIES)
_activities[settings.DATA_WAREHOUSE_COMPACTION_TASK_QUEUE].update(DATA_SYNC_ACTIVITIES + DATA_MODELING_ACTIVITIES)
_activities[settings.DATA_MODELING_TASK_QUEUE].update(DATA_MODELING_ACTIVITIES)
_activities[settings.GENERAL_PURPOSE_TASK_QUEUE].update(
    PROXY_SERVICE_ACTIVITIES
    + DELETE_PERSONS_ACTIVITIES
    + USAGE_REPORTS_ACTIVITIES
    + QUOTA_LIMITING_ACTIVITIES
    + SALESFORCE_ENRICHMENT_ACTIVITIES
    + PRODUCT_ANALYTICS_ACTIVITIES
    + LLM_ANALYTICS_ACTIVITIES
)
_activities[settings.ANALYTICS_PLATFORM_TASK_QUEUE].update(SUBSCRIPTION_ACTIVITIES)
_activities[settings.TASKS_TASK_QUEUE].update(TASKS_ACTIVITIES)
_activities[settings.MAX_AI_TASK_QUEUE].update(AI_ACTIVITIES)
_activities[settings.TEST_TASK_QUEUE].update(TEST_ACTIVITIES)
_activities[settings.BILLING_TASK_QUEUE].update(QUOTA_LIMITING_ACTIVITIES + SALESFORCE_ENRICHMENT_ACTIVITIES)
_activities[settings.VIDEO_EXPORT_TASK_QUEUE].update(VIDEO_EXPORT_ACTIVITIES)
_activities[settings.SESSION_REPLAY_TASK_QUEUE].update(
    DELETE_RECORDING_ACTIVITIES + ENFORCE_MAX_REPLAY_RETENTION_ACTIVITIES
)
_activities[settings.MESSAGING_TASK_QUEUE].update(MESSAGING_ACTIVITIES)
_activities[settings.WEEKLY_DIGEST_TASK_QUEUE].update(WEEKLY_DIGEST_ACTIVITIES)
ACTIVITIES_DICT = dict(_activities)

if settings.DEBUG:
    TASK_QUEUE_METRIC_PREFIXES = {}
else:
    TASK_QUEUE_METRIC_PREFIXES = {
        settings.BATCH_EXPORTS_TASK_QUEUE: "batch_exports_",
    }

LOGGER = get_logger(__name__)


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
            "--graceful-shutdown-timeout-seconds",
            default=settings.GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS,
            help="Time that the worker will wait after shutdown before canceling activities, in seconds",
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
        parser.add_argument(
            "--use-pydantic-converter",
            action="store_true",
            default=settings.TEMPORAL_USE_PYDANTIC_CONVERTER,
            help="Use Pydantic data converter for this worker",
        )

    def handle(self, *args, **options):
        temporal_host = options["temporal_host"]
        temporal_port = options["temporal_port"]
        namespace = options["namespace"]
        task_queue = options["task_queue"]
        server_root_ca_cert = options.get("server_root_ca_cert", None)
        client_cert = options.get("client_cert", None)
        client_key = options.get("client_key", None)
        graceful_shutdown_timeout_seconds = options.get("graceful_shutdown_timeout_seconds", None)
        max_concurrent_workflow_tasks = options.get("max_concurrent_workflow_tasks", None)
        max_concurrent_activities = options.get("max_concurrent_activities", None)
        use_pydantic_converter = options["use_pydantic_converter"]

        try:
            workflows = list(WORKFLOWS_DICT[task_queue])
            activities = list(ACTIVITIES_DICT[task_queue])
        except KeyError:
            raise ValueError(f'Task queue "{task_queue}" not found in WORKFLOWS_DICT or ACTIVITIES_DICT')

        if options["client_key"]:
            options["client_key"] = "--SECRET--"

        structlog.reset_defaults()

        # enable faulthandler to print stack traces on segfaults
        faulthandler.enable()

        metrics_port = int(options["metrics_port"])

        shutdown_task = None

        tag_queries(kind="temporal")

        def shutdown_worker_on_signal(worker: Worker, sig: signal.Signals, loop: asyncio.AbstractEventLoop):
            """Shutdown Temporal worker on receiving signal."""
            nonlocal shutdown_task

            logger.info("Signal %s received", sig)

            if worker.is_shutdown:
                logger.info("Temporal worker already shut down")
                return

            logger.info("Initiating Temporal worker shutdown")
            shutdown_task = loop.create_task(worker.shutdown())

        with asyncio.Runner() as runner:
            loop = runner.get_loop()

            configure_logger(loop=loop)
            logger = LOGGER.bind(
                host=temporal_host,
                port=temporal_port,
                namespace=namespace,
                task_queue=task_queue,
                graceful_shutdown_timeout_seconds=graceful_shutdown_timeout_seconds,
                max_concurrent_workflow_tasks=max_concurrent_workflow_tasks,
                max_concurrent_activities=max_concurrent_activities,
            )
            logger.info("Starting Temporal Worker")

            worker = runner.run(
                create_worker(
                    temporal_host,
                    temporal_port,
                    metrics_port=metrics_port,
                    namespace=namespace,
                    task_queue=task_queue,
                    server_root_ca_cert=server_root_ca_cert,
                    client_cert=client_cert,
                    client_key=client_key,
                    workflows=workflows,  # type: ignore
                    activities=activities,
                    graceful_shutdown_timeout=(
                        dt.timedelta(seconds=graceful_shutdown_timeout_seconds)
                        if graceful_shutdown_timeout_seconds is not None
                        else None
                    ),
                    max_concurrent_workflow_tasks=max_concurrent_workflow_tasks,
                    max_concurrent_activities=max_concurrent_activities,
                    metric_prefix=TASK_QUEUE_METRIC_PREFIXES.get(task_queue, None),
                    use_pydantic_converter=use_pydantic_converter,
                )
            )

            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(
                    sig,
                    functools.partial(shutdown_worker_on_signal, worker=worker, sig=sig, loop=loop),
                )

            runner.run(worker.run())

            if shutdown_task:
                logger.info("Waiting on shutdown_task")
                _ = runner.run(asyncio.wait([shutdown_task]))
                logger.info("Finished Temporal worker shutdown")
