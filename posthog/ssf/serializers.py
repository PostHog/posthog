from typing import Any

from django.db import models
from django.utils import timezone

from drf_spectacular.utils import extend_schema_field
from pydantic import JsonValue, RootModel
from rest_framework import serializers

from posthog.api.scoped_related_fields import OrgScopedPrimaryKeyRelatedField
from posthog.models.ssf import SSFConfiguration, SSFConnection, SSFStream
from posthog.ssf.validation import (
    CONTROL_EVENTS,
    POLL_DELIVERY,
    SSFOutgoingEventType,
    SSFStreamEventType,
    validate_issuer,
    validate_subject,
)


class SSFSubject(RootModel[dict[str, JsonValue]]):
    pass


@extend_schema_field(SSFSubject)  # type: ignore[arg-type] # Pydantic models are absent from the stubs.
class SubjectField(serializers.JSONField):
    def to_internal_value(self, data: Any) -> dict[str, JsonValue]:
        try:
            return validate_subject(super().to_internal_value(data))
        except ValueError as error:
            raise serializers.ValidationError(str(error)) from error


class SSFConfigurationSerializer(serializers.ModelSerializer):
    event_types = serializers.ListField(
        child=serializers.ChoiceField(choices=SSFOutgoingEventType.choices),
        max_length=len(SSFOutgoingEventType),
        required=False,
        help_text="Preset security event types allowed for outgoing producers. Custom event types are not accepted. SSF control events are always supported.",
    )

    class Meta:
        model = SSFConfiguration
        fields = ["enabled", "event_types"]
        extra_kwargs = {
            "enabled": {
                "help_text": "Enable SSF for this organization. Connections and streams remain organization-scoped."
            }
        }

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if any(field.startswith("receiver_") or field == "transmitter_audience" for field in self.initial_data):
            raise serializers.ValidationError(
                "Configure peers through the SSF connections API and streams through the SSF streams API."
            )
        return attrs

    def to_representation(self, instance: SSFConfiguration) -> dict[str, JsonValue]:
        data: dict[str, JsonValue] = super().to_representation(instance)
        data["event_types"] = [event for event in SSFOutgoingEventType.values if event in instance.event_types]
        return data

    def validate_event_types(self, value: list[str]) -> list[str]:
        if (
            self.instance
            and set(value) != (set(self.instance.event_types) & set(SSFOutgoingEventType.values))
            and SSFStream.objects.filter(
                organization=self.instance.organization, connection__direction=SSFConnection.Direction.OUTGOING
            ).exists()
        ):
            raise serializers.ValidationError("Delete outgoing streams before changing the supported event types.")
        return [event for event in SSFOutgoingEventType.values if event in value]


class SSFEndpointsSerializer(serializers.Serializer):
    issuer = serializers.URLField(help_text="PostHog's organization-specific transmitter issuer.")
    discovery_url = serializers.URLField(help_text="Transmitter metadata URL for external receivers.")
    jwks_url = serializers.URLField(help_text="Public signing keys used by the organization's transmitter.")


class SSFEventTypeOptionSerializer(serializers.Serializer):
    key = serializers.ChoiceField(choices=SSFOutgoingEventType.choices, help_text="Preset security event type URI.")
    label = serializers.CharField(help_text="Human-readable event type name.")  # type: ignore[assignment]


class SSFSettingsSerializer(SSFConfigurationSerializer):
    endpoints = SSFEndpointsSerializer(read_only=True, help_text="Organization-specific transmitter endpoints.")
    event_type_options = serializers.SerializerMethodField(
        help_text="Fixed catalog of additional outgoing security event types available for selection."
    )

    @extend_schema_field(SSFEventTypeOptionSerializer(many=True))
    def get_event_type_options(self, instance: SSFConfiguration) -> list[dict[str, str]]:
        return [{"key": key, "label": str(label)} for key, label in SSFOutgoingEventType.choices]

    class Meta(SSFConfigurationSerializer.Meta):
        fields = [*SSFConfigurationSerializer.Meta.fields, "endpoints", "event_type_options"]


class SSFCredentialSerializer(serializers.Serializer):
    token = serializers.CharField(help_text="New stream management bearer credential. Returned only once.")


