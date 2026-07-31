from __future__ import annotations

import os
import time
import errno
import threading
from typing import TYPE_CHECKING

from django.dispatch import receiver

import structlog
from celery import Celery
from celery.signals import (
    celeryd_init,
    setup_logging,
    task_failure,
    task_postrun,
    task_prerun,
    task_retry,
    task_success,
    worker_process_init,
    worker_process_shutdown,
)
from django_structlog.celery import signals
from django_structlog.celery.steps import DjangoStructLogInitStep
from opentelemetry import trace
from prometheus_client import Counter, Histogram, start_http_server

if TYPE_CHECKING:
    from posthog.finops.usage_meter import FinopsUsageMeter

# When PROMETHEUS_MULTIPROC_DIR is set (by bin/docker-worker-celery),
# prometheus_client uses file-backed storage so all prefork children's
# metrics are aggregated into a single /metrics endpoint.  Without it,
# only the one child that binds port 8001 is visible to Prometheus.
_PROMETHEUS_MULTIPROC_DIR = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
if _PROMETHEUS_MULTIPROC_DIR:
    os.makedirs(_PROMETHEUS_MULTIPROC_DIR, exist_ok=True)

logger = structlog.get_logger(__name__)


# set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")


app = Celery("posthog")

CELERY_TASK_PRE_RUN_COUNTER = Counter(
    "posthog_celery_task_pre_run",
    "task prerun signal is dispatched before a task is executed.",
    labelnames=["task_name"],
)

CELERY_TASK_SUCCESS_COUNTER = Counter(
    "posthog_celery_task_success",
    "task success signal is dispatched when a task succeeds.",
    labelnames=["task_name"],
)

CELERY_TASK_FAILURE_COUNTER = Counter(
    "posthog_celery_task_failure",
    "task failure signal is dispatched when a task succeeds.",
    labelnames=["task_name"],
)

CELERY_TASK_RETRY_COUNTER = Counter(
    "posthog_celery_task_retry",
    "task retry signal is dispatched when a task will be retried.",
    labelnames=["task_name", "reason"],  # Attention: Keep reason as low cardinality as possible
)


CELERY_TASK_DURATION_HISTOGRAM = Histogram(
    "posthog_celery_task_duration_seconds",
    "Time spent running a task",
    labelnames=["task_name"],
    buckets=(1, 5, 10, 30, 60, 120, 600, 1200, float("inf")),
)

CELERY_TASK_INITIALIZATION_FAILURE_COUNTER = Counter(
    "posthog_celery_task_initialization_failure",
    "Number of times task initialization failed",
)


# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Load task modules from all registered Django app configs.
app.autodiscover_tasks()

# Make sure Redis doesn't add too many connections
# https://stackoverflow.com/questions/47106592/redis-connections-not-being-released-after-celery-task-is-complete
app.conf.broker_pool_limit = 0

if app.steps:
    app.steps["worker"].add(DjangoStructLogInitStep)

task_timings: dict[str, float] = {}

# Lazily initialized at worker_process_init; None when metering is disabled.
_finops_meter: FinopsUsageMeter | None = None


def _initialize_worker_metrics() -> None:
    """Initialize metrics that need to survive pod restarts."""
    # Only initialize cohort metrics on long-running workers that handle cohort calculations
    if not _is_longrunning_worker():
        return

    try:
        # Initialize cohort backlog metric from database state
        from posthog.tasks.calculate_cohort import (
            COHORT_RECALCULATIONS_BACKLOG_GAUGE,
            get_cohort_calculation_candidates_queryset,
        )

        backlog = get_cohort_calculation_candidates_queryset().count()
        COHORT_RECALCULATIONS_BACKLOG_GAUGE.set(backlog)

        logger.info("worker_metrics_initialized", cohort_backlog=backlog)
    except Exception as e:
        # Don't let metric initialization break worker startup
        logger.warning("failed_to_initialize_worker_metrics", error=str(e))


def _is_longrunning_worker() -> bool:
    """Check if this is a long-running worker that handles cohort calculations."""
    from posthog.tasks.utils import CeleryQueue

    # Check if LONG_RUNNING queue is in the worker's queue list
    worker_queues = os.environ.get("CELERY_WORKER_QUEUES", "").split(",")
    return CeleryQueue.LONG_RUNNING.value in worker_queues


@setup_logging.connect
def receiver_setup_logging(loglevel, logfile, format, colorize, **kwargs) -> None:
    from logging import config as logging_config

    from posthog.settings import logs

    # following instructions from here https://django-structlog.readthedocs.io/en/latest/celery.html
    logging_config.dictConfig(logs.LOGGING)


@receiver(signals.bind_extra_task_metadata)
def receiver_bind_extra_request_metadata(sender, signal, task=None, logger=None):
    import structlog

    if task:
        structlog.contextvars.bind_contextvars(task_name=task.name)


