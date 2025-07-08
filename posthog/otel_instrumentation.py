import logging
import os

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.django import DjangoInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
from opentelemetry.instrumentation.kafka import KafkaInstrumentor
from opentelemetry.instrumentation.aiokafka import AIOKafkaInstrumentor

import structlog

# Get a structlog logger for this module's own messages
logger = structlog.get_logger(__name__)


def _otel_django_request_hook(span, request):
    if span and span.is_recording():
        actual_path = request.path
        http_method = request.method
        span.set_attribute("http.method", http_method)
        span.set_attribute("http.url", actual_path)
        # span.update_name(f"{http_method} {actual_path}") # Use with caution - high cardinality


def _otel_django_response_hook(span, request, response):
    if span and span.is_recording():
        span.set_attribute("http.status_code", response.status_code)


def initialize_otel():
    # --- BEGIN FORCED OTEL DEBUG LOGGING ---
    otel_python_log_level_env = os.environ.get("OTEL_PYTHON_LOG_LEVEL", "info").lower()
    effective_log_level = logging.DEBUG if otel_python_log_level_env == "debug" else logging.INFO

    root_logger = logging.getLogger()
    # Set root logger level only if we are making it more verbose than it might already be.
    # Or if it's not set (None), then set it.
    # This avoids overriding a potentially more restrictive level set elsewhere.
    if root_logger.level == logging.NOTSET or effective_log_level < root_logger.level:
        root_logger.setLevel(effective_log_level)

    django_instr_logger = logging.getLogger("opentelemetry.instrumentation.django")
    django_instr_logger.setLevel(logging.DEBUG)  # Force this to DEBUG
    django_instr_logger.propagate = True  # Ensure its messages go to root handlers for structlog processing

    logger.info(
        "otel_sdk_logging_config_from_instrumentation_module",
        note="Configured OTel SDK log levels. Formatting via django-structlog.",
        root_logger_current_level=logging.getLevelName(root_logger.level),
        root_logger_target_level=logging.getLevelName(effective_log_level),
        django_instrumentor_logger_target_level="DEBUG",
        otel_python_log_level_env=otel_python_log_level_env,
    )
    # --- END FORCED OTEL DEBUG LOGGING ---

    if os.environ.get("OTEL_SDK_DISABLED", "false").lower() != "true":
        service_name = os.environ.get("OTEL_SERVICE_NAME", "posthog-django-default")
        resource = Resource.create(attributes={"service.name": service_name})

        # Let OpenTelemetry SDK handle sampling configuration via OTEL_TRACES_SAMPLER and OTEL_TRACES_SAMPLER_ARG
        # This allows parentbased_traceidratio and other standard sampler types
        sampler_type = os.environ.get("OTEL_TRACES_SAMPLER", "parentbased_traceidratio")  # Respect parent decisions
        sampler_arg = os.environ.get("OTEL_TRACES_SAMPLER_ARG", "0")

        logger.info(
            "otel_sampler_configured",
            sampler_type=sampler_type,
            sampler_arg=sampler_arg if sampler_arg else "default",
            note="Using OpenTelemetry standard sampling configuration",
            source_module="otel_instrumentation",
        )

        provider = TracerProvider(resource=resource)
        otlp_exporter = OTLPSpanExporter()  # Assumes OTLP endpoint is configured via env vars
        processor = BatchSpanProcessor(otlp_exporter)
        provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)
        logger.info(
            "otel_core_components_initialized_successfully",
            service_name=service_name,
            source_module="otel_instrumentation",
        )

        try:
            DjangoInstrumentor().instrument(
                tracer_provider=provider,
                request_hook=_otel_django_request_hook,
                response_hook=_otel_django_response_hook,
            )
            logger.info("otel_instrumentation_attempt", instrumentor="DjangoInstrumentor", status="success")
        except Exception as e:
            logger.exception(
                "otel_instrumentation_attempt", instrumentor="DjangoInstrumentor", status="error", exc_info=e
            )

        try:
            RedisInstrumentor().instrument(tracer_provider=provider)
            logger.info("otel_instrumentation_attempt", instrumentor="RedisInstrumentor", status="success")
        except Exception as e:
            logger.exception(
                "otel_instrumentation_attempt", instrumentor="RedisInstrumentor", status="error", exc_info=e
            )

        try:
            PsycopgInstrumentor().instrument(tracer_provider=provider, enable_commenter=False)
            logger.info(
                "otel_instrumentation_attempt",
                instrumentor="PsycopgInstrumentor",
                status="success",
                note="SQLCommenter enabled for diagnostics",
            )
        except Exception as e:
            logger.exception(
                "otel_instrumentation_attempt", instrumentor="PsycopgInstrumentor", status="error", exc_info=e
            )

        try:
            KafkaInstrumentor().instrument(tracer_provider=provider)
            logger.info("otel_instrumentation_attempt", instrumentor="KafkaInstrumentor", status="success")
        except Exception as e:
            logger.exception(
                "otel_instrumentation_attempt", instrumentor="KafkaInstrumentor", status="error", exc_info=e
            )

        try:
            AIOKafkaInstrumentor().instrument(tracer_provider=provider)
            logger.info("otel_instrumentation_attempt", instrumentor="AIOKafkaInstrumentor", status="success")
        except Exception as e:
            logger.exception(
                "otel_instrumentation_attempt", instrumentor="AIOKafkaInstrumentor", status="error", exc_info=e
            )

        logger.info(
            "otel_manual_init_status_from_instrumentation_module",
            service_name=service_name,
            detail="OpenTelemetry manually initialized with hooks (no manual middleware entry in settings.MIDDLEWARE)",
        )
    else:
        logger.info(
            "otel_manual_init_status_from_instrumentation_module",
            status="disabled",
            reason="OTEL_SDK_DISABLED environment variable is set to true",
        )
