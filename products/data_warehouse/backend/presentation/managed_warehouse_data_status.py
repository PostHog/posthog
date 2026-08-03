from rest_framework import serializers

READINESS_STATE_CHOICES = [
    "not_configured",
    "waiting",
    "backfilling",
    "up_to_date",
    "needs_attention",
]


class ManagedWarehouseDatasetStatusSerializer(serializers.Serializer):
    dataset = serializers.ChoiceField(
        choices=["events", "persons"], help_text="Warehouse dataset represented by this status."
    )
    readiness_state = serializers.ChoiceField(
        choices=READINESS_STATE_CHOICES, help_text="User-facing readiness state for this dataset."
    )
    detail = serializers.CharField(help_text="Human-readable explanation of the current readiness state.")
    completed_partitions = serializers.IntegerField(
        help_text="Number of historical backfill partitions completed successfully."
    )
    total_partitions = serializers.IntegerField(
        allow_null=True, help_text="Expected historical partitions, or null while the range is being calculated."
    )
    current_partition = serializers.CharField(
        allow_null=True, help_text="Partition currently running or requiring attention, when applicable."
    )
    last_updated_at = serializers.DateTimeField(
        allow_null=True, help_text="When the durable backfill status last changed."
    )


class ManagedWarehouseDataStatusResponseSerializer(serializers.Serializer):
    overall_readiness_state = serializers.ChoiceField(
        choices=READINESS_STATE_CHOICES, help_text="Highest-priority readiness state across all warehouse datasets."
    )
    events = ManagedWarehouseDatasetStatusSerializer(help_text="Events backfill readiness.")
    persons = ManagedWarehouseDatasetStatusSerializer(help_text="Persons backfill readiness.")
    generated_at = serializers.DateTimeField(help_text="When this status snapshot was generated.")
