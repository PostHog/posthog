from django.db import models

from rest_framework import serializers


class ManagedWarehouseReadinessState(models.TextChoices):
    NOT_CONFIGURED = "not_configured", "not_configured"
    WAITING = "waiting", "waiting"
    BACKFILLING = "backfilling", "backfilling"
    UP_TO_DATE = "up_to_date", "up_to_date"
    NEEDS_ATTENTION = "needs_attention", "needs_attention"
    SYNC_PAUSED = "sync_paused", "sync_paused"


class ManagedWarehouseLandingState(models.TextChoices):
    IN_SYNC = "in_sync", "in_sync"
    BEHIND = "behind", "behind"
    FAILING = "failing", "failing"
    NOT_IN_WAREHOUSE = "not_in_warehouse", "not_in_warehouse"
    PAUSED = "paused", "paused"


class ManagedWarehouseLandingHistoryDays(models.IntegerChoices):
    WEEK = 7, "7"
    MONTH = 30, "30"


LANDING_STATE_CHOICES = ManagedWarehouseLandingState.choices
READINESS_STATE_CHOICES = list(ManagedWarehouseReadinessState.values)
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
    landing_state = serializers.ChoiceField(
        choices=LANDING_STATE_CHOICES,
        help_text="Whether this dataset's data has landed in the warehouse: in_sync, behind, failing or not_in_warehouse.",
    )
    failed_partitions = serializers.IntegerField(help_text="Number of backfill partitions whose latest run failed.")
    last_error = serializers.CharField(
        allow_null=True, help_text="Error from the failed partition named in current_partition, when one failed."
    )
    last_completed_at = serializers.DateTimeField(
        allow_null=True, help_text="When a backfill partition most recently completed, or null if none completed."
    )
    latest_day_loaded = serializers.DateField(
        allow_null=True,
        help_text="Most recent day covered by a completed daily backfill partition, or null if none completed.",
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
    landing_state = serializers.ChoiceField(
        choices=LANDING_STATE_CHOICES,
        help_text="Whether the latest upstream import has landed in the warehouse: in_sync, behind, failing, "
        "not_in_warehouse or paused.",
    )
    pending_since = serializers.DateTimeField(
        allow_null=True,
        help_text="When an upstream import started waiting for the warehouse to apply it, or null if nothing is waiting.",
    )
    workflow_finished_at = serializers.DateTimeField(
        allow_null=True, help_text="When the latest copy or register workflow finished, or null if it has not."
    )
    workflow_error = serializers.CharField(
        allow_null=True, help_text="Error from the latest copy or register workflow, only when that workflow failed."
    )
    sync_status = serializers.CharField(allow_null=True, help_text="Status of the upstream source sync for this table.")
    sync_error = serializers.CharField(
        allow_null=True, help_text="Error from the upstream source sync, only when that sync is failing."
    )
    last_sync_rows = serializers.IntegerField(
        allow_null=True, help_text="Rows imported by the most recent completed upstream sync, or null if none."
    )


class ManagedWarehouseLandingCountsSerializer(serializers.Serializer):
    in_sync = serializers.IntegerField(help_text="Schemas whose latest import is applied to the warehouse.")
    behind = serializers.IntegerField(help_text="Schemas with an import waiting or being applied.")
    failing = serializers.IntegerField(help_text="Schemas whose latest warehouse workflow failed.")
    not_in_warehouse = serializers.IntegerField(help_text="Schemas never applied to the warehouse.")
    paused = serializers.IntegerField(help_text="Schemas with sync paused.")


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
    landing_state = serializers.ChoiceField(
        choices=LANDING_STATE_CHOICES,
        help_text="Rolled-up landing state across this source's schemas, worst first: failing, behind, "
        "not_in_warehouse, in_sync, paused.",
    )
    landing_counts = ManagedWarehouseLandingCountsSerializer(
        help_text="Number of this source's schemas in each landing state."
    )
    pending_since = serializers.DateTimeField(
        allow_null=True,
        help_text="Oldest time an upstream import started waiting for the warehouse, or null if nothing is waiting.",
    )
    sync_failed_schemas = serializers.IntegerField(
        help_text="Number of active schemas whose upstream source sync is currently failing."
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


class ManagedWarehouseLandingHistoryQuerySerializer(serializers.Serializer):
    days = serializers.ChoiceField(
        choices=ManagedWarehouseLandingHistoryDays.choices,
        default=ManagedWarehouseLandingHistoryDays.WEEK,
        help_text="Number of calendar days to return, ending today in the project timezone.",
    )


class ManagedWarehouseLandingHistoryBucketSerializer(serializers.Serializer):
    date = serializers.DateField(help_text="Calendar day in the project timezone.")
    source_succeeded = serializers.IntegerField(
        help_text="Copy or register workflow attempts for imported sources that completed on this day."
    )
    source_failed = serializers.IntegerField(
        help_text="Copy or register workflow attempts for imported sources that failed on this day."
    )
    backfill_succeeded = serializers.IntegerField(
        help_text="Events and persons backfill partitions whose latest outcome was completed on this day. "
        "A partition row is overwritten on retry, so each partition counts once, at its latest outcome."
    )
    backfill_failed = serializers.IntegerField(
        help_text="Events and persons backfill partitions whose latest outcome was failed on this day. "
        "A partition row is overwritten on retry, so each partition counts once, at its latest outcome."
    )


class ManagedWarehouseLandingHistoryResponseSerializer(serializers.Serializer):
    days = serializers.IntegerField(help_text="Number of days covered by the buckets.")
    buckets = ManagedWarehouseLandingHistoryBucketSerializer(
        many=True, help_text="One bucket per calendar day, oldest first, zero filled."
    )
