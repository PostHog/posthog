"""Hog function input and filter serializers that other products' views reuse.

A facade must not hand out DRF classes, so these cross through presentation instead.
"""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from products.cdp.backend.facade.mcp_event_types import MCPEventData, MCPEventEnvelope
from products.cdp.backend.validation import (
    HogFunctionFiltersSerializer as HogFunctionFiltersSerializer,
    InputsSchemaSerializer as InputsSchemaSerializer,
    InputsSerializer as InputsSerializer,
    require_viewer_access_to_added_actions as require_viewer_access_to_added_actions,
)


@extend_schema_field(
    {
        "type": "object",
        "additionalProperties": {
            "nullable": True,
            "oneOf": [
                {"type": "string"},
                {"type": "number"},
                {"type": "boolean"},
                {"type": "object", "additionalProperties": True},
                {"type": "array", "items": {}},
            ],
        },
    }
)
class _MCPEventPropertiesField(serializers.JSONField):
    pass


class MCPEventDataSerializer(DataclassSerializer):
    properties = _MCPEventPropertiesField(help_text="Event properties the subscriber is allowed to read.")

    class Meta:
        dataclass = MCPEventData
        extra_kwargs = {
            "event": {"help_text": "Original captured event name.", "allow_blank": True},
            "distinct_id": {"help_text": "Distinct ID attached to the captured event.", "allow_blank": True},
        }


class MCPEventEnvelopeSerializer(DataclassSerializer):
    timestamp = serializers.DateTimeField(help_text="Event occurrence time, including its timezone.")
    cursor = serializers.JSONField(allow_null=True, help_text="Null because replay is unavailable.")

    class Meta:
        dataclass = MCPEventEnvelope
        extra_kwargs = {
            "eventId": {
                "min_length": 1,
                "max_length": 255,
                "help_text": "Stable source event ID used to deduplicate deliveries.",
            },
            "name": {"help_text": "Subscribed MCP event type."},
        }

    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        fields["data"] = MCPEventDataSerializer(help_text="Captured event data.")
        return fields
