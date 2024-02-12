from django.db import models
from django.conf import settings
from posthog.models.team import Team
from posthog.models.utils import CreatedMetaFields, UUIDModel, sane_repr
from posthog.warehouse.s3 import get_s3_client
from uuid import UUID
from posthog.warehouse.util import database_sync_to_async


class ExternalDataJob(CreatedMetaFields, UUIDModel):
    class Status(models.TextChoices):
        RUNNING = "Running", "Running"
        FAILED = "Failed", "Failed"
        COMPLETED = "Completed", "Completed"
        CANCELLED = "Cancelled", "Cancelled"

    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    pipeline: models.ForeignKey = models.ForeignKey("posthog.ExternalDataSource", on_delete=models.CASCADE)
    status: models.CharField = models.CharField(max_length=400)
    rows_synced: models.BigIntegerField = models.BigIntegerField(null=True, blank=True)
    latest_error: models.TextField = models.TextField(
        null=True, help_text="The latest error that occurred during this run."
    )

    workflow_id: models.CharField = models.CharField(max_length=400, null=True, blank=True)

    __repr__ = sane_repr("id")

    @property
    def folder_path(self) -> str:
        return f"team_{self.team_id}_{self.pipeline.source_type}_{str(self.pk)}".lower().replace("-", "_")

    def url_pattern_by_schema(self, schema: str) -> str:
        return f"https://{settings.AIRBYTE_BUCKET_DOMAIN}/dlt/{self.folder_path}/{schema.lower()}/*.parquet"

    def delete_data_in_bucket(self) -> None:
        s3 = get_s3_client()
        s3.delete(f"{settings.BUCKET_URL}/{self.folder_path}", recursive=True)


@database_sync_to_async
def get_external_data_job(job_id: UUID) -> ExternalDataJob:
    return ExternalDataJob.objects.prefetch_related("pipeline").get(pk=job_id)


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
