from rest_framework import serializers

READINESS_STATE_CHOICES = [
    "not_configured",
    "waiting",
    "backfilling",
    "catching_up",
    "up_to_date",
    "needs_attention",
    "unknown",
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


class ManagedWarehouseSourceTableStatusSerializer(serializers.Serializer):
    schema_id = serializers.UUIDField(help_text="Imported source schema identifier.")
    source_id = serializers.UUIDField(help_text="Imported source connection identifier.")
    source_name = serializers.CharField(help_text="Display name for the imported source connection.")
    source_type = serializers.CharField(help_text="Type of the imported source connection.")
    table_name = serializers.CharField(help_text="Imported table name.")
    readiness_state = serializers.ChoiceField(
        choices=READINESS_STATE_CHOICES, help_text="User-facing warehouse readiness state for this table."
    )
    detail = serializers.CharField(help_text="Human-readable explanation of the table's readiness state.")
    completed_chunks = serializers.IntegerField(help_text="Backfill chunks already copied into the warehouse.")
    total_chunks = serializers.IntegerField(
        allow_null=True, help_text="Total backfill chunks, or null before the copy plan is ready."
    )
    pending_batches = serializers.IntegerField(
        allow_null=True, help_text="Imported batches waiting to be applied, or null when queue status is unavailable."
    )
    oldest_pending_at = serializers.DateTimeField(
        allow_null=True, help_text="Creation time of the oldest unapplied imported batch."
    )
    last_applied_at = serializers.DateTimeField(
        allow_null=True, help_text="When an imported batch was most recently applied to the warehouse."
    )
    last_synced_at = serializers.DateTimeField(
        allow_null=True, help_text="When PostHog most recently completed the upstream source import."
    )


class ManagedWarehouseSourcesStatusSerializer(serializers.Serializer):
    readiness_state = serializers.ChoiceField(
        choices=READINESS_STATE_CHOICES, help_text="Rolled-up readiness state for imported source tables."
    )
    detail = serializers.CharField(help_text="Human-readable explanation of imported source readiness.")
    tables = ManagedWarehouseSourceTableStatusSerializer(
        many=True, help_text="Per-table source backfill and live import application statuses."
    )


class ManagedWarehouseDataStatusResponseSerializer(serializers.Serializer):
    overall_readiness_state = serializers.ChoiceField(
        choices=READINESS_STATE_CHOICES, help_text="Highest-priority readiness state across all warehouse datasets."
    )
    events = ManagedWarehouseDatasetStatusSerializer(help_text="Events backfill readiness.")
    persons = ManagedWarehouseDatasetStatusSerializer(help_text="Persons backfill readiness.")
    sources = ManagedWarehouseSourcesStatusSerializer(help_text="Imported source table readiness.")
    generated_at = serializers.DateTimeField(help_text="When this status snapshot was generated.")
