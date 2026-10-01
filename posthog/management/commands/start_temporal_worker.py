import os
import time
import signal
import typing
import asyncio
import datetime as dt
import threading
import dataclasses
import faulthandler

import structlog
from temporalio import workflow

from posthog.temporal.common.open_telemetry import initialize_otel
from posthog.temporal.common.options import (
    ConcurrencyOptions,
    ConnectionOptions,
    MTLSOptions,
    SlotOptions,
    TunerOptions,
    WorkerOptions,
)

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

if typing.TYPE_CHECKING:
    import argparse

    from _typeshed import DataclassInstance


if settings.DEBUG:
    TASK_QUEUE_METRIC_PREFIXES = {}
else:
    TASK_QUEUE_METRIC_PREFIXES = {
        settings.BATCH_EXPORTS_TASK_QUEUE: "batch_exports_",
    }

LOGGER = get_logger(__name__)

_T = typing.TypeVar("_T", bound="DataclassInstance")


def _from_options(dataclass: type[_T], options: dict[str, typing.Any], *, prefix: str = "") -> _T:
    """Consume options to initialize a dataclass.

    Expects options to be already properly parsed.
    """
    names = {f.name for f in dataclasses.fields(dataclass)}
    return dataclass(
        **{
            name: options.pop(f"{prefix}{name}")
            for name in names
            if f"{prefix}{name}" in options and options[f"{prefix}{name}"] is not None
        }
    )


def _try_from_options(dataclass: type[_T], options: dict[str, typing.Any]) -> _T | None:
    try:
        return _from_options(dataclass, options)
    except TypeError:
        return None


def _str_as_timedelta_seconds(s: str) -> dt.timedelta:
    return dt.timedelta(seconds=int(s))


def _str_to_timedelta_milliseconds(s: str) -> dt.timedelta:
    return dt.timedelta(milliseconds=int(s))


