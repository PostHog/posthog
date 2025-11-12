"""
Tests for OpenTelemetry OTLP ingestion endpoint.
"""

from unittest.mock import patch

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.resource.v1.resource_pb2 import Resource
from opentelemetry.proto.trace.v1.trace_pb2 import ResourceSpans, ScopeSpans, Span, Status

from posthog.api.otel_ingestion import OTLPAttributeMapper, OTLPSpanConverter
from posthog.models import Team
from posthog.test.base import APIBaseTest


class TestOTLPAttributeMapper(APIBaseTest):
    """Test attribute mapping from OpenTelemetry to PostHog format."""

    def test_genai_attribute_mapping(self):
        """Test mapping of gen_ai.* attributes to PostHog properties."""
        otel_attributes = {
            "gen_ai.system": "openai",
            "gen_ai.request.model": "gpt-4",
            "gen_ai.usage.prompt_tokens": 100,
            "gen_ai.usage.completion_tokens": 50,
            "gen_ai.request.temperature": 0.7,
            "gen_ai.request.max_tokens": 1000,
        }

        mapped = OTLPAttributeMapper.map_attributes(otel_attributes)

        assert mapped["$ai_provider"] == "openai"
        assert mapped["$ai_model"] == "gpt-4"
        assert mapped["$ai_prompt_tokens"] == 100
        assert mapped["$ai_completion_tokens"] == 50
        assert mapped["$ai_temperature"] == 0.7
        assert mapped["$ai_max_tokens"] == 1000

    def test_llm_attribute_mapping(self):
        """Test mapping of llm.* attributes (alternative convention)."""
        otel_attributes = {
            "llm.model": "claude-3-opus",
            "llm.provider": "anthropic",
            "llm.request.type": "chat",
        }

        mapped = OTLPAttributeMapper.map_attributes(otel_attributes)

        assert mapped["$ai_model"] == "claude-3-opus"
        assert mapped["$ai_provider"] == "anthropic"
        assert mapped["$ai_request_type"] == "chat"

    def test_http_error_attribute_mapping(self):
        """Test mapping of HTTP and error attributes."""
        otel_attributes = {
            "http.status_code": 500,
            "error.type": "RateLimitError",
            "error.message": "Rate limit exceeded",
        }

        mapped = OTLPAttributeMapper.map_attributes(otel_attributes)

        assert mapped["$ai_status_code"] == 500
        assert mapped["$ai_error_type"] == "RateLimitError"
        assert mapped["$ai_error"] == "Rate limit exceeded"

    def test_unknown_attributes_prefixed(self):
        """Test that unknown attributes are passed through with otel. prefix."""
        otel_attributes = {
            "custom.attribute": "value",
            "other.field": 123,
        }

        mapped = OTLPAttributeMapper.map_attributes(otel_attributes)

        assert mapped["otel.custom.attribute"] == "value"
        assert mapped["otel.other.field"] == 123


