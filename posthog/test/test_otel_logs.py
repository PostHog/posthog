import sys
import logging
from typing import Any

from unittest import mock

from django.test import SimpleTestCase, override_settings

from opentelemetry._logs import SeverityNumber
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import InMemoryLogExporter, SimpleLogRecordProcessor
from opentelemetry.sdk.resources import Resource
from parameterized import parameterized

from posthog import otel_logs
from posthog.otel_logs import OtelLogHandler, reset_otel_logs_for_tests


def _structlog_record(
    event_dict: dict[str, Any],
    *,
    level: int = logging.INFO,
    name: str = "products.replay_vision.backend.temporal.activities.call_scanner_provider",
    exc_info: Any = None,
) -> logging.LogRecord:
    # structlog's ProcessorFormatter path leaves the event dict on record.msg.
    return logging.LogRecord(
        name=name, level=level, pathname=__file__, lineno=1, msg=event_dict, args=(), exc_info=exc_info
    )


class TestOtelLogs(SimpleTestCase):
    def setUp(self) -> None:
        reset_otel_logs_for_tests()
        self.addCleanup(reset_otel_logs_for_tests)

    def _emit(
        self,
        record: logging.LogRecord,
        *,
        service_name: str = "replay-vision",
        static_attributes: dict[str, str] | None = None,
        attribute_allowlist: set[str] | None = None,
    ) -> list[Any]:
        exporter = InMemoryLogExporter()
        provider = LoggerProvider(resource=Resource.create({"service.name": service_name}))
        provider.add_log_record_processor(SimpleLogRecordProcessor(exporter))
        with mock.patch("posthog.otel_logs._build_provider", return_value=provider):
            OtelLogHandler(
                service_name, attribute_allowlist=attribute_allowlist, static_attributes=static_attributes
            ).emit(record)
        return [item.log_record for item in exporter.get_finished_logs()]

    @parameterized.expand(
        [("both_empty", "", ""), ("endpoint_only", "http://c/i/v1/logs", ""), ("token_only", "", "phc_x")]
    )
    def test_noop_when_unconfigured(self, _name: str, endpoint: str, token: str) -> None:
        # A half- or un-configured lane must never build a provider (an unauthenticated export would
        # 401 and drop records) and emit must not crash the worker.
        with override_settings(OTLP_LOGS_INGEST_ENDPOINT=endpoint, OTLP_LOGS_INGEST_TOKEN=token):
            OtelLogHandler("replay-vision").emit(_structlog_record({"event": "hello"}))
        assert otel_logs._providers.get("replay-vision") is None

    def test_maps_event_dict_to_body_and_stringified_attributes(self) -> None:
        # The core contract: `event` becomes the body, scalar fields become attributes stringified (the
        # logs pipeline only indexes string-typed values), the logger name rides along, and the record's
        # resource is pinned to the service — not the pod's OTEL_SERVICE_NAME, which the read filter
        # (service.name = replay-vision) would otherwise miss.
        with mock.patch.dict("os.environ", {"OTEL_SERVICE_NAME": "temporal-worker-general-purpose"}):
            records = self._emit(
                _structlog_record(
                    {"event": "scanner_call_failed", "observation_id": "obs_1", "team_id": 42, "attempt": 2}
                ),
                static_attributes={"region": "us"},
            )
        assert len(records) == 1
        record = records[0]
        assert record.body == "scanner_call_failed"
        assert record.attributes["observation_id"] == "obs_1"
        assert record.attributes["team_id"] == "42"
        assert record.attributes["attempt"] == "2"
        assert record.attributes["region"] == "us"
        assert record.attributes["logger"] == "products.replay_vision.backend.temporal.activities.call_scanner_provider"
        assert record.resource.attributes["service.name"] == "replay-vision"

    @parameterized.expand(
        [
            (logging.DEBUG, "DEBUG", SeverityNumber.DEBUG),
            (logging.INFO, "INFO", SeverityNumber.INFO),
            (logging.WARNING, "WARN", SeverityNumber.WARN),
            (logging.ERROR, "ERROR", SeverityNumber.ERROR),
            (logging.CRITICAL, "FATAL", SeverityNumber.FATAL),
        ]
    )
    def test_severity_mapping(self, levelno: int, expected_text: str, expected_number: SeverityNumber) -> None:
        # The Logs UI filters and sorts on severity; a broken level map degrades triage silently.
        records = self._emit(_structlog_record({"event": "x"}, level=levelno))
        assert records[0].severity_text == expected_text
        assert records[0].severity_number == expected_number

    def test_drops_non_scalar_attributes(self) -> None:
        # OTEL attributes accept scalars only; a Mapping/list value must be dropped, not crash or
        # serialize garbage, while scalar attributes survive.
        records = self._emit(_structlog_record({"event": "x", "count": 1, "nested": {"a": 1}, "items": [1, 2]}))
        assert records[0].attributes["count"] == "1"
        assert "nested" not in records[0].attributes
        assert "items" not in records[0].attributes

    def test_plain_stdlib_message_becomes_body(self) -> None:
        # A third-party library logging under the namespace passes a format string, not an event dict;
        # it must render into a real body rather than str(dict) garbage.
        record = logging.LogRecord(
            name="products.replay_vision.backend.temporal.x",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="uploaded %s bytes",
            args=(1024,),
            exc_info=None,
        )
        records = self._emit(record)
        assert records[0].body == "uploaded 1024 bytes"

    def test_exception_info_is_attached(self) -> None:
        # Shipping the pipeline's logs is worthless for debugging if stack traces are dropped.
        try:
            raise ValueError("boom")
        except ValueError:
            record = _structlog_record({"event": "scan_failed"}, level=logging.ERROR, exc_info=sys.exc_info())
        records = self._emit(record)
        assert "ValueError: boom" in records[0].attributes["exception"]

    def test_attribute_allowlist_drops_payload_derived_fields(self) -> None:
        # Fail-closed: shipping to a shared project forwards only allowlisted operational fields. A
        # content field like response_preview (model output derived from customer sessions) must never
        # leave the process. Guards the cross-tenant content-exposure fix.
        records = self._emit(
            _structlog_record(
                {"event": "invalid_response", "observation_id": "obs_1", "response_preview": "customer session text"}
            ),
            attribute_allowlist={"observation_id"},
        )
        assert records[0].body == "invalid_response"
        assert records[0].attributes["observation_id"] == "obs_1"
        assert "response_preview" not in records[0].attributes

    def test_restricted_mode_ships_exception_type_not_traceback(self) -> None:
        # With an allowlist the exception contributes only its class name — the message and traceback
        # can embed customer data, so they must not be forwarded.
        try:
            raise ValueError("customer data in message")
        except ValueError:
            record = _structlog_record({"event": "scan_failed"}, level=logging.ERROR, exc_info=sys.exc_info())
        records = self._emit(record, attribute_allowlist={"observation_id"})
        assert records[0].attributes["exception_type"] == "ValueError"
        assert "exception" not in records[0].attributes
        assert all("customer data" not in str(value) for value in records[0].attributes.values())

    def test_emit_is_fail_soft(self) -> None:
        # A telemetry throw must never propagate out of emit — that would crash the activity it rode in on.
        provider = mock.MagicMock()
        provider.get_logger.side_effect = RuntimeError("exporter down")
        with mock.patch("posthog.otel_logs._build_provider", return_value=provider):
            OtelLogHandler("replay-vision").emit(_structlog_record({"event": "x"}))
        assert provider.get_logger.called

    def test_production_exporter_bypasses_egress_proxy(self) -> None:
        # The endpoint+token path builds the real OTLP exporter, whose requests.Session must have
        # trust_env=False: capture-logs is an in-cluster private ClusterIP and the worker's
        # HTTP_PROXY Smokescreen egress proxy denies private-range hosts (407), silently dropping every
        # batch. This branch is otherwise untested (the rest inject providers), which is how the same
        # 407 shipped unnoticed on the metrics/CI-logs lanes.
        endpoint = "http://capture-logs.posthog.svc.cluster.local:4318/i/v1/logs"
        with override_settings(OTLP_LOGS_INGEST_ENDPOINT=endpoint, OTLP_LOGS_INGEST_TOKEN="phc_x"):
            with mock.patch("opentelemetry.exporter.otlp.proto.http._log_exporter.OTLPLogExporter") as mock_otlp:
                provider = otel_logs._build_provider("replay-vision")
        assert mock_otlp.call_args.kwargs["endpoint"] == endpoint
        assert mock_otlp.call_args.kwargs["headers"] == {"authorization": "Bearer phc_x"}
        assert mock_otlp.call_args.kwargs["session"].trust_env is False
        if provider is not None:
            provider.shutdown()
