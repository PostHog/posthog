# posthog/test/test_otel_instrumentation.py
from unittest import mock
import logging
import os


from posthog.otel_instrumentation import initialize_otel, _otel_django_request_hook, _otel_django_response_hook
from posthog.test.base import BaseTest


class TestOtelInstrumentation(BaseTest):
    def setUp(self):
        super().setUp()
        # Store original levels to restore them after tests
        self.original_root_level = logging.getLogger().level
        self.original_django_otel_logger_level = logging.getLogger("opentelemetry.instrumentation.django").level
        self.original_django_otel_logger_propagate = logging.getLogger("opentelemetry.instrumentation.django").propagate

        # Set to a known, possibly different, state before each test that calls initialize_otel
        logging.getLogger().setLevel(logging.WARNING)
        # For the django_instr_logger, initialize_otel always sets it to DEBUG and propagate=True
        # So, we don't need to change its initial state as much as ensure it's reset.
        logging.getLogger("opentelemetry.instrumentation.django").setLevel(logging.WARNING)
        logging.getLogger("opentelemetry.instrumentation.django").propagate = False

    def tearDown(self):
        # Restore original levels and propagation
        logging.getLogger().setLevel(self.original_root_level)
        django_otel_logger = logging.getLogger("opentelemetry.instrumentation.django")
        django_otel_logger.setLevel(self.original_django_otel_logger_level)
        django_otel_logger.propagate = self.original_django_otel_logger_propagate

        # Clear any potentially set OTel provider to avoid state leakage between tests
        # if initialize_otel was called and set a global provider.
        from opentelemetry import trace

        trace._TRACER_PROVIDER = None

        super().tearDown()

    @mock.patch("posthog.otel_instrumentation.AIOKafkaInstrumentor")
    @mock.patch("posthog.otel_instrumentation.KafkaInstrumentor")
    @mock.patch("posthog.otel_instrumentation.PsycopgInstrumentor")
    @mock.patch("posthog.otel_instrumentation.RedisInstrumentor")
    @mock.patch("posthog.otel_instrumentation.DjangoInstrumentor")
    @mock.patch("posthog.otel_instrumentation.BatchSpanProcessor")
    @mock.patch("posthog.otel_instrumentation.OTLPSpanExporter")
    @mock.patch("posthog.otel_instrumentation.TracerProvider")
    @mock.patch("posthog.otel_instrumentation.Resource")
    @mock.patch("opentelemetry.trace.set_tracer_provider")
    @mock.patch.dict(
        os.environ,
        {
            "OTEL_SERVICE_NAME": "test-service",
            "OTEL_SDK_DISABLED": "false",
            "OTEL_PYTHON_LOG_LEVEL": "debug",
        },
        clear=True,
    )
    @mock.patch("posthog.otel_instrumentation.logger")
    def test_initialize_otel_enabled_and_configured(
        self,
        mock_structlog_logger,
        mock_set_tracer_provider,
        mock_resource_cls,
        mock_tracer_provider_cls,
        mock_otlp_exporter_cls,
        mock_batch_processor_cls,
        mock_django_instrumentor_cls,
        mock_redis_instrumentor_cls,
        mock_psycopg_instrumentor_cls,
        mock_kafka_instrumentor_cls,
        mock_aio_kafka_instrumentor_cls,
    ):
        # Arrange
        mock_resource_instance = mock.Mock()
        mock_resource_cls.create.return_value = mock_resource_instance

        mock_provider_instance = mock.Mock()
        mock_tracer_provider_cls.return_value = mock_provider_instance

        mock_django_instrumentor_instance = mock.Mock()
        mock_django_instrumentor_cls.return_value = mock_django_instrumentor_instance

        mock_redis_instrumentor_instance = mock.Mock()
        mock_redis_instrumentor_cls.return_value = mock_redis_instrumentor_instance

        mock_psycopg_instrumentor_instance = mock.Mock()
        mock_psycopg_instrumentor_cls.return_value = mock_psycopg_instrumentor_instance

        mock_kafka_instrumentor_instance = mock.Mock()
        mock_kafka_instrumentor_cls.return_value = mock_kafka_instrumentor_instance

        mock_aio_kafka_instrumentor_instance = mock.Mock()
        mock_aio_kafka_instrumentor_cls.return_value = mock_aio_kafka_instrumentor_instance

        # Act
        initialize_otel()

        # Assert
        mock_resource_cls.create.assert_called_once_with(attributes={"service.name": "test-service"})

        # Check TracerProvider call with sampler
        self.assertEqual(mock_tracer_provider_cls.call_count, 1)
        call_args = mock_tracer_provider_cls.call_args
        self.assertEqual(call_args[1]["resource"], mock_resource_instance)
        # No longer passing sampler manually - OpenTelemetry SDK handles it via env vars
        self.assertNotIn("sampler", call_args[1])

        mock_otlp_exporter_cls.assert_called_once_with()
        mock_batch_processor_cls.assert_called_once_with(mock_otlp_exporter_cls.return_value)
        mock_provider_instance.add_span_processor.assert_called_once_with(mock_batch_processor_cls.return_value)
        mock_set_tracer_provider.assert_called_once_with(mock_provider_instance)

        mock_django_instrumentor_cls.assert_called_once_with()
        mock_django_instrumentor_instance.instrument.assert_called_once()

        instrument_call_args = mock_django_instrumentor_instance.instrument.call_args
        self.assertEqual(instrument_call_args[1]["tracer_provider"], mock_provider_instance)
        self.assertEqual(instrument_call_args[1]["request_hook"], _otel_django_request_hook)
        self.assertEqual(instrument_call_args[1]["response_hook"], _otel_django_response_hook)

        # Assert RedisInstrumentor call
        mock_redis_instrumentor_cls.assert_called_once_with()
        mock_redis_instrumentor_instance.instrument.assert_called_once_with(tracer_provider=mock_provider_instance)

        # Assert PsycopgInstrumentor call
        mock_psycopg_instrumentor_cls.assert_called_once_with()
        mock_psycopg_instrumentor_instance.instrument.assert_called_once_with(
            tracer_provider=mock_provider_instance, enable_commenter=False
        )

        # Assert KafkaInstrumentor call
        mock_kafka_instrumentor_cls.assert_called_once_with()
        mock_kafka_instrumentor_instance.instrument.assert_called_once_with(tracer_provider=mock_provider_instance)

        # Assert AIOKafkaInstrumentor call
        mock_aio_kafka_instrumentor_cls.assert_called_once_with()
        mock_aio_kafka_instrumentor_instance.instrument.assert_called_once_with(tracer_provider=mock_provider_instance)

        # Check structlog logging calls
        found_init_success_log = False
        found_sdk_config_log = False
        found_sampler_config_log = False
        for call_args_tuple in mock_structlog_logger.info.call_args_list:
            args, kwargs = call_args_tuple
            event_name = args[0] if args else None
            if event_name == "otel_manual_init_status_from_instrumentation_module":
                if kwargs.get("service_name") == "test-service":
                    found_init_success_log = True
            elif event_name == "otel_sdk_logging_config_from_instrumentation_module":
                found_sdk_config_log = True
            elif event_name == "otel_sampler_configured":
                # Check for new env var based logging instead of sampler object properties
                if kwargs.get("sampler_type") == "parentbased_traceidratio" and kwargs.get("sampler_arg") == "0":
                    found_sampler_config_log = True

        self.assertTrue(found_init_success_log, "Expected OTel initialization success log not found or incorrect.")
        self.assertTrue(found_sdk_config_log, "Expected OTel SDK logging configuration log not found.")
        self.assertTrue(found_sampler_config_log, "Expected OTel sampler configuration log not found or incorrect.")

        # Check standard library logger configurations
        root_logger = logging.getLogger()
        self.assertEqual(root_logger.level, logging.DEBUG)  # OTEL_PYTHON_LOG_LEVEL is debug
        django_otel_lib_logger = logging.getLogger("opentelemetry.instrumentation.django")
        self.assertEqual(django_otel_lib_logger.level, logging.DEBUG)  # Always set to DEBUG
        self.assertTrue(django_otel_lib_logger.propagate)

    @mock.patch("posthog.otel_instrumentation.AIOKafkaInstrumentor")
    @mock.patch("posthog.otel_instrumentation.KafkaInstrumentor")
    @mock.patch("posthog.otel_instrumentation.PsycopgInstrumentor")
    @mock.patch("posthog.otel_instrumentation.RedisInstrumentor")
    @mock.patch("posthog.otel_instrumentation.DjangoInstrumentor")
    @mock.patch("posthog.otel_instrumentation.logger")
    @mock.patch.dict(os.environ, {"OTEL_SDK_DISABLED": "true", "OTEL_PYTHON_LOG_LEVEL": "info"}, clear=True)
    def test_initialize_otel_disabled(
        self,
        mock_structlog_logger,
        mock_django_instrumentor_cls,
        mock_redis_instrumentor_cls,
        mock_psycopg_instrumentor_cls,
        mock_kafka_instrumentor_cls,
        mock_aio_kafka_instrumentor_cls,
    ):
        # Act
        initialize_otel()

        # Assert
        mock_django_instrumentor_cls.return_value.instrument.assert_not_called()
        mock_redis_instrumentor_cls.return_value.instrument.assert_not_called()
        mock_psycopg_instrumentor_cls.return_value.instrument.assert_not_called()
        mock_kafka_instrumentor_cls.return_value.instrument.assert_not_called()
        mock_aio_kafka_instrumentor_cls.return_value.instrument.assert_not_called()

        found_disabled_log = False
        for call_args_tuple in mock_structlog_logger.info.call_args_list:
            args, kwargs = call_args_tuple
            event_name = args[0] if args else None
            if event_name == "otel_manual_init_status_from_instrumentation_module":
                if kwargs.get("status") == "disabled":
                    found_disabled_log = True
        self.assertTrue(found_disabled_log, "Expected OTel disabled status log not found or incorrect.")

        # Check standard library logger configurations (logging setup still happens)
        root_logger = logging.getLogger()
        self.assertEqual(root_logger.level, logging.INFO)  # OTEL_PYTHON_LOG_LEVEL is info
        django_otel_lib_logger = logging.getLogger("opentelemetry.instrumentation.django")
        self.assertEqual(django_otel_lib_logger.level, logging.DEBUG)  # Always set to DEBUG
        self.assertTrue(django_otel_lib_logger.propagate)

    def test_otel_django_request_hook(self):
        mock_span = mock.Mock()
        mock_span.is_recording.return_value = True
        mock_request = mock.Mock()
        mock_request.path = "/test/path"
        mock_request.method = "GET"

        _otel_django_request_hook(mock_span, mock_request)

        mock_span.set_attribute.assert_any_call("http.method", "GET")
        mock_span.set_attribute.assert_any_call("http.url", "/test/path")
        self.assertEqual(mock_span.set_attribute.call_count, 2)

    def test_otel_django_request_hook_not_recording(self):
        mock_span = mock.Mock()
        mock_span.is_recording.return_value = False
        mock_request = mock.Mock()

        _otel_django_request_hook(mock_span, mock_request)

        mock_span.set_attribute.assert_not_called()

    def test_otel_django_response_hook(self):
        mock_span = mock.Mock()
        mock_span.is_recording.return_value = True
        mock_request = mock.Mock()  # Not used by this hook's logic
        mock_response = mock.Mock()
        mock_response.status_code = 200

        _otel_django_response_hook(mock_span, mock_request, mock_response)

        mock_span.set_attribute.assert_called_once_with("http.status_code", 200)

    def test_otel_django_response_hook_not_recording(self):
        mock_span = mock.Mock()
        mock_span.is_recording.return_value = False
        mock_request = mock.Mock()
        mock_response = mock.Mock()

        _otel_django_response_hook(mock_span, mock_request, mock_response)

        mock_span.set_attribute.assert_not_called()

    @mock.patch("posthog.otel_instrumentation.AIOKafkaInstrumentor")
    @mock.patch("posthog.otel_instrumentation.KafkaInstrumentor")
    @mock.patch("posthog.otel_instrumentation.PsycopgInstrumentor")
    @mock.patch("posthog.otel_instrumentation.RedisInstrumentor")
    @mock.patch("posthog.otel_instrumentation.DjangoInstrumentor")
    @mock.patch("posthog.otel_instrumentation.BatchSpanProcessor")
    @mock.patch("posthog.otel_instrumentation.OTLPSpanExporter")
    @mock.patch("posthog.otel_instrumentation.TracerProvider")
    @mock.patch("posthog.otel_instrumentation.Resource")
    @mock.patch("opentelemetry.trace.set_tracer_provider")
    @mock.patch.dict(
        os.environ,
        {
            "OTEL_SERVICE_NAME": "test-service-custom-sample",
            "OTEL_SDK_DISABLED": "false",
            "OTEL_PYTHON_LOG_LEVEL": "info",
            "OTEL_TRACES_SAMPLER": "parentbased_traceidratio",
            "OTEL_TRACES_SAMPLER_ARG": "0.5",
        },
        clear=True,
    )
    @mock.patch("posthog.otel_instrumentation.logger")
    def test_initialize_otel_with_custom_sampling_ratio(
        self,
        mock_structlog_logger,
        mock_set_tracer_provider,
        mock_resource_cls,
        mock_tracer_provider_cls,
        mock_otlp_exporter_cls,
        mock_batch_processor_cls,
        mock_django_instrumentor_cls,
        mock_redis_instrumentor_cls,
        mock_psycopg_instrumentor_cls,
        mock_kafka_instrumentor_cls,
        mock_aio_kafka_instrumentor_cls,
    ):
        # Arrange
        mock_resource_instance = mock.Mock()
        mock_resource_cls.create.return_value = mock_resource_instance
        mock_provider_instance = mock.Mock()
        mock_tracer_provider_cls.return_value = mock_provider_instance

        # Added mock instantiations for kafka instrumentors
        mock_django_instrumentor_instance = mock.Mock()
        mock_django_instrumentor_cls.return_value = mock_django_instrumentor_instance

        mock_redis_instrumentor_instance = mock.Mock()
        mock_redis_instrumentor_cls.return_value = mock_redis_instrumentor_instance

        mock_psycopg_instrumentor_instance = mock.Mock()
        mock_psycopg_instrumentor_cls.return_value = mock_psycopg_instrumentor_instance

        mock_kafka_instrumentor_instance = mock.Mock()
        mock_kafka_instrumentor_cls.return_value = mock_kafka_instrumentor_instance

        mock_aio_kafka_instrumentor_instance = mock.Mock()
        mock_aio_kafka_instrumentor_cls.return_value = mock_aio_kafka_instrumentor_instance

        # Act
        initialize_otel()

        # Assert
        mock_resource_cls.create.assert_called_once_with(attributes={"service.name": "test-service-custom-sample"})

        # Check TracerProvider call with sampler
        self.assertEqual(mock_tracer_provider_cls.call_count, 1)
        call_args = mock_tracer_provider_cls.call_args
        self.assertEqual(call_args[1]["resource"], mock_resource_instance)
        # No longer passing sampler manually - OpenTelemetry SDK handles it via env vars
        self.assertNotIn("sampler", call_args[1])

        mock_set_tracer_provider.assert_called_once_with(mock_provider_instance)

        # Check for sampler configured log
        found_sampler_config_log = False
        for call_args_tuple in mock_structlog_logger.info.call_args_list:
            args, kwargs = call_args_tuple
            event_name = args[0] if args else None
            if event_name == "otel_sampler_configured":
                if kwargs.get("sampler_type") == "parentbased_traceidratio" and kwargs.get("sampler_arg") == "0.5":
                    found_sampler_config_log = True
        self.assertTrue(
            found_sampler_config_log, "Expected OTel sampler configuration log with custom ratio not found."
        )

        # Assert KafkaInstrumentor call
        mock_kafka_instrumentor_cls.assert_called_once_with()
        mock_kafka_instrumentor_instance.instrument.assert_called_once_with(tracer_provider=mock_provider_instance)

        # Assert AIOKafkaInstrumentor call
        mock_aio_kafka_instrumentor_cls.assert_called_once_with()
        mock_aio_kafka_instrumentor_instance.instrument.assert_called_once_with(tracer_provider=mock_provider_instance)
