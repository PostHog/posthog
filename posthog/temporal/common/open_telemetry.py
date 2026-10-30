import collections.abc
from typing import TYPE_CHECKING

from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk import trace as trace_sdk
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Tracer, set_tracer_provider
from opentelemetry.util import types
from temporalio.contrib.opentelemetry import ReplaySafeTracerProvider, create_tracer_provider

from posthog.otel_instrumentation import INSTRUMENTORS

if TYPE_CHECKING:
    from temporalio.contrib.opentelemetry._id_generator import TemporalIdGenerator


class CachingReplaySafeTracerProvider(ReplaySafeTracerProvider):
    """Replay-safe tracer provider that returns one cached tracer for each instrumentation scope.

    The OpenTelemetry SDK calls `warnings.filterwarnings` in every `get_tracer` call, and
    Temporal's `OpenTelemetryPlugin` calls `get_tracer` for every span that it starts in workflow code.
    Each `filterwarnings` call takes the process-wide warnings lock and clears every warning registry,
    so each later warning is printed again while a thread holds that lock.
    When the Temporal deadlock detector interrupts a workflow thread that waits for that lock,
    the interrupt can arrive after the thread gets the lock and before the `with` block starts.
    The lock then stays held, and every thread in the process that warns or changes a filter blocks.
    """

    def __init__(self, tracer_provider: trace_sdk.TracerProvider, id_generator: "TemporalIdGenerator") -> None:
        super().__init__(tracer_provider, id_generator)
        self._tracers: dict[tuple[str, str | None, str | None], Tracer] = {}

    @classmethod
    def create(cls, resource: Resource) -> "CachingReplaySafeTracerProvider":
        # create_tracer_provider sets up the TemporalIdGenerator that replay safety needs, so wrap its SDK provider.
        provider = create_tracer_provider(resource=resource)
        return cls(provider._tracer_provider, provider.id_generator())

    def get_tracer(
        self,
        instrumenting_module_name: str,
        instrumenting_library_version: str | None = None,
        schema_url: str | None = None,
        attributes: types.Attributes | None = None,
    ) -> Tracer:
        # A mapping of attributes is not hashable, so a call with attributes does not use the cache.
        if attributes:
            return super().get_tracer(instrumenting_module_name, instrumenting_library_version, schema_url, attributes)

        key = (instrumenting_module_name, instrumenting_library_version, schema_url)
        tracer = self._tracers.get(key)
        if tracer is None:
            tracer = self._tracers.setdefault(key, super().get_tracer(*key))
        return tracer


def initialize_otel(service_name: str, libraries_to_instrument: collections.abc.Iterable[str] = ()) -> None:
    """Initialize Open Telemetry for Temporal workers.

    This uses Temporal's replay-safe tracer provider which is meant to work with
    Temporal's `OpenTelemetryPlugin`.
    """
    resource = Resource.create(attributes={"service.name": service_name})
    provider = CachingReplaySafeTracerProvider.create(resource)

    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    set_tracer_provider(provider)

    for lib in libraries_to_instrument:
        if instrument := INSTRUMENTORS.get(lib.lower()):
            instrument(provider)
