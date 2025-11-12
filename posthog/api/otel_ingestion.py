"""
OpenTelemetry OTLP ingestion endpoint for LLM analytics.

This module provides an endpoint compatible with OpenTelemetry Protocol (OTLP) HTTP/protobuf
format, mapping OpenTelemetry semantic conventions (gen_ai.*) to PostHog AI events.

Supports instrumentation from:
- OpenLLMetry
- LangChain/LangSmith OTLP exports
- OpenLIT
- Any OTLP-compliant LLM tracing library

Endpoint: POST /api/public/otel/v1/traces
Content-Type: application/x-protobuf
Authorization: Bearer <project_api_key>
"""

import base64
import structlog
from typing import Any, Optional
from uuid import UUID

from django.http import HttpRequest, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.trace.v1.trace_pb2 import Span as OTLPSpan

from posthog.api.capture import capture_internal
from posthog.api.utils import get_token
from posthog.models import Team

logger = structlog.get_logger(__name__)


class OTLPAttributeMapper:
    """Maps OpenTelemetry semantic conventions to PostHog AI properties."""

    # OpenTelemetry GenAI semantic conventions to PostHog property mapping
    GENAI_ATTR_MAP = {
        # System and model
        "gen_ai.system": "$ai_provider",
        "gen_ai.request.model": "$ai_model",
        "gen_ai.response.model": "$ai_model",
        # Token usage
        "gen_ai.usage.prompt_tokens": "$ai_prompt_tokens",
        "gen_ai.usage.completion_tokens": "$ai_completion_tokens",
        "gen_ai.usage.total_tokens": "$ai_total_tokens",
        # Request parameters
        "gen_ai.request.temperature": "$ai_temperature",
        "gen_ai.request.max_tokens": "$ai_max_tokens",
        "gen_ai.request.top_p": "$ai_top_p",
        "gen_ai.request.frequency_penalty": "$ai_frequency_penalty",
        "gen_ai.request.presence_penalty": "$ai_presence_penalty",
        # Response metadata
        "gen_ai.response.id": "$ai_response_id",
        "gen_ai.response.finish_reasons": "$ai_finish_reason",
        # Agent and conversation tracking
        "gen_ai.agent.id": "$ai_agent_id",
        "gen_ai.agent.name": "$ai_agent_name",
        "gen_ai.conversation.id": "$ai_session_id",
        # Provider-specific
        "gen_ai.provider.name": "$ai_provider",
        # Additional common attributes
        "llm.model": "$ai_model",
        "llm.provider": "$ai_provider",
        "llm.request.type": "$ai_request_type",
    }

    # HTTP and error attributes
    HTTP_ATTR_MAP = {
        "http.status_code": "$ai_status_code",
        "error.type": "$ai_error_type",
        "error.message": "$ai_error",
    }

    @classmethod
    def map_attributes(cls, otel_attributes: dict[str, Any]) -> dict[str, Any]:
        """
        Map OpenTelemetry attributes to PostHog properties.

        Args:
            otel_attributes: Dictionary of OTLP attribute key-value pairs

        Returns:
            Dictionary of PostHog AI properties
        """
        mapped = {}

        for otel_key, otel_value in otel_attributes.items():
            # Check GenAI mappings
            if otel_key in cls.GENAI_ATTR_MAP:
                posthog_key = cls.GENAI_ATTR_MAP[otel_key]
                mapped[posthog_key] = otel_value
            # Check HTTP/error mappings
            elif otel_key in cls.HTTP_ATTR_MAP:
                posthog_key = cls.HTTP_ATTR_MAP[otel_key]
                mapped[posthog_key] = otel_value
            # Handle prompt/completion content (indexed)
            elif otel_key.startswith("gen_ai.prompt.") and otel_key.endswith(".content"):
                mapped[f"$ai_input_{otel_key.split('.')[2]}"] = otel_value
            elif otel_key.startswith("gen_ai.completion.") and otel_key.endswith(".content"):
                mapped[f"$ai_output_{otel_key.split('.')[2]}"] = otel_value
            # Pass through unknown attributes with otel. prefix
            else:
                mapped[f"otel.{otel_key}"] = otel_value

        return mapped