class SSFConnectionSerializer(serializers.ModelSerializer):
    remote_token = serializers.RegexField(
        r"^[A-Za-z0-9\-._~+/]+=*$",
        max_length=4096,
        required=False,
        write_only=True,
        help_text="Transmitter API bearer token, without the Bearer prefix. Stored encrypted and never returned.",
    )
    has_remote_token = serializers.SerializerMethodField(
        help_text="Whether a transmitter API bearer token is configured."
    )
    has_management_token = serializers.SerializerMethodField(
        help_text="Whether a management credential has been issued to this receiver."
    )
    stream_count = serializers.SerializerMethodField(help_text="Number of local streams attached to this connection.")

    class Meta:
        model = SSFConnection
        fields = [
            "id",
            "name",
            "direction",
            "enabled",
            "issuer",
            "audience",
            "remote_token",
            "jwks_uri",
            "discovered_at",
            "has_remote_token",
            "has_management_token",
            "stream_count",
            "created_at",
        ]
        read_only_fields = ["id", "jwks_uri", "discovered_at", "created_at"]
        extra_kwargs = {
            "name": {"help_text": "Human-readable connection name."},
            "direction": {
                "help_text": "Incoming receives events from a transmitter; outgoing grants an external receiver access to PostHog streams."
            },
            "enabled": {
                "help_text": "Allow this connection to send or receive events when organization SSF is enabled."
            },
            "issuer": {
                "help_text": "Incoming transmitter's exact HTTPS issuer. Its SSF metadata and JWKS are discovered automatically."
            },
            "audience": {
                "help_text": "Optional agreed receiver audience. Outgoing connections get a unique audience when omitted. Incoming connections can restrict the audience assigned by their transmitter."
            },
            "jwks_uri": {"help_text": "Signing-key URL discovered from the trusted transmitter's metadata."},
            "discovered_at": {"help_text": "When transmitter metadata and signing keys were last checked."},
            "created_at": {"help_text": "When the connection was created."},
        }

    def get_has_remote_token(self, instance: SSFConnection) -> bool:
        return bool(instance.remote_token)

    def get_has_management_token(self, instance: SSFConnection) -> bool:
        return bool(instance.token_hash)

    def get_stream_count(self, instance: SSFConnection) -> int:
        count = getattr(instance, "stream_count", None)
        return count if count is not None else instance.streams.filter(organization=instance.organization).count()

    def validate_issuer(self, value: str) -> str:
        try:
            return validate_issuer(value) if value else value
        except ValueError as error:
            raise serializers.ValidationError(str(error)) from error

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if self.instance:
            for field in ("direction", "issuer", "audience"):
                if field in attrs and attrs[field] != getattr(self.instance, field):
                    raise serializers.ValidationError({field: "Create a separate connection to change this identity."})
            direction = self.instance.direction
        else:
            direction = attrs.get("direction")
        if direction == SSFConnection.Direction.INCOMING:
            if not (attrs.get("issuer") or (self.instance and self.instance.issuer)):
                raise serializers.ValidationError({"issuer": "Enter the trusted transmitter issuer."})
            if not self.instance and not attrs.get("remote_token"):
                raise serializers.ValidationError({"remote_token": "Enter the transmitter API bearer token."})
        elif direction == SSFConnection.Direction.OUTGOING:
            if attrs.get("issuer") or attrs.get("remote_token"):
                raise serializers.ValidationError("Outgoing receivers do not use remote transmitter credentials.")
        return attrs


class SSFConnectionField(OrgScopedPrimaryKeyRelatedField):
    scope_field = "organization"


class SSFStreamUpdateSerializer(serializers.Serializer):
    description = serializers.CharField(
        max_length=1024, required=False, allow_blank=True, help_text="Updated stream description."
    )
    events_requested = serializers.ListField(
        child=serializers.ChoiceField(choices=SSFStreamEventType.choices),
        max_length=len(SSFStreamEventType),
        required=False,
        help_text="Updated preset event type URIs. SSF control events are supported automatically.",
    )


class SSFStreamCreateSerializer(serializers.Serializer):
    connection = SSFConnectionField(
        queryset=SSFConnection.objects.all(), help_text="Connection in the organization that owns this stream."
    )
    description = serializers.CharField(
        max_length=1024, required=False, allow_blank=True, default="", help_text="Human-readable stream description."
    )
    events_requested = serializers.ListField(
        child=serializers.ChoiceField(choices=SSFStreamEventType.choices),
        max_length=len(SSFStreamEventType),
        required=False,
        default=CONTROL_EVENTS,
        help_text="Requested preset event type URIs. Leave unset to request SSF control events for setup.",
    )


