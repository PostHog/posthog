from django.contrib import admin
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import format_html

from products.data_modeling.backend.models.dag import DAG


@admin.register(DAG)
class DataModelingDAGAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "team_link", "sync_frequency_interval", "tiers_link")
    list_display_links = ("id", "name")
    list_select_related = ("team",)
    search_fields = ("id", "name", "team__id", "team__name")
    raw_id_fields = ("team", "created_by")
    readonly_fields = ("id", "created_at", "updated_at", "tiers_link")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: DAG | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: DAG | None = None) -> bool:
        return False

    @admin.display(description="Team")
    def team_link(self, dag: DAG):
        return format_html(
            '<a href="{}">{} ({})</a>',
            reverse("admin:posthog_team_change", args=[dag.team_id]),
            dag.team.name,
            dag.team_id,
        )

    @admin.display(description="Tiers")
    def tiers_link(self, dag: DAG):
        if not dag.pk:
            return "—"
        return format_html(
            '<a href="{}?dag={}">Schedule tiers and last run: now in PostHog Admin &#8599;</a>',
            reverse("admin_console_tool", kwargs={"tool_key": "dag-tiers"}),
            dag.pk,
        )
