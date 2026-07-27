import sys
from typing import Any

from unittest import mock

from django.test import SimpleTestCase, override_settings

from opentelemetry._logs import SeverityNumber
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import InMemoryLogExporter, SimpleLogRecordProcessor
from opentelemetry.sdk.resources import Resource
from parameterized import parameterized

from posthog import otel_logs
from posthog.otel_logs import otel_log_mirror_processor, reset_otel_logs_for_tests

_PREFIX = "products.replay_vision.backend.temporal"
_ALLOWLIST = frozenset({"observation_id", "team_id"})


class TestOtelLogMirror(SimpleTestCase):
    def setUp(self) -> None:
        reset_otel_logs_for_tests()
        self.addCleanup(reset_otel_logs_for_tests)

    def _run(
        self,
        event_dict: dict[str, Any],
        *,
        method_name: str = "info",
        allowlist: set[str] | frozenset[str] = _ALLOWLIST,
        service_name: str = "replay-vision",
    ) -> list[Any]:
        exporter = InMemoryLogExporter()
        provider = LoggerProvider(resource=Resource.create({"service.name": service_name}))
        provider.add_log_record_processor(SimpleLogRecordProcessor(exporter))
        with mock.patch("posthog.otel_logs._build_provider", return_value=provider):
            mirror = otel_log_mirror_processor(service_name, logger_prefix=_PREFIX, attribute_allowlist=allowlist)
            mirror(None, method_name, dict(event_dict))
        return [item.log_record for item in exporter.get_finished_logs()]

    def test_mirrors_event_and_allowlisted_attributes(self) -> None:
        records = self._run(
            {
                "event": "scanner_call_failed",
                "logger": f"{_PREFIX}.activities.call_scanner_provider",
                "observation_id": "obs_1",
                "team_id": 42,
                "response_preview": "customer session text",
            }
        )
        assert len(records) == 1
        record = records[0]
        assert record.body == "scanner_call_failed"
        assert record.attributes["observation_id"] == "obs_1"
        assert record.attributes["team_id"] == "42"
        assert "response_preview" not in record.attributes
        assert record.attributes["logger"] == f"{_PREFIX}.activities.call_scanner_provider"
        assert record.resource.attributes["service.name"] == "replay-vision"

    def test_ignores_loggers_outside_the_prefix(self) -> None:
        records = self._run({"event": "shutting down", "logger": "temporalio.worker"})
        assert records == []

    @parameterized.expand(
        [
            ("debug", SeverityNumber.DEBUG, "DEBUG"),
            ("info", SeverityNumber.INFO, "INFO"),
            ("warning", SeverityNumber.WARN, "WARN"),
            ("error", SeverityNumber.ERROR, "ERROR"),
            ("critical", SeverityNumber.FATAL, "FATAL"),
        ]
    )
    def test_severity_mapping(self, level_name: str, number: SeverityNumber, text: str) -> None:
        records = self._run({"event": "x", "logger": f"{_PREFIX}.x", "level": level_name}, method_name=level_name)
        assert records[0].severity_text == text
        assert records[0].severity_number == number

    def test_drops_non_scalar_attributes(self) -> None:
        # OTEL attributes are scalars only; an allowlisted key with a Mapping/list value is dropped.
        records = self._run(
            {"event": "x", "logger": f"{_PREFIX}.x", "team_id": {"nested": 1}, "observation_id": "obs_1"}
        )
        assert records[0].attributes["observation_id"] == "obs_1"
        assert "team_id" not in records[0].attributes

    def test_restricted_mode_ships_exception_type_not_traceback(self) -> None:
        try:
            raise ValueError("customer data in message")
        except ValueError:
            exc_info = sys.exc_info()
        records = self._run(
            {"event": "scan_failed", "logger": f"{_PREFIX}.x", "exc_info": exc_info}, method_name="error"
        )
        assert records[0].attributes["exception_type"] == "ValueError"
        assert "exception" not in records[0].attributes
        assert all("customer data" not in str(value) for value in records[0].attributes.values())

    def test_mirror_is_fail_soft(self) -> None:
        provider = mock.MagicMock()
        provider.get_logger.side_effect = RuntimeError("exporter down")
        event_dict = {"event": "x", "logger": f"{_PREFIX}.x"}
        with mock.patch("posthog.otel_logs._build_provider", return_value=provider):
            mirror = otel_log_mirror_processor("replay-vision", logger_prefix=_PREFIX, attribute_allowlist=_ALLOWLIST)
            result = mirror(None, "info", event_dict)
        assert provider.get_logger.called
        assert result == event_dict

    def test_factory_is_fail_soft_when_provider_build_fails(self) -> None:
        # Provider construction failing at warm-up must not break worker startup: the factory returns a
        # no-op processor instead of propagating out of configure_logger.
        event_dict = {"event": "x", "logger": f"{_PREFIX}.x"}
        with mock.patch("posthog.otel_logs._build_provider", side_effect=RuntimeError("boom")):
            mirror = otel_log_mirror_processor("replay-vision", logger_prefix=_PREFIX, attribute_allowlist=_ALLOWLIST)
        assert mirror(None, "info", dict(event_dict)) == event_dict

    @parameterized.expand(
        [("both_empty", "", ""), ("endpoint_only", "http://c/i/v1/logs", ""), ("token_only", "", "phc_x")]
    )
    def test_noop_when_unconfigured(self, _name: str, endpoint: str, token: str) -> None:
        with override_settings(OTLP_LOGS_INGEST_ENDPOINT=endpoint, OTLP_LOGS_INGEST_TOKEN=token):
            mirror = otel_log_mirror_processor("replay-vision", logger_prefix=_PREFIX, attribute_allowlist=_ALLOWLIST)
            mirror(None, "info", {"event": "x", "logger": f"{_PREFIX}.x"})
        assert otel_logs._providers.get("replay-vision") is None

    def test_production_exporter_bypasses_egress_proxy(self) -> None:
        # trust_env=False, else the worker's Smokescreen proxy 407s the in-cluster ClusterIP.
        endpoint = "http://capture-logs.posthog.svc.cluster.local:4318/i/v1/logs"
        with override_settings(OTLP_LOGS_INGEST_ENDPOINT=endpoint, OTLP_LOGS_INGEST_TOKEN="phc_x"):
            with mock.patch("opentelemetry.exporter.otlp.proto.http._log_exporter.OTLPLogExporter") as mock_otlp:
                provider = otel_logs._build_provider("replay-vision")
        assert mock_otlp.call_args.kwargs["endpoint"] == endpoint
        assert mock_otlp.call_args.kwargs["headers"] == {"authorization": "Bearer phc_x"}
        assert mock_otlp.call_args.kwargs["session"].trust_env is False
        if provider is not None:
            provider.shutdown()
