"""OpenTelemetry instruments for the tracked HTTP transport.

Cardinality is bounded by `(team_id, source_type, host, status_class)`.
Schema id, job id, and the full URL deliberately do not appear as metric
labels — they live in logs only.

`workflow.metric_meter()` is only valid inside a Temporal workflow or
activity. Outside of that — for example a unit test that directly drives
the transport without spinning up Temporal — the helpers fall back to
no-op recorders so that tests don't have to mock the workflow runtime.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol

from temporalio import workflow

if TYPE_CHECKING:
    from temporalio.common import MetricCounter, MetricHistogram

logger = logging.getLogger(__name__)


class _NullCounter:
    def add(self, value: int, additional_attributes: dict[str, Any] | None = None) -> None:
        return None


class _NullHistogram:
    def record(self, value: int, additional_attributes: dict[str, Any] | None = None) -> None:
        return None


class _CounterLike(Protocol):
    def add(self, value: int, additional_attributes: dict[str, Any] | None = None) -> None: ...


class _HistogramLike(Protocol):
    def record(self, value: int, additional_attributes: dict[str, Any] | None = None) -> None: ...


def _safe_metric_meter() -> Any | None:
    try:
        return workflow.metric_meter()
    except Exception:
        # Not inside a workflow / activity — fall through to no-op recorders.
        return None


def get_http_requests_counter(team_id: int, source_type: str) -> _CounterLike | MetricCounter:
    meter = _safe_metric_meter()
    if meter is None:
        return _NullCounter()
    return meter.with_additional_attributes({"team_id": str(team_id), "source_type": source_type}).create_counter(
        "data_import_http_requests_total",
        "Outbound HTTP requests issued by warehouse source syncs.",
    )


def get_http_response_bytes_histogram(team_id: int, source_type: str) -> _HistogramLike | MetricHistogram:
    meter = _safe_metric_meter()
    if meter is None:
        return _NullHistogram()
    return meter.with_additional_attributes({"team_id": str(team_id), "source_type": source_type}).create_histogram(
        "data_import_http_response_bytes",
        "Size of outbound HTTP response bodies in bytes.",
        unit="By",
    )


def get_http_latency_histogram(team_id: int, source_type: str) -> _HistogramLike | MetricHistogram:
    meter = _safe_metric_meter()
    if meter is None:
        return _NullHistogram()
    return meter.with_additional_attributes({"team_id": str(team_id), "source_type": source_type}).create_histogram(
        "data_import_http_latency_ms",
        "Outbound HTTP round-trip latency in milliseconds.",
        unit="ms",
    )


def status_class(status_code: int | None) -> str:
    if status_code is None:
        return "error"
    if 200 <= status_code < 300:
        return "2xx"
    if 300 <= status_code < 400:
        return "3xx"
    if 400 <= status_code < 500:
        return "4xx"
    if 500 <= status_code < 600:
        return "5xx"
    return "other"
