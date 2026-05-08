import time
import uuid
from dataclasses import asdict
from typing import Any, assert_never, get_args

from django.conf import settings
from django.contrib import admin, messages
from django.core.paginator import Paginator
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils.html import format_html

from asgiref.sync import async_to_sync
from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy

from posthog.models.activity_logging.activity_log import Detail, log_activity
from posthog.temporal.common.client import sync_connect
from posthog.temporal.data_imports.compact_delta_table_job import CompactDeltaTableWorkflowInputs
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
    readonly_fields = ("table", "source", "created_by", "delta_fragmentation_stats")
    ordering = ("-created_at",)
    actions = ("trigger_compact_delta_table",)

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
            # Exhaustive over PartitionMode after the None check above; assert_never
            # makes mypy happy and crashes loudly if a new mode is added without
            # updating this view.
            assert_never(schema.partition_mode)

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
            # Best-effort rollback of the pause we just did. Without this, a failed
            # workflow start leaves the schedule paused forever (the flag is read
            # by the workflow at completion, and there's no workflow if start
            # failed) and the flag orphaned in sync_type_config.
            if admin_paused_now:
                try:
                    unpause_external_data_schedule(str(schema.id))
                    schema.sync_type_config.pop("admin_unpause_schedule_after_run", None)
                    schema.save(update_fields=["sync_type_config"])
                except Exception:
                    pass
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
        # the schedule's stored input cannot override `billable` per-trigger. To avoid
        # racing with the regular scheduled run, mirror repartition_view: pause the
        # schedule (if not already paused), record the auto-unpause marker, and let
        # `update_external_data_job_model` resume the schedule on COMPLETED.
        if request.method != "POST":
            return redirect(_change_url(schema_id))

        try:
            schema = ExternalDataSchema.objects.select_related("source").get(id=schema_id)
        except ExternalDataSchema.DoesNotExist:
            messages.error(request, f"Schema {schema_id} not found.")
            return redirect(reverse("admin:data_warehouse_externaldataschema_changelist"))

        # Both checkboxes default to off: an unchecked checkbox isn't sent in the
        # POST body, so .get() returns None, and `None == "on"` is False.
        reset_pipeline = request.POST.get("reset_pipeline") == "on"
        billable = request.POST.get("billable") == "on"

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
                messages.error(request, f"Failed to pause schedule before sync: {e}.")
                return redirect(_change_url(schema_id))

        # Single save: stage reset_pipeline (only when ticked) + the auto-unpause
        # marker. reset_pipeline goes on sync_type_config rather than the workflow
        # input — the pipeline pops it after the first reset; on the input it
        # would re-fire on every activity retry and wipe progress.
        sync_type_config_dirty = False
        if reset_pipeline:
            schema.sync_type_config["reset_pipeline"] = True
            sync_type_config_dirty = True
        if admin_paused_now:
            schema.sync_type_config["admin_unpause_schedule_after_run"] = True
            sync_type_config_dirty = True
        if sync_type_config_dirty:
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
            _start_external_data_workflow(client, workflow_id, inputs)
        except Exception as e:
            # Best-effort rollback of the pause we just did so the schedule doesn't
            # stay paused forever after a failed workflow start.
            if admin_paused_now:
                try:
                    unpause_external_data_schedule(str(schema.id))
                    schema.sync_type_config.pop("admin_unpause_schedule_after_run", None)
                    schema.save(update_fields=["sync_type_config"])
                except Exception:
                    pass
            messages.error(request, f"Failed to trigger sync: {e}")
            return redirect(_change_url(schema_id))

        billable_label = "billable" if billable else "non-billable"
        action_label = "resync (with reset)" if reset_pipeline else "sync"
        pause_note = (
            " Schedule paused for the duration of this run; will auto-unpause on a successful completion."
            if admin_paused_now
            else " Schedule was already paused; leaving it paused."
        )
        messages.success(
            request,
            f"Triggered {billable_label} {action_label} for {schema.name} (workflow_id={workflow_id}).{pause_note}",
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

    @admin.display(description="Delta fragmentation stats")
    def delta_fragmentation_stats(self, schema: ExternalDataSchema):
        """Compute total file count + per-partition average for the Delta target.

        Hits S3 to list files, so it's only rendered on the change-detail page
        (not the changelist) and tolerates failure — surfacing the error inline
        rather than blowing up the admin page.
        """
        try:
            stats = _get_delta_fragmentation_stats(schema)
        except Exception as e:
            return format_html("<em>error reading Delta files: {}</em>", str(e))

        if stats is None:
            return format_html("<em>no Delta target found</em>")

        # Pre-format the float; `format_html` wraps args as SafeString and
        # SafeString rejects numeric format codes like `{:.1f}` at format time.
        fpp = f"{stats['files_per_partition_avg']:.1f}"
        return format_html(
            "total_files={} | partition_count={} | files_per_partition_avg={} | total_size_bytes={}",
            stats["total_files"],
            stats["partition_count"],
            fpp,
            stats["total_size_bytes"],
        )

    @admin.action(description="Compact + vacuum Delta target")
    def trigger_compact_delta_table(self, request, queryset):
        """Queue one Temporal workflow per selected schema. Compaction runs
        asynchronously — the admin response returns immediately with a count
        of workflows started."""
        temporal = sync_connect()
        started = 0
        failed: list[tuple[str, str]] = []

        for schema in queryset:
            ok, err = queue_compact_for_schema(
                temporal=temporal,
                schema=schema,
                request=request,
                audit_item_id=schema.id,
                audit_scope="ExternalDataSchema",
                audit_name=schema.name,
            )
            if ok:
                started += 1
            else:
                failed.append((str(schema.id), err or "unknown error"))

        if started:
            self.message_user(
                request,
                f"Queued compaction workflow for {started} schema(s). Check Temporal UI for progress.",
                level=messages.INFO,
            )
        for schema_id, err in failed:
            self.message_user(request, f"Failed to queue compaction for {schema_id}: {err}", level=messages.ERROR)


def queue_compact_for_schema(
    *,
    temporal: Any,
    schema: ExternalDataSchema,
    request,
    audit_item_id,
    audit_scope: str,
    audit_name: str,
) -> tuple[bool, str | None]:
    """Queue one compaction workflow for a schema and write an audit log row.

    Shared helper so both ExternalDataSchemaAdmin and DataWarehouseTableAdmin
    can trigger the same workflow without duplicating the start + audit
    bookkeeping. The two admins exist as separate operator entry points
    (schema list vs table list) — they only differ in the audit `scope` /
    `item_id` they record, which is what makes the trigger surface
    discoverable from either admin section.

    Returns `(True, None)` on success, `(False, error_message)` on failure.
    Audit log is only written on success — we don't want half-trigger noise
    in the audit trail.
    """
    workflow_id = f"compact-delta-{schema.id}-{uuid.uuid4()}"
    inputs = CompactDeltaTableWorkflowInputs(
        team_id=schema.team_id,
        schema_id=str(schema.id),
    )
    try:
        _start_compact_workflow(temporal, asdict(inputs), workflow_id)
    except Exception as e:
        return False, str(e)

    log_activity(
        organization_id=schema.team.organization_id,
        team_id=schema.team_id,
        user=request.user,
        was_impersonated=False,
        item_id=audit_item_id,
        scope=audit_scope,
        activity="admin_compact_triggered",
        detail=Detail(
            name=audit_name,
            short_id=str(audit_item_id),
            type="admin_compact_delta",
        ),
    )
    return True, None


def _start_compact_workflow(temporal: Any, inputs_dict: dict, workflow_id: str) -> None:
    """Sync wrapper around `temporal.start_workflow` for the compact-delta job.

    `temporal.start_workflow` is heavily overloaded; running it through
    `async_to_sync` erases the overloads and confuses mypy. Localising the
    call here keeps a single typed-ignore in one place rather than scattered
    through every admin action.
    """
    async_to_sync(temporal.start_workflow)(
        "dwh-compact-delta-table",
        inputs_dict,
        id=workflow_id,
        task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
    )


def _get_delta_fragmentation_stats(schema: ExternalDataSchema) -> dict | None:
    """Inspect the Delta target for one schema and return file/partition stats.

    Returns None when no Delta target exists.

    Implemented synchronously (no `async_to_sync`) because the admin runs under
    an ASGI server in dev — calling `async_to_sync` from inside the already-
    running event loop raises `RuntimeError: You cannot use AsyncToSync in the
    same thread as an async event loop` and Django renders the field as `-`.
    The DeltaTableHelper internals only `await` two sync operations: the DB
    folder_path lookup and the deltalake constructor. We replicate them inline.
    """
    from django.conf import settings

    import deltalake

    from posthog.temporal.common.logger import get_logger
    from posthog.temporal.data_imports.naming_convention import NamingConvention
    from posthog.temporal.data_imports.pipelines.pipeline.delta_table_helper import DeltaTableHelper

    job = ExternalDataJob.objects.filter(schema_id=schema.id, team_id=schema.team_id).order_by("-created_at").first()
    if job is None:
        return None

    # Build the URI exactly like DeltaTableHelper._get_delta_table_uri does.
    normalized_resource_name = NamingConvention.normalize_identifier(schema.name)
    folder_path = job.folder_path()
    delta_uri = f"{settings.BUCKET_URL}/{folder_path}/{normalized_resource_name}"

    # Borrow DeltaTableHelper just for its credentials helper — that part is sync.
    storage_options = DeltaTableHelper(
        resource_name=schema.name, job=job, logger=get_logger(__name__)
    )._get_credentials()

    if not deltalake.DeltaTable.is_deltatable(table_uri=delta_uri, storage_options=storage_options):
        return None

    delta_table = deltalake.DeltaTable(table_uri=delta_uri, storage_options=storage_options)
    file_uris = delta_table.file_uris()
    total_files = len(file_uris)
    partition_count = schema.partition_count or 1

    total_size_bytes: int | None
    try:
        # delta-rs ships `get_add_actions(flatten=True)` typed as a pyarrow
        # RecordBatch, but at runtime it's an arro3 RecordBatch (delta-rs uses
        # arro3 internally). The two are not interchangeable — the arro3
        # variant lacks `to_pydict()` / `to_pylist()` and isn't accepted by
        # `pa.Table.from_batches`. Column-by-name access via `__getitem__`
        # does work on both, so we go through that path.
        add_actions: Any = delta_table.get_add_actions(flatten=True)
        size_bytes_col = add_actions["size_bytes"].to_pylist()
        total_size_bytes = sum(int(v or 0) for v in size_bytes_col)
    except Exception:
        total_size_bytes = None

    return {
        "total_files": total_files,
        "partition_count": partition_count,
        "files_per_partition_avg": total_files / partition_count,
        "total_size_bytes": total_size_bytes if total_size_bytes is not None else "n/a",
    }