class TestOTLPSpanConverter(APIBaseTest):
    """Test conversion of OTLP spans to PostHog events."""

    def create_test_span(
        self,
        name: str = "test_span",
        trace_id: bytes = b"\x01" * 16,
        span_id: bytes = b"\x02" * 8,
        parent_span_id: bytes = None,
        attributes: dict = None,
        start_time: int = 1000000000,
        end_time: int = 2000000000,
        status_code: int = 1,  # STATUS_CODE_OK
        status_message: str = "",
    ) -> Span:
        """Create a test OTLP span."""
        span = Span()
        span.name = name
        span.trace_id = trace_id
        span.span_id = span_id
        if parent_span_id:
            span.parent_span_id = parent_span_id
        span.start_time_unix_nano = start_time
        span.end_time_unix_nano = end_time
        span.status.code = status_code
        span.status.message = status_message

        if attributes:
            for key, value in attributes.items():
                kv = KeyValue()
                kv.key = key
                if isinstance(value, str):
                    kv.value.string_value = value
                elif isinstance(value, bool):
                    kv.value.bool_value = value
                elif isinstance(value, int):
                    kv.value.int_value = value
                elif isinstance(value, float):
                    kv.value.double_value = value
                span.attributes.append(kv)

        return span

    def test_span_id_conversion(self):
        """Test conversion of span IDs to hex strings."""
        span_id = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        hex_id = OTLPSpanConverter.span_id_to_hex(span_id)
        assert hex_id == "0102030405060708"

    def test_trace_id_conversion(self):
        """Test conversion of trace IDs to hex strings."""
        trace_id = b"\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10"
        hex_id = OTLPSpanConverter.trace_id_to_hex(trace_id)
        assert hex_id == "0102030405060708090a0b0c0d0e0f10"

    def test_parse_otlp_attributes_string(self):
        """Test parsing string attributes."""
        span = self.create_test_span(attributes={"key": "value"})
        parsed = OTLPSpanConverter.parse_otlp_attributes(span.attributes)
        assert parsed["key"] == "value"

    def test_parse_otlp_attributes_numeric(self):
        """Test parsing numeric attributes."""
        span = self.create_test_span(attributes={"int_val": 42, "float_val": 3.14, "bool_val": True})
        parsed = OTLPSpanConverter.parse_otlp_attributes(span.attributes)
        assert parsed["int_val"] == 42
        assert parsed["float_val"] == 3.14
        assert parsed["bool_val"] is True

    def test_convert_span_basic(self):
        """Test basic span conversion."""
        span = self.create_test_span(
            name="llm.chat",
            attributes={
                "gen_ai.system": "openai",
                "gen_ai.request.model": "gpt-4",
            },
        )

        event = OTLPSpanConverter.convert_span(span, {})

        assert event["event"] == "$ai_generation"
        assert event["properties"]["$ai_span_name"] == "llm.chat"
        assert event["properties"]["$ai_provider"] == "openai"
        assert event["properties"]["$ai_model"] == "gpt-4"
        assert event["properties"]["$ai_trace_id"] == "01" * 16
        assert event["properties"]["$ai_span_id"] == "02" * 8

    def test_convert_span_with_parent(self):
        """Test span conversion with parent span ID."""
        parent_id = b"\x03" * 8
        span = self.create_test_span(parent_span_id=parent_id)

        event = OTLPSpanConverter.convert_span(span, {})

        assert event["properties"]["$ai_parent_id"] == "03" * 8

    def test_convert_span_latency_calculation(self):
        """Test latency calculation from span timestamps."""
        start_ns = 1000000000  # 1ms in nanoseconds
        end_ns = 3000000000  # 3ms in nanoseconds
        span = self.create_test_span(start_time=start_ns, end_time=end_ns)

        event = OTLPSpanConverter.convert_span(span, {})

        # Latency should be 2ms
        assert event["properties"]["$ai_latency"] == 2.0

    def test_convert_span_with_error(self):
        """Test span conversion with error status."""
        span = self.create_test_span(
            status_code=2,  # STATUS_CODE_ERROR
            status_message="API error occurred",
        )

        event = OTLPSpanConverter.convert_span(span, {})

        assert event["properties"]["$ai_is_error"] is True
        assert event["properties"]["$ai_error"] == "API error occurred"

    def test_convert_span_timestamp(self):
        """Test that span timestamp is correctly converted."""
        start_ns = 1640000000000000000  # Some timestamp in nanoseconds
        span = self.create_test_span(start_time=start_ns)

        event = OTLPSpanConverter.convert_span(span, {})

        # Should be converted to seconds
        assert event["timestamp"] == start_ns / 1_000_000_000

    def test_convert_embedding_span(self):
        """Test detection of embedding operations."""
        span = self.create_test_span(
            name="embedding.create",
            attributes={
                "gen_ai.request.model": "text-embedding-ada-002",
            },
        )

        event = OTLPSpanConverter.convert_span(span, {})

        assert event["event"] == "$ai_embedding"

    def test_convert_generic_span(self):
        """Test conversion of generic AI span without model info."""
        span = self.create_test_span(name="preprocessing")

        event = OTLPSpanConverter.convert_span(span, {})

        assert event["event"] == "$ai_span"


