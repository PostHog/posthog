"""Snapshot materialization configuration and read-only run state."""

from rest_framework import serializers


class SnapshotConfigSerializer(serializers.Serializer):
    unique_key = serializers.ListField(
        child=serializers.CharField(),
        allow_empty=False,
        help_text="Output columns that identify an entity. Every key column must be present, non-null, and unique.",
    )


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
