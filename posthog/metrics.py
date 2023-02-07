# Shared metrics and labels for prometheus metrics
from contextlib import contextmanager

import structlog
from prometheus_client import CollectorRegistry, push_to_gateway
from sentry_sdk import capture_exception

from posthog.settings import PROM_PUSHGATEWAY_ADDRESS

logger = structlog.get_logger(__name__)

# Common label names

LABEL_TEAM_ID = "team_id"


#
@contextmanager
def pushed_metrics_registry(job_name: str):
    registry = CollectorRegistry()
    yield registry
    try:
        if PROM_PUSHGATEWAY_ADDRESS:
            push_to_gateway(PROM_PUSHGATEWAY_ADDRESS, job=job_name, registry=registry)
    except Exception as err:
        logger.error("push_to_gateway", target=PROM_PUSHGATEWAY_ADDRESS, exception=err)
        capture_exception(err)
