from rest_framework import serializers

READINESS_STATE_CHOICES = [
    "not_configured",
    "waiting",
    "backfilling",
    "up_to_date",
    "needs_attention",
    "sync_paused",
]
WORKFLOW_TYPE_CHOICES = ["copy", "register"]
WORKFLOW_STATUS_CHOICES = ["running", "completed", "failed", "skipped", "stale"]


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
    workflow_type = serializers.ChoiceField(
        choices=WORKFLOW_TYPE_CHOICES,
        allow_null=True,
        help_text="Workflow applying the latest source import, or null if no workflow has run.",
    )
    workflow_status = serializers.ChoiceField(
        choices=WORKFLOW_STATUS_CHOICES,
        allow_null=True,
        help_text="State of the latest copy or register workflow, or null if no workflow has run.",
    )
    workflow_started_at = serializers.DateTimeField(
        allow_null=True,
        help_text="When the latest copy or register workflow started, or null if no workflow has run.",
    )
    applied = serializers.BooleanField(
        help_text="Whether a copy or register workflow has applied this table to the warehouse."
    )
    last_applied_at = serializers.DateTimeField(
        allow_null=True,
        help_text="When a copy or register workflow most recently applied this table, or null if no workflow completed.",
    )
    last_synced_at = serializers.DateTimeField(
        allow_null=True, help_text="When PostHog most recently completed the upstream source import."
    )


class ManagedWarehouseSourceSummarySerializer(serializers.Serializer):
    source_id = serializers.UUIDField(help_text="Imported source connection identifier.")
    source_name = serializers.CharField(help_text="Display name for the imported source connection.")
    source_type = serializers.CharField(help_text="Type of the imported source connection.")
    readiness_state = serializers.ChoiceField(
        choices=READINESS_STATE_CHOICES, help_text="Rolled-up warehouse readiness state across this source's schemas."
    )
    detail = serializers.CharField(help_text="Human-readable explanation of this source's readiness state.")
    total_schemas = serializers.IntegerField(help_text="Number of this source's schemas visible to the warehouse.")
    applied_schemas = serializers.IntegerField(
        help_text="Number of schemas applied by a completed copy or register workflow."
    )
    last_applied_at = serializers.DateTimeField(
        allow_null=True,
        help_text="Most recent completed copy or register workflow across this source's schemas, or null if none completed.",
    )
    last_synced_at = serializers.DateTimeField(
        allow_null=True, help_text="Most recent upstream source import completion across this source's schemas."
    )


class ManagedWarehouseSourcesStatusSerializer(serializers.Serializer):
    readiness_state = serializers.ChoiceField(
        choices=READINESS_STATE_CHOICES, help_text="Rolled-up readiness state for imported sources."
    )
    detail = serializers.CharField(help_text="Human-readable explanation of imported source readiness.")
    sources = ManagedWarehouseSourceSummarySerializer(
        many=True,
        help_text="Per-source rollup of copy and register workflow statuses for configured warehouse source imports.",
    )


class ManagedWarehouseSourceSchemasQuerySerializer(serializers.Serializer):
    source_id = serializers.UUIDField(help_text="Imported source connection to fetch per-schema detail for.")


class ManagedWarehouseSourceSchemasResponseSerializer(serializers.Serializer):
    schemas = ManagedWarehouseSourceTableStatusSerializer(
        many=True, help_text="Per-schema copy or register workflow status for the requested source."
    )


class ManagedWarehouseDataStatusResponseSerializer(serializers.Serializer):
    overall_readiness_state = serializers.ChoiceField(
        choices=READINESS_STATE_CHOICES, help_text="Highest-priority readiness state across all warehouse datasets."
    )
    events = ManagedWarehouseDatasetStatusSerializer(help_text="Events backfill readiness.")
    persons = ManagedWarehouseDatasetStatusSerializer(help_text="Persons backfill readiness.")
    sources = ManagedWarehouseSourcesStatusSerializer(help_text="Imported source table readiness.")
    generated_at = serializers.DateTimeField(help_text="When this status snapshot was generated.")
