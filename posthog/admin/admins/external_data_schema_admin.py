import uuid
from dataclasses import asdict
from typing import Any

from django.conf import settings
from django.contrib import admin, messages
from django.core.paginator import Paginator
from django.urls import reverse
from django.utils.html import format_html

from asgiref.sync import async_to_sync

from posthog.models.activity_logging.activity_log import Detail, log_activity
from posthog.temporal.common.client import sync_connect
from posthog.temporal.data_imports.compact_delta_table_job import CompactDeltaTableWorkflowInputs

from products.data_warehouse.backend.models.external_data_job import ExternalDataJob
from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema


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
        of workflows started.

        Uses `async_to_sync(temporal.start_workflow)` rather than
        `asyncio.run(...)` because the admin can be served under an ASGI
        runtime (Granian) where a running event loop in the calling thread
        would make `asyncio.run` raise. `async_to_sync` runs the coroutine
        in its own dedicated thread + loop and is safe under both WSGI and
        ASGI.
        """
        temporal = sync_connect()
        started = 0
        failed: list[tuple[str, str]] = []

        for schema in queryset:
            workflow_id = f"compact-delta-{schema.id}-{uuid.uuid4()}"
            inputs = CompactDeltaTableWorkflowInputs(
                team_id=schema.team_id,
                schema_id=str(schema.id),
            )
            try:
                _start_compact_workflow(temporal, asdict(inputs), workflow_id)
                started += 1
            except Exception as e:
                failed.append((str(schema.id), str(e)))
                continue

            # Audit log the manual trigger so we can trace who kicked off
            # which compaction. `log_activity` swallows its own errors so
            # this never blocks the workflow that already started.
            log_activity(
                organization_id=schema.team.organization_id,
                team_id=schema.team_id,
                user=request.user,
                was_impersonated=False,
                item_id=schema.id,
                scope="ExternalDataSchema",
                activity="admin_compact_triggered",
                detail=Detail(
                    name=schema.name,
                    short_id=str(schema.id),
                    type="admin_compact_delta",
                ),
            )

        if started:
            self.message_user(
                request,
                f"Queued compaction workflow for {started} schema(s). Check Temporal UI for progress.",
                level=messages.INFO,
            )
        for schema_id, err in failed:
            self.message_user(request, f"Failed to queue compaction for {schema_id}: {err}", level=messages.ERROR)


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