class TestOTLPEndpoint(APIBaseTest):
    """Test the OTLP HTTP endpoint."""

    def setUp(self):
        super().setUp()
        self.endpoint_url = "/api/public/otel/v1/traces"

    def create_otlp_request(self, spans: list[Span], resource_attributes: dict = None) -> bytes:
        """Create an OTLP ExportTraceServiceRequest."""
        request = ExportTraceServiceRequest()
        resource_span = ResourceSpans()

        # Add resource attributes if provided
        if resource_attributes:
            resource = Resource()
            for key, value in resource_attributes.items():
                kv = KeyValue()
                kv.key = key
                if isinstance(value, str):
                    kv.value.string_value = value
                resource.attributes.append(kv)
            resource_span.resource.CopyFrom(resource)

        # Add spans to scope
        scope_span = ScopeSpans()
        for span in spans:
            scope_span.spans.append(span)

        resource_span.scope_spans.append(scope_span)
        request.resource_spans.append(resource_span)

        return request.SerializeToString()

    def test_endpoint_missing_auth(self):
        """Test endpoint rejects requests without authentication."""
        span = Span()
        span.name = "test"
        span.trace_id = b"\x01" * 16
        span.span_id = b"\x02" * 8

        otlp_data = self.create_otlp_request([span])

        response = self.client.post(
            self.endpoint_url,
            data=otlp_data,
            content_type="application/x-protobuf",
        )

        assert response.status_code == 401
        assert "Invalid or missing authentication token" in response.json()["error"]

    def test_endpoint_invalid_token(self):
        """Test endpoint rejects invalid Bearer tokens."""
        span = Span()
        span.name = "test"
        span.trace_id = b"\x01" * 16
        span.span_id = b"\x02" * 8

        otlp_data = self.create_otlp_request([span])

        response = self.client.post(
            self.endpoint_url,
            data=otlp_data,
            content_type="application/x-protobuf",
            HTTP_AUTHORIZATION="Bearer invalid_token",
        )

        assert response.status_code == 401

    def test_endpoint_wrong_content_type(self):
        """Test endpoint rejects non-protobuf content types."""
        response = self.client.post(
            self.endpoint_url,
            data=b"some data",
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.team.api_token}",
        )

        assert response.status_code == 415
        assert "application/x-protobuf" in response.json()["error"]

    def test_endpoint_invalid_protobuf(self):
        """Test endpoint handles invalid protobuf data."""
        response = self.client.post(
            self.endpoint_url,
            data=b"invalid protobuf data",
            content_type="application/x-protobuf",
            HTTP_AUTHORIZATION=f"Bearer {self.team.api_token}",
        )

        assert response.status_code == 400
        assert "Invalid OTLP protobuf format" in response.json()["error"]

    @patch("posthog.api.otel_ingestion.capture_internal")
    def test_endpoint_success(self, mock_capture):
        """Test successful OTLP trace ingestion."""
        span = Span()
        span.name = "llm.chat"
        span.trace_id = b"\x01" * 16
        span.span_id = b"\x02" * 8
        span.start_time_unix_nano = 1000000000
        span.end_time_unix_nano = 2000000000

        # Add GenAI attributes
        for key, value in {
            "gen_ai.system": "openai",
            "gen_ai.request.model": "gpt-4",
            "gen_ai.usage.prompt_tokens": "100",
            "gen_ai.usage.completion_tokens": "50",
        }.items():
            kv = KeyValue()
            kv.key = key
            kv.value.string_value = value
            span.attributes.append(kv)

        otlp_data = self.create_otlp_request([span])

        response = self.client.post(
            self.endpoint_url,
            data=otlp_data,
            content_type="application/x-protobuf",
            HTTP_AUTHORIZATION=f"Bearer {self.team.api_token}",
        )

        assert response.status_code == 200
        assert response.json() == {"partialSuccess": {}}

        # Verify capture_internal was called
        assert mock_capture.called
        call_args = mock_capture.call_args
        assert call_args.kwargs["event"] == "$ai_generation"
        assert call_args.kwargs["team_id"] == self.team.id

    @patch("posthog.api.otel_ingestion.capture_internal")
    def test_endpoint_multiple_spans(self, mock_capture):
        """Test ingesting multiple spans in one request."""
        spans = []
        for i in range(3):
            span = Span()
            span.name = f"span_{i}"
            span.trace_id = b"\x01" * 16
            span.span_id = (b"\x02" + bytes([i])).ljust(8, b"\x00")
            span.start_time_unix_nano = 1000000000 + i * 1000000
            span.end_time_unix_nano = 2000000000 + i * 1000000
            spans.append(span)

        otlp_data = self.create_otlp_request(spans)

        response = self.client.post(
            self.endpoint_url,
            data=otlp_data,
            content_type="application/x-protobuf",
            HTTP_AUTHORIZATION=f"Bearer {self.team.api_token}",
        )

        assert response.status_code == 200

        # Verify capture_internal was called 3 times
        assert mock_capture.call_count == 3

    @patch("posthog.api.otel_ingestion.capture_internal")
    def test_endpoint_with_resource_attributes(self, mock_capture):
        """Test that resource-level attributes are included."""
        span = Span()
        span.name = "test"
        span.trace_id = b"\x01" * 16
        span.span_id = b"\x02" * 8

        resource_attrs = {
            "service.name": "my-app",
            "service.version": "1.0.0",
        }

        otlp_data = self.create_otlp_request([span], resource_attributes=resource_attrs)

        response = self.client.post(
            self.endpoint_url,
            data=otlp_data,
            content_type="application/x-protobuf",
            HTTP_AUTHORIZATION=f"Bearer {self.team.api_token}",
        )

        assert response.status_code == 200

        # Check that resource attributes were passed through
        call_args = mock_capture.call_args
        props = call_args.kwargs["properties"]
        assert "otel.service.name" in props
        assert props["otel.service.name"] == "my-app"

    def test_endpoint_empty_request(self):
        """Test endpoint handles empty request gracefully."""
        request = ExportTraceServiceRequest()
        otlp_data = request.SerializeToString()

        response = self.client.post(
            self.endpoint_url,
            data=otlp_data,
            content_type="application/x-protobuf",
            HTTP_AUTHORIZATION=f"Bearer {self.team.api_token}",
        )

        assert response.status_code == 200
        assert "No valid spans found" in response.json()["message"]
