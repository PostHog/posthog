from django.db import models
from django.db.models import Prefetch
from django.conf import settings
from posthog.models.team import Team
from posthog.models.utils import CreatedMetaFields, UUIDModel, UpdatedMetaFields, sane_repr
from posthog.settings import TEST
from posthog.warehouse.s3 import get_s3_client
from uuid import UUID
from posthog.warehouse.util import database_sync_to_async


class ExternalDataJob(CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    class Status(models.TextChoices):
        RUNNING = "Running", "Running"
        FAILED = "Failed", "Failed"
        COMPLETED = "Completed", "Completed"
        CANCELLED = "Cancelled", "Cancelled"

    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    pipeline = models.ForeignKey("posthog.ExternalDataSource", related_name="jobs", on_delete=models.CASCADE)
    schema = models.ForeignKey("posthog.ExternalDataSchema", on_delete=models.CASCADE, null=True, blank=True)
    status = models.CharField(max_length=400)
    rows_synced = models.BigIntegerField(null=True, blank=True)
    latest_error = models.TextField(null=True, help_text="The latest error that occurred during this run.")

    workflow_id = models.CharField(max_length=400, null=True, blank=True)
    workflow_run_id = models.CharField(max_length=400, null=True, blank=True)

    __repr__ = sane_repr("id")

    def folder_path(self) -> str:
        return f"team_{self.team_id}_{self.pipeline.source_type}_{str(self.schema_id)}".lower().replace("-", "_")

    def deprecated_folder_path(self) -> str:
        return f"team_{self.team_id}_{self.pipeline.source_type}_{str(self.pk)}".lower().replace("-", "_")

    def url_pattern_by_schema(self, schema: str) -> str:
        if TEST:
            return f"http://{settings.AIRBYTE_BUCKET_DOMAIN}/{settings.BUCKET}/{self.folder_path()}/{schema.lower()}/"

        return f"https://{settings.AIRBYTE_BUCKET_DOMAIN}/dlt/{self.folder_path()}/{schema.lower()}/"

    def delete_deprecated_data_in_bucket(self) -> None:
        s3 = get_s3_client()

        if s3.exists(f"{settings.BUCKET_URL}/{self.deprecated_folder_path()}"):
            s3.delete(f"{settings.BUCKET_URL}/{self.deprecated_folder_path()}", recursive=True)

        return


@database_sync_to_async
def get_external_data_job(job_id: UUID) -> ExternalDataJob:
    from posthog.warehouse.models import ExternalDataSchema

    return ExternalDataJob.objects.prefetch_related(
        "pipeline", Prefetch("schema", queryset=ExternalDataSchema.objects.prefetch_related("source"))
    ).get(pk=job_id)


@database_sync_to_async
def aget_external_data_jobs_by_schema_id(schema_id: UUID) -> list[ExternalDataJob]:
    from posthog.warehouse.models import ExternalDataSchema

    return list(
        ExternalDataJob.objects.prefetch_related(
            "pipeline", Prefetch("schema", queryset=ExternalDataSchema.objects.prefetch_related("source"))
        )
        .filter(schema_id=schema_id)
        .order_by("-created_at")
        .all()
    )


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
