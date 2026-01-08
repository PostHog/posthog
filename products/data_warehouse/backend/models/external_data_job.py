from uuid import UUID

from django.conf import settings
from django.db import models
from django.db.models import Prefetch

from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDTModel, sane_repr
from posthog.sync import database_sync_to_async


class ExternalDataJob(CreatedMetaFields, UpdatedMetaFields, UUIDTModel):
    class Status(models.TextChoices):
        RUNNING = "Running", "Running"
        FAILED = "Failed", "Failed"
        COMPLETED = "Completed", "Completed"
        BILLING_LIMIT_REACHED = "BillingLimitReached", "BillingLimitReached"
        BILLING_LIMIT_TOO_LOW = "BillingLimitTooLow", "BillingLimitTooLow"

    class PipelineVersion(models.TextChoices):
        V1 = "v1-dlt-sync", "v1-dlt-sync"
        V2 = "v2-non-dlt", "v2-non-dlt"
        V3 = "v3-split", "v3-split"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    pipeline = models.ForeignKey("data_warehouse.ExternalDataSource", related_name="jobs", on_delete=models.CASCADE)
    schema = models.ForeignKey("data_warehouse.ExternalDataSchema", on_delete=models.CASCADE, null=True, blank=True)
    status = models.CharField(max_length=400)
    rows_synced = models.BigIntegerField(null=True, blank=True)
    latest_error = models.TextField(null=True, help_text="The latest error that occurred during this run.")

    workflow_id = models.CharField(max_length=400, null=True, blank=True)
    workflow_run_id = models.CharField(max_length=400, null=True, blank=True)

    pipeline_version = models.CharField(max_length=400, choices=PipelineVersion.choices, null=True, blank=True)
    billable = models.BooleanField(default=True, null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    storage_delta_mib = models.FloatField(null=True, blank=True, default=0)

    # ET+L separation tracking (only populated when using ET+L separation path)
    et_workflow_id = models.CharField(max_length=400, null=True, blank=True)
    l_workflow_id = models.CharField(max_length=400, null=True, blank=True)
    temp_s3_prefix = models.CharField(max_length=500, null=True, blank=True)
    manifest_path = models.CharField(max_length=500, null=True, blank=True)
    et_started_at = models.DateTimeField(null=True, blank=True)
    et_finished_at = models.DateTimeField(null=True, blank=True)
    l_started_at = models.DateTimeField(null=True, blank=True)
    l_finished_at = models.DateTimeField(null=True, blank=True)
    et_rows_extracted = models.BigIntegerField(null=True, blank=True)
    l_rows_loaded = models.BigIntegerField(null=True, blank=True)

    __repr__ = sane_repr("id")

    class Meta:
        db_table = "posthog_externaldatajob"

    def folder_path(self) -> str:
        if self.schema:
            return self.schema.folder_path()
        else:
            raise ValueError("Job does not have a schema")

    def url_pattern_by_schema(self, schema: str) -> str:
        if settings.USE_LOCAL_SETUP:
            return (
                f"http://{settings.AIRBYTE_BUCKET_DOMAIN}/{settings.BUCKET_PATH}/{self.folder_path()}/{schema.lower()}/"
            )

        return f"https://{settings.AIRBYTE_BUCKET_DOMAIN}/{settings.BUCKET_PATH}/{self.folder_path()}/{schema.lower()}/"


class ExternalDataJobBatch(CreatedMetaFields, UUIDTModel):
    """
    Tracks individual batches/parquet files created during ET+L separation.
    Only populated when using ET+L separation path.
    """

    job = models.ForeignKey(ExternalDataJob, on_delete=models.CASCADE, related_name="batches")
    batch_number = models.IntegerField()
    parquet_path = models.CharField(max_length=500)
    row_count = models.BigIntegerField(null=True, blank=True)
    loaded_at = models.DateTimeField(null=True, blank=True)

    __repr__ = sane_repr("id", "batch_number")

    class Meta:
        db_table = "posthog_externaldatajobbatch"
        ordering = ["batch_number"]
        constraints = [
            models.UniqueConstraint(fields=["job", "batch_number"], name="unique_job_batch_number"),
        ]


@database_sync_to_async
def get_external_data_job(job_id: UUID) -> ExternalDataJob:
    from products.data_warehouse.backend.models import ExternalDataSchema

    return ExternalDataJob.objects.prefetch_related(
        "pipeline", Prefetch("schema", queryset=ExternalDataSchema.objects.prefetch_related("source"))
    ).get(pk=job_id)


@database_sync_to_async
def get_latest_run_if_exists(
    team_id: int, pipeline_id: UUID, expected_status: ExternalDataJob.Status = ExternalDataJob.Status.COMPLETED
) -> ExternalDataJob | None:
    job = (
        ExternalDataJob.objects.filter(team_id=team_id, pipeline_id=pipeline_id, status=expected_status)
        .prefetch_related("pipeline")
        .order_by("-created_at")
        .first()
    )

    return job
