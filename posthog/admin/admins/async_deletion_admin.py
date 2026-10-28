from datetime import datetime

from django.contrib import admin
from django.db.models import QuerySet, Subquery
from django.http import HttpRequest
from django.utils.html import format_html

from posthog.admin.admins.data_deletion_request_admin import dagster_run_url
from posthog.models import AsyncDeletion
from posthog.models.async_deletion import DeletionRunJob, DeletionRunLog, DeletionRunStatus, DeletionType

# deletes_job loads these types. The others are deleted by other jobs and never show up in its log.
DELETES_JOB_TYPES = (DeletionType.Person, DeletionType.Team, DeletionType.Event)


def deletion_status(deletion: AsyncDeletion, watermark: datetime | None) -> str:
    """What support can tell a customer about one deletion request, based on the last deletes_job run."""
    if deletion.delete_verified_at:
        return f"Deleted on {deletion.delete_verified_at:%Y-%m-%d %H:%M} UTC"
    if deletion.deletion_type not in DELETES_JOB_TYPES:
        return "Pending. Not handled by deletes_job."
    if deletion.deletion_type == DeletionType.Person and (watermark is None or deletion.created_at > watermark):
        reached = f"The last run reached {watermark:%Y-%m-%d %H:%M} UTC." if watermark else "No run recorded yet."
        return f"Waiting for the person overrides squash. {reached}"
    return "Queued for the next deletes_job run"


@admin.register(AsyncDeletion)
class AsyncDeletionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "deletion_type",
        "group_type_index",
        "team_id",
        "key",
        "created_by",
        "created_at",
        "delete_verified_at",
        "status",
    )
    list_filter = ("deletion_type", "delete_verified_at")
    search_fields = ("key",)

    def get_queryset(self, request: HttpRequest) -> QuerySet[AsyncDeletion]:
        # A subquery keeps the watermark lookup to the one changelist query instead of one per row.
        latest_watermark = (
            DeletionRunLog.objects.filter(
                job=DeletionRunJob.DELETES,
                status=DeletionRunStatus.SUCCEEDED,
                limited_to_team_id__isnull=True,
                # A run that skipped the watermark step has no watermark and must not hide the last known one.
                watermark__isnull=False,
            )
            .order_by("-started_at")
            .values("watermark")[:1]
        )
        return super().get_queryset(request).annotate(latest_watermark=Subquery(latest_watermark))

    @admin.display(description="Status")
    def status(self, obj: AsyncDeletion) -> str:
        return deletion_status(obj, getattr(obj, "latest_watermark", None))

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


def _run_link(run_id: str) -> str:
    url = dagster_run_url(run_id)
    if url is None:
        return run_id
    return format_html('<a href="{}" target="_blank" rel="noopener">{}</a>', url, run_id)


@admin.register(DeletionRunLog)
class DeletionRunLogAdmin(admin.ModelAdmin):
    list_display = (
        "started_at",
        "job",
        "status",
        "finished_at",
        "squash_cutoff",
        "watermark",
        "skipped_person_deletions",
        "oldest_skipped_created_at",
        "dagster_run",
        "reexecution_of",
    )
    list_filter = ("job", "status")
    search_fields = ("dagster_run_id", "parent_run_id")
    ordering = ("-started_at",)
    readonly_fields = ("dagster_run", "reexecution_of")

    @admin.display(description="Dagster run")
    def dagster_run(self, obj: DeletionRunLog) -> str:
        return _run_link(obj.dagster_run_id)

    @admin.display(description="Re-execution of")
    def reexecution_of(self, obj: DeletionRunLog) -> str:
        return _run_link(obj.parent_run_id) if obj.parent_run_id else "-"

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