class OTLPSpanConverter:
    """Converts OTLP spans to PostHog AI events."""

    @staticmethod
    def span_id_to_hex(span_id: bytes) -> str:
        """Convert OTLP span ID bytes to hex string."""
        return span_id.hex() if span_id else ""

    @staticmethod
    def trace_id_to_hex(trace_id: bytes) -> str:
        """Convert OTLP trace ID bytes to hex string."""
        return trace_id.hex() if trace_id else ""

    @classmethod
    def parse_otlp_attributes(cls, attributes) -> dict[str, Any]:
        """
        Parse OTLP KeyValue attributes to dictionary.

        Args:
            attributes: Repeated KeyValue protobuf field

        Returns:
            Dictionary of attribute key-value pairs
        """
        result = {}
        for kv in attributes:
            key = kv.key
            value_field = kv.value.WhichOneof("value")

            if value_field == "string_value":
                result[key] = kv.value.string_value
            elif value_field == "bool_value":
                result[key] = kv.value.bool_value
            elif value_field == "int_value":
                result[key] = kv.value.int_value
            elif value_field == "double_value":
                result[key] = kv.value.double_value
            elif value_field == "array_value":
                result[key] = [
                    cls._parse_array_value(v) for v in kv.value.array_value.values
                ]
            elif value_field == "kvlist_value":
                result[key] = cls.parse_otlp_attributes(kv.value.kvlist_value.values)

        return result

    @staticmethod
    def _parse_array_value(value):
        """Parse a single array value from OTLP."""
        value_field = value.WhichOneof("value")
        if value_field == "string_value":
            return value.string_value
        elif value_field == "bool_value":
            return value.bool_value
        elif value_field == "int_value":
            return value.int_value
        elif value_field == "double_value":
            return value.double_value
        return None

    @classmethod
    def convert_span(cls, span: OTLPSpan, resource_attributes: dict[str, Any]) -> dict[str, Any]:
        """
        Convert an OTLP span to PostHog AI event format.

        Args:
            span: OTLP Span protobuf message
            resource_attributes: Resource-level attributes from OTLP

        Returns:
            PostHog event dictionary
        """
        # Parse span attributes
        span_attributes = cls.parse_otlp_attributes(span.attributes)

        # Merge resource attributes (lower priority)
        all_attributes = {**resource_attributes, **span_attributes}

        # Map to PostHog properties
        properties = OTLPAttributeMapper.map_attributes(all_attributes)

        # Add trace/span identifiers
        properties["$ai_trace_id"] = cls.trace_id_to_hex(span.trace_id)
        properties["$ai_span_id"] = cls.span_id_to_hex(span.span_id)

        if span.parent_span_id:
            properties["$ai_parent_id"] = cls.span_id_to_hex(span.parent_span_id)

        # Add span metadata
        properties["$ai_span_name"] = span.name

        # Calculate latency in milliseconds
        if span.end_time_unix_nano and span.start_time_unix_nano:
            latency_ns = span.end_time_unix_nano - span.start_time_unix_nano
            properties["$ai_latency"] = latency_ns / 1_000_000  # Convert to milliseconds

        # Check for errors
        if span.status and span.status.code == 2:  # STATUS_CODE_ERROR
            properties["$ai_is_error"] = True
            if span.status.message:
                properties["$ai_error"] = span.status.message

        # Determine event type based on span attributes
        event_name = cls._determine_event_type(span_attributes, span.name)

        # Use span start time as event timestamp (convert from nanoseconds to seconds)
        timestamp = None
        if span.start_time_unix_nano:
            timestamp = span.start_time_unix_nano / 1_000_000_000

        return {
            "event": event_name,
            "properties": properties,
            "timestamp": timestamp,
        }

    @staticmethod
    def _determine_event_type(attributes: dict[str, Any], span_name: str) -> str:
        """
        Determine PostHog event type from span attributes.

        Maps to PostHog event types:
        - $ai_generation: LLM completions
        - $ai_embedding: Embedding generation
        - $ai_span: Generic AI operation span
        """
        # Check for LLM generation
        if "gen_ai.request.model" in attributes or "llm.model" in attributes:
            # Check if it's an embedding operation
            if "embedding" in span_name.lower():
                return "$ai_embedding"
            return "$ai_generation"

        # Default to generic AI span
        return "$ai_span"


