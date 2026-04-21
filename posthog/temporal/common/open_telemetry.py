import collections.abc

from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import set_tracer_provider
from temporalio.contrib.opentelemetry import create_tracer_provider

from posthog.otel_instrumentation import INSTRUMENTORS


def initialize_otel(service_name: str, libraries_to_instrument: collections.abc.Iterable[str] = ()) -> None:
    """Initialize Open Telemetry for Temporal workers.

    This uses Temporal's replay-safe tracer provider which is meant to work with
    Temporal's `OpenTelemetryPlugin`.
    """
    resource = Resource.create(attributes={"service.name": service_name})
    provider = create_tracer_provider(resource=resource)

    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    set_tracer_provider(provider)

    for lib in libraries_to_instrument:
        if instrument := INSTRUMENTORS.get(lib.lower()):
            instrument(provider)
