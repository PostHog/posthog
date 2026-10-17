import json
from datetime import datetime
from typing import cast

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from pydantic import JsonValue
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework_dataclasses.serializers import DataclassSerializer

from products.cdp.backend.facade.mcp_event_types import MCPEventData, MCPEventEnvelope


class MCPEventPropertiesField(serializers.JSONField):
    def to_internal_value(self, data: object) -> dict[str, JsonValue]:
        if not isinstance(data, dict):
            raise ValidationError("The event properties must be a JSON object.")
        return cast(dict[str, JsonValue], super().to_internal_value(data))


class _StrictCharField(serializers.CharField):
    def to_internal_value(self, data: object) -> str:
        if not isinstance(data, str):
            raise ValidationError("Use a string.")
        return super().to_internal_value(data)


class _StrictDataclassSerializer(DataclassSerializer):
    serializer_field_mapping = {**DataclassSerializer.serializer_field_mapping, str: _StrictCharField}

    def to_internal_value(self, data: object) -> object:
        if not isinstance(data, dict) or set(data) != set(self.fields):
            raise ValidationError({"non_field_errors": ["Send the exact event envelope fields."]})
        return super().to_internal_value(data)


class MCPEventDataSerializer(_StrictDataclassSerializer):
    properties = MCPEventPropertiesField()

    class Meta:
        dataclass = MCPEventData
        extra_kwargs = {
            "event": {"allow_blank": True, "trim_whitespace": False},
            "distinct_id": {
                "allow_blank": True,
                "trim_whitespace": False,
            },
        }


class _AwareDateTimeField(serializers.DateTimeField):
    def to_internal_value(self, data: object) -> datetime:
        if not isinstance(data, str):
            raise ValidationError("Use a timestamp string including its timezone.")
        try:
            timestamp = parse_datetime(data)
        except ValueError:
            timestamp = None
        if timestamp is None or timezone.is_naive(timestamp):
            raise ValidationError("The event timestamp must include a timezone.")
        return super().to_internal_value(data)


class MCPEventEnvelopeSerializer(_StrictDataclassSerializer):
    timestamp = _AwareDateTimeField()
    cursor = serializers.JSONField(allow_null=True)

    class Meta:
        dataclass = MCPEventEnvelope
        extra_kwargs = {
            "eventId": {
                "min_length": 1,
                "max_length": 255,
                "trim_whitespace": False,
            },
        }

    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        fields["data"] = MCPEventDataSerializer()
        return fields

    def validate_cursor(self, value: object) -> None:
        if value is not None:
            raise ValidationError("Replay is unavailable. Use null.")

    @classmethod
    def parse(cls, body: str) -> MCPEventEnvelope:
        try:
            value = json.loads(body)
        except ValueError:
            raise ValidationError("Send a valid JSON event envelope.") from None
        serializer = cls(data=value)
        serializer.is_valid(raise_exception=True)
        return cast(MCPEventEnvelope, serializer.validated_data)

    @classmethod
    def render(cls, envelope: MCPEventEnvelope) -> str:
        try:
            return json.dumps(cls(envelope).data, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        except ValueError:
            raise ValidationError("Event properties must contain valid JSON values.") from None
