import uuid
from dataclasses import asdict

from django.contrib import admin, messages
from django.urls import reverse
from django.utils.html import format_html

from posthog.admin.admins.external_data_schema_admin import _start_compact_workflow
from posthog.models.activity_logging.activity_log import Detail, log_activity
from posthog.temporal.common.client import sync_connect
from posthog.temporal.data_imports.compact_delta_table_job import CompactDeltaTableWorkflowInputs

from products.dashboards.backend.models.dashboard import Dashboard
from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema


class DataWarehouseTableAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "format",
        "url_pattern",
        "team_link",
        "organization_link",
        "created_at",
        "created_by",
    )
    list_display_links = ("id", "name")
    list_select_related = ("team", "team__organization")
    search_fields = ("id", "name", "team__name", "team__organization__name")
    autocomplete_fields = ("team", "created_by")
    readonly_fields = ("credential", "external_data_source")
    ordering = ("-created_at",)
    actions = ("trigger_compact_delta_table",)

    @admin.action(description="Compact + vacuum Delta target (via owning schema)")
    def trigger_compact_delta_table(self, request, queryset):
        """Triggers the same workflow as the schema admin, but routed via the
        DataWarehouseTable's owning ExternalDataSchema. Tables not backed by an
        ExternalDataSchema are skipped with a message."""
        temporal = sync_connect()
        started = 0
        skipped = 0
        failed: list[tuple[str, str]] = []

        for table in queryset:
            schema = ExternalDataSchema.objects.filter(table_id=table.id).first()
            if schema is None:
                skipped += 1
                continue

            workflow_id = f"compact-delta-{schema.id}-{uuid.uuid4()}"
            inputs = CompactDeltaTableWorkflowInputs(
                team_id=schema.team_id,
                schema_id=str(schema.id),
            )
            try:
                # See ExternalDataSchemaAdmin._start_compact_workflow for why
                # we route through that helper (async_to_sync + workflow-name
                # encapsulation, plus mypy overload erasure).
                _start_compact_workflow(temporal, asdict(inputs), workflow_id)
                started += 1
            except Exception as e:
                failed.append((str(table.id), str(e)))
                continue

            log_activity(
                organization_id=schema.team.organization_id,
                team_id=schema.team_id,
                user=request.user,
                was_impersonated=False,
                item_id=table.id,
                scope="DataWarehouseTable",
                activity="admin_compact_triggered",
                detail=Detail(
                    name=table.name,
                    short_id=str(table.id),
                    type="admin_compact_delta",
                ),
            )

        if started:
            self.message_user(request, f"Queued compaction for {started} table(s).", level=messages.INFO)
        if skipped:
            self.message_user(
                request,
                f"Skipped {skipped} table(s) without an owning ExternalDataSchema.",
                level=messages.WARNING,
            )
        for table_id, err in failed:
            self.message_user(request, f"Failed for {table_id}: {err}", level=messages.ERROR)

    @admin.display(description="Team")
    def team_link(self, dashboard: Dashboard):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[dashboard.team.pk]),
            dashboard.team.name,
        )

    @admin.display(description="Organization")
    def organization_link(self, dashboard: Dashboard):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_organization_change", args=[dashboard.team.organization.pk]),
            dashboard.team.organization.name,
        )
