import os
import time
import signal
import asyncio
import datetime as dt
import threading
import faulthandler

import structlog
from temporalio import workflow

from posthog.temporal.common.open_telemetry import initialize_otel

with workflow.unsafe.imports_passed_through():
    from django.conf import settings
    from django.core.management.base import BaseCommand, CommandError

from posthog.clickhouse.query_tagging import tag_queries
from posthog.temporal.common.health_server import HealthCheckServer
from posthog.temporal.common.interceptor import is_task_queue_supported
from posthog.temporal.common.liveness_tracker import LivenessInterceptor, get_liveness_tracker
from posthog.temporal.common.logger import configure_logger, get_logger
from posthog.temporal.common.shutdown import ShutdownSignalListener
from posthog.temporal.common.worker import ManagedWorker, create_worker
from posthog.temporal.registry import create_worker_bag_collector

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
            default=None,
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
            type=int,
            default=settings.GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS,
            help="Time that the worker will wait after shutdown before canceling activities, in seconds",
        )
        parser.add_argument(
            "--max-concurrent-workflow-tasks",
            type=int,
            default=settings.MAX_CONCURRENT_WORKFLOW_TASKS,
            help="Maximum number of concurrent workflow tasks for this worker",
        )
        parser.add_argument(
            "--max-concurrent-activities",
            type=int,
            default=settings.MAX_CONCURRENT_ACTIVITIES,
            help="Maximum number of concurrent activity tasks for this worker",
        )
        parser.add_argument(
            "--use-pydantic-converter",
            action="store_true",
            default=settings.TEMPORAL_USE_PYDANTIC_CONVERTER,
            help="Use Pydantic data converter for this worker",
        )
        parser.add_argument(
            "--target-memory-usage",
            type=float,
            default=settings.TEMPORAL_TARGET_MEMORY_USAGE,
            help="Fraction of available memory to use",
        )
        parser.add_argument(
            "--target-cpu-usage",
            type=float,
            default=settings.TEMPORAL_TARGET_CPU_USAGE,
            help="Fraction of available CPU to use",
        )
        parser.add_argument(
            "--activity-ramp-throttle-ms",
            type=int,
            default=settings.TEMPORAL_ACTIVITY_RAMP_THROTTLE_MS,
            help="Minimum milliseconds between two activity slot issues when the resource-based tuner is on",
        )
        parser.add_argument(
            "--health-port",
            type=int,
            default=settings.TEMPORAL_HEALTH_PORT,
            help="Port for health check endpoints (/healthz, /readyz)",
        )
        parser.add_argument(
            "--health-max-idle-seconds",
            type=float,
            default=settings.TEMPORAL_HEALTH_MAX_IDLE_SECONDS,
            help="Maximum seconds without workflow/activity execution before unhealthy",
        )
        parser.add_argument(
            "--disable-combined-metrics-server",
            action="store_true",
            default=not settings.TEMPORAL_COMBINED_METRICS_SERVER_ENABLED,
            help="Disable the combined metrics server (useful for workers with GIL contention issues)",
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
        target_memory_usage = options.get("target_memory_usage", None)
        target_cpu_usage = options.get("target_cpu_usage", None)
        activity_ramp_throttle_ms = options.get("activity_ramp_throttle_ms", None)
        health_port = options.get("health_port", None)
        health_max_idle_seconds = options.get("health_max_idle_seconds", None)
        disable_combined_metrics_server = options.get("disable_combined_metrics_server", False)

        bag = create_worker_bag_collector().collect(task_queue)

        # Data-import source modules import vendor SDKs (google-ads, etc.) at module scope, and those
        # SDKs register protobuf descriptors into a process-global pool that rejects a second
        # registration of the same symbol. They must be imported exactly once per process. Do it here
        # — synchronously, at worker boot, on the main thread — for any queue that runs data syncs.
        # Deferring to the first SourceRegistry.get_source() at runtime (the lazy path) let the
        # registration recur and broke unrelated syncs with "duplicate symbol". Other workers never
        # import the vendor SDKs, so they keep their fast startup.
        if task_queue in (
            settings.DATA_WAREHOUSE_TASK_QUEUE,
            settings.DATA_WAREHOUSE_CDP_PRODUCER_TASK_QUEUE,
        ):
            from products.warehouse_sources.backend.facade.temporal import (
                load_all_sources,  # noqa: PLC0415 - keeps vendor SDK imports on data-import workers
            )

            load_all_sources()

        if options["client_key"]:
            options["client_key"] = "--SECRET--"

        structlog.reset_defaults()

        # enable faulthandler to print stack traces on segfaults
        faulthandler.enable()

        metrics_port = int(options["metrics_port"])

        shutdown_task = None
        health_server: HealthCheckServer | None = None

        tag_queries(kind="temporal")

        # Max AI, tasks-agent, and wizard traces span the Django request and the Temporal activity that runs
        # the agent loop. Without the OTel plugin on the worker, every span emitted from an activity
        # is a root span and the conversation trace splits across disconnected pieces. Force-enable
        # for these queues so investigations don't depend on an operator flipping
        # TEMPORAL_OTEL_PLUGIN_ENABLED.
        enable_otel = (
            settings.TEMPORAL_OTEL_PLUGIN_ENABLED is True
            or task_queue in (settings.MAX_AI_TASK_QUEUE, settings.TASKS_TASK_QUEUE, settings.WIZARD_TASK_QUEUE)
        ) and settings.OTEL_SERVICE_NAME is not None
        if enable_otel is True:
            # Mypy doesn't understand we have already checked settings.OTEL_SERVICE_NAME
            initialize_otel(settings.OTEL_SERVICE_NAME, settings.TEMPORAL_OTEL_LIBRARIES_TO_INSTRUMENT)  # type: ignore

        async def shutdown_all(
            worker: ManagedWorker, health_srv: HealthCheckServer | None, sig: signal.Signals
        ) -> None:
            """Shutdown worker and health server."""
            nonlocal shutdown_task

            logger.info("Signal %s received", sig)

            if worker.is_shutdown():
                logger.info("Temporal worker already shut down")
                return

            logger.info("Initiating shutdown")

            # Each activity that runs now holds this pod until it returns or the graceful shutdown
            # timeout ends, so this list shows what a slow shutdown waits on.
            running_activities = get_liveness_tracker().get_running_activities()
            now = time.time()
            logger.info("Activities running at shutdown", count=len(running_activities))
            for running in running_activities:
                logger.info(
                    "Activity running at shutdown",
                    activity_type=running.activity_type,
                    workflow_type=running.workflow_type,
                    workflow_id=running.workflow_id,
                    attempt=running.attempt,
                    running_seconds=round(now - running.started_at),
                )

            # Shutdown health server first so k8s stops sending traffic
            if health_srv:
                await health_srv.stop()

            # Then shutdown the worker
            await worker.shutdown()

        def shutdown_on_signal(
            worker: ManagedWorker,
            health_srv: HealthCheckServer | None,
            sig: signal.Signals,
            loop: asyncio.AbstractEventLoop,
        ):
            """Signal handler that initiates shutdown."""
            nonlocal shutdown_task

            if shutdown_task is None:
                shutdown_task = loop.create_task(shutdown_all(worker, health_srv, sig))

        with asyncio.Runner() as runner:
            loop = runner.get_loop()
            otel_log_mirror = None
            if task_queue == settings.REPLAY_VISION_TASK_QUEUE:
                from products.replay_vision.backend.temporal.logs import (
                    build_vision_log_mirror,  # noqa: PLC0415 - keeps replay-vision dependencies off other workers
                )

                otel_log_mirror = build_vision_log_mirror()
            configure_logger(loop=loop, otel_log_mirror=otel_log_mirror)

            logger = LOGGER.bind(
                host=temporal_host,
                port=temporal_port,
                namespace=namespace,
                task_queue=task_queue,
                graceful_shutdown_timeout_seconds=graceful_shutdown_timeout_seconds,
                max_concurrent_workflow_tasks=max_concurrent_workflow_tasks,
                max_concurrent_activities=max_concurrent_activities,
                target_memory_usage=target_memory_usage,
                target_cpu_usage=target_cpu_usage,
                activity_ramp_throttle_ms=activity_ramp_throttle_ms,
                health_port=health_port,
                health_max_idle_seconds=health_max_idle_seconds,
                combined_metrics_server_enabled=not disable_combined_metrics_server,
            )
            logger.info("Starting Temporal Worker")

            if task_queue == settings.SURFACING_SCORING_SWEEP_TASK_QUEUE:
                from posthog.temporal.session_replay.surfacing_scoring_sweep.scorer import warmup_best_effort

                # Best-effort: surfacing shares this queue with the rest of the
                # session-replay worker, so a model problem must not crash the
                # pod. It logs and continues; scoring activities retry until the
                # model is fixed.
                warmup_best_effort()

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
                    workflows=bag.workflows,
                    activities=bag.activities,
                    graceful_shutdown_timeout=(
                        dt.timedelta(seconds=graceful_shutdown_timeout_seconds)
                        if graceful_shutdown_timeout_seconds is not None
                        else None
                    ),
                    max_concurrent_workflow_tasks=max_concurrent_workflow_tasks,
                    max_concurrent_activities=max_concurrent_activities,
                    metric_prefix=TASK_QUEUE_METRIC_PREFIXES.get(task_queue, None),
                    use_pydantic_converter=use_pydantic_converter,
                    target_memory_usage=target_memory_usage,
                    target_cpu_usage=target_cpu_usage,
                    activity_ramp_throttle=(
                        dt.timedelta(milliseconds=activity_ramp_throttle_ms)
                        if activity_ramp_throttle_ms is not None
                        else None
                    ),
                    enable_combined_metrics_server=not disable_combined_metrics_server,
                    enable_open_telemetry_plugin=enable_otel,
                )
            )

            # Create and start health check server
            if health_port and health_max_idle_seconds:
                # Without the liveness interceptor nothing ever feeds the tracker, so `idle_seconds`
                # is just process uptime and the probe 503s at `max_idle_seconds` on a perfectly
                # healthy worker — k8s then reaps every replica on a fixed cycle. Refuse to serve a
                # probe that can only ever fail; a worker that won't start is far louder than one
                # that restarts forever.
                if not is_task_queue_supported(task_queue, LivenessInterceptor):
                    raise CommandError(
                        f"Refusing to start the health server: task queue '{task_queue}' is not covered by "
                        f"LivenessInterceptor, so /healthz would report process uptime as idle time and fail "
                        f"after {health_max_idle_seconds}s regardless of worker health. Add the queue to "
                        f"LivenessInterceptor.task_queue, or unset TEMPORAL_HEALTH_PORT / "
                        f"TEMPORAL_HEALTH_MAX_IDLE_SECONDS for this deployment."
                    )

                health_server = HealthCheckServer(
                    port=health_port,
                    liveness_tracker=get_liveness_tracker(),
                    max_idle_seconds=health_max_idle_seconds,
                )
                runner.run(health_server.start())
            else:
                logger.warning(
                    f"No healthcheck server due to health_port={health_port} and health_max_idle_seconds={health_max_idle_seconds}"
                )

            signal_listener = ShutdownSignalListener()
            signal_listener.install()

            async def run_until_worker_stops() -> None:
                async def shut_down_on_first_signal() -> None:
                    sig = await signal_listener.wait()
                    shutdown_on_signal(worker=worker, health_srv=health_server, sig=sig, loop=loop)

                signal_watcher = asyncio.create_task(shut_down_on_first_signal())
                try:
                    await worker.run()
                finally:
                    _ = signal_watcher.cancel()

            runner.run(run_until_worker_stops())

            if shutdown_task:
                logger.info("Waiting on shutdown_task")
                _ = runner.run(asyncio.wait([shutdown_task]))
                logger.info("Finished Temporal worker shutdown")

                logger.info("Listing active threads at shutdown:")
                for t in threading.enumerate():
                    logger.info(
                        "Thread still alive at shutdown",
                        thread_name=t.name,
                        daemon=t.daemon,
                        ident=t.ident,
                    )

                # _something_ is preventing clean exit after worker shutdown
                logger.info("Temporal Worker has shut down, starting hard exit timer of 5 mins")

                def hard_exit():
                    logger.info("Hard exiting")
                    os._exit(0)

                timer = threading.Timer(60 * 5, hard_exit)
                timer.daemon = True
                timer.start()