@celeryd_init.connect
def on_celeryd_init(**kwargs) -> None:
    """Clean stale prometheus multiproc files from a previous run."""
    if not _PROMETHEUS_MULTIPROC_DIR:
        return
    logger.info("prometheus_multiproc_cleanup_start", directory=_PROMETHEUS_MULTIPROC_DIR)
    removed = 0
    try:
        for entry in os.scandir(_PROMETHEUS_MULTIPROC_DIR):
            if entry.is_file(follow_symlinks=False) and entry.name.endswith(".db"):
                os.unlink(entry.path)
                removed += 1
    except OSError as e:
        logger.warning("prometheus_multiproc_cleanup_failed", error=str(e))
    logger.info("prometheus_multiproc_cleanup_done", removed=removed)


def _tag_celery_span_with_team_id(task_kwargs: dict | None) -> None:
    """Tag the active Celery task span (created by CeleryInstrumentor) with team_id, read
    best-effort from the task's keyword arguments. Coverage is partial by design: only tasks
    invoked with an explicit ``team_id=`` keyword are tagged. No-op when the span isn't recording."""
    try:
        team_id = (task_kwargs or {}).get("team_id")
        if not isinstance(team_id, int) or isinstance(team_id, bool):
            return
        span = trace.get_current_span()
        if span.is_recording():
            span.set_attribute("team_id", team_id)
    except Exception:
        pass


def _celery_team_id_prerun_receiver(task_id=None, task=None, args=None, kwargs=None, **_) -> None:
    _tag_celery_span_with_team_id(kwargs)


@worker_process_init.connect
def on_worker_start(**kwargs) -> None:
    from posthoganalytics import setup

    from posthog.otel_instrumentation import (
        initialize_otel,  # noqa: PLC0415 — keep the OTel stack off the celery import path; only the worker child loads it
    )

    setup()  # makes sure things like exception autocapture are initialised

    # Initialize tracing in the forked worker child (not at import / pre-fork): the
    # BatchSpanProcessor's export thread and gRPC channel do not survive fork(), so the
    # provider must be created per child. This also enables CeleryInstrumentor, which starts
    # a span per task. No-op when OTEL_SDK_DISABLED is set.
    initialize_otel()
    # Connect the team_id tagger AFTER initialize_otel (which instruments Celery) so Celery
    # dispatches it after CeleryInstrumentor's own prerun receiver — the task span is the
    # active span by then. Degrades to a no-op if that ordering ever changes.
    task_prerun.connect(_celery_team_id_prerun_receiver, weak=False)

    port = int(os.getenv("CELERY_METRICS_PORT", "8001"))
    try:
        if _PROMETHEUS_MULTIPROC_DIR:
            from prometheus_client import CollectorRegistry, multiprocess

            registry = CollectorRegistry()
            multiprocess.MultiProcessCollector(registry)
            start_http_server(port, registry=registry)
        else:
            start_http_server(port)
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE:
            logger.warning("metrics_server_start_failed", port=port, error=str(exc))

    # Initialize metrics that need to survive pod restarts
    _initialize_worker_metrics()

    # Initialize FinOps usage meter (fail-safe — never breaks worker startup)
    _initialize_finops_meter()


_ANALYTICS_METRICS_FLUSH_TIMEOUT_SECONDS = 5.0


@worker_process_shutdown.connect
def on_worker_process_shutdown(**kwargs) -> None:
    """Remove metric files for this child so recycled workers don't leak stale data."""
    if _PROMETHEUS_MULTIPROC_DIR:
        from prometheus_client import multiprocess

        multiprocess.mark_process_dead(os.getpid())

    # Flush the posthoganalytics SDK's final metrics window: `client.metrics`
    # aggregates in memory and flushes on an interval, so a recycled child
    # (--max-tasks-per-child) would otherwise drop up to one interval of samples.
    # Inert on SDK versions without the metrics API and on untouched/disabled clients.
    import posthoganalytics  # noqa: PLC0415 — keep the SDK off the celery import path

    try:
        client = posthoganalytics.default_client
        metrics = getattr(client, "metrics", None) if client is not None else None
        if metrics is not None:
            # Bound the wait: an unreachable metrics endpoint must not hold a
            # recycling child hostage (same hazard otel_instrumentation.py caps
            # with a 5s force_flush). The daemon thread is abandoned on timeout.
            def _flush() -> None:
                try:
                    metrics.flush()
                except Exception:
                    logger.warning("posthoganalytics_metrics_flush_failed", exc_info=True)

            flush_thread = threading.Thread(target=_flush, name="posthoganalytics-metrics-flush", daemon=True)
            flush_thread.start()
            flush_thread.join(timeout=_ANALYTICS_METRICS_FLUSH_TIMEOUT_SECONDS)
            if flush_thread.is_alive():
                logger.warning("posthoganalytics_metrics_flush_timed_out")
    except Exception:
        logger.warning("posthoganalytics_metrics_flush_failed", exc_info=True)


