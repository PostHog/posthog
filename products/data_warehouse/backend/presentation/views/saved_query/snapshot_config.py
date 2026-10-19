"""Snapshot materialization configuration and read-only run state."""

from rest_framework import serializers


class SnapshotConfigSerializer(serializers.Serializer):
    unique_key = serializers.ListField(
        child=serializers.CharField(),
        allow_empty=False,
        help_text="Output columns that identify an entity. Every key column must be present, non-null, and unique.",
    )

    def validate(self, attrs: dict) -> dict:
        # A partial update skips required child fields, so require the key here: the object replaces the config.
        unique_key = attrs.get("unique_key")
        if not unique_key:
            raise serializers.ValidationError({"unique_key": "This field is required."})
        if len(set(unique_key)) != len(unique_key):
            raise serializers.ValidationError({"unique_key": "Unique-key columns must be distinct."})
        return attrs


class SnapshotStateSerializer(serializers.Serializer):
    generation = serializers.CharField(allow_null=True, required=False)
    definition_fingerprint = serializers.CharField(allow_null=True, required=False)
    first_observation_at = serializers.DateTimeField(allow_null=True, required=False)
    last_observation_at = serializers.DateTimeField(allow_null=True, required=False)
    last_run_id = serializers.CharField(allow_null=True, required=False)
    inserted = serializers.IntegerField(required=False)
    changed = serializers.IntegerField(required=False)
    removed = serializers.IntegerField(required=False)
    unchanged = serializers.IntegerField(required=False)
    rows_scanned = serializers.IntegerField(required=False)
