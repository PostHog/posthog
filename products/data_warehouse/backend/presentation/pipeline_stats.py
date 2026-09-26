"""Response shapes for the team-wide pipeline aggregates on `DataWarehouseViewSet`.

These actions returned raw dicts, so drf-spectacular inferred nothing and their generated
clients came out as `Promise<void>` — callable, but with no types to build a UI against.

Status and type fields are plain `CharField`s listing their values in `help_text` rather than
`ChoiceField`s. The values here have no `TextChoices` class behind them, and an inline
`choices=` list mints an OpenAPI enum named after the field, which collides with every other
`status`/`type` enum and fails the schema build under `--fail-on-warn`.
"""

from rest_framework import serializers


class PipelineErrorSerializer(serializers.Serializer):
    error = serializers.CharField(help_text="What went wrong, for a reader rather than a parser.")


class JobStatsQuerySerializer(serializers.Serializer):
    days = serializers.ChoiceField(
        choices=[1, 7, 30],
        required=False,
        default=7,
        help_text="Window the counts should cover, in days. One of 1, 7 or 30. Defaults to 7.",
    )


class PipelineActivityQuerySerializer(serializers.Serializer):
    limit = serializers.IntegerField(
        required=False, default=20, help_text="Max rows to return. Capped at 50 server-side. Defaults to 20."
    )
    offset = serializers.IntegerField(
        required=False, default=0, help_text="Rows to skip, for pagination. Defaults to 0."
    )
    cutoff_days = serializers.IntegerField(
        required=False, default=30, help_text="Only include runs created within this many days of now. Defaults to 30."
    )


class CompletedActivityQuerySerializer(PipelineActivityQuerySerializer):
    outcome = serializers.ChoiceField(
        choices=["completed", "failed"],
        required=False,
        default="completed",
        help_text="Which outcome to return: 'completed' or 'failed'. Defaults to 'completed'.",
    )


class JobCountsSerializer(serializers.Serializer):
    total = serializers.IntegerField(help_text="Runs that finished inside the window.")
    running = serializers.IntegerField(help_text="Runs in flight right now, regardless of the window.")
    successful = serializers.IntegerField(help_text="Runs that completed.")
    failed = serializers.IntegerField(help_text="Runs that errored or that billing stopped.")


class JobStatsBucketSerializer(serializers.Serializer):
    successful = serializers.IntegerField(help_text="Runs that completed in this bucket.")
    failed = serializers.IntegerField(help_text="Runs that failed in this bucket.")


class PipelineJobStatsResponseSerializer(serializers.Serializer):
    days = serializers.IntegerField(help_text="Window the counts cover, in days. One of 1, 7 or 30.")
    cutoff_time = serializers.DateTimeField(help_text="Start of the window, in the project's timezone.")
    total_jobs = serializers.IntegerField(help_text="Sync runs plus materialization runs in the window.")
    successful_jobs = serializers.IntegerField(help_text="Sync and materialization runs that completed.")
    failed_jobs = serializers.IntegerField(help_text="Sync and materialization runs that failed.")
    external_data_jobs = JobCountsSerializer(help_text="Counts for warehouse source syncs alone.")
    modeling_jobs = JobCountsSerializer(help_text="Counts for materialized view runs alone.")
    breakdown = serializers.DictField(
        child=JobStatsBucketSerializer(),
        help_text=(
            "Runs per time bucket, keyed by ISO hour when days=1 and by ISO date otherwise. "
            "Buckets with no runs are absent rather than zero."
        ),
    )


class PipelineRowsStatsResponseSerializer(serializers.Serializer):
    billing_available = serializers.BooleanField(
        help_text="Whether billing answered. When false, only the counts derived from runs are meaningful."
    )
    billing_interval = serializers.CharField(
        allow_null=True, help_text="Length of the billing period, for example 'month'."
    )
    billing_period_start = serializers.DateTimeField(allow_null=True, help_text="Start of the current billing period.")
    billing_period_end = serializers.DateTimeField(allow_null=True, help_text="End of the current billing period.")
    total_rows = serializers.IntegerField(help_text="Rows synced in the billing period, billed and not yet billed.")
    tracked_billing_rows = serializers.IntegerField(help_text="Rows billing has already counted.")
    pending_billing_rows = serializers.IntegerField(help_text="Rows synced since billing last counted.")
    materialized_rows_in_billing_period = serializers.IntegerField(
        help_text="Rows written by materialized view runs in the billing period."
    )
    breakdown_of_rows_by_source = serializers.DictField(
        child=serializers.IntegerField(),
        help_text="Rows synced in the billing period, keyed by source id.",
    )


class PipelineActivityRowSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Run id.")
    type = serializers.CharField(
        allow_null=True,
        help_text="The source type for a sync, or 'Materialized view' for a model run.",
    )
    name = serializers.CharField(allow_null=True, help_text="Table or view the run wrote.")
    status = serializers.CharField(
        help_text="Run status. One of: Running, Completed, Failed, BillingLimitReached, BillingLimitTooLow."
    )
    rows = serializers.IntegerField(help_text="Rows the run wrote. Zero while it is still going.")
    created_at = serializers.DateTimeField(help_text="When the run was created. There is no separate start time.")
    finished_at = serializers.DateTimeField(allow_null=True, help_text="When the run ended, or null while running.")
    latest_error = serializers.CharField(allow_null=True, help_text="Error the run ended with, if any.")
    workflow_run_id = serializers.CharField(allow_null=True, help_text="Temporal run id, for finding the run's logs.")
    origin = serializers.CharField(allow_null=True, help_text="Where a materialized view came from. Null for syncs.")


class PipelineActivityResponseSerializer(serializers.Serializer):
    results = PipelineActivityRowSerializer(many=True, help_text="Runs, newest first.")
    next = serializers.CharField(allow_null=True, help_text="Query string for the next page, or null on the last.")
    previous = serializers.CharField(
        allow_null=True, help_text="Query string for the previous page, or null on the first."
    )


class DataHealthIssueSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Id of the thing that is unhealthy.")
    name = serializers.CharField(help_text="Table, view or export the issue is about.")
    type = serializers.CharField(
        help_text=(
            "What kind of thing is unhealthy. One of: materialized_view, external_data_sync, source, "
            "destination, transformation."
        )
    )
    source_type = serializers.CharField(
        allow_null=True, required=False, help_text="Source type for a sync issue, for example 'Stripe'."
    )
    status = serializers.CharField(help_text="Why it is unhealthy. One of: failed, disabled, degraded, billing_limit.")
    error = serializers.CharField(allow_null=True, help_text="The error, where one was recorded.")
    failed_at = serializers.DateTimeField(allow_null=True, help_text="When it last failed.")
    url = serializers.CharField(allow_null=True, help_text="Where to go to fix it.")


class DataHealthIssuesResponseSerializer(serializers.Serializer):
    results = DataHealthIssueSerializer(many=True, help_text="Everything currently unhealthy.")
    count = serializers.IntegerField(help_text="How many issues are in `results`.")
