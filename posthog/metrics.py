# Shared metrics and labels for prometheus metrics
from contextlib import contextmanager

import structlog
from prometheus_client import CollectorRegistry, push_to_gateway
from sentry_sdk import capture_exception

logger = structlog.get_logger(__name__)

__doc__ = """
This module holds common labels, metrics and helpers for Prometheus instrumentation.

- Common label names should be imported from this module for consistency across metrics.
- Metrics should be declared in the same file than the code that sets them,
  but they could be declared here if set from several code paths.
"""

# Common metric labels
LABEL_TEAM_ID = "team_id"


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

    from posthog.settings import PROM_PUSHGATEWAY_ADDRESS

    registry = CollectorRegistry()
    yield registry
    try:
        if PROM_PUSHGATEWAY_ADDRESS:
            push_to_gateway(PROM_PUSHGATEWAY_ADDRESS, job=job_name, registry=registry)
    except Exception as err:
        logger.error("push_to_gateway", target=PROM_PUSHGATEWAY_ADDRESS, exception=err)
        capture_exception(err)
