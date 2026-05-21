"""Serializer for DeploymentEvent."""

from __future__ import annotations

from rest_framework import serializers

from ..models import DeploymentEvent


class DeploymentEventSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True, help_text="Unique identifier for the event row.")
    deployment: serializers.PrimaryKeyRelatedField = serializers.PrimaryKeyRelatedField(  # ty: ignore[invalid-assignment]
        read_only=True,
        help_text="The deployment this event belongs to.",
    )
    event_type = serializers.CharField(
        max_length=50,
        help_text="Event category, e.g. `status_changed`, `preview_captured`, `dispatched`.",
    )
    payload = serializers.JSONField(
        help_text="Arbitrary structured payload for the event. Shape varies by event_type.",
    )
    occurred_at = serializers.DateTimeField(
        read_only=True,
        help_text="When the event occurred (server time).",
    )

    class Meta:
        model = DeploymentEvent
        fields = ["id", "deployment", "event_type", "payload", "occurred_at"]
        read_only_fields = ["id", "deployment", "occurred_at"]
