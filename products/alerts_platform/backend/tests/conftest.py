from collections.abc import Iterator

import pytest

import structlog
from opentelemetry import trace
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from structlog.testing import LogCapture
from structlog.typing import EventDict
from temporalio.contrib.opentelemetry import create_tracer_provider

from posthog.temporal.common.logger import configure_logger


@pytest.fixture
def activity_logs(settings) -> Iterator[list[EventDict]]:
    previous_config = structlog.get_config()
    previously_configured = structlog.is_configured()
    capture = LogCapture()
    settings.TEST = True
    settings.TEMPORAL_LOG_LEVEL = "INFO"
    configure_logger(cache_logger_on_first_use=False, otel_log_mirror=capture)
    try:
        yield capture.entries
    finally:
        if previously_configured:
            structlog.configure(**previous_config)
        else:
            structlog.reset_defaults()


@pytest.fixture(scope="module")
def span_exporter() -> Iterator[InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = create_tracer_provider(shutdown_on_exit=False)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(trace, "_TRACER_PROVIDER", provider)
        try:
            yield exporter
        finally:
            provider.shutdown()
