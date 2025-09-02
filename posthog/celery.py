import os
import time

from django.dispatch import receiver

import structlog
from celery import Celery
from celery.signals import (
    setup_logging,
    task_failure,
    task_postrun,
    task_prerun,
    task_retry,
    task_success,
    worker_process_init,
)
from django_structlog.celery import signals
from django_structlog.celery.steps import DjangoStructLogInitStep
from prometheus_client import Counter, Histogram

from posthog.cloud_utils import is_cloud

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

app.steps["worker"].add(DjangoStructLogInitStep)

task_timings: dict[str, float] = {}


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


@worker_process_init.connect
def on_worker_start(**kwargs) -> None:
    from posthoganalytics import setup
    from prometheus_client import start_http_server

    setup()  # makes sure things like exception autocapture are initialised
    start_http_server(int(os.getenv("CELERY_METRICS_PORT", "8001")))


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
def postrun_signal_handler(task_id, task, **kwargs):
    from posthog.clickhouse.query_tagging import reset_query_tags

    if task_id in task_timings:
        start_time = task_timings.pop(task_id, None)
        if start_time:
            CELERY_TASK_DURATION_HISTOGRAM.labels(task_name=task.name).observe(time.time() - start_time)

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
    from posthog.pagerduty.pd import create_incident
    from posthog.tasks.scheduled import setup_periodic_tasks

    try:
        setup_periodic_tasks(sender)
    except Exception as exc:
        # Setup fails silently. Alert the team if a configuration error is detected in periodic tasks.
        if is_cloud():
            create_incident(
                f"Periodic tasks setup failed: {exc}",
                "posthog.celery.setup_periodic_tasks",
                "critical",
            )
        else:
            logger.exception("Periodic tasks setup failed", exception=exc)
