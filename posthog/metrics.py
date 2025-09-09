# Shared metrics and labels for prometheus metrics
from contextlib import contextmanager

from django.conf import settings

import structlog
from prometheus_client import CollectorRegistry, Counter, push_to_gateway

from posthog.exceptions_capture import capture_exception

logger = structlog.get_logger(__name__)

__doc__ = """
This module holds common labels, metrics and helpers for Prometheus instrumentation.

- Common label names should be imported from this module for consistency across metrics.
- Metrics should be declared in the same file than the code that sets them,
  but they could be declared here if set from several code paths.
"""

# Common metric labels
LABEL_PATH = "path"
LABEL_ROUTE = "route"
LABEL_RESOURCE_TYPE = "resource_type"
LABEL_TEAM_ID = "team_id"

KLUDGES_COUNTER = Counter(
    "posthog_kludges_total",
    "Tracking code paths eligible for deletion if they are not used.",
    labelnames=["kludge"],
)


def _push(settings, job, registry):
    push_to_gateway(settings, job, registry)


@contextmanager
def pushed_metrics_registry(job_name: str):
    """
    Return a temporary Prometheus registry that will be pushed to the
    PushGateway when the context closes.

    Parameter job_name: a unique job name to use, all metrics previously
    pushed with that name will be deleted.

    NOTE: only use to expose gauges, for use cases where one value per
    region makes sense (e.g. instance metrics computed by celery jobs).
    """

    registry = CollectorRegistry()
    yield registry
    try:
        if settings.PROM_PUSHGATEWAY_ADDRESS:
            _push(settings.PROM_PUSHGATEWAY_ADDRESS, job=job_name, registry=registry)
    except Exception as err:
        logger.exception("push_to_gateway", target=settings.PROM_PUSHGATEWAY_ADDRESS, exception=err)
        capture_exception(err)
