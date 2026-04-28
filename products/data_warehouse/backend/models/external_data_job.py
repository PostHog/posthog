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
        V3 = "v3-kafka-s3", "v3-kafka-s3"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    pipeline = models.ForeignKey("data_warehouse.ExternalDataSource", related_name="jobs", on_delete=models.CASCADE)
    schema = models.ForeignKey("data_warehouse.ExternalDataSchema", on_delete=models.CASCADE, null=True, blank=True)
    status = models.CharField(max_length=400)
    rows_synced = models.BigIntegerField(null=True, blank=True)
    latest_error = models.TextField(null=True, help_text="The latest error that occurred during this run.")

    workflow_id = models.CharField(max_length=400, null=True, blank=True)
    workflow_run_id = models.CharField(max_length=400, null=True, blank=True)

    pipeline_version = models.CharField(max_length=400, choices=PipelineVersion, null=True, blank=True)
    billable = models.BooleanField(default=True, null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    storage_delta_mib = models.FloatField(null=True, blank=True, default=0)
    schema_snapshot = models.JSONField(
        null=True,
        blank=True,
        help_text="Snapshot of the ExternalDataSchema at the time this job was created.",
    )

    __repr__ = sane_repr("id")

    class Meta:
        db_table = "posthog_externaldatajob"

    def folder_path(self) -> str:
        if not self.schema:
            raise ValueError("Job does not have a schema")
        # `pipeline` and `schema.source` point at the same ExternalDataSource
        # row. Reach `source_type` through the job's `pipeline` FK rather
        # than the schema's `source` FK so we don't trigger a lazy DB lookup
        # if the schema instance was rehydrated by `refresh_from_db()` during
        # the sync — that lookup happens during exception unwinding and can
        # exhaust the worker's pgbouncer pool.
        return self.schema.folder_path(source_type=self._cached_source_type())

    def _cached_source_type(self) -> str | None:
        """Return source_type from the in-memory FK cache, or None.

        Falls through to None when neither `pipeline` nor `schema.source`
        is loaded — `ExternalDataSchema.folder_path` then handles the lazy
        load itself for non-Temporal callers (admin, tests) where a fresh
        DB connection is acceptable.
        """
        cache = getattr(self._state, "fields_cache", {})
        pipeline = cache.get("pipeline")
        if pipeline is not None:
            return pipeline.source_type
        if self.schema is not None:
            schema_cache = getattr(self.schema._state, "fields_cache", {})
            source = schema_cache.get("source")
            if source is not None:
                return source.source_type
        return None

    def url_pattern_by_schema(self, schema: str) -> str:
        if settings.USE_LOCAL_SETUP:
            return f"http://{settings.DATAWAREHOUSE_BUCKET_DOMAIN}/{settings.BUCKET_PATH}/{self.folder_path()}/{schema.lower()}/"

        return f"https://{settings.DATAWAREHOUSE_BUCKET_DOMAIN}/{settings.BUCKET_PATH}/{self.folder_path()}/{schema.lower()}/"


@database_sync_to_async
def get_external_data_job(job_id: UUID) -> ExternalDataJob:
    from products.data_warehouse.backend.models import ExternalDataSchema

    return ExternalDataJob.objects.prefetch_related(
        "pipeline", Prefetch("schema", queryset=ExternalDataSchema.objects.prefetch_related("source"))
    ).get(pk=job_id)


@database_sync_to_async
def get_latest_run_if_exists(team_id: int, pipeline_id: UUID) -> ExternalDataJob | None:
    job = (
        ExternalDataJob.objects.filter(
            team_id=team_id, pipeline_id=pipeline_id, status=ExternalDataJob.Status.COMPLETED
        )
        .prefetch_related("pipeline")
        .order_by("-created_at")
        .first()
    )

    return job
