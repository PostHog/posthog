"""FinOps usage meter — accumulates and produces usage meters to the finops pipeline.

Shared by Celery (via the task postrun signal) and Temporal (via the finops interceptor).

Usage meters are internal ops telemetry — dimensionless counts ("task X ran N times for
team Y consuming Z ms") — that feed the FinOps allocation job. They never carry dollars;
pricing is a separate pipeline. See posthog/models/finops/usage_meters.py for the ClickHouse
schema.
"""

from __future__ import annotations

import logging
import datetime as dt
from dataclasses import dataclass
from typing import TYPE_CHECKING

from prometheus_client import Counter

if TYPE_CHECKING:
    from posthog.kafka_client.client import _KafkaProducer

logger = logging.getLogger(__name__)

_queued_counter = Counter(
    "finops_usage_meter_queued_total",
    "FinOps usage meters queued — counted before in-memory dedup.",
    ["product", "billable_unit"],
)

_flushed_counter = Counter(
    "finops_usage_meter_flushed_total",
    "Unique FinOps usage meter rows produced to Kafka after in-memory dedup.",
    ["product", "billable_unit"],
)

_errors_counter = Counter(
    "finops_usage_meter_errors_total",
    "FinOps usage meter errors, swallowed to keep metering non-blocking.",
    ["operation"],
)


@dataclass
class FinopsUsageMeterInput:
    """One usage-meter data point, matching the ClickHouse `usage_meters` schema."""

    product: str
    billable_unit: str
    quantity: float
    team_id: int = 0
    org_id: str = ""
    feature: str = ""
    system: str = ""
    workload: str = ""
    resource_id: str = ""
    duration_ms: float = 0.0
    count: int = 1
    user_id: int = 0


@dataclass
class _AccumulatedMeter:
    product: str
    billable_unit: str
    team_id: int
    org_id: str
    feature: str
    system: str
    workload: str
    resource_id: str
    quantity: float
    duration_ms: float
    count: int
    user_id: int


def _make_key(m: FinopsUsageMeterInput) -> str:
    return ":".join(
        [
            m.product,
            str(m.team_id),
            m.org_id,
            m.feature,
            m.billable_unit,
            m.system,
            m.workload,
            m.resource_id,
            str(m.user_id),
        ]
    )


def _resolve_environment() -> str:
    from posthog.settings.base_variables import CLOUD_DEPLOYMENT

    deployment = (CLOUD_DEPLOYMENT or "").strip().upper()
    if deployment == "US":
        return "prod-us"
    if deployment == "EU":
        return "prod-eu"
    return "dev"


def _resolve_service_name() -> str:
    from django.conf import settings

    return getattr(settings, "OTEL_SERVICE_NAME", None) or ""


class FinopsUsageMeter:
    """Dedupes FinOps usage meters on ``queue``, produces them on ``flush``.

    The caller supplies identity dimensions + a quantity; ``queue()`` accumulates
    (summing quantity, duration_ms, count on matching keys); ``flush()`` drains the
    buffer and produces one JSON row per key to the finops Kafka topic. Fail-safe:
    errors are captured, never raised.
    """

    def __init__(self, *, enabled: bool = False) -> None:
        self._enabled = enabled
        self._buffer: dict[str, _AccumulatedMeter] = {}

    def queue(self, meter: FinopsUsageMeterInput) -> None:
        if not self._enabled:
            return
        try:
            _queued_counter.labels(product=meter.product, billable_unit=meter.billable_unit).inc()
            key = _make_key(meter)
            existing = self._buffer.get(key)
            if existing is not None:
                existing.quantity += meter.quantity
                existing.duration_ms += meter.duration_ms
                existing.count += meter.count
            else:
                self._buffer[key] = _AccumulatedMeter(
                    product=meter.product,
                    billable_unit=meter.billable_unit,
                    team_id=meter.team_id,
                    org_id=meter.org_id,
                    feature=meter.feature,
                    system=meter.system,
                    workload=meter.workload,
                    resource_id=meter.resource_id,
                    quantity=meter.quantity,
                    duration_ms=meter.duration_ms,
                    count=meter.count,
                    user_id=meter.user_id,
                )
        except Exception:
            _errors_counter.labels(operation="queue").inc()
            _capture_exception_safe()

    def flush(self) -> None:
        if not self._enabled or not self._buffer:
            return

        drained = list(self._buffer.values())
        self._buffer.clear()

        try:
            producer = _get_producer()
            timestamp = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M:%S.%f")
            environment = _resolve_environment()
            service_name = _resolve_service_name()

            for m in drained:
                producer.produce(
                    topic=_get_topic(),
                    data={
                        "timestamp": timestamp,
                        "product": m.product,
                        "team_id": m.team_id,
                        "org_id": m.org_id,
                        "feature": m.feature,
                        "environment": environment,
                        "billable_unit": m.billable_unit,
                        "quantity": m.quantity,
                        "system": m.system,
                        "workload": m.workload,
                        "resource_id": m.resource_id,
                        "duration_ms": m.duration_ms,
                        "service_name": service_name,
                        "count": m.count,
                        "user_id": m.user_id,
                    },
                )
                _flushed_counter.labels(product=m.product, billable_unit=m.billable_unit).inc()

            producer.flush(timeout=5.0)
        except Exception:
            _errors_counter.labels(operation="flush").inc()
            _capture_exception_safe()


def _get_topic() -> str:
    from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_FINOPS_USAGE_METERS

    return KAFKA_CLICKHOUSE_FINOPS_USAGE_METERS


def _get_producer() -> _KafkaProducer:
    from posthog.kafka_client.routing import get_producer

    return get_producer(topic=_get_topic())


def _capture_exception_safe() -> None:
    try:
        from posthoganalytics import capture_exception

        capture_exception()
    except Exception:
        logger.exception("Failed to capture finops usage meter exception")