@method_decorator(csrf_exempt, name="dispatch")
class OTLPTraceView(View):
    """
    OTLP HTTP/protobuf endpoint for ingesting OpenTelemetry traces.

    Accepts OpenTelemetry Protocol (OTLP) trace data in protobuf format and
    converts it to PostHog AI events.

    Endpoint: POST /api/public/otel/v1/traces
    Content-Type: application/x-protobuf
    Authorization: Bearer <project_api_key>
    """

    def post(self, request: HttpRequest) -> JsonResponse:
        """Handle OTLP trace export request."""
        try:
            # Authenticate using Bearer token
            team = self._authenticate(request)
            if not team:
                return JsonResponse(
                    {"error": "Invalid or missing authentication token"},
                    status=status.HTTP_401_UNAUTHORIZED,
                )

            # Parse Content-Type
            content_type = request.headers.get("Content-Type", "")
            if "application/x-protobuf" not in content_type and "application/protobuf" not in content_type:
                return JsonResponse(
                    {"error": "Content-Type must be application/x-protobuf"},
                    status=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                )

            # Parse OTLP protobuf request
            try:
                otlp_request = ExportTraceServiceRequest()
                otlp_request.ParseFromString(request.body)
            except Exception as e:
                logger.error("Failed to parse OTLP protobuf", error=str(e))
                return JsonResponse(
                    {"error": f"Invalid OTLP protobuf format: {str(e)}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Convert OTLP spans to PostHog events
            events = self._convert_otlp_to_events(otlp_request, team)

            if not events:
                return JsonResponse(
                    {"message": "No valid spans found"},
                    status=status.HTTP_200_OK,
                )

            # Send events to PostHog capture
            self._capture_events(events, team, request)

            logger.info(
                "Successfully ingested OTLP traces",
                team_id=team.id,
                span_count=len(events),
            )

            return JsonResponse(
                {
                    "partialSuccess": {},
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            logger.exception("Error processing OTLP request", error=str(e))
            return JsonResponse(
                {"error": f"Internal server error: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def _authenticate(self, request: HttpRequest) -> Optional[Team]:
        """
        Authenticate request using Bearer token.

        Supports both Authorization header and query parameter.
        """
        # Try Authorization header first
        auth_header = request.headers.get("Authorization", "")
        token = None

        if auth_header.startswith("Bearer "):
            token = auth_header[7:]  # Remove "Bearer " prefix
        else:
            # Fallback to query parameter or form data
            token = get_token(None, request)

        if not token:
            return None

        # Find team by API token
        try:
            team = Team.objects.get(api_token=token)
            return team
        except Team.DoesNotExist:
            logger.warning("Invalid API token provided", token_prefix=token[:8] if token else None)
            return None

    def _convert_otlp_to_events(
        self,
        otlp_request: ExportTraceServiceRequest,
        team: Team,
    ) -> list[dict[str, Any]]:
        """
        Convert OTLP request to PostHog events.

        Args:
            otlp_request: Parsed OTLP protobuf request
            team: PostHog team for distinct_id

        Returns:
            List of PostHog event dictionaries
        """
        events = []

        for resource_span in otlp_request.resource_spans:
            # Parse resource attributes (applies to all spans in this resource)
            resource_attributes = {}
            if resource_span.resource and resource_span.resource.attributes:
                resource_attributes = OTLPSpanConverter.parse_otlp_attributes(
                    resource_span.resource.attributes
                )

            # Process each scope's spans
            for scope_span in resource_span.scope_spans:
                for span in scope_span.spans:
                    try:
                        event_data = OTLPSpanConverter.convert_span(span, resource_attributes)

                        # Add distinct_id (use trace_id or default)
                        event_data["distinct_id"] = event_data["properties"].get(
                            "$ai_trace_id", "otel_trace"
                        )

                        events.append(event_data)
                    except Exception as e:
                        logger.warning(
                            "Failed to convert span",
                            span_id=span.span_id.hex() if span.span_id else None,
                            error=str(e),
                        )
                        continue

        return events

    def _capture_events(self, events: list[dict[str, Any]], team: Team, request: HttpRequest) -> None:
        """
        Send events to PostHog capture pipeline.

        Args:
            events: List of event dictionaries
            team: PostHog team
            request: Original HTTP request
        """
        # Use internal capture function to process events
        # This reuses the existing event ingestion pipeline
        for event in events:
            capture_internal(
                event=event["event"],
                distinct_id=event["distinct_id"],
                ip=self._get_client_ip(request),
                site_url=request.build_absolute_uri("/"),
                now=event.get("timestamp"),
                sent_at=None,
                team_id=team.id,
                properties=event["properties"],
            )

    @staticmethod
    def _get_client_ip(request: HttpRequest) -> str:
        """Extract client IP from request."""
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR", "")
