import time
from typing import Any, get_args

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
from posthog.temporal.data_imports.pipelines.pipeline.typings import PartitionFormat
from posthog.temporal.utils import ExternalDataWorkflowInputs

from products.data_warehouse.backend.data_load.service import (
    pause_external_data_schedule,
    unpause_external_data_schedule,
)
from products.data_warehouse.backend.models.external_data_job import ExternalDataJob
from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema

# Source of truth lives in pipeline.typings.PartitionFormat. Re-deriving here keeps
# the dropdown in sync if a new format is ever added.
PARTITION_FORMAT_CHOICES: tuple[str, ...] = get_args(PartitionFormat)


@async_to_sync
async def _start_external_data_workflow(client: Client, workflow_id: str, inputs: ExternalDataWorkflowInputs) -> None:
    await client.start_workflow(
        "external-data-job",
        inputs,
        id=workflow_id,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
    )


@async_to_sync
async def _is_schedule_paused(client: Client, schedule_id: str) -> bool:
    """Best-effort check whether the per-schema Temporal schedule is currently paused.

    Returns False if the schedule does not exist or describe fails — the caller
    treats that as 'no schedule to pause' and proceeds without pausing.
    """
    handle = client.get_schedule_handle(schedule_id)
    try:
        desc = await handle.describe()
    except Exception:
        return False
    return bool(desc.schedule.state.paused)


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
            path(
                "<uuid:schema_id>/pause-schedule/",
                self.admin_site.admin_view(self.pause_schedule_view),
                name="external_data_schema_pause_schedule",
            ),
            path(
                "<uuid:schema_id>/unpause-schedule/",
                self.admin_site.admin_view(self.unpause_schedule_view),
                name="external_data_schema_unpause_schedule",
            ),
        ]
        return custom_urls + urls

    def repartition_view(self, request, schema_id):
        # Update the partition knob that matches the schema's partition_mode AND
        # immediately trigger a non-billable resync with reset_pipeline=True.
        # Repartition without a reset risks mixing old/new partition layouts in
        # the same Delta table, which corrupts the data with no easy way to
        # recover — so the two actions are bundled.
        #
        # We require an explicit partition_mode on the schema. The pipeline picks
        # the mode the first time a table is partitioned (based on column shape);
        # forcing a mode here would cause the next sync to crash if the table
        # doesn't carry a column compatible with that mode.
        if request.method != "POST":
            return redirect(_change_url(schema_id))

        try:
            schema = ExternalDataSchema.objects.select_related("source").get(id=schema_id)
        except ExternalDataSchema.DoesNotExist:
            messages.error(request, f"Schema {schema_id} not found.")
            return redirect(reverse("admin:data_warehouse_externaldataschema_changelist"))

        if schema.partition_mode is None:
            messages.error(
                request,
                "Schema has no partition_mode set. Run a sync first so the pipeline can pick "
                "the appropriate mode for this table, then come back to repartition.",
            )
            return redirect(_change_url(schema_id))

        # Validate input by mode and stage the value to write. We defer the actual
        # save so we can do one DB write that updates the partition knob AND sets
        # reset_pipeline AND records whether to auto-unpause the schedule.
        partition_field: str
        partition_value: Any
        previous_value: Any
        if schema.partition_mode == "datetime":
            new_format = request.POST.get("partition_format")
            if new_format not in PARTITION_FORMAT_CHOICES:
                messages.error(request, f"Invalid partition_format: {new_format!r}.")
                return redirect(_change_url(schema_id))
            partition_field = "partition_format"
            partition_value = new_format
            previous_value = schema.partition_format
        elif schema.partition_mode == "numerical":
            raw = request.POST.get("partition_size", "").strip()
            try:
                new_size = int(raw)
            except ValueError:
                messages.error(request, f"partition_size must be an integer; got {raw!r}.")
                return redirect(_change_url(schema_id))
            if new_size < 1:
                messages.error(request, f"partition_size must be >= 1; got {new_size}.")
                return redirect(_change_url(schema_id))
            partition_field = "partition_size"
            partition_value = new_size
            previous_value = schema.partition_size
        elif schema.partition_mode == "md5":
            raw = request.POST.get("partition_count", "").strip()
            try:
                new_count = int(raw)
            except ValueError:
                messages.error(request, f"partition_count must be an integer; got {raw!r}.")
                return redirect(_change_url(schema_id))
            if new_count < 1:
                messages.error(request, f"partition_count must be >= 1; got {new_count}.")
                return redirect(_change_url(schema_id))
            partition_field = "partition_count"
            partition_value = new_count
            previous_value = schema.partition_count
        else:
            messages.error(
                request,
                f"Unsupported partition_mode {schema.partition_mode!r}; admin repartition only "
                f"handles datetime / numerical / md5.",
            )
            return redirect(_change_url(schema_id))

        change_label = f"{partition_field}: {previous_value!r} → {partition_value!r}"

        # Pause the schedule before triggering an admin resync so the scheduled
        # workflow doesn't race with the admin one (Temporal's "OnlyOne" overlap
        # policy is per-schedule, not across schedule + ad-hoc workflow). If the
        # schedule was already paused (operator paused it manually beforehand),
        # skip auto-unpause so we don't undo their action.
        try:
            client = sync_connect()
        except Exception as e:
            messages.error(request, f"Failed to connect to Temporal: {e}.")
            return redirect(_change_url(schema_id))

        was_paused = _is_schedule_paused(client, str(schema.id))
        admin_paused_now = False
        if not was_paused:
            try:
                pause_external_data_schedule(str(schema.id))
                admin_paused_now = True
            except Exception as e:
                messages.error(request, f"Failed to pause schedule before resync: {e}.")
                return redirect(_change_url(schema_id))

        # Single save: stage the partition update, reset_pipeline, and the auto-
        # unpause marker (read by `update_external_data_job_model` at workflow end)
        # in one round-trip. reset_pipeline goes on sync_type_config rather than the
        # workflow input so the pipeline can pop it after the first reset; passing
        # it on inputs makes every activity retry re-read True and wipe Delta +
        # cursor, restarting from row 0.
        schema.sync_type_config[partition_field] = partition_value
        schema.sync_type_config["reset_pipeline"] = True
        if admin_paused_now:
            schema.sync_type_config["admin_unpause_schedule_after_run"] = True
        schema.save(update_fields=["sync_type_config"])

        inputs = ExternalDataWorkflowInputs(
            team_id=schema.team_id,
            external_data_source_id=schema.source.id,
            external_data_schema_id=schema.id,
            billable=False,
            reset_pipeline=None,
        )
        workflow_id = f"{schema.id}-admin-repartition-{int(time.time())}"
        try:
            _start_external_data_workflow(client, workflow_id, inputs)
        except Exception as e:
            messages.error(
                request,
                f"Saved {change_label}, but failed to trigger reset resync: {e}. "
                f"Trigger one manually before the next scheduled sync.",
            )
            return redirect(_change_url(schema_id))

        pause_note = (
            " Schedule paused for the duration of this run; will auto-unpause on a successful completion."
            if admin_paused_now
            else " Schedule was already paused; leaving it paused."
        )
        messages.success(
            request,
            f"{change_label}. Triggered non-billable reset resync (workflow_id={workflow_id}).{pause_note}",
        )
        return redirect(_change_url(schema_id))

    def trigger_sync_view(self, request, schema_id):
        # Ad-hoc external-data-job workflow execution. Bypasses the schedule because
        # the schedule's stored input cannot override `billable` per-trigger.
        # WARNING: this can race with the schedule's own runs. Pause the schedule
        # first using the buttons below if there's any chance of overlap.
        if request.method != "POST":
            return redirect(_change_url(schema_id))

        try:
            schema = ExternalDataSchema.objects.select_related("source").get(id=schema_id)
        except ExternalDataSchema.DoesNotExist:
            messages.error(request, f"Schema {schema_id} not found.")
            return redirect(reverse("admin:data_warehouse_externaldataschema_changelist"))

        reset_pipeline = request.POST.get("reset_pipeline") == "on"
        billable = request.POST.get("billable") == "on"

        # See note in repartition_view: reset_pipeline goes on sync_type_config so the
        # pipeline can clear it after the first reset. Passing it on the workflow
        # input would make every activity retry re-reset, wiping progress.
        if reset_pipeline:
            schema.sync_type_config["reset_pipeline"] = True
            schema.save(update_fields=["sync_type_config"])

        inputs = ExternalDataWorkflowInputs(
            team_id=schema.team_id,
            external_data_source_id=schema.source.id,
            external_data_schema_id=schema.id,
            billable=billable,
            reset_pipeline=None,
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

    def pause_schedule_view(self, request, schema_id):
        if request.method != "POST":
            return redirect(_change_url(schema_id))
        try:
            pause_external_data_schedule(str(schema_id))
            messages.success(request, "Schedule paused. Remember to unpause when admin work is done.")
        except Exception as e:
            messages.error(request, f"Failed to pause schedule: {e}")
        return redirect(_change_url(schema_id))

    def unpause_schedule_view(self, request, schema_id):
        if request.method != "POST":
            return redirect(_change_url(schema_id))
        try:
            unpause_external_data_schedule(str(schema_id))
            messages.success(request, "Schedule unpaused.")
        except Exception as e:
            messages.error(request, f"Failed to unpause schedule: {e}")
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
            extra_context["repartition_url"] = reverse("admin:external_data_schema_repartition", args=[obj.id])
            extra_context["trigger_sync_url"] = reverse("admin:external_data_schema_trigger_sync", args=[obj.id])
            extra_context["pause_schedule_url"] = reverse("admin:external_data_schema_pause_schedule", args=[obj.id])
            extra_context["unpause_schedule_url"] = reverse(
                "admin:external_data_schema_unpause_schedule", args=[obj.id]
            )
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
