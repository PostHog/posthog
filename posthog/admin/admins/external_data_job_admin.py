from django.conf import settings
from django.contrib import admin, messages
from django.db import transaction
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html

from products.data_warehouse.backend.models.external_data_job import ExternalDataJob


def _change_url(job_id) -> str:
    return reverse("admin:data_warehouse_externaldatajob_change", args=[job_id])


@admin.register(ExternalDataJob)
class ExternalDataJobAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "status",
        "schema_link",
        "source_type",
        "team_link",
        "rows_synced",
        "billable",
        "created_at",
        "finished_at",
    )
    list_display_links = ("id",)
    list_select_related = ("team", "team__organization", "schema", "pipeline")
    list_filter = ("status", "billable", "pipeline_version")
    search_fields = (
        "id",
        "workflow_id",
        "workflow_run_id",
        "schema__name",
        "team__name",
        "team__organization__name",
    )
    autocomplete_fields = ("team", "schema")
    raw_id_fields = ("pipeline",)
    readonly_fields = (
        "created_at",
        "updated_at",
        "created_by",
        "rows_synced",
        "workflow_id",
        "workflow_run_id",
        "pipeline_version",
        "storage_delta_mib",
        "schema_snapshot",
        "temporal_workflow_link",
        "logs_link",
    )
    ordering = ("-created_at",)

    change_form_template = "admin/data_warehouse/externaldatajob/change_form.html"

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "team",
                    "pipeline",
                    "schema",
                    "status",
                    "rows_synced",
                    "billable",
                    "finished_at",
                    "latest_error",
                )
            },
        ),
        (
            "Temporal",
            {
                "fields": (
                    "workflow_id",
                    "workflow_run_id",
                    "temporal_workflow_link",
                    "logs_link",
                )
            },
        ),
        (
            "Pipeline",
            {
                "fields": (
                    "pipeline_version",
                    "storage_delta_mib",
                    "schema_snapshot",
                )
            },
        ),
        (
            "Meta",
            {"fields": ("created_at", "updated_at", "created_by")},
        ),
    )

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<uuid:job_id>/mark-failed/",
                self.admin_site.admin_view(self.mark_failed_view),
                name="external_data_job_mark_failed",
            ),
        ]
        return custom_urls + urls

    def mark_failed_view(self, request, job_id):
        # Convenience for orphaned Running jobs: workflow was terminated in Temporal
        # without the cleanup activity running, so the DB row is stuck on Running
        # forever. This flips status to Failed and stamps finished_at so downstream
        # status surfaces match reality.
        if request.method != "POST":
            return redirect(_change_url(job_id))

        # Wrap the read-check-write in a transaction with select_for_update so two
        # concurrent staff POSTs can't both observe Running and double-write
        # latest_error / finished_at.
        with transaction.atomic():
            try:
                job = ExternalDataJob.objects.select_for_update().get(id=job_id)
            except ExternalDataJob.DoesNotExist:
                messages.error(request, f"Job {job_id} not found.")
                return redirect(reverse("admin:data_warehouse_externaldatajob_changelist"))

            if job.status != ExternalDataJob.Status.RUNNING:
                messages.warning(request, f"Job is not Running (status={job.status}). No change.")
                return redirect(_change_url(job_id))

            reason = (request.POST.get("reason") or "").strip()
            job.status = ExternalDataJob.Status.FAILED
            job.latest_error = (
                reason or "Marked Failed via admin (Temporal workflow terminated without cleanup activity)"
            )
            if job.finished_at is None:
                job.finished_at = timezone.now()
            job.save(update_fields=["status", "latest_error", "finished_at", "updated_at"])

        messages.success(request, f"Marked job {job.id} as Failed.")
        return redirect(_change_url(job_id))

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        obj = self.get_object(request, object_id)
        if obj:
            extra_context["site_url"] = settings.SITE_URL
            extra_context["temporal_ui_host"] = settings.TEMPORAL_UI_HOST
            extra_context["temporal_namespace"] = settings.TEMPORAL_NAMESPACE
            extra_context["team_id"] = obj.team_id
            extra_context["is_running"] = obj.status == ExternalDataJob.Status.RUNNING
            extra_context["mark_failed_url"] = reverse("admin:external_data_job_mark_failed", args=[obj.id])
            if obj.schema_id:
                extra_context["schema_admin_url"] = reverse(
                    "admin:data_warehouse_externaldataschema_change", args=[obj.schema_id]
                )
        return super().change_view(request, object_id, form_url, extra_context=extra_context)

    @admin.display(description="Team")
    def team_link(self, job: ExternalDataJob):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[job.team.pk]),
            job.team.name,
        )

    @admin.display(description="Schema")
    def schema_link(self, job: ExternalDataJob):
        if job.schema_id is None:
            return "—"
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:data_warehouse_externaldataschema_change", args=[job.schema_id]),
            job.schema.name if job.schema else job.schema_id,
        )

    @admin.display(description="Source type")
    def source_type(self, job: ExternalDataJob):
        return job.pipeline.source_type

    @admin.display(description="Temporal workflow")
    def temporal_workflow_link(self, job: ExternalDataJob):
        if not job.workflow_id or not job.workflow_run_id:
            return "—"
        url = (
            f"{settings.TEMPORAL_UI_HOST}/namespaces/{settings.TEMPORAL_NAMESPACE}"
            f"/workflows/{job.workflow_id}/{job.workflow_run_id}"
        )
        return format_html('<a href="{}" target="_blank">View workflow</a>', url)

    @admin.display(description="Logs")
    def logs_link(self, job: ExternalDataJob):
        if not job.workflow_id:
            return "—"
        url = f"{settings.SITE_URL}/project/{job.team_id}/logs?searchTerm={job.workflow_id}"
        return format_html('<a href="{}" target="_blank">View logs</a>', url)