class Command(BaseCommand):
    help = "Start Temporal Python Django-aware Worker"

    def add_arguments(self, parser: "argparse.ArgumentParser"):
        parser.add_argument(
            "--temporal-host",
            default=settings.TEMPORAL_HOST,
            help="Hostname for Temporal Scheduler",
            dest="host",
        )
        parser.add_argument(
            "--temporal-port",
            default=settings.TEMPORAL_PORT,
            help="Port for Temporal Scheduler",
            dest="port",
            type=int,
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
            "--client-key", default=settings.TEMPORAL_CLIENT_KEY, help="Optional client key", dest="client_private_key"
        )
        parser.add_argument(
            "--metrics-port",
            default=settings.PROMETHEUS_METRICS_EXPORT_PORT,
            help="Port to export Prometheus metrics on",
        )
        parser.add_argument(
            "--graceful-shutdown-timeout-seconds",
            type=_str_as_timedelta_seconds,
            default=dt.timedelta(seconds=settings.GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS),
            help="Time that the worker will wait after shutdown before canceling activities, in seconds",
            dest="graceful_shutdown_timeout",
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
            "--activity-maximum-slots",
            type=int,
            default=None,
            help="Maximum number of activity task slots for this worker. Requires tuner options to be set",
        )
        parser.add_argument(
            "--activity-minimum-slots",
            type=int,
            default=1,
            help="Minimum number of activity task slots for this worker. Requires tuner options to be set",
        )
        parser.add_argument(
            "--workflow-maximum-slots",
            type=int,
            default=None,
            help="Maximum number of workflow task slots for this worker. Requires tuner options to be set",
        )
        parser.add_argument(
            "--workflow-minimum-slots",
            type=int,
            default=5,
            help="Minimum number of workflow task slots for this worker. Requires tuner options to be set",
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
            type=_str_to_timedelta_milliseconds,
            default=(
                dt.timedelta(milliseconds=settings.TEMPORAL_ACTIVITY_RAMP_THROTTLE_MS)
                if settings.TEMPORAL_ACTIVITY_RAMP_THROTTLE_MS is not None
                else None
            ),
            help="Minimum milliseconds between two activity slot issues when the resource-based tuner is on",
            dest="activity_ramp_throttle",
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
        connection_options = _from_options(ConnectionOptions, options)
        mtls_options = _from_options(MTLSOptions, options)
        worker_options = _from_options(WorkerOptions, options)
        concurrency_options = _from_options(ConcurrencyOptions, options)
        tuner_options: TunerOptions | None = _try_from_options(TunerOptions, options)
        activity_slot_options = _from_options(SlotOptions, options, prefix="activity_")
        workflow_slot_options = _from_options(SlotOptions, options, prefix="workflow_")

        use_pydantic_converter = options["use_pydantic_converter"]
        health_port = options.get("health_port", None)
        health_max_idle_seconds = options.get("health_max_idle_seconds", None)
        disable_combined_metrics_server = options.get("disable_combined_metrics_server", False)

        bag = create_worker_bag_collector().collect(worker_options.task_queue)

        # Data-import source modules import vendor SDKs (google-ads, etc.) at module scope, and those
        # SDKs register protobuf descriptors into a process-global pool that rejects a second
        # registration of the same symbol. They must be imported exactly once per process. Do it here
        # — synchronously, at worker boot, on the main thread — for any queue that runs data syncs.
        # Deferring to the first SourceRegistry.get_source() at runtime (the lazy path) let the
        # registration recur and broke unrelated syncs with "duplicate symbol". Other workers never
        # import the vendor SDKs, so they keep their fast startup.
        if worker_options.task_queue in (
            settings.DATA_WAREHOUSE_TASK_QUEUE,
            settings.DATA_WAREHOUSE_CDP_PRODUCER_TASK_QUEUE,
        ):
            from products.warehouse_sources.backend.facade.temporal import (
                load_all_sources,  # noqa: PLC0415 - keeps vendor SDK imports on data-import workers
            )

            load_all_sources()

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
            or worker_options.task_queue
            in (settings.MAX_AI_TASK_QUEUE, settings.TASKS_TASK_QUEUE, settings.WIZARD_TASK_QUEUE)
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
            if worker_options.task_queue == settings.REPLAY_VISION_TASK_QUEUE:
                from products.replay_vision.backend.temporal.logs import (
                    build_vision_log_mirror,  # noqa: PLC0415 - keeps replay-vision dependencies off other workers
                )

                otel_log_mirror = build_vision_log_mirror()
            configure_logger(loop=loop, otel_log_mirror=otel_log_mirror)

            logger = LOGGER.bind(
                connection=connection_options,
                task_queue=worker_options.task_queue,
                graceful_shutdown_timeout_seconds=worker_options.graceful_shutdown_timeout,
                concurrency=concurrency_options,
                tuner=tuner_options,
                activity_slots=activity_slot_options,
                health_port=health_port,
                health_max_idle_seconds=health_max_idle_seconds,
                combined_metrics_server_enabled=not disable_combined_metrics_server,
            )
            logger.info("Starting Temporal Worker")

            if worker_options.task_queue == settings.SURFACING_SCORING_SWEEP_TASK_QUEUE:
                from posthog.temporal.session_replay.surfacing_scoring_sweep.scorer import warmup_best_effort

                # Best-effort: surfacing shares this queue with the rest of the
                # session-replay worker, so a model problem must not crash the
                # pod. It logs and continues; scoring activities retry until the
                # model is fixed.
                warmup_best_effort()

            worker = runner.run(
                create_worker(
                    connection_options.host,
                    connection_options.port,
                    metrics_port=metrics_port,
                    namespace=connection_options.namespace,
                    task_queue=worker_options.task_queue,
                    server_root_ca_cert=mtls_options.server_root_ca_cert,
                    client_cert=mtls_options.client_cert,
                    client_key=mtls_options.client_private_key,
                    workflows=bag.workflows,
                    activities=bag.activities,
                    graceful_shutdown_timeout=worker_options.graceful_shutdown_timeout,
                    max_concurrent_workflow_tasks=concurrency_options.max_concurrent_workflow_tasks,
                    max_concurrent_activities=concurrency_options.max_concurrent_activities,
                    metric_prefix=TASK_QUEUE_METRIC_PREFIXES.get(worker_options.task_queue, None),
                    use_pydantic_converter=use_pydantic_converter,
                    target_memory_usage=tuner_options.target_memory_usage if tuner_options else None,
                    target_cpu_usage=tuner_options.target_cpu_usage if tuner_options else None,
                    activity_slot_options=activity_slot_options,
                    workflow_slot_options=workflow_slot_options,
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
                if not is_task_queue_supported(worker_options.task_queue, LivenessInterceptor):
                    raise CommandError(
                        f"Refusing to start the health server: task queue '{worker_options.task_queue}' is not covered by "
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