class SSFStreamSerializer(serializers.ModelSerializer):
    direction = serializers.ChoiceField(
        source="connection.direction",
        choices=SSFConnection.Direction.choices,
        read_only=True,
        help_text="Connection direction.",
    )
    audiences = serializers.ListField(
        child=serializers.CharField(), read_only=True, help_text="Immutable receiver audiences assigned to the stream."
    )
    events_requested = serializers.ListField(
        child=serializers.CharField(), read_only=True, help_text="Requested event types."
    )
    events_delivered = serializers.ListField(
        child=serializers.CharField(), read_only=True, help_text="Event types negotiated for delivery."
    )
    verification_pending = serializers.SerializerMethodField(
        help_text="Whether a verification request is awaiting delivery within its five-minute confirmation window."
    )
    is_busy = serializers.SerializerMethodField(help_text="Whether another stream operation holds the setup lease.")

    class Meta:
        model = SSFStream
        fields = [
            "id",
            "connection",
            "direction",
            "description",
            "status",
            "reason",
            "audiences",
            "events_requested",
            "events_delivered",
            "remote_stream_id",
            "endpoint_url",
            "last_verified_at",
            "last_error",
            "retry_at",
            "verification_pending",
            "is_busy",
            "created_at",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "id": {"help_text": "Local stream ID."},
            "connection": {"help_text": "Owning connection ID."},
            "description": {"help_text": "Human-readable stream description."},
            "status": {"help_text": "Current delivery or provisioning status."},
            "reason": {"help_text": "Reason for the current stream status."},
            "remote_stream_id": {"help_text": "Stream ID assigned by the remote transmitter for incoming streams."},
            "endpoint_url": {
                "help_text": "Local push receiver URL for incoming streams, or polling URL for outgoing streams."
            },
            "last_verified_at": {"help_text": "When the last valid incoming verification event was received."},
            "last_error": {
                "help_text": "Last provisioning or delivery setup error. No credentials or event payloads are included."
            },
            "retry_at": {"help_text": "Earliest retry allowed by the transmitter after rate limiting."},
            "created_at": {"help_text": "When the stream was created."},
        }

    def get_verification_pending(self, instance: SSFStream) -> bool:
        requested = instance.verification_requested_at
        return bool(
            requested
            and not instance.last_error
            and (instance.last_verified_at is None or instance.last_verified_at < requested)
            and (timezone.now() - requested).total_seconds() < 300
        )

    def get_is_busy(self, instance: SSFStream) -> bool:
        return bool(instance.operation_until and instance.operation_until > timezone.now())


class SSFProtocolStatus(models.TextChoices):
    ENABLED = "enabled", "Enabled"
    PAUSED = "paused", "Paused"
    DISABLED = "disabled", "Disabled"


class SSFStatusInputSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=SSFProtocolStatus.choices, help_text="Requested delivery status.")
    reason = serializers.CharField(
        max_length=1024, allow_blank=True, required=False, default="", help_text="Reason for the change."
    )


class SSFSubjectInputSerializer(serializers.Serializer):
    subject = SubjectField(help_text="Simple or complex SSF subject identifier to subscribe to or remove.")


class SSFVerificationInputSerializer(serializers.Serializer):
    state = serializers.CharField(
        max_length=1024,
        allow_blank=True,
        required=False,
        help_text="Optional opaque verification state. A fresh state is generated when omitted.",
    )


class DeliverySerializer(serializers.Serializer):
    method = serializers.CharField(
        default=POLL_DELIVERY, help_text="Outgoing delivery method URI; PostHog supports urn:ietf:rfc:8936."
    )
    endpoint_url = serializers.URLField(required=False, help_text="Transmitter-assigned polling URL.")

    def validate_method(self, value: str) -> str:
        if value != POLL_DELIVERY:
            raise serializers.ValidationError("This transmitter supports poll delivery only.")
        return value


class StreamRequestSerializer(serializers.Serializer):
    stream_id = serializers.UUIDField(required=False, help_text="Stream to update.")
    events_requested = serializers.ListField(
        child=serializers.CharField(max_length=2048),
        max_length=100,
        required=False,
        help_text="Requested event type URIs.",
    )
    delivery = DeliverySerializer(required=False, help_text="Polling delivery configuration.")
    description = serializers.CharField(
        max_length=1024, allow_blank=True, required=False, help_text="Stream description."
    )


class StreamIDSerializer(serializers.Serializer):
    stream_id = serializers.UUIDField(help_text="Local transmitter stream ID.")


class StreamStatusSerializer(StreamIDSerializer, SSFStatusInputSerializer):
    pass


class SubjectRequestSerializer(StreamIDSerializer, SSFSubjectInputSerializer):
    verified = serializers.BooleanField(
        required=False, default=True, help_text="Whether the receiver verified the subject."
    )


class VerificationRequestSerializer(StreamIDSerializer, SSFVerificationInputSerializer):
    pass


class SETErrorSerializer(serializers.Serializer):
    err = serializers.CharField(max_length=128, help_text="Security event token error code.")
    description = serializers.CharField(
        max_length=1024, required=False, allow_blank=True, help_text="Token validation error description."
    )


class PollRequestSerializer(serializers.Serializer):
    maxEvents = serializers.IntegerField(
        min_value=0, required=False, default=100, help_text="Maximum events to retrieve; zero acknowledges only."
    )
    returnImmediately = serializers.BooleanField(
        required=False, default=False, help_text="Return without waiting for new events."
    )
    ack = serializers.ListField(
        child=serializers.CharField(max_length=255),
        max_length=1000,
        required=False,
        default=list,
        help_text="Successfully received token IDs to acknowledge.",
    )
    setErrs = serializers.DictField(
        child=SETErrorSerializer(), required=False, default=dict, help_text="Rejected token IDs and validation errors."
    )

    def validate_setErrs(self, value: dict[str, Any]) -> dict[str, Any]:
        if len(value) > 1000 or any(len(key) > 255 for key in value):
            raise serializers.ValidationError(
                "Acknowledge at most 1000 token IDs of at most 255 characters per request."
            )
        return value
