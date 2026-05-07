from django.contrib import admin, messages
from django.urls import reverse
from django.utils.html import format_html

from posthog.admin.admins.external_data_schema_admin import queue_compact_for_schema
from posthog.temporal.common.client import sync_connect

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
        ExternalDataSchema are skipped.

        Audit log scope is `DataWarehouseTable` (operator acted on a table)
        even though the underlying workflow is keyed on schema_id — the
        delegation is invisible at the audit layer.
        """
        temporal = sync_connect()
        started = 0
        skipped = 0
        failed: list[tuple[str, str]] = []

        for table in queryset:
            schema = ExternalDataSchema.objects.filter(table_id=table.id).first()
            if schema is None:
                skipped += 1
                continue

            ok, err = queue_compact_for_schema(
                temporal=temporal,
                schema=schema,
                request=request,
                audit_item_id=table.id,
                audit_scope="DataWarehouseTable",
                audit_name=table.name,
            )
            if ok:
                started += 1
            else:
                failed.append((str(table.id), err or "unknown error"))

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
