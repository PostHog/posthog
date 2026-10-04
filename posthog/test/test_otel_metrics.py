from typing import Any

import pytest
from unittest import mock

from django.test import SimpleTestCase, override_settings

from opentelemetry.metrics import NoOpMeter
from opentelemetry.sdk.metrics.export import MetricExporter, MetricExportResult
from prometheus_client import (
    CollectorRegistry,
    Counter as PromCounter,
    Histogram as PromHistogram,
)

from posthog.otel_metrics import OtelInstrumentFactory, get_otel_meter, reset_otel_metrics_for_tests


class _CapturingExporter(MetricExporter):
    def __init__(self) -> None:
        super().__init__()
        self.exported: list[Any] = []

    def export(self, metrics_data: Any, timeout_millis: float = 10_000, **kwargs: Any) -> MetricExportResult:
        self.exported.append(metrics_data)
        return MetricExportResult.SUCCESS

    def force_flush(self, timeout_millis: float = 10_000) -> bool:
        return True

    def shutdown(self, timeout_millis: float = 30_000, **kwargs: Any) -> None:
        pass


class TestOtelMetrics(SimpleTestCase):
    def setUp(self) -> None:
        reset_otel_metrics_for_tests()
        self.addCleanup(reset_otel_metrics_for_tests)

    def test_unconfigured_is_a_safe_noop(self) -> None:
        assert isinstance(get_otel_meter("test"), NoOpMeter)
        factory = OtelInstrumentFactory("test")
        factory.counter("test_counter_total").add(1, {"a": "b"})
        factory.histogram("test_histogram_seconds", boundaries=(1, 5)).record(0.1)
        factory.gauge("test_gauge").set(3)

    @override_settings(
        OTEL_METRICS_EXPORT_URL="http://capture-logs.local/i/v1/metrics",
        OTEL_METRICS_EXPORT_TOKEN="phc_test",
    )
    def test_configured_records_through_the_sdk_pipeline(self) -> None:
        exporters: list[_CapturingExporter] = []

        def _make_exporter(**kwargs: Any) -> _CapturingExporter:
            assert kwargs["endpoint"] == "http://capture-logs.local/i/v1/metrics"
            assert kwargs["headers"] == {"authorization": "Bearer phc_test"}
            exporter = _CapturingExporter()
            exporters.append(exporter)
            return exporter

        with mock.patch(
            "opentelemetry.exporter.otlp.proto.http.metric_exporter.OTLPMetricExporter",
            side_effect=_make_exporter,
        ):
            meter = get_otel_meter("test")
            assert not isinstance(meter, NoOpMeter)

            factory = OtelInstrumentFactory("test")
            factory.counter("test_counter_total").add(2, {"a": "b"})
            factory.histogram("test_histogram_seconds", boundaries=(1, 5)).record(0.1)
            factory.gauge("test_gauge").set(3)

            # Twins derive their identity from the prom instrument: the counter must get the
            # _total suffix back that prometheus_client strips internally, and the histogram
            # must inherit the prom bucket ladder so the two sinks stay 1:1.
            registry = CollectorRegistry()
            factory.record_counter_twin(PromCounter("twin_probe_total", "d", registry=registry), 3, {"a": "b"})
            factory.record_histogram_twin(
                PromHistogram("twin_probe_seconds", "d", registry=registry, buckets=(0.5, 1, 5)), 0.2, {}
            )

        # Shutdown performs the final collect + export into the capturing exporter.
        reset_otel_metrics_for_tests()

        assert len(exporters) == 1
        exported = {
            metric.name: metric
            for metrics_data in exporters[0].exported
            for resource_metrics in metrics_data.resource_metrics
            for scope_metrics in resource_metrics.scope_metrics
            for metric in scope_metrics.metrics
        }
        assert {
            "test_counter_total",
            "test_histogram_seconds",
            "test_gauge",
            "twin_probe_total",
            "twin_probe_seconds",
        } <= exported.keys()
        twin_histogram_points = exported["twin_probe_seconds"].data.data_points
        assert [list(point.explicit_bounds) for point in twin_histogram_points] == [[0.5, 1, 5]]

    def test_timed_histogram_twin_observes_prom_and_propagates_exceptions(self) -> None:
        registry = CollectorRegistry()
        histogram = PromHistogram("timed_probe_seconds", "d", ["stage"], registry=registry)
        factory = OtelInstrumentFactory("test")

        with pytest.raises(ValueError):
            with factory.timed_histogram_twin(histogram, {"stage": "fetch"}):
                raise ValueError("boom")

        assert registry.get_sample_value("timed_probe_seconds_count", {"stage": "fetch"}) == 1
