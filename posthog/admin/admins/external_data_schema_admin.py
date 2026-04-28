import time

from django.conf import settings
from django.contrib import admin, messages
from django.core.paginator import Paginator
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils.html import format_html

from asgiref.sync import async_to_sync
from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy

from posthog.temporal.common.client import sync_connect
from posthog.temporal.utils import ExternalDataWorkflowInputs

from products.data_warehouse.backend.models.external_data_job import ExternalDataJob
from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema

PARTITION_FORMAT_CHOICES = ("month", "week", "day", "hour")
PARTITION_SIZE_MIN = 1
PARTITION_SIZE_MAX = 1_000_000_000
PARTITION_COUNT_MIN = 1
PARTITION_COUNT_MAX = 100_000


@async_to_sync
async def _start_external_data_workflow(client: Client, workflow_id: str, inputs: ExternalDataWorkflowInputs) -> None:
    await client.start_workflow(
        "external-data-job",
        inputs,
        id=workflow_id,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
    )


def _change_url(schema_id) -> str:
    return reverse("admin:data_warehouse_externaldataschema_change", args=[schema_id])


class ExternalDataSchemaAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "status",
        "should_sync",
        "sync_type",
        "source_type",
        "team_link",
        "last_synced_at",
        "created_at",
    )
    list_display_links = ("id", "name")
    list_select_related = ("team", "team__organization", "source")
    list_filter = ("status", "should_sync", "sync_type")
    search_fields = ("id", "name", "team__name", "team__organization__name")
    autocomplete_fields = ("team",)
    raw_id_fields = ("table", "source")
    readonly_fields = ("table", "source", "created_by")
    ordering = ("-created_at",)

    change_form_template = "admin/data_warehouse/externaldataschema/change_form.html"

    JOBS_PER_PAGE = 20

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<uuid:schema_id>/repartition/",
                self.admin_site.admin_view(self.repartition_view),
                name="external_data_schema_repartition",
            ),
            path(
                "<uuid:schema_id>/trigger-sync/",
                self.admin_site.admin_view(self.trigger_sync_view),
                name="external_data_schema_trigger_sync",
            ),
        ]
        return custom_urls + urls

    def repartition_view(self, request, schema_id):
        # Update the partition knob that matches the schema's partition_mode:
        #   datetime  → partition_format ∈ {month, week, day, hour}
        #   numerical → partition_size (rows per integer-id bucket)
        #   md5       → partition_count (number of hash buckets)
        # Takes effect on the next run; pair with a reset resync to rebuild Delta
        # files at the new granularity.
        if request.method != "POST":
            return redirect(_change_url(schema_id))

        try:
            schema = ExternalDataSchema.objects.get(id=schema_id)
        except ExternalDataSchema.DoesNotExist:
            messages.error(request, f"Schema {schema_id} not found.")
            return redirect(reverse("admin:data_warehouse_externaldataschema_changelist"))

        # Default unset partition_mode to "datetime" so legacy schemas that pre-date
        # the explicit partition_mode column still get the format dropdown they expect.
        effective_mode = schema.partition_mode or "datetime"

        if effective_mode == "datetime":
            new_format = request.POST.get("partition_format")
            if new_format not in PARTITION_FORMAT_CHOICES:
                messages.error(request, f"Invalid partition_format: {new_format!r}.")
                return redirect(_change_url(schema_id))
            previous_format = schema.partition_format
            schema.update_partition_setting("partition_format", new_format)
            messages.success(
                request,
                f"partition_format updated: {previous_format!r} → {new_format!r}. "
                f"Trigger a resync (with reset) to rebuild Delta with the new partitioning.",
            )
            return redirect(_change_url(schema_id))

        if effective_mode == "numerical":
            raw = request.POST.get("partition_size", "").strip()
            try:
                new_size = int(raw)
            except ValueError:
                messages.error(request, f"partition_size must be an integer; got {raw!r}.")
                return redirect(_change_url(schema_id))
            if not (PARTITION_SIZE_MIN <= new_size <= PARTITION_SIZE_MAX):
                messages.error(
                    request,
                    f"partition_size out of range [{PARTITION_SIZE_MIN}, {PARTITION_SIZE_MAX}]: {new_size}.",
                )
                return redirect(_change_url(schema_id))
            previous_size = schema.partition_size
            schema.update_partition_setting("partition_size", new_size)
            messages.success(
                request,
                f"partition_size updated: {previous_size!r} → {new_size}. "
                f"Trigger a resync (with reset) to rebuild Delta with the new bucket size.",
            )
            return redirect(_change_url(schema_id))

        # md5 — exhaustive over PartitionMode after the datetime fallback above.
        raw = request.POST.get("partition_count", "").strip()
        try:
            new_count = int(raw)
        except ValueError:
            messages.error(request, f"partition_count must be an integer; got {raw!r}.")
            return redirect(_change_url(schema_id))
        if not (PARTITION_COUNT_MIN <= new_count <= PARTITION_COUNT_MAX):
            messages.error(
                request,
                f"partition_count out of range [{PARTITION_COUNT_MIN}, {PARTITION_COUNT_MAX}]: {new_count}.",
            )
            return redirect(_change_url(schema_id))
        previous_count = schema.partition_count
        schema.update_partition_setting("partition_count", new_count)
        messages.success(
            request,
            f"partition_count updated: {previous_count!r} → {new_count}. "
            f"Trigger a resync (with reset) to rebuild Delta with the new bucket count.",
        )
        return redirect(_change_url(schema_id))

    def trigger_sync_view(self, request, schema_id):
        # Ad-hoc external-data-job workflow execution. We start a fresh workflow rather
        # than triggering the schedule because the schedule's stored input cannot
        # override `billable` per-trigger.
        if request.method != "POST":
            return redirect(_change_url(schema_id))

        try:
            schema = ExternalDataSchema.objects.select_related("source").get(id=schema_id)
        except ExternalDataSchema.DoesNotExist:
            messages.error(request, f"Schema {schema_id} not found.")
            return redirect(reverse("admin:data_warehouse_externaldataschema_changelist"))

        reset_pipeline = request.POST.get("reset_pipeline") == "on"
        billable = request.POST.get("billable") == "on"

        inputs = ExternalDataWorkflowInputs(
            team_id=schema.team_id,
            external_data_source_id=schema.source.id,
            external_data_schema_id=schema.id,
            billable=billable,
            reset_pipeline=reset_pipeline or None,
        )
        workflow_id = f"{schema.id}-admin-resync-{int(time.time())}"
        try:
            client = sync_connect()
            _start_external_data_workflow(client, workflow_id, inputs)
        except Exception as e:
            messages.error(request, f"Failed to trigger sync: {e}")
            return redirect(_change_url(schema_id))

        billable_label = "billable" if billable else "non-billable"
        action_label = "resync (with reset)" if reset_pipeline else "sync"
        messages.success(
            request,
            f"Triggered {billable_label} {action_label} for {schema.name} (workflow_id={workflow_id}).",
        )
        return redirect(_change_url(schema_id))

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        obj = self.get_object(request, object_id)
        if obj:
            jobs_qs = ExternalDataJob.objects.filter(schema=obj).order_by("-created_at")
            paginator = Paginator(jobs_qs, self.JOBS_PER_PAGE)
            page_number = request.GET.get("page", 1)
            page_obj = paginator.get_page(page_number)

            extra_context["page_obj"] = page_obj
            extra_context["temporal_ui_host"] = settings.TEMPORAL_UI_HOST
            extra_context["temporal_namespace"] = settings.TEMPORAL_NAMESPACE
            extra_context["site_url"] = settings.SITE_URL
            extra_context["team_id"] = obj.team_id

            extra_context["partition_format_choices"] = PARTITION_FORMAT_CHOICES
            extra_context["current_partition_format"] = obj.partition_format
            extra_context["current_partition_mode"] = obj.partition_mode
            extra_context["current_partition_keys"] = obj.partitioning_keys
            extra_context["current_partition_size"] = obj.partition_size
            extra_context["current_partition_count"] = obj.partition_count
            extra_context["partitioning_enabled"] = obj.partitioning_enabled
            # `effective_mode` mirrors repartition_view: unset modes fall back to datetime
            # so legacy schemas still get the format dropdown.
            extra_context["effective_partition_mode"] = obj.partition_mode or "datetime"
            extra_context["repartition_url"] = reverse("admin:external_data_schema_repartition", args=[obj.id])
            extra_context["trigger_sync_url"] = reverse("admin:external_data_schema_trigger_sync", args=[obj.id])
        return super().change_view(request, object_id, form_url, extra_context=extra_context)

    @admin.display(description="Team")
    def team_link(self, schema: ExternalDataSchema):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[schema.team.pk]),
            schema.team.name,
        )

    @admin.display(description="Source type")
    def source_type(self, schema: ExternalDataSchema):
        return schema.source.source_type
