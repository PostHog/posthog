from django.db import models

from posthog.models.utils import sane_repr


class ExternalDataJobBatch(models.Model):
    class Status(models.TextChoices):
        WAITING = "waiting", "waiting"
        EXECUTING = "executing", "executing"
        SUCCEEDED = "succeeded", "succeeded"
        WAITING_RETRY = "waiting_retry", "waiting_retry"
        FAILED = "failed", "failed"

    class SyncType(models.TextChoices):
        FULL_REFRESH = "full_refresh", "full_refresh"
        INCREMENTAL = "incremental", "incremental"
        APPEND = "append", "append"
        CDC = "cdc", "cdc"

    team_id = models.IntegerField()
    schema_id = models.CharField(max_length=200)
    source_id = models.CharField(max_length=200)
    job_id = models.CharField(max_length=200, help_text="FK to ExternalDataJob (UUID as string).")
    run_uuid = models.CharField(max_length=200)

    batch_index = models.IntegerField()
    s3_path = models.TextField()
    row_count = models.IntegerField()
    byte_size = models.BigIntegerField()
    is_final_batch = models.BooleanField()
    total_batches = models.IntegerField(null=True, blank=True)
    total_rows = models.BigIntegerField(null=True, blank=True)
    sync_type = models.CharField(max_length=32, choices=SyncType.choices)
    cumulative_row_count = models.BigIntegerField(default=0)

    resource_name = models.CharField(max_length=400)
    is_resume = models.BooleanField(default=False)
    is_first_ever_sync = models.BooleanField(default=False)

    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Stores partitioning config, CDC mode, primary keys, schema path, data folder, etc.",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    __repr__ = sane_repr("id", "team_id", "schema_id", "batch_index")

    class Meta:
        db_table = "posthog_externaldatajobbatch"
        indexes = [
            models.Index(fields=["team_id", "schema_id"], name="edjb_team_schema_idx"),
            models.Index(fields=["run_uuid"], name="edjb_run_uuid_idx"),
        ]


class ExternalDataJobBatchStatus(models.Model):
    class State(models.TextChoices):
        WAITING = "waiting", "waiting"
        EXECUTING = "executing", "executing"
        SUCCEEDED = "succeeded", "succeeded"
        WAITING_RETRY = "waiting_retry", "waiting_retry"
        FAILED = "failed", "failed"

    batch = models.ForeignKey(
        ExternalDataJobBatch,
        on_delete=models.CASCADE,
        related_name="statuses",
    )
    job_state = models.CharField(max_length=32, choices=State.choices)
    attempt = models.SmallIntegerField(default=0)
    exec_time = models.DateTimeField(null=True, blank=True)
    error_response = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "posthog_externaldatajobbatchstatus"
        indexes = [
            models.Index(
                fields=["batch_id", "-id", "job_state"],
                name="edjbs_batch_id_desc_state_idx",
            ),
        ]
