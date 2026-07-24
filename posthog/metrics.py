# Shared metrics and labels for prometheus metrics
from contextlib import contextmanager
from typing import TypeVar

from django.conf import settings

import structlog

# Patch prometheus_client to bypass HTTP_PROXY/HTTPS_PROXY for pushgateway calls.
# The pushgateway is an internal service — the outbound proxy would reject it.
# ProxyHandler({}) tells urllib to ignore proxy env vars.
import prometheus_client.exposition as _expo
from prometheus_client import REGISTRY, CollectorRegistry, Counter, push_to_gateway
from prometheus_client.metrics import MetricWrapperBase

from posthog.exceptions_capture import capture_exception

_MetricT = TypeVar("_MetricT", bound=MetricWrapperBase)

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

TOMBSTONE_COUNTER = Counter(
    "posthog_tombstone_total",
    "Rare anomalous events that should almost never occur. Used to track edge cases, cleanup operations finding stale data, and other scenarios that indicate potential bugs or race conditions. Details (team_id, flag_id, etc.) are logged separately to avoid high-cardinality labels.",
    labelnames=["namespace", "operation", "component"],
)


def get_or_create_metric(metric_cls: type[_MetricT], name: str, documentation: str, **kwargs) -> _MetricT:
    """Idempotently define a Prometheus metric against the global registry.

    Module-level ``Histogram(...)`` / ``Counter(...)`` calls run again whenever their module
    is re-imported — for example when a partially-completed import is retried after an earlier
    ``ImportError`` left the collectors already registered. The second definition would raise
    ``Duplicated timeseries in CollectorRegistry``, masking the real import failure with a
    confusing error. Reuse the collector already registered under ``name`` instead.
    """
    try:
        return metric_cls(name, documentation, **kwargs)
    except ValueError:
        existing = REGISTRY._names_to_collectors.get(name)
        if isinstance(existing, metric_cls):
            return existing
        raise


def _make_handler_no_proxy(url, method, timeout, headers, data, base_handler):
    from urllib.request import ProxyHandler, Request, build_opener

    def handle():
        request = Request(url, data=data, method=method)
        for k, v in headers:
            request.add_header(k, v)
        resp = build_opener(ProxyHandler({}), base_handler).open(request, timeout=timeout)
        if resp.code >= 400:
            raise OSError(f"error talking to pushgateway: {resp.code} {resp.msg}")

    return handle


_expo._make_handler = _make_handler_no_proxy  # ty: ignore[invalid-assignment]


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
            push_to_gateway(settings.PROM_PUSHGATEWAY_ADDRESS, job=job_name, registry=registry)
    except Exception as err:
        logger.exception("push_to_gateway", target=settings.PROM_PUSHGATEWAY_ADDRESS, exception=err)
        capture_exception(err)