def _initialize_finops_meter() -> None:
    """Create the FinOps usage meter singleton if metering is enabled."""
    global _finops_meter
    try:
        from django.conf import settings

        if not getattr(settings, "CELERY_FINOPS_USAGE_METERS_ENABLED", False):
            return
        from posthog.finops.usage_meter import FinopsUsageMeter  # noqa: PLC0415

        _finops_meter = FinopsUsageMeter(enabled=True)
        logger.info("finops_usage_meter_initialized")
    except Exception:
        logger.warning("finops_usage_meter_init_failed", exc_info=True)


def _extract_celery_team_id(kwargs: dict | None) -> int:
    """Extract team_id from task kwargs, returning 0 when unavailable."""
    try:
        team_id = (kwargs or {}).get("team_id")
        if isinstance(team_id, int) and not isinstance(team_id, bool):
            return team_id
    except Exception:
        pass
    return 0


def _extract_celery_user_id() -> int:
    """Read user_id from structlog contextvars, set by django_structlog when
    the task was dispatched from an HTTP request. Returns 0 for periodic tasks
    or tasks without request context."""
    try:
        import structlog as _structlog  # noqa: PLC0415

        ctx = _structlog.contextvars.get_merged_contextvars(_structlog.get_logger())
        user_id = ctx.get("user_id")
        if isinstance(user_id, int) and not isinstance(user_id, bool):
            return user_id
    except Exception:
        pass
    return 0


def _emit_finops_meter(task_name: str, task_kwargs: dict | None, duration_ms: float, queue: str) -> None:
    """Emit a FinOps usage meter for a completed Celery task. Fail-safe: never raises."""
    meter = _finops_meter
    if meter is None:
        return
    try:
        from posthog.finops.celery_task_product_map import resolve_celery_task_product  # noqa: PLC0415
        from posthog.finops.usage_meter import FinopsUsageMeterInput  # noqa: PLC0415

        task_product = resolve_celery_task_product(task_name)
        meter.queue(
            FinopsUsageMeterInput(
                product=task_product.product,
                billable_unit=task_product.billable_unit,
                quantity=1,
                team_id=_extract_celery_team_id(task_kwargs),
                user_id=_extract_celery_user_id(),
                system="celery",
                workload=task_name,
                resource_id=queue,
                duration_ms=duration_ms,
            )
        )
        meter.flush()
    except Exception:
        pass


# Set up clickhouse query instrumentation
@task_prerun.connect
def prerun_signal_handler(task_id, task, **kwargs):
    from statshog.defaults.django import statsd

    from posthog.clickhouse.client.connection import Workload, set_default_clickhouse_workload_type
    from posthog.clickhouse.query_tagging import tag_queries

    statsd.incr("celery_tasks_metrics.pre_run", tags={"name": task.name})
    tag_queries(kind="celery", id=task.name)
    set_default_clickhouse_workload_type(Workload.OFFLINE)

    task_timings[task_id] = time.time()

    CELERY_TASK_PRE_RUN_COUNTER.labels(task_name=task.name).inc()


@task_postrun.connect
def postrun_signal_handler(task_id, task, args=None, kwargs=None, **_):
    from posthog.clickhouse.query_tagging import reset_query_tags

    duration_ms = 0.0
    if task_id in task_timings:
        start_time = task_timings.pop(task_id, None)
        if start_time:
            elapsed = time.time() - start_time
            CELERY_TASK_DURATION_HISTOGRAM.labels(task_name=task.name).observe(elapsed)
            duration_ms = elapsed * 1000

    queue = ""
    try:
        queue = task.request.delivery_info.get("routing_key", "")
    except Exception:
        pass

    _emit_finops_meter(task.name, kwargs, duration_ms, queue)

    reset_query_tags()


@task_success.connect
def success_signal_handler(sender, **kwargs):
    CELERY_TASK_SUCCESS_COUNTER.labels(task_name=sender.name).inc()


@task_failure.connect
def failure_signal_handler(sender, **kwargs):
    CELERY_TASK_FAILURE_COUNTER.labels(task_name=sender.name).inc()


@task_retry.connect
def retry_signal_handler(sender, reason, **kwargs):
    # Make reason low cardinality (e.g. only the exception type)
    reason = reason.__class__.__name__
    CELERY_TASK_RETRY_COUNTER.labels(task_name=sender.name, reason=reason).inc()


@app.on_after_finalize.connect
def setup_periodic_tasks(sender: Celery, **kwargs):
    from posthog.tasks.scheduled import setup_periodic_tasks

    try:
        setup_periodic_tasks(sender)
    except Exception as exc:
        # Setup fails silently. Alert the team if a configuration error is detected in periodic tasks.
        CELERY_TASK_INITIALIZATION_FAILURE_COUNTER.inc()
        logger.exception("Periodic tasks setup failed", exception=exc)
