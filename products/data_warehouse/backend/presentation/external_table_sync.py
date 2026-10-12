from rest_framework import serializers

from products.managed_warehouse.backend.facade.contracts import ExternalTableSyncStatus


class ExternalTableSyncRequestSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(help_text="Opt in to scheduled snapshots into the managed warehouse.")
    interval_minutes = serializers.IntegerField(
        min_value=5, max_value=10080, help_text="Minutes between refreshes, from five minutes to seven days."
    )


class ExternalTableSyncSettingsSerializer(serializers.Serializer):
    available = serializers.BooleanField(help_text="Whether this table and project support warehouse sync.")
    unavailable_reason = serializers.CharField(allow_null=True, help_text="Reason warehouse sync cannot be enabled.")
    enabled = serializers.BooleanField(help_text="Whether the project opted in to refreshing this table.")
    interval_minutes = serializers.IntegerField(help_text="Minutes between scheduled refreshes.")
    status = serializers.ChoiceField(choices=ExternalTableSyncStatus.choices, help_text="Latest publication status.")
    last_synced_at = serializers.DateTimeField(allow_null=True, help_text="Time of the last successful refresh.")
    error = serializers.CharField(allow_null=True, help_text="Safe guidance for retrying a failed refresh.")


class ExternalTableSyncErrorSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Safe explanation of why the sync settings could not be applied.")
